"""Generate one visual-first description per Avantage v2 element for v3.

Run from the repository root. The API key is deliberately an argument so that it
is never written to a dataset file or read from a source-controlled config::

    python train_data/generate_avantage_v3.py \
        --base-url "$env:DASHSCOPE_BASE_URL" \
        --api-key "$env:DASHSCOPE_API_KEY"

Use ``--dry-run`` first to validate the source pairing without importing Pillow
or OpenAI and without creating the v3 directory.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CSV_COLUMNS = ("id", "image", "description", "left", "top", "right", "bottom", "app_version")
SOURCE_COLUMNS = {"id", "image", "left", "top", "right", "bottom", "app_version"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DEFAULT_SOURCE_DIR = Path("train_data/avantage/v2")
DEFAULT_CAPTURES_DIR = Path("train_data/captures")
DEFAULT_OUTPUT_DIR = Path("train_data/avantage/v3")
MAX_DESCRIPTION_LENGTH = 420
MIN_DESCRIPTION_LENGTH = 12
MAX_BATCH_SIZE = 15
CHECKPOINT_SCHEMA_VERSION = 1
CONTEXT_CROP_MARGIN = 20
PROMPT_VERSION = "full-image-batched-target-context-crops-v4"


class GenerationError(RuntimeError):
    """Raised when the input dataset or model response is unsafe to use."""


@dataclass(frozen=True)
class Bbox:
    """An element rectangle in raw screenshot pixels, right/bottom exclusive."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def key(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom


@dataclass(frozen=True)
class Target:
    """One de-duplicated v2 element that must receive one v3 description."""

    identifier: str
    image_name: str
    bbox: Bbox
    app_version: str

    @property
    def checkpoint_key(self) -> str:
        return f"{self.identifier}|{self.image_name}|{','.join(map(str, self.bbox.key))}"


@dataclass(frozen=True)
class SourceImage:
    """A v2 training image paired with its equal raw capture screenshot."""

    image_name: str
    v2_path: Path
    raw_path: Path
    uia_path: Path
    width: int
    height: int
    raw_sha256: str
    uia_sha256: str


@dataclass(frozen=True)
class MatchedTarget:
    """A CSV target plus its exact UIA element and screenshot source."""

    target: Target
    source: SourceImage
    element: dict[str, Any]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments without accepting secrets from disk."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--captures-dir", type=Path, default=DEFAULT_CAPTURES_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL.")
    parser.add_argument("--api-key", help="OpenAI-compatible API key.")
    parser.add_argument("--model", default="qwen3.7-plus", help="Chat-completions model name.")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout in seconds.")
    parser.add_argument("--max-retries", type=int, default=3, help="Attempts per target, including the first.")
    parser.add_argument("--resume", action="store_true", help="Continue from the incomplete checkpoint in output-dir.")
    parser.add_argument("--overwrite", action="store_true", help="Replace a completed annotations.csv in output-dir.")
    parser.add_argument("--dry-run", action="store_true", help="Validate all inputs without API calls or writes.")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.max_retries < 1:
        parser.error("--max-retries must be at least 1")
    if not args.dry_run and (not args.base_url or not args.api_key):
        parser.error("--base-url and --api-key are required unless --dry-run is used")
    if args.resume and args.overwrite:
        parser.error("--resume and --overwrite cannot be used together")
    return args


def read_png_dimensions(path: Path) -> tuple[int, int]:
    """Read a PNG IHDR without importing Pillow during a dry run."""
    try:
        header = path.read_bytes()[:24]
    except OSError as exc:
        raise GenerationError(f"Cannot read PNG: {path}") from exc
    if len(header) != 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise GenerationError(f"Expected a valid PNG image: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise GenerationError(f"PNG has invalid dimensions: {path}")
    return width, height


def file_sha256(path: Path) -> str:
    """Return a file digest used only to prove an image pairing."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_int(value: str, column: str, row_number: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise GenerationError(f"CSV row {row_number}: {column} must be an integer, got {value!r}") from exc


def base_identifier(identifier: str) -> str:
    """Remove only the old description-variant suffix, such as ``-01``."""
    match = re.fullmatch(r"(.+)-(\d{2})", identifier)
    return match.group(1) if match else identifier


def load_targets(annotations_path: Path) -> list[Target]:
    """Read selection fields only; old descriptions are never accessed."""
    if not annotations_path.is_file():
        raise GenerationError(f"Source annotations are missing: {annotations_path}")
    target_candidates: dict[tuple[str, tuple[int, int, int, int]], list[Target]] = {}
    target_order: list[tuple[str, tuple[int, int, int, int]]] = []
    canonical_ids: dict[tuple[str, tuple[int, int, int, int]], str] = {}
    with annotations_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.reader(csv_file)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise GenerationError(f"Source annotations are empty: {annotations_path}") from exc
        indices = {name: index for index, name in enumerate(headers)}
        missing = SOURCE_COLUMNS - set(indices)
        if missing:
            raise GenerationError("Source CSV is missing columns: " + ", ".join(sorted(missing)))
        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(headers):
                raise GenerationError(f"CSV row {row_number}: expected {len(headers)} columns, got {len(row)}")
            # Do not index the description column: it is deliberately invisible to v3 generation.
            identifier = row[indices["id"]].strip()
            image_name = row[indices["image"]].strip()
            if not identifier or not image_name or Path(image_name).name != image_name:
                raise GenerationError(f"CSV row {row_number}: id and image must be non-empty filenames/identifiers")
            bbox = Bbox(
                parse_int(row[indices["left"]], "left", row_number),
                parse_int(row[indices["top"]], "top", row_number),
                parse_int(row[indices["right"]], "right", row_number),
                parse_int(row[indices["bottom"]], "bottom", row_number),
            )
            if bbox.left >= bbox.right or bbox.top >= bbox.bottom:
                raise GenerationError(f"CSV row {row_number}: bbox must satisfy left < right and top < bottom")
            key = image_name, bbox.key
            current_base = base_identifier(identifier)
            previous_base = canonical_ids.setdefault(key, current_base)
            if previous_base != current_base:
                raise GenerationError(f"CSV row {row_number}: one bbox is assigned to multiple target IDs")
            if key not in target_candidates:
                target_candidates[key] = []
                target_order.append(key)
            target_candidates[key].append(Target(identifier, image_name, bbox, row[indices["app_version"]].strip()))
    if not target_candidates:
        raise GenerationError("Source annotations contain no elements")
    targets: list[Target] = []
    for key in target_order:
        candidates = target_candidates[key]
        selected = [candidate for candidate in candidates if candidate.identifier.endswith("-01")]
        if len(selected) != 1:
            raise GenerationError(f"{key[0]} {key[1]}: expected exactly one existing -01 target ID")
        targets.append(selected[0])
    return targets


def pair_source_images(source_dir: Path, captures_dir: Path, image_names: Iterable[str]) -> dict[str, SourceImage]:
    """Pair each named v2 image with a byte-identical raw screenshot by hash."""
    captures: dict[str, list[tuple[Path, Path]]] = {}
    for raw_path in sorted(captures_dir.glob("*/raw_screenshot.png")):
        uia_path = raw_path.with_name("filtered_uia.json")
        if not uia_path.is_file():
            raise GenerationError(f"Capture is missing UIA data: {uia_path}")
        captures.setdefault(file_sha256(raw_path), []).append((raw_path, uia_path))
    if not captures:
        raise GenerationError(f"No raw screenshots found under {captures_dir}")

    pairs: dict[str, SourceImage] = {}
    for image_name in sorted(set(image_names)):
        image_path = source_dir / "images" / image_name
        if not image_path.is_file():
            raise GenerationError(f"v2 image is missing: {image_path}")
        raw_digest = file_sha256(image_path)
        candidates = captures.get(raw_digest, [])
        if len(candidates) != 1:
            raise GenerationError(f"{image_name}: expected exactly one identical raw screenshot, found {len(candidates)}")
        raw_path, uia_path = candidates[0]
        width, height = read_png_dimensions(raw_path)
        if read_png_dimensions(image_path) != (width, height):
            raise GenerationError(f"{image_name}: matching image hashes have conflicting dimensions")
        pairs[image_name] = SourceImage(
            image_name, image_path, raw_path, uia_path, width, height, raw_digest, file_sha256(uia_path)
        )
    return pairs


def load_uia_elements(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationError(f"Cannot read filtered UIA JSON: {path}") from exc
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        raise GenerationError(f"UIA payload has no elements list: {path}")
    if not all(isinstance(element, dict) for element in elements):
        raise GenerationError(f"UIA payload has a non-object element: {path}")
    return tuple(elements)


def uia_rect_key(element: dict[str, Any]) -> tuple[int, int, int, int] | None:
    rect = element.get("rect_screenshot")
    if not isinstance(rect, dict):
        return None
    try:
        return tuple(int(rect[name]) for name in ("left", "top", "right", "bottom"))  # type: ignore[return-value]
    except (KeyError, TypeError, ValueError):
        return None


def match_targets(targets: list[Target], sources: dict[str, SourceImage]) -> list[MatchedTarget]:
    """Ensure every selected element has exactly one UIA control in screenshot space."""
    elements_by_image = {name: load_uia_elements(source.uia_path) for name, source in sources.items()}
    by_rect: dict[str, dict[tuple[int, int, int, int], list[dict[str, Any]]]] = {}
    for image_name, elements in elements_by_image.items():
        indexed: dict[tuple[int, int, int, int], list[dict[str, Any]]] = {}
        for element in elements:
            key = uia_rect_key(element)
            if key is not None:
                indexed.setdefault(key, []).append(element)
        by_rect[image_name] = indexed

    matched: list[MatchedTarget] = []
    for target in targets:
        source = sources[target.image_name]
        if target.bbox.left < 0 or target.bbox.top < 0 or target.bbox.right > source.width or target.bbox.bottom > source.height:
            raise GenerationError(f"{target.identifier}: bbox falls outside {target.image_name}")
        candidates = by_rect[target.image_name].get(target.bbox.key, [])
        if len(candidates) != 1:
            raise GenerationError(f"{target.identifier}: expected one exact UIA rect match, found {len(candidates)}")
        matched.append(MatchedTarget(target, source, candidates[0]))
    return matched


def text_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def uia_hint(target: MatchedTarget) -> str:
    """Return the target's sole UIA field permitted in a model request."""
    content = text_value(target.element.get("content"))
    return content if content else "(empty)"


def png_data_url(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def context_crop_box(image_width: int, image_height: int, bbox: Bbox) -> tuple[int, int, int, int]:
    """Return the in-bounds crop rectangle for one target's screenshot context."""
    return (
        max(0, bbox.left - CONTEXT_CROP_MARGIN),
        max(0, bbox.top - CONTEXT_CROP_MARGIN),
        min(image_width, bbox.right + CONTEXT_CROP_MARGIN),
        min(image_height, bbox.bottom + CONTEXT_CROP_MARGIN),
    )


def context_crop_png(full_image: bytes, bbox: Bbox) -> bytes:
    """Encode the bbox plus its in-bounds surrounding screenshot context."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - depends on the active environment.
        raise GenerationError("Pillow is required to create element context crops") from exc
    try:
        with Image.open(io.BytesIO(full_image)) as image:
            image.load()
            crop = image.crop(context_crop_box(image.width, image.height, bbox))
            output = io.BytesIO()
            crop.save(output, format="PNG")
    except (OSError, ValueError) as exc:
        raise GenerationError("Cannot create a context crop from the full screenshot") from exc
    return output.getvalue()


def build_messages(batch: list[MatchedTarget], full_image: bytes) -> list[dict[str, Any]]:
    """Build one full-image request followed by interleaved target context crops."""
    if not batch or len(batch) > MAX_BATCH_SIZE:
        raise GenerationError(f"A request batch must contain 1-{MAX_BATCH_SIZE} targets")
    if len({item.source.raw_sha256 for item in batch}) != 1:
        raise GenerationError("A request batch must contain targets from exactly one screenshot")
    prompt = f"""Describe {len(batch)} GUI elements for an image-grounding dataset.

First is one unmodified full raw screenshot for global context. No boxes have been drawn on any image. Each element is then presented as text followed by its own context-crop image. Each target rectangle uses zero-based screenshot pixels with right and bottom exclusive.

For every target, write one specific, unambiguous English referring expression for its exact element. Use the full screenshot for global position and surrounding application context, and its context crop to identify the exact control. Prioritize visible evidence: text, icon shape/color, control role, position, containing pane/dialog, and additional prominent identifying features. The target UIA content is supplementary only; use it only when it agrees with the visual evidence. Do not invent unseen details.

Output only a JSON object with exactly the string keys \"1\" through \"{len(batch)}\", where each value is the description for the target with that number. Do not output Markdown, a code fence, labels, reasoning, or alternatives. Prompt version: {PROMPT_VERSION}."""
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": png_data_url(full_image)}},
    ]
    for index, item in enumerate(batch, start=1):
        content.append({
            "type": "text",
            "text": (
                f"Element {index}:\n"
                f"- Element ID: {item.target.identifier}\n"
                f"- Rectangle (left, top, right, bottom): {item.target.bbox.key}\n"
                f"- content (the only UIA field provided): {uia_hint(item)}\n"
                f"The following image is Element {index}'s context crop."
            ),
        })
        content.append({
            "type": "image_url",
            "image_url": {"url": png_data_url(context_crop_png(full_image, item.target.bbox))},
        })
    return [
        {"role": "system", "content": "You produce concise visual GUI descriptions and output only the requested JSON object."},
        {
            "role": "user",
            "content": content,
        },
    ]


def normalize_description(response: str) -> str:
    """Accept only a single plain-English description after minor wrapper cleanup."""
    text = response.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) == 2 and re.fullmatch(r"(?:description|answer)\s*:", lines[0], flags=re.IGNORECASE):
        text = lines[1]
    elif len(lines) == 1:
        text = lines[0]
    else:
        raise GenerationError("model response contains multiple lines")
    text = re.sub(r"^(?:description|answer)\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:[-*]|\d+[.)])\s+", "", text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    text = re.sub(r"\s+", " ", text)
    if not (MIN_DESCRIPTION_LENGTH <= len(text) <= MAX_DESCRIPTION_LENGTH):
        raise GenerationError(f"model description must contain {MIN_DESCRIPTION_LENGTH}-{MAX_DESCRIPTION_LENGTH} characters")
    if text.startswith(("{", "[")) or re.search(r"\b(?:here is|i cannot|as an ai)\b", text, flags=re.IGNORECASE):
        raise GenerationError("model response is not a plain description")
    if len(re.findall(r"[A-Za-z]", text)) < 6 or re.search(r"[\u4e00-\u9fff]", text):
        raise GenerationError("model description is not English text")
    return text


def normalize_batch_descriptions(response: str, batch: list[MatchedTarget]) -> dict[str, str]:
    """Validate a complete ordinal-to-description JSON response for one request batch."""
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise GenerationError("model batch response contains a duplicate target number")
            payload[key] = value
        return payload

    try:
        payload = json.loads(response, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise GenerationError("model batch response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise GenerationError("model batch response must be a JSON object")
    expected_keys = {str(index) for index in range(1, len(batch) + 1)}
    if set(payload) != expected_keys:
        raise GenerationError("model batch response must contain exactly the expected target numbers")
    descriptions: dict[str, str] = {}
    for index, item in enumerate(batch, start=1):
        value = payload[str(index)]
        if not isinstance(value, str):
            raise GenerationError(f"model batch response target {index} is not a description string")
        descriptions[item.target.checkpoint_key] = normalize_description(value)
    return descriptions


def iter_pending_batches(
    targets: list[MatchedTarget], completed: dict[str, str]
) -> Iterable[list[MatchedTarget]]:
    """Group unfinished targets by screenshot while preserving image and target order."""
    pending_by_screenshot: dict[str, list[MatchedTarget]] = {}
    for item in targets:
        if item.target.checkpoint_key not in completed:
            pending_by_screenshot.setdefault(item.source.raw_sha256, []).append(item)
    for items in pending_by_screenshot.values():
        for start in range(0, len(items), MAX_BATCH_SIZE):
            yield items[start:start + MAX_BATCH_SIZE]


def generation_fingerprint(targets: list[MatchedTarget], model: str) -> str:
    """Bind resumed work to every visual/UIA input and prompt-affecting setting."""
    payload = {
        "checkpoint_schema": CHECKPOINT_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "targets": [
            {
                "key": item.target.checkpoint_key,
                "app_version": item.target.app_version,
                "raw_sha256": item.source.raw_sha256,
                "uia_sha256": item.source.uia_sha256,
            }
            for item in targets
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def initialize_checkpoint(path: Path, fingerprint: str) -> None:
    """Create the checkpoint header before the first billable request."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = json.dumps({"kind": "metadata", "fingerprint": fingerprint}, ensure_ascii=True)
    with path.open("w", encoding="utf-8", newline="\n") as checkpoint:
        checkpoint.write(record + "\n")
        checkpoint.flush()
        os.fsync(checkpoint.fileno())


def load_checkpoint(path: Path, targets: list[MatchedTarget], fingerprint: str) -> dict[str, str]:
    """Load a durable per-target checkpoint and reject stale or malformed rows."""
    if not path.exists():
        return {}
    allowed = {item.target.checkpoint_key for item in targets}
    completed: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as checkpoint:
        for line_number, line in enumerate(checkpoint, start=1):
            try:
                record = json.loads(line)
            except (KeyError, TypeError, json.JSONDecodeError, GenerationError) as exc:
                raise GenerationError(f"Invalid checkpoint row {line_number}: {path}") from exc
            if not isinstance(record, dict):
                raise GenerationError(f"Invalid checkpoint row {line_number}: {path}")
            if line_number == 1:
                if record.get("kind") != "metadata" or record.get("fingerprint") != fingerprint:
                    raise GenerationError("Checkpoint does not match the current screenshots, UIA, prompt, or model")
                continue
            try:
                if record.get("kind") != "target":
                    raise KeyError("kind")
                key = str(record["key"])
                description = normalize_description(str(record["description"]))
            except (KeyError, TypeError, GenerationError) as exc:
                raise GenerationError(f"Invalid checkpoint row {line_number}: {path}") from exc
            if key not in allowed or key in completed:
                raise GenerationError(f"Checkpoint row {line_number} does not match the current source dataset")
            completed[key] = description
    if not completed and path.stat().st_size == 0:
        raise GenerationError(f"Checkpoint is empty: {path}")
    return completed


def append_checkpoint(path: Path, target: Target, description: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = json.dumps({"kind": "target", "key": target.checkpoint_key, "description": description}, ensure_ascii=False)
    with path.open("a", encoding="utf-8", newline="\n") as checkpoint:
        checkpoint.write(record + "\n")
        checkpoint.flush()
        os.fsync(checkpoint.fileno())


def write_annotations(path: Path, targets: list[MatchedTarget], descriptions: dict[str, str]) -> None:
    """Atomically write only the final CSV after every target has a description."""
    missing = [item.target.identifier for item in targets if item.target.checkpoint_key not in descriptions]
    if missing:
        raise GenerationError(f"Cannot write incomplete annotations; {len(missing)} target(s) are missing")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", delete=False, dir=path.parent, suffix=".tmp") as file:
        temporary_path = Path(file.name)
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for item in targets:
            target = item.target
            writer.writerow({
                "id": target.identifier,
                "image": target.image_name,
                "description": descriptions[target.checkpoint_key],
                "left": target.bbox.left,
                "top": target.bbox.top,
                "right": target.bbox.right,
                "bottom": target.bbox.bottom,
                "app_version": target.app_version,
            })
    temporary_path.replace(path)


def copy_images(sources: dict[str, SourceImage], output_dir: Path) -> None:
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for image_name, source in sources.items():
        destination = images_dir / image_name
        temporary = destination.with_name(destination.name + ".tmp")
        shutil.copyfile(source.raw_path, temporary)
        temporary.replace(destination)


def require_generation_dependencies() -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - depends on active environment.
        raise SystemExit("OpenAI is required; install the project dependencies before generating descriptions.") from exc
    return OpenAI


def prepare_checkpoint(
    output_dir: Path,
    targets: list[MatchedTarget],
    fingerprint: str,
    *,
    resume: bool,
    overwrite: bool,
) -> tuple[Path, dict[str, str]]:
    """Preserve the previous final CSV while a replacement run is in progress."""
    annotations_path = output_dir / "annotations.csv"
    checkpoint_path = output_dir / "generation_checkpoint.jsonl"
    if checkpoint_path.exists():
        if overwrite:
            checkpoint_path.unlink()
        elif resume:
            return checkpoint_path, load_checkpoint(checkpoint_path, targets, fingerprint)
        else:
            raise GenerationError(f"Incomplete checkpoint exists: {checkpoint_path}. Use --resume to continue it.")
    elif resume:
        raise GenerationError(f"No checkpoint exists to resume: {checkpoint_path}")
    if annotations_path.exists() and not overwrite:
        raise GenerationError(f"Output already exists: {annotations_path}. Use --overwrite to replace it.")
    initialize_checkpoint(checkpoint_path, fingerprint)
    return checkpoint_path, {}


def request_descriptions(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float,
    batch: list[MatchedTarget],
) -> dict[str, str]:
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=160 * len(batch),
        timeout=timeout,
    )
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError) as exc:
        raise GenerationError("model response contains no chat-completions message") from exc
    if not isinstance(content, str):
        raise GenerationError("model response message is not text")
    return normalize_batch_descriptions(content, batch)


def generate_descriptions(args: argparse.Namespace, targets: list[MatchedTarget], sources: dict[str, SourceImage]) -> dict[str, str]:
    """Call the model in same-screenshot batches, preserving per-target checkpoints."""
    OpenAI = require_generation_dependencies()
    output_dir = args.output_dir.resolve()
    annotations_path = output_dir / "annotations.csv"
    fingerprint = generation_fingerprint(targets, args.model)
    checkpoint_path, completed = prepare_checkpoint(
        output_dir, targets, fingerprint, resume=args.resume, overwrite=args.overwrite
    )
    copy_images(sources, output_dir)
    client = OpenAI(api_key=args.api_key, base_url=args.base_url, timeout=args.timeout, max_retries=0)
    raw_bytes = {name: source.raw_path.read_bytes() for name, source in sources.items()}

    target_positions = {item.target.checkpoint_key: index for index, item in enumerate(targets, start=1)}
    for batch in iter_pending_batches(targets, completed):
        image_name = batch[0].target.image_name
        messages = build_messages(batch, raw_bytes[image_name])
        last_error: Exception | None = None
        for attempt in range(1, args.max_retries + 1):
            try:
                descriptions = request_descriptions(client, args.model, messages, args.timeout, batch)
                break
            except Exception as exc:  # OpenAI-compatible providers expose varying exception classes.
                last_error = exc
                if attempt < args.max_retries:
                    time.sleep(min(8.0, 2.0 ** (attempt - 1)))
        else:
            identifiers = ", ".join(item.target.identifier for item in batch)
            raise GenerationError(
                f"Batch ({identifiers}): model failed after {args.max_retries} attempt(s): {last_error}"
            ) from last_error
        for item in batch:
            target = item.target
            description = descriptions[target.checkpoint_key]
            append_checkpoint(checkpoint_path, target, description)
            completed[target.checkpoint_key] = description
            print(f"[{target_positions[target.checkpoint_key]}/{len(targets)}] {target.identifier}")

    write_annotations(annotations_path, targets, completed)
    checkpoint_path.unlink(missing_ok=True)
    return completed


def main(args: argparse.Namespace) -> None:
    source_dir = args.source_dir.resolve()
    captures_dir = args.captures_dir.resolve()
    targets = load_targets(source_dir / "annotations.csv")
    sources = pair_source_images(source_dir, captures_dir, (target.image_name for target in targets))
    matched = match_targets(targets, sources)
    per_image = {name: sum(item.target.image_name == name for item in matched) for name in sources}
    print(f"Validated {len(matched)} unique elements across {len(sources)} source screenshot(s).")
    for image_name in sorted(per_image):
        print(f"  {image_name}: {per_image[image_name]} elements")
    if args.dry_run:
        print("Dry run complete; no API calls or files were written.")
        return
    generate_descriptions(args, matched, sources)
    print(f"Wrote {len(matched)} one-description annotations to {args.output_dir.resolve() / 'annotations.csv'}")


if __name__ == "__main__":
    try:
        main(parse_args())
    except GenerationError as exc:
        raise SystemExit(f"Cannot generate Avantage v3: {exc}") from exc
