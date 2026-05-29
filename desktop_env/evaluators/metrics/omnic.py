import logging
import os
import re
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("desktopenv.metric.omnic")


_NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _check_basic_file(path: str, rules: Dict[str, Any]) -> bool:
    if not path or not os.path.isfile(path):
        logger.debug("OMNIC metric: result file missing: %s", path)
        return False

    min_bytes = int(rules.get("min_bytes", 1))
    if _safe_size(path) < min_bytes:
        logger.debug("OMNIC metric: file too small: %s", path)
        return False

    extension = rules.get("extension")
    if extension and not path.lower().endswith(str(extension).lower()):
        logger.debug("OMNIC metric: extension mismatch: %s", path)
        return False

    basename = rules.get("basename")
    if basename and os.path.basename(path) != basename:
        logger.debug("OMNIC metric: basename mismatch: %s", path)
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


def _numeric_rows(text: str) -> List[Tuple[float, ...]]:
    rows: List[Tuple[float, ...]] = []
    for line in text.splitlines():
        values = tuple(float(match.group(0)) for match in _NUMBER_RE.finditer(line))
        if len(values) >= 2:
            rows.append(values)
    return rows


def _wavenumber_values(rows: List[Tuple[float, ...]]) -> List[float]:
    values = []
    for row in rows:
        for value in row:
            if 350 <= value <= 4500:
                values.append(value)
                break
    return values


def check_omnic_file_metadata(result_path: str, rules: Dict[str, Any]) -> float:
    """Check that OMNIC produced the requested output file."""
    return float(_check_basic_file(result_path, rules))


def check_omnic_export_table(result_path: str, rules: Dict[str, Any]) -> float:
    """Check a text/CSV spectrum export for parseable spectral data."""
    if not _check_basic_file(result_path, rules):
        return 0.0

    text = _read_text(result_path)
    if not text:
        return 0.0

    lowered = text.lower()
    for keyword in rules.get("include_keywords", []):
        if str(keyword).lower() not in lowered:
            logger.debug("OMNIC export table missing keyword: %s", keyword)
            return 0.0

    rows = _numeric_rows(text)
    if len(rows) < int(rules.get("min_numeric_rows", 20)):
        logger.debug("OMNIC export table has too few numeric rows: %d", len(rows))
        return 0.0

    wavenumbers = _wavenumber_values(rows)
    if not wavenumbers:
        return 0.0

    min_wavenumber = rules.get("min_wavenumber")
    if min_wavenumber is not None and min(wavenumbers) > float(min_wavenumber):
        logger.debug("OMNIC export table does not reach low wavenumber bound")
        return 0.0

    max_wavenumber = rules.get("max_wavenumber")
    if max_wavenumber is not None and max(wavenumbers) < float(max_wavenumber):
        logger.debug("OMNIC export table does not reach high wavenumber bound")
        return 0.0

    max_ranges = rules.get("normalized_max_ranges")
    if max_ranges:
        y_values = [row[1] for row in rows if len(row) >= 2]
        if not y_values:
            return 0.0
        y_max = max(y_values)
        if not any(float(low) <= y_max <= float(high) for low, high in max_ranges):
            logger.debug("OMNIC export table max intensity outside normalized ranges: %s", y_max)
            return 0.0

    return 1.0


def check_omnic_peak_table(result_path: str, rules: Dict[str, Any]) -> float:
    """Check that exported peak positions include all expected bands."""
    if not _check_basic_file(result_path, rules):
        return 0.0

    text = _read_text(result_path)
    rows = _numeric_rows(text)
    peak_values = _wavenumber_values(rows)
    if not peak_values:
        return 0.0

    tolerance = float(rules.get("tolerance", 8))
    for expected_peak in rules.get("expected_peaks", []):
        expected = float(expected_peak)
        if not any(abs(value - expected) <= tolerance for value in peak_values):
            logger.debug("OMNIC peak table missing expected peak: %s", expected)
            return 0.0

    return 1.0


def check_omnic_image_export(result_path: str, rules: Dict[str, Any]) -> float:
    """Check that OMNIC exported a readable spectrum image."""
    if not _check_basic_file(result_path, rules):
        return 0.0

    try:
        from PIL import Image

        with Image.open(result_path) as image:
            width, height = image.size
            min_width = int(rules.get("min_width", 1))
            min_height = int(rules.get("min_height", 1))
            return float(width >= min_width and height >= min_height)
    except Exception as exc:
        logger.debug("OMNIC image export is not readable: %s", exc)
        return 0.0


def check_omnic_text_contains(result_path: str, rules: Dict[str, Any]) -> float:
    """Check that an OMNIC text export contains expected words."""
    if not _check_basic_file(result_path, rules):
        return 0.0

    text = _read_text(result_path)
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
            logger.debug("OMNIC text export missing keyword: %s", keyword)
            return 0.0

    if alternatives and not any(keyword in haystack for keyword in alternatives):
        logger.debug("OMNIC text export missing all alternative keywords")
        return 0.0

    return 1.0


def check_omnic_pdf_text(result_path: str, rules: Dict[str, Any]) -> float:
    """Check that an OMNIC PDF report exists and contains expected text."""
    if not _check_basic_file(result_path, rules):
        return 0.0

    try:
        import pdfplumber

        with pdfplumber.open(result_path) as pdf:
            if len(pdf.pages) < int(rules.get("min_pages", 1)):
                return 0.0
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:
        logger.debug("OMNIC PDF export is not readable: %s", exc)
        return 0.0

    lowered = text.lower()
    for keyword in rules.get("include_keywords", []):
        if str(keyword).lower() not in lowered:
            logger.debug("OMNIC PDF missing keyword: %s", keyword)
            return 0.0

    alternatives = rules.get("include_any_keywords", [])
    if alternatives and not any(str(keyword).lower() in lowered for keyword in alternatives):
        logger.debug("OMNIC PDF missing all alternative keywords")
        return 0.0

    return 1.0
