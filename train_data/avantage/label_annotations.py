"""Draw Avantage annotation bounding boxes on their source screenshots.

Run from the repository root with:

    python train_data/avantage/label_annotations.py
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover - depends on the active environment.
    raise SystemExit("Pillow is required; install the project's Python dependencies first.") from exc


DATASET_DIR = Path(__file__).resolve().parent
ANNOTATIONS_PATH = DATASET_DIR / "annotations.csv"
IMAGES_DIR = DATASET_DIR / "images"
OUTPUT_DIR = DATASET_DIR / "labeled_images"
REQUIRED_COLUMNS = {"image", "description", "left", "top", "right", "bottom"}
COLORS_BY_DESCRIPTION_COUNT = {
    1: (0, 114, 178),
    2: (230, 159, 0),
    3: (204, 121, 167),
}
LINE_WIDTH = 3


class AnnotationError(ValueError):
    """Raised when an annotation cannot be rendered safely."""


def parse_coordinate(value: str, column: str, row_number: int) -> int:
    """Return an integer CSV coordinate with a clear error for invalid input."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AnnotationError(
            f"Row {row_number}: {column!r} must be an integer, got {value!r}."
        ) from exc


def load_elements() -> dict[str, Counter[tuple[int, int, int, int]]]:
    """Group annotation rows by screenshot and unique bounding box."""
    if not ANNOTATIONS_PATH.is_file():
        raise AnnotationError(f"Annotation CSV is missing: {ANNOTATIONS_PATH}")

    elements: dict[str, Counter[tuple[int, int, int, int]]] = defaultdict(Counter)
    with ANNOTATIONS_PATH.open("r", encoding="utf-8-sig", newline="") as csv_file:
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
                    f"Row {row_number}: image must be a filename in {IMAGES_DIR}, got {image_name!r}."
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
    image_name: str, elements: Counter[tuple[int, int, int, int]]
) -> int:
    """Draw every element in one screenshot and return its element count."""
    image_path = IMAGES_DIR / image_name
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_DIR / image_name, format="PNG")
    return len(elements)


def main() -> None:
    """Render all screenshots named by the annotation CSV."""
    elements_by_image = load_elements()
    description_counts = Counter()
    element_total = 0

    for image_name in sorted(elements_by_image):
        elements = elements_by_image[image_name]
        element_total += render_image(image_name, elements)
        description_counts.update(elements.values())

    count_summary = ", ".join(
        f"{count} description(s): {description_counts[count]}"
        for count in sorted(COLORS_BY_DESCRIPTION_COUNT)
    )
    print(
        f"Wrote {len(elements_by_image)} labeled image(s) containing "
        f"{element_total} element(s) to {OUTPUT_DIR}\n{count_summary}"
    )


if __name__ == "__main__":
    try:
        main()
    except AnnotationError as exc:
        raise SystemExit(f"Cannot render annotations: {exc}") from exc
