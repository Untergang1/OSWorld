"""Draw annotation bounding boxes for a versioned training dataset.

Run from the repository root with:

    python train_data/label_annotations.py train_data/avantage/v2
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

REQUIRED_COLUMNS = {"image", "description", "left", "top", "right", "bottom"}
COLORS_BY_DESCRIPTION_COUNT = {
    1: (0, 114, 178),
    2: (230, 159, 0),
    3: (204, 121, 167),
}
LINE_WIDTH = 3


class AnnotationError(ValueError):
    """Raised when an annotation cannot be rendered safely."""


@dataclass(frozen=True)
class DatasetPaths:
    """Locations required to render one versioned annotation dataset."""

    root: Path

    @property
    def annotations(self) -> Path:
        return self.root / "annotations.csv"

    @property
    def images(self) -> Path:
        return self.root / "images"

    @property
    def output(self) -> Path:
        return self.root / "labeled_images"


def parse_coordinate(value: str, column: str, row_number: int) -> int:
    """Return an integer CSV coordinate with a clear error for invalid input."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AnnotationError(
            f"Row {row_number}: {column!r} must be an integer, got {value!r}."
        ) from exc


def load_elements(paths: DatasetPaths) -> dict[str, Counter[tuple[int, int, int, int]]]:
    """Group annotation rows by screenshot and unique bounding box."""
    if not paths.annotations.is_file():
        raise AnnotationError(f"Annotation CSV is missing: {paths.annotations}")

    elements: dict[str, Counter[tuple[int, int, int, int]]] = defaultdict(Counter)
    with paths.annotations.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = set(reader.fieldnames or ())
        missing_columns = REQUIRED_COLUMNS - columns
        if missing_columns:
            raise AnnotationError(
                "Annotation CSV is missing required columns: "
                + ", ".join(sorted(missing_columns))
            )

        for row_number, row in enumerate(reader, start=2):
            image_name = (row["image"] or "").strip()
            if not image_name or Path(image_name).name != image_name:
                raise AnnotationError(
                    f"Row {row_number}: image must be a filename in {paths.images}, "
                    f"got {image_name!r}."
                )

            left = parse_coordinate(row["left"], "left", row_number)
            top = parse_coordinate(row["top"], "top", row_number)
            right = parse_coordinate(row["right"], "right", row_number)
            bottom = parse_coordinate(row["bottom"], "bottom", row_number)
            if left >= right or top >= bottom:
                raise AnnotationError(
                    f"Row {row_number}: bbox must satisfy left < right and top < bottom."
                )

            elements[image_name][(left, top, right, bottom)] += 1

    if not elements:
        raise AnnotationError("Annotation CSV has no data rows.")
    return dict(elements)


def render_image(
    paths: DatasetPaths,
    image_name: str,
    elements: Counter[tuple[int, int, int, int]],
) -> int:
    """Draw every element in one screenshot and return its element count."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - depends on the active environment.
        raise SystemExit(
            "Pillow is required; install the project's Python dependencies first."
        ) from exc

    image_path = paths.images / image_name
    if not image_path.is_file():
        raise AnnotationError(f"Source image is missing: {image_path}")

    with Image.open(image_path) as source:
        image = source.convert("RGB")

    draw = ImageDraw.Draw(image)
    for (left, top, right, bottom), description_count in elements.items():
        if description_count not in COLORS_BY_DESCRIPTION_COUNT:
            raise AnnotationError(
                f"{image_name}: bbox {(left, top, right, bottom)} has "
                f"{description_count} descriptions; expected 1, 2, or 3."
            )
        if left < 0 or top < 0 or right > image.width or bottom > image.height:
            raise AnnotationError(
                f"{image_name}: bbox {(left, top, right, bottom)} exceeds "
                f"image size {image.width}x{image.height}."
            )

        draw.rectangle(
            (left, top, right, bottom),
            outline=COLORS_BY_DESCRIPTION_COUNT[description_count],
            width=LINE_WIDTH,
        )

    paths.output.mkdir(parents=True, exist_ok=True)
    image.save(paths.output / image_name, format="PNG")
    return len(elements)


def parse_args() -> argparse.Namespace:
    """Parse the versioned dataset directory to render."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_dir",
        type=Path,
        help="Directory containing annotations.csv and images/.",
    )
    return parser.parse_args()


def main(dataset_dir: Path) -> None:
    """Render all screenshots named by one annotation CSV."""
    paths = DatasetPaths(dataset_dir.resolve())
    if not paths.root.is_dir():
        raise AnnotationError(f"Dataset directory is missing: {paths.root}")

    elements_by_image = load_elements(paths)
    description_counts = Counter()
    element_total = 0

    for image_name in sorted(elements_by_image):
        elements = elements_by_image[image_name]
        element_total += render_image(paths, image_name, elements)
        description_counts.update(elements.values())

    count_summary = ", ".join(
        f"{count} description(s): {description_counts[count]}"
        for count in sorted(COLORS_BY_DESCRIPTION_COUNT)
    )
    print(
        f"Wrote {len(elements_by_image)} labeled image(s) containing "
        f"{element_total} element(s) to {paths.output}\n{count_summary}"
    )


if __name__ == "__main__":
    try:
        main(parse_args().dataset_dir)
    except AnnotationError as exc:
        raise SystemExit(f"Cannot render annotations: {exc}") from exc
