"""Capture and inspect the current OSWorld Windows UI Automation tree.

Run from the repository root after manually opening the target UI in a VM::

    python train_data/capture_uia.py --vm-ip 192.168.1.20
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import requests
from PIL import Image, ImageDraw, ImageFont


COMMON_DPI_SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)
BACKGROUND_NAMES = {"program manager", "desktop", "taskbar"}
BACKGROUND_CLASSES = {"progman", "workerw", "shell_traywnd", "shell_secondarytraywnd"}


class CaptureError(RuntimeError):
    """Raised when the VM cannot provide a complete capture."""


def local_name(name: str) -> str:
    return str(name or "").rsplit("}", 1)[-1]


def normalized_attributes(node: ET.Element) -> dict[str, str]:
    return {local_name(key): str(value) for key, value in node.attrib.items()}


def parse_pair(value: Any) -> tuple[int, int]:
    """Parse OSWorld's ``(x, y)`` XML attributes without evaluating code."""
    text = str(value or "").strip()
    if not text:
        return 0, 0
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, (tuple, list)) and len(parsed) >= 2:
            return int(float(parsed[0])), int(float(parsed[1]))
    except (ValueError, SyntaxError, TypeError):
        pass
    parts = [part.strip() for part in text.strip("()").split(",")]
    if len(parts) >= 2:
        try:
            return int(float(parts[0])), int(float(parts[1]))
        except ValueError:
            pass
    return 0, 0


def rect_from_attributes(attributes: dict[str, str]) -> dict[str, int]:
    left, top = parse_pair(attributes.get("screencoord"))
    width, height = parse_pair(attributes.get("size"))
    return {
        "left": left,
        "top": top,
        "right": left + width,
        "bottom": top + height,
        "width": width,
        "height": height,
    }


def has_rect(rect: dict[str, Any]) -> bool:
    return int(rect.get("width", 0) or 0) > 1 and int(rect.get("height", 0) or 0) > 1


def rect_area(rect: dict[str, Any]) -> int:
    return max(0, int(rect.get("width", 0) or 0)) * max(0, int(rect.get("height", 0) or 0))


def text_content(node: ET.Element, attributes: dict[str, str]) -> str:
    for value in (attributes.get("name"), (node.text or "").strip(), attributes.get("value"), attributes.get("automation_id")):
        if str(value or "").strip():
            return str(value).strip()
    return ""


def control_type(node: ET.Element, attributes: dict[str, str]) -> str:
    friendly_name = str(attributes.get("friendly_class_name") or "").strip()
    if friendly_name:
        suffix = "" if friendly_name.endswith("Control") else "Control"
        return f"{friendly_name[:1].upper()}{friendly_name[1:]}{suffix}"
    tag = local_name(node.tag).replace("-", " ").title().replace(" ", "")
    return f"{tag or 'Custom'}Control"


def bool_attribute(attributes: dict[str, str], name: str) -> Optional[bool]:
    if name not in attributes:
        return None
    value = attributes[name].strip().casefold()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    return None


def state_payload(attributes: dict[str, str]) -> dict[str, bool]:
    state: dict[str, bool] = {}
    for name in (
        "focused", "keyboard_focused", "has_keyboard_focus", "visible", "enabled",
        "minimized", "maximized", "normal", "selected", "expanded", "editable",
        "pressable",
    ):
        value = bool_attribute(attributes, name)
        if value is not None:
            state[name] = value
    return state


def stable_uid(
    attributes: dict[str, str], content: str, element_type: str, rect: dict[str, int], occurrence: int
) -> str:
    # Traversal occurrence keeps duplicate controls distinguishable inside one capture.
    source = json.dumps(
        {
            "automation_id": attributes.get("automation_id", ""),
            "control_id": attributes.get("control_id", ""),
            "window_id": attributes.get("window_id", ""),
            "class_name": attributes.get("class_name", ""),
            "type": element_type,
            "content": content,
            "rect": rect,
            "occurrence": occurrence,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    # hashlib is deliberately imported lazily so parsing remains easy to inspect.
    import hashlib

    return "osworld:" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:20]


def is_background_shell(element: dict[str, Any]) -> bool:
    content = str(element.get("content") or "").strip().casefold()
    locator = dict(element.get("locator") or {})
    class_name = str(locator.get("class_name") or "").strip().casefold()
    element_type = str(element.get("type") or "")
    return (
        content in BACKGROUND_NAMES
        or class_name in BACKGROUND_CLASSES
        or (element_type in {"ListboxControl", "PaneControl"} and content in {"desktop", "taskbar"})
    )


def is_window_root(element: dict[str, Any]) -> bool:
    element_type = str(element.get("type") or "")
    locator = dict(element.get("locator") or {})
    class_name = str(locator.get("class_name") or "").strip().casefold()
    content = str(element.get("content") or "").strip()
    return (
        element_type in {"WindowControl", "DialogControl"}
        or (class_name == "#32770" and element_type in {"WindowControl", "DialogControl"})
        or (element_type == "PaneControl" and content in {"Program Manager", "Taskbar"})
    )


def is_modal_dialog(element: dict[str, Any]) -> bool:
    element_type = str(element.get("type") or "")
    class_name = str((element.get("locator") or {}).get("class_name") or "").casefold()
    content = str(element.get("content") or "").strip().casefold()
    return element_type in {"WindowControl", "DialogControl"} and (
        class_name == "#32770" or content in {"open", "save", "save as"}
    ) and not is_background_shell(element)


def is_overlay(element: dict[str, Any]) -> bool:
    element_type = str(element.get("type") or "")
    class_name = str((element.get("locator") or {}).get("class_name") or "").casefold()
    return class_name == "#32768" or element_type in {"MenuControl", "MenuitemControl"}


def is_mdi_child_window(element: dict[str, Any]) -> bool:
    element_type = str(element.get("type") or "")
    class_name = str((element.get("locator") or {}).get("class_name") or "").casefold()
    return element_type in {"WindowControl", "DialogControl"} and class_name == "mdispectralchild"


def build_elements(root: ET.Element) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    stack: list[tuple[ET.Element, int, list[str], list[str], Optional[str]]] = [(root, 0, [], [], None)]
    while stack:
        node, depth, ancestor_uids, ancestor_window_uids, parent_uid = stack.pop()
        attributes = normalized_attributes(node)
        rect = rect_from_attributes(attributes)
        element_uid: Optional[str] = None
        next_ancestors = list(ancestor_uids)
        next_window_ancestors = list(ancestor_window_uids)
        if has_rect(rect):
            element_type = control_type(node, attributes)
            content = text_content(node, attributes)
            element_uid = stable_uid(attributes, content, element_type, rect, len(elements))
            center = {"x": rect["left"] + rect["width"] // 2, "y": rect["top"] + rect["height"] // 2}
            locator = {
                "kind": "uia",
                "automation_id": attributes.get("automation_id", ""),
                "class_name": attributes.get("class_name") or local_name(node.tag),
                "type": element_type,
                "name": attributes.get("name") or content,
                "depth": depth,
                "control_uid": element_uid,
            }
            for name in ("access_key", "accelerator_key", "help_text", "window_id", "control_id"):
                if attributes.get(name):
                    locator[name] = attributes[name]
            if node.text and node.text.strip():
                locator["text"] = node.text.strip()
            element = {
                "ID": len(elements),
                "type": element_type,
                "content": content,
                "capabilities": ["click"],
                "control_uid": element_uid,
                "rect_screen": rect,
                "center_screen": center,
                "clickable_point": {**center, "available": True},
                "locator": locator,
                "state": state_payload(attributes),
                "ancestor_control_uids": list(ancestor_uids),
                "ancestor_window_uids": list(ancestor_window_uids),
                "parent_control_uid": parent_uid,
                "geometry_source": "osworld_accessibility",
            }
            element["is_background_shell"] = is_background_shell(element)
            elements.append(element)
            next_ancestors.append(element_uid)
            if is_window_root(element):
                next_window_ancestors.append(element_uid)

        children = list(node)
        for child in reversed(children):
            stack.append((child, depth + 1, next_ancestors, next_window_ancestors, element_uid or parent_uid))
    return elements


def near_common_dpi_scale(scale: float) -> bool:
    return any(abs(scale - candidate) <= 0.035 for candidate in COMMON_DPI_SCALES)


def coordinate_root_score(element: dict[str, Any], image_width: int, image_height: int) -> tuple[int, int]:
    rect = dict(element.get("rect_screen") or {})
    if not has_rect(rect):
        return 0, 0
    if abs(int(rect["left"])) > 3 or abs(int(rect["top"])) > 3:
        return 0, rect_area(rect)
    content = str(element.get("content") or "").casefold()
    class_name = str((element.get("locator") or {}).get("class_name") or "").casefold()
    score = 0
    if content in {"program manager", "desktop"}:
        score += 80
    if class_name in {"progman", "workerw"}:
        score += 60
    if is_background_shell(element):
        score += 40
    if element.get("type") in {"PaneControl", "WindowControl"}:
        score += 10
    scale_x, scale_y = image_width / rect["width"], image_height / rect["height"]
    if abs(scale_x - scale_y) / max(scale_x, scale_y, 1e-6) <= 0.03:
        score += 20
    if near_common_dpi_scale((scale_x + scale_y) / 2.0):
        score += 15
    if min(rect["width"] / max(1, image_width), rect["height"] / max(1, image_height)) >= 0.60:
        score += 10
    return score, rect_area(rect)


def infer_coordinate_transform(elements: list[dict[str, Any]], image_width: int, image_height: int) -> dict[str, Any]:
    identity = {
        "enabled": False, "source": "identity", "confidence": 1.0,
        "scale_x": 1.0, "scale_y": 1.0, "offset_x": 0.0, "offset_y": 0.0,
        "screenshot_space": "physical", "action_space": "uia",
    }
    candidates = [element for element in elements if coordinate_root_score(element, image_width, image_height)[0] > 0]
    if not candidates:
        return {**identity, "reason": "no_high_confidence_root"}
    root = max(candidates, key=lambda element: coordinate_root_score(element, image_width, image_height))
    score, _ = coordinate_root_score(root, image_width, image_height)
    rect = dict(root["rect_screen"])
    scale_x, scale_y = image_width / rect["width"], image_height / rect["height"]
    average_scale = (scale_x + scale_y) / 2.0
    if score < 80 or abs(scale_x - scale_y) / max(scale_x, scale_y, 1e-6) > 0.03 or not near_common_dpi_scale(average_scale):
        return {**identity, "reason": "low_confidence_or_nonuniform_root"}
    return {
        "enabled": abs(average_scale - 1.0) > 0.035,
        "source": "fullscreen_root_ratio" if abs(average_scale - 1.0) > 0.035 else "identity_root_ratio",
        "confidence": 0.99 if score >= 120 else 0.9,
        "scale_x": round(scale_x, 6), "scale_y": round(scale_y, 6),
        "offset_x": 0.0, "offset_y": 0.0,
        "screenshot_space": "physical", "action_space": "uia",
        "reference_element": {"content": root["content"], "type": root["type"], "rect_screen": rect},
    }


def project_elements(elements: Iterable[dict[str, Any]], image_width: int, image_height: int, transform: dict[str, Any]) -> None:
    scale_x, scale_y = float(transform["scale_x"]), float(transform["scale_y"])
    for element in elements:
        rect = dict(element["rect_screen"])
        projected = {
            "left": round(rect["left"] * scale_x), "top": round(rect["top"] * scale_y),
            "right": round(rect["right"] * scale_x), "bottom": round(rect["bottom"] * scale_y),
        }
        projected["width"] = max(0, projected["right"] - projected["left"])
        projected["height"] = max(0, projected["bottom"] - projected["top"])
        element["rect_screenshot"] = projected
        element["center_screenshot"] = {
            "x": projected["left"] + projected["width"] // 2,
            "y": projected["top"] + projected["height"] // 2,
        }
        element["bbox"] = [
            max(0.0, min(1.0, projected["left"] / image_width)),
            max(0.0, min(1.0, projected["top"] / image_height)),
            max(0.0, min(1.0, projected["right"] / image_width)),
            max(0.0, min(1.0, projected["bottom"] / image_height)),
        ]


def infer_active_root(elements: list[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], str]:
    roots = [element for element in elements if is_window_root(element)]
    by_uid = {str(root["control_uid"]): root for root in roots}

    def promoted_root(root: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        if not is_mdi_child_window(root):
            return root, False
        for uid in reversed(root.get("ancestor_window_uids", [])):
            candidate = by_uid.get(str(uid))
            if candidate and not is_background_shell(candidate) and not is_mdi_child_window(candidate):
                return candidate, True
        return root, False

    for state_names, source in ((("keyboard_focused", "has_keyboard_focus"), "keyboard_focus"), (("focused",), "focus")):
        for element in elements:
            if not any(element.get("state", {}).get(name) for name in state_names):
                continue
            for uid in reversed(list(element.get("ancestor_control_uids") or []) + [element["control_uid"]]):
                if uid in by_uid:
                    root = by_uid[uid]
                    if is_modal_dialog(root):
                        return root, f"modal_dialog_{source}"
                    root, promoted = promoted_root(root)
                    return root, f"{source}_promoted_to_window" if promoted else source
    non_shell_roots = [root for root in roots if not is_background_shell(root)]
    modal_roots = [root for root in non_shell_roots if is_modal_dialog(root)]
    if modal_roots:
        return max(modal_roots, key=lambda root: rect_area(root["rect_screen"])), "modal_dialog"
    if non_shell_roots:
        return max(non_shell_roots, key=lambda root: rect_area(root["rect_screen"])), "largest_non_shell_window"
    if roots:
        return max(roots, key=lambda root: rect_area(root["rect_screen"])), "largest_root"
    return None, "none"


def rect_center_in_rect(rect: dict[str, Any], bounds: dict[str, Any]) -> bool:
    x = int(rect["left"]) + int(rect["width"]) // 2
    y = int(rect["top"]) + int(rect["height"]) // 2
    return int(bounds["left"]) <= x <= int(bounds["right"]) and int(bounds["top"]) <= y <= int(bounds["bottom"])


def visible_ratio(rect: dict[str, Any], bounds: dict[str, Any]) -> float:
    left, top = max(int(rect["left"]), int(bounds["left"])), max(int(rect["top"]), int(bounds["top"]))
    right, bottom = min(int(rect["right"]), int(bounds["right"])), min(int(rect["bottom"]), int(bounds["bottom"]))
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top) / max(1, rect_area(rect))


def filter_elements(elements: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_root, source = infer_active_root(elements)
    metadata: dict[str, Any] = {"active_root_source": source, "prefilter_count": len(elements)}
    if not active_root:
        metadata.update({"active_root_name": "", "filtered_count": len(elements), "suppressed_background_count": 0})
        return elements, metadata
    active_uid = str(active_root["control_uid"])
    active_rect = dict(active_root["rect_screen"])
    supports_ancestry = any(active_uid == element["control_uid"] or active_uid in element.get("ancestor_control_uids", []) for element in elements)
    filtered = [
        element for element in elements
        if (not supports_ancestry or active_uid == element["control_uid"] or active_uid in element.get("ancestor_control_uids", []))
        and (
            rect_center_in_rect(element["rect_screen"], active_rect)
            or visible_ratio(element["rect_screen"], active_rect) >= 0.50
        )
    ]
    existing_uids = {element["control_uid"] for element in filtered}
    filtered.extend(
        element for element in elements
        if element["control_uid"] not in existing_uids
        and is_overlay(element)
        and active_uid in element.get("ancestor_window_uids", [])
    )
    suppressed = 0
    if not is_background_shell(active_root):
        background_uids = {element["control_uid"] for element in elements if is_background_shell(element)}
        kept = []
        for element in filtered:
            if element["control_uid"] in background_uids or background_uids.intersection(element.get("ancestor_control_uids", [])):
                suppressed += 1
            else:
                kept.append(element)
        filtered = kept
    for index, element in enumerate(filtered):
        element["ID"] = index
    metadata.update({
        "active_root_name": active_root.get("content", ""), "active_root_uid": active_uid,
        "filtered_count": len(filtered), "suppressed_background_count": suppressed,
    })
    return filtered, metadata


def build_filtered_payload(xml_text: str, image_width: int, image_height: int, capture_metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as error:
        raise CaptureError(f"The VM returned invalid accessibility XML: {error}") from error
    elements = build_elements(root)
    transform = infer_coordinate_transform(elements, image_width, image_height)
    project_elements(elements, image_width, image_height, transform)
    filtered, filter_metadata = filter_elements(elements)
    return {
        "captured_at": capture_metadata["captured_at"],
        "capture": capture_metadata,
        "monitor": {"left": 0, "top": 0, "right": image_width, "bottom": image_height, "width": image_width, "height": image_height},
        "backend": "osworld_windows_accessibility",
        "coordinate_transform": transform,
        "filter_metadata": filter_metadata,
        "elements": filtered,
    }


def annotate_screenshot(image_bytes: bytes, elements: Iterable[dict[str, Any]], output_path: Path) -> None:
    with Image.open(io.BytesIO(image_bytes)).convert("RGB") as image:
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        for element in elements:
            rect = dict(element["rect_screenshot"])
            x1, y1 = max(0, rect["left"]), max(0, rect["top"])
            x2, y2 = min(image.width, rect["right"]), min(image.height, rect["bottom"])
            if x2 <= x1 or y2 <= y1:
                continue
            draw.rectangle((x1, y1, x2, y2), outline=(230, 71, 54), width=2)
            label = str(element["ID"])
            label_box = draw.textbbox((0, 0), label, font=font)
            label_width, label_height = label_box[2] - label_box[0], label_box[3] - label_box[1]
            label_top = max(0, y1 - label_height - 4)
            draw.rectangle((x1, label_top, x1 + label_width + 6, label_top + label_height + 4), fill=(18, 18, 18))
            draw.text((x1 + 3, label_top + 2), label, fill=(255, 255, 255), font=font)
        image.save(output_path, format="PNG")


def fetch_capture(base_url: str, timeout: float) -> tuple[str, bytes, dict[str, Any]]:
    try:
        accessibility_response = requests.get(f"{base_url}/accessibility", timeout=timeout)
        accessibility_response.raise_for_status()
        payload = accessibility_response.json()
        xml_text = payload.get("AT") if isinstance(payload, dict) else None
        if not isinstance(xml_text, str) or not xml_text.strip():
            raise CaptureError("The /accessibility response did not contain a non-empty 'AT' XML string.")
        accessibility_at = datetime.now().isoformat(timespec="milliseconds")

        screenshot_response = requests.get(f"{base_url}/screenshot", timeout=timeout)
        screenshot_response.raise_for_status()
        image_bytes = screenshot_response.content
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.verify()
        screenshot_at = datetime.now().isoformat(timespec="milliseconds")
    except requests.RequestException as error:
        raise CaptureError(f"Could not reach the VM service at {base_url}: {error}") from error
    except (OSError, ValueError) as error:
        raise CaptureError(f"The /screenshot response was not a valid image: {error}") from error
    return xml_text, image_bytes, {
        "captured_at": screenshot_at,
        "capture_order": ["accessibility", "screenshot"],
        "accessibility_captured_at": accessibility_at,
        "screenshot_captured_at": screenshot_at,
        "server_url": base_url,
    }


def new_capture_directory(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    base_name = datetime.now().strftime("%m%d_%H%M%S")
    candidate = root / base_name
    suffix = 1
    while candidate.exists():
        candidate = root / f"{base_name}_{suffix:02d}"
        suffix += 1
    candidate.mkdir()
    return candidate


def capture(vm_ip: str, server_port: int, timeout: float, output_root: Path) -> Path:
    base_url = f"http://{vm_ip}:{server_port}"
    xml_text, image_bytes, capture_metadata = fetch_capture(base_url, timeout)
    with Image.open(io.BytesIO(image_bytes)) as image:
        width, height = image.size
    filtered_payload = build_filtered_payload(xml_text, width, height, capture_metadata)

    # Create files only after both remote responses and all parsing have succeeded.
    capture_dir = new_capture_directory(output_root)
    try:
        (capture_dir / "raw_screenshot.png").write_bytes(image_bytes)
        (capture_dir / "raw_accessibility.xml").write_text(xml_text, encoding="utf-8")
        (capture_dir / "filtered_uia.json").write_text(
            json.dumps(filtered_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        annotate_screenshot(image_bytes, filtered_payload["elements"], capture_dir / "annotated_screenshot.png")
    except Exception:
        # Retain no directory whose four artifacts do not describe one complete capture.
        for path in capture_dir.iterdir():
            path.unlink()
        capture_dir.rmdir()
        raise
    return capture_dir


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture the current OSWorld VM screenshot and Windows UIA tree.")
    parser.add_argument("--vm-ip", required=True, help="VM service address, for example 192.168.1.20 or localhost")
    parser.add_argument("--server-port", type=int, default=5000, help="OSWorld VM service port (default: 5000)")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds (default: 20)")
    parser.add_argument("--output-root", type=Path, default=Path(__file__).parent / "captures", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        capture_dir = capture(args.vm_ip, args.server_port, args.timeout, args.output_root)
    except CaptureError as error:
        print(f"Capture failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # Keep CLI failures concise while preserving a nonzero exit status.
        print(f"Capture failed unexpectedly: {error}", file=sys.stderr)
        return 1
    print(f"Saved UIA capture to: {capture_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
