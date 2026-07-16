"""Focused tests for the standalone manual UIA capture formatter."""

import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "train_data" / "capture_uia.py"
XML = """\
<desktop xmlns:state="https://accessibility.windows.example.org/ns/state"
         xmlns:component="https://accessibility.windows.example.org/ns/component">
  <pane name="Program Manager" class_name="Progman"
        component:screencoord="(0, 0)" component:size="(960, 540)">
    <button name="Desktop icon" state:visible="true" state:enabled="true"
            component:screencoord="(10, 10)" component:size="(20, 20)" />
  </pane>
  <window name="Target app" class_name="TargetWindow"
          component:screencoord="(100, 100)" component:size="(400, 300)">
    <button name="Save" state:visible="true" state:enabled="true" state:focused="true"
            component:screencoord="(120, 120)" component:size="(80, 30)" />
  </window>
  <window name="Background app" class_name="OtherWindow"
          component:screencoord="(500, 100)" component:size="(300, 300)">
    <button name="Do not keep" state:visible="true" state:enabled="true"
            component:screencoord="(510, 120)" component:size="(80, 30)" />
  </window>
</desktop>
"""


class CaptureUiaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("capture_uia", SCRIPT_PATH)
        assert spec is not None and spec.loader is not None
        cls.capture_uia = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.capture_uia)

    def test_filtered_payload_selects_focused_window_and_projects_dpi_coordinates(self):
        payload = self.capture_uia.build_filtered_payload(
            XML,
            image_width=1920,
            image_height=1080,
            capture_metadata={"captured_at": "2026-07-16T12:00:00.000"},
        )

        contents = {element["content"] for element in payload["elements"]}
        self.assertEqual(contents, {"Target app", "Save"})
        self.assertEqual(payload["filter_metadata"]["active_root_name"], "Target app")
        self.assertTrue(payload["coordinate_transform"]["enabled"])
        save_button = next(element for element in payload["elements"] if element["content"] == "Save")
        self.assertEqual(
            save_button["rect_screenshot"],
            {"left": 240, "top": 240, "right": 400, "bottom": 300, "width": 160, "height": 60},
        )

    def test_capture_writes_all_artifacts_after_validating_responses(self):
        image_buffer = io.BytesIO()
        self.capture_uia.Image.new("RGB", (1920, 1080), "white").save(image_buffer, format="PNG")

        class Response:
            def __init__(self, *, payload=None, content=b""):
                self.payload = payload
                self.content = content

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        responses = [
            Response(payload={"AT": XML}),
            Response(content=image_buffer.getvalue()),
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.object(self.capture_uia.requests, "get", side_effect=responses):
                capture_dir = self.capture_uia.capture("127.0.0.1", 5000, 1, Path(temporary_directory) / "captures")

            self.assertEqual(
                {path.name for path in capture_dir.iterdir()},
                {"raw_screenshot.png", "raw_accessibility.xml", "filtered_uia.json", "annotated_screenshot.png"},
            )
            filtered = self.capture_uia.json.loads((capture_dir / "filtered_uia.json").read_text(encoding="utf-8"))
            self.assertEqual([element["content"] for element in filtered["elements"]], ["Target app", "Save"])

    def test_invalid_xml_does_not_create_an_output_directory(self):
        class Response:
            def __init__(self, *, payload=None, content=b""):
                self.payload = payload
                self.content = content

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        image_buffer = io.BytesIO()
        self.capture_uia.Image.new("RGB", (10, 10), "white").save(image_buffer, format="PNG")

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "captures"
            responses = [Response(payload={"AT": "<desktop>"}), Response(content=image_buffer.getvalue())]
            with patch.object(self.capture_uia.requests, "get", side_effect=responses):
                with self.assertRaises(self.capture_uia.CaptureError):
                    self.capture_uia.capture("127.0.0.1", 5000, 1, output_root)
            self.assertFalse(output_root.exists())

    def test_mdi_child_focus_promotes_its_parent_window(self):
        xml = """\
<desktop xmlns:state="https://accessibility.windows.example.org/ns/state"
         xmlns:component="https://accessibility.windows.example.org/ns/component">
  <window name="Editor" class_name="MainWindow" component:screencoord="(0, 0)" component:size="(1000, 700)">
    <window name="Document" class_name="MDISpectralChild" component:screencoord="(100, 100)" component:size="(600, 400)">
      <button name="Focused control" state:focused="true" component:screencoord="(150, 150)" component:size="(80, 30)" />
    </window>
  </window>
</desktop>
"""
        payload = self.capture_uia.build_filtered_payload(
            xml, 1000, 700, {"captured_at": "2026-07-16T12:00:00.000"}
        )

        self.assertEqual(payload["filter_metadata"]["active_root_name"], "Editor")
        self.assertEqual(payload["filter_metadata"]["active_root_source"], "focus_promoted_to_window")
        self.assertEqual({element["content"] for element in payload["elements"]}, {"Editor", "Document", "Focused control"})

    def test_duplicate_controls_receive_distinct_uids(self):
        xml = """\
<desktop xmlns:component="https://accessibility.windows.example.org/ns/component">
  <window name="Target" component:screencoord="(0, 0)" component:size="(100, 100)">
    <button name="Duplicate" component:screencoord="(10, 10)" component:size="(20, 20)" />
    <button name="Duplicate" component:screencoord="(10, 10)" component:size="(20, 20)" />
  </window>
</desktop>
"""
        elements = self.capture_uia.build_elements(self.capture_uia.ET.fromstring(xml))
        duplicate_uids = [element["control_uid"] for element in elements if element["content"] == "Duplicate"]

        self.assertEqual(len(duplicate_uids), 2)
        self.assertEqual(len(set(duplicate_uids)), 2)
