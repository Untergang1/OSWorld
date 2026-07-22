import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "train_data" / "generate_avantage_v3.py"
SPEC = importlib.util.spec_from_file_location("generate_avantage_v3", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class GenerateAvantageV3Tests(unittest.TestCase):
    def test_normalize_description_handles_only_minor_wrappers(self):
        self.assertEqual(
            MODULE.normalize_description('Description: "The File menu at the far left of the menu bar."'),
            "The File menu at the far left of the menu bar.",
        )
        with self.assertRaises(MODULE.GenerationError):
            MODULE.normalize_description("Description:\nThe File menu.\nIt opens files.")

    def test_source_loader_does_not_expose_old_descriptions(self):
        targets = MODULE.load_targets(ROOT / "train_data" / "avantage" / "v2" / "annotations.csv")
        self.assertEqual(len(targets), 146)
        self.assertEqual({target.image_name for target in targets}, {
            "avantage_empty_workspace.png",
            "avantage_peak_table.png",
            "avantage_data_list.png",
        })
        self.assertFalse(any(hasattr(target, "description") for target in targets))
        self.assertTrue(all(target.identifier.endswith("-01") for target in targets))

    def test_checkpoint_binds_resume_to_its_fingerprint(self):
        target = MODULE.Target("avantage-target-001-01", "sample.png", MODULE.Bbox(1, 2, 3, 4), "unknown")
        matched = [SimpleNamespace(target=target)]
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "generation_checkpoint.jsonl"
            MODULE.initialize_checkpoint(checkpoint, "source-a")
            MODULE.append_checkpoint(checkpoint, target, "The File menu at the far left of the menu bar.")
            self.assertEqual(
                MODULE.load_checkpoint(checkpoint, matched, "source-a"),
                {target.checkpoint_key: "The File menu at the far left of the menu bar."},
            )
            with self.assertRaises(MODULE.GenerationError):
                MODULE.load_checkpoint(checkpoint, matched, "source-b")

    def test_checkpoint_rejects_non_object_json_rows(self):
        target = MODULE.Target("avantage-target-001-01", "sample.png", MODULE.Bbox(1, 2, 3, 4), "unknown")
        matched = [SimpleNamespace(target=target)]
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "generation_checkpoint.jsonl"
            checkpoint.write_text("[]\n", encoding="utf-8")
            with self.assertRaises(MODULE.GenerationError):
                MODULE.load_checkpoint(checkpoint, matched, "source-a")
            checkpoint.write_text(
                '{"kind":"metadata","fingerprint":"source-a"}\nnull\n', encoding="utf-8"
            )
            with self.assertRaises(MODULE.GenerationError):
                MODULE.load_checkpoint(checkpoint, matched, "source-a")

    def test_resume_can_continue_an_overwrite_while_old_csv_remains(self):
        target = MODULE.Target("avantage-target-001-01", "sample.png", MODULE.Bbox(1, 2, 3, 4), "unknown")
        matched = [SimpleNamespace(target=target)]
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "annotations.csv").write_text("old final CSV", encoding="utf-8")
            checkpoint, completed = MODULE.prepare_checkpoint(
                output_dir, matched, "source-a", resume=False, overwrite=True
            )
            self.assertEqual(completed, {})
            MODULE.append_checkpoint(checkpoint, target, "The File menu at the far left of the menu bar.")
            _, completed = MODULE.prepare_checkpoint(output_dir, matched, "source-a", resume=True, overwrite=False)
            self.assertIn(target.checkpoint_key, completed)
            self.assertEqual((output_dir / "annotations.csv").read_text(encoding="utf-8"), "old final CSV")

    def test_prompt_does_not_contain_a_source_description_field(self):
        source = MODULE.SourceImage("sample.png", Path("v2.png"), Path("raw.png"), Path("uia.json"), 100, 100, "raw", "uia")
        element = {
            "control_uid": "target", "type": "ButtonControl", "content": "Open", "state": {"enabled": True},
            "rect_screenshot": {"left": 10, "top": 20, "right": 30, "bottom": 40}, "ancestor_control_uids": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            annotations = Path(directory) / "annotations.csv"
            annotations.write_text(
                "id,image,description,left,top,right,bottom,app_version\n"
                "avantage-target-001-01,sample.png,SOURCE_DESCRIPTION_SENTINEL,10,20,30,40,unknown\n",
                encoding="utf-8",
            )
            target = MODULE.load_targets(annotations)[0]
            matched = MODULE.MatchedTarget(target, source, element, (element,))
            messages = MODULE.build_messages(matched, b"full", b"crop", (0, 0, 100, 100))
            serialized = json.dumps(messages)
            self.assertNotIn("SOURCE_DESCRIPTION_SENTINEL", serialized)
            self.assertIn("reported name/function: Open", serialized)

    def test_dry_run_validates_real_dataset_without_writing_output(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--dry-run"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("Validated 146 unique elements across 3 source screenshot(s).", result.stdout)
        self.assertIn("Dry run complete; no API calls or files were written.", result.stdout)


if __name__ == "__main__":
    unittest.main()
