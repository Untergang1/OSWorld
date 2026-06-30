import logging
import hashlib
import os
import re
import struct
from typing import Any, Dict, Iterable, List, Tuple

logger = logging.getLogger("desktopenv.metric.scikit")

_NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _extensions(rules: Dict[str, Any]) -> List[str]:
    values = rules.get("extensions")
    if values is None:
        value = rules.get("extension")
        return [str(value).lower()] if value else []
    return [str(value).lower() for value in values]


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_basic_file(path: str, rules: Dict[str, Any]) -> bool:
    if not path or not os.path.isfile(path):
        logger.debug("SciKit metric: result file missing: %s", path)
        return False

    if _safe_size(path) < int(rules.get("min_bytes", 1)):
        logger.debug("SciKit metric: file too small: %s", path)
        return False

    exts = _extensions(rules)
    if exts and not any(path.lower().endswith(ext) for ext in exts):
        logger.debug("SciKit metric: extension mismatch: %s", path)
        return False

    basename = rules.get("basename")
    if basename and os.path.basename(path) != basename:
        logger.debug("SciKit metric: basename mismatch: %s", path)
        return False

    forbidden_hashes = {str(value).lower() for value in rules.get("forbidden_sha256", [])}
    if forbidden_hashes:
        try:
            if _file_sha256(path).lower() in forbidden_hashes:
                logger.debug("SciKit metric: output is byte-identical to a forbidden source file: %s", path)
                return False
        except OSError:
            return False

    return True


def _read_text(path: str) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                return handle.read()
        except UnicodeError:
            continue
        except OSError:
            return ""
    return ""


def _numeric_rows(text: str, min_cols: int = 1) -> List[Tuple[float, ...]]:
    rows: List[Tuple[float, ...]] = []
    for line in text.splitlines():
        values = tuple(float(match.group(0)) for match in _NUMBER_RE.finditer(line))
        if len(values) >= min_cols:
            rows.append(values)
    return rows


def _all_numbers(rows: Iterable[Tuple[float, ...]]) -> List[float]:
    return [value for row in rows for value in row]


def _check_text_keywords(text: str, rules: Dict[str, Any], label: str) -> bool:
    if rules.get("ignore_case", True):
        haystack = text.lower()
        required = [str(keyword).lower() for keyword in rules.get("include_keywords", [])]
        alternatives = [str(keyword).lower() for keyword in rules.get("include_any_keywords", [])]
    else:
        haystack = text
        required = [str(keyword) for keyword in rules.get("include_keywords", [])]
        alternatives = [str(keyword) for keyword in rules.get("include_any_keywords", [])]

    for keyword in required:
        if keyword not in haystack:
            logger.debug("SciKit %s missing keyword: %s", label, keyword)
            return False

    if alternatives and not any(keyword in haystack for keyword in alternatives):
        logger.debug("SciKit %s missing all alternative keywords", label)
        return False

    return True


def check_scikit_file_metadata(result_path: str, rules: Dict[str, Any]) -> float:
    """Check that a scientific application produced the requested file."""
    return float(_check_basic_file(result_path, rules))


def check_scikit_csv_table(result_path: str, rules: Dict[str, Any]) -> float:
    """Check a CSV/text export for parseable numeric scientific data."""
    if not _check_basic_file(result_path, rules):
        return 0.0

    text = _read_text(result_path)
    if not text or not _check_text_keywords(text, rules, "table"):
        return 0.0

    header_text = "\n".join(text.splitlines()[:10]).lower()
    for keyword in rules.get("required_header_keywords", []):
        if str(keyword).lower() not in header_text:
            logger.debug("SciKit table header missing keyword: %s", keyword)
            return 0.0

    min_cols = int(rules.get("min_numeric_cols", 1))
    rows = _numeric_rows(text, min_cols=min_cols)
    if len(rows) < int(rules.get("min_numeric_rows", 1)):
        logger.debug("SciKit table has too few numeric rows with %d columns: %d", min_cols, len(rows))
        return 0.0

    numbers = _all_numbers(rows)
    tolerance = float(rules.get("tolerance", 0.25))
    for expected in rules.get("expected_values", []):
        value = float(expected)
        if not any(abs(candidate - value) <= tolerance for candidate in numbers):
            logger.debug("SciKit table missing expected value near %s", value)
            return 0.0

    for spec in rules.get("column_ranges", []):
        idx = int(spec.get("index", 0))
        values = [row[idx] for row in rows if len(row) > idx]
        if not values:
            logger.debug("SciKit table missing numeric column %d", idx)
            return 0.0
        if "min_at_most" in spec and min(values) > float(spec["min_at_most"]):
            return 0.0
        if "max_at_least" in spec and max(values) < float(spec["max_at_least"]):
            return 0.0
        if "min_at_least" in spec and min(values) < float(spec["min_at_least"]):
            return 0.0
        if "max_at_most" in spec and max(values) > float(spec["max_at_most"]):
            return 0.0

    return 1.0


def check_scikit_text_report(result_path: str, rules: Dict[str, Any]) -> float:
    """Check a text or PDF scientific report for required labels/terms."""
    if not _check_basic_file(result_path, rules):
        return 0.0

    text = _read_text(result_path)
    if not text:
        return 0.0
    return float(_check_text_keywords(text, rules, "report"))


def _image_size_with_pillow(path: str) -> Tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def _image_size_from_header(path: str) -> Tuple[int, int] | None:
    try:
        with open(path, "rb") as handle:
            data = handle.read(64)
    except OSError:
        return None

    if data.startswith(b"BM") and len(data) >= 26:
        return struct.unpack_from("<ii", data, 18)
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack_from(">II", data, 16)
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack_from("<HH", data, 6)
    if data.startswith((b"II*\x00", b"MM\x00*")):
        endian = "<" if data.startswith(b"II") else ">"
        try:
            with open(path, "rb") as handle:
                handle.seek(struct.unpack_from(endian + "I", data, 4)[0])
                count = struct.unpack(endian + "H", handle.read(2))[0]
                width = height = None
                for _ in range(count):
                    entry = handle.read(12)
                    tag, typ, num, value = struct.unpack(endian + "HHII", entry)
                    if tag == 256:
                        width = value
                    elif tag == 257:
                        height = value
                if width and height:
                    return int(width), int(height)
        except Exception:
            return None
    return None


def _read_bmp_rgb(path: str):
    try:
        import numpy as np

        with open(path, "rb") as handle:
            header = handle.read(54)
            if not header.startswith(b"BM") or len(header) < 54:
                return None
            offset = struct.unpack_from("<I", header, 10)[0]
            width = struct.unpack_from("<i", header, 18)[0]
            height = struct.unpack_from("<i", header, 22)[0]
            planes = struct.unpack_from("<H", header, 26)[0]
            bits = struct.unpack_from("<H", header, 28)[0]
            compression = struct.unpack_from("<I", header, 30)[0]
            if planes != 1 or bits != 24 or compression != 0 or width <= 0 or height == 0:
                return None
            abs_height = abs(height)
            row_stride = (width * 3 + 3) // 4 * 4
            handle.seek(offset)
            rows = []
            for _ in range(abs_height):
                row = handle.read(row_stride)[: width * 3]
                rows.append(np.frombuffer(row, dtype=np.uint8).reshape(width, 3)[:, ::-1])
            if height > 0:
                rows.reverse()
            return np.stack(rows, axis=0)
    except Exception as exc:
        logger.debug("SciKit BMP read failed: %s", exc)
        return None


def _read_image_rgb(path: str):
    try:
        import numpy as np
        from PIL import Image

        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"), dtype=np.uint8)
    except Exception:
        return _read_bmp_rgb(path)


def _check_image_content(path: str, rules: Dict[str, Any]) -> bool:
    if not any(key in rules for key in ("colorfulness_min", "center_brightness_ratio_min", "roi_contrast_min")):
        return True

    image = _read_image_rgb(path)
    if image is None:
        logger.debug("SciKit image content could not be read: %s", path)
        return False

    try:
        import numpy as np

        arr = image.astype(float)
        if "colorfulness_min" in rules:
            colorfulness = float(np.mean(np.std(arr, axis=2)))
            if colorfulness < float(rules["colorfulness_min"]):
                logger.debug("SciKit image colorfulness too low: %s", colorfulness)
                return False

        gray = arr.mean(axis=2)
        if "center_brightness_ratio_min" in rules:
            height, width = gray.shape
            y0, y1 = int(height * 0.45), int(height * 0.55)
            x0, x1 = int(width * 0.45), int(width * 0.55)
            ratio = float(gray[y0:y1, x0:x1].mean() / max(gray.mean(), 1e-6))
            if ratio < float(rules["center_brightness_ratio_min"]):
                logger.debug("SciKit image center brightness ratio too low: %s", ratio)
                return False

        if "roi_contrast_min" in rules:
            height, width = gray.shape
            x0, y0, x1, y1 = rules.get("roi_fraction", [0.55, 0.72, 0.98, 0.98])
            roi = gray[int(height * y0):int(height * y1), int(width * x0):int(width * x1)]
            if roi.size == 0 or float(roi.max() - roi.min()) < float(rules["roi_contrast_min"]):
                return False
    except Exception as exc:
        logger.debug("SciKit image content check failed: %s", exc)
        return False

    return True


def check_scikit_image_properties(result_path: str, rules: Dict[str, Any]) -> float:
    """Check that an exported microscope/spectrum image is readable enough."""
    if not _check_basic_file(result_path, rules):
        return 0.0

    size = _image_size_with_pillow(result_path) or _image_size_from_header(result_path)
    if not size:
        logger.debug("SciKit image size could not be read: %s", result_path)
        return 0.0

    width, height = size
    if width < int(rules.get("min_width", 1)) or height < int(rules.get("min_height", 1)):
        logger.debug("SciKit image too small: %sx%s", width, height)
        return 0.0

    if not _check_image_content(result_path, rules):
        return 0.0

    return 1.0
