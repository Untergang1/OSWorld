import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "train_data" / "generate_avantage_v3.py"
SPEC = importlib.util.spec_from_file_location("generate_avantage_v3", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class GenerateAvantageV3Tests(unittest.TestCase):
    @staticmethod
    def make_matched_target(identifier: str, image_name: str, index: int, raw_sha256: str = "raw") -> object:
        source = MODULE.SourceImage(
            image_name,
            Path("v2.png"),
            Path("raw.png"),
            Path("uia.json"),
            100,
            100,
            raw_sha256,
            "uia",
        )
        target = MODULE.Target(identifier, image_name, MODULE.Bbox(index, 2, index + 1, 4), "unknown")
        return MODULE.MatchedTarget(target, source, {"content": f"Control {index}"})

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
            "control_uid": "CONTROL_UID_SENTINEL", "type": "TYPE_SENTINEL", "content": "Open",
            "state": {"STATE_SENTINEL": "not-for-model"},
            "rect_screenshot": {"internal": "UIA_RECT_SENTINEL"},
            "ancestor_control_uids": ["ANCESTOR_SENTINEL"],
        }
        with tempfile.TemporaryDirectory() as directory:
            annotations = Path(directory) / "annotations.csv"
            annotations.write_text(
                "id,image,description,left,top,right,bottom,app_version\n"
                "avantage-target-001-01,sample.png,SOURCE_DESCRIPTION_SENTINEL,10,20,30,40,unknown\n",
                encoding="utf-8",
            )
            target = MODULE.load_targets(annotations)[0]
            matched = MODULE.MatchedTarget(target, source, element)
            messages = MODULE.build_messages([matched], b"full")
            serialized = json.dumps(messages)
            user_content = messages[1]["content"]
            prompt = user_content[0]["text"]
            image_parts = [part for part in user_content if part["type"] == "image_url"]
            self.assertNotIn("SOURCE_DESCRIPTION_SENTINEL", serialized)
            self.assertEqual([part["type"] for part in user_content], ["text", "image_url"])
            self.assertEqual(len(image_parts), 1)
            self.assertEqual(image_parts[0]["image_url"]["url"], MODULE.png_data_url(b"full"))
            self.assertIn("Target UIA content", prompt)
            self.assertIn("provided): Open\n", prompt)
            for forbidden in ("CONTROL_UID_SENTINEL", "TYPE_SENTINEL", "STATE_SENTINEL", "UIA_RECT_SENTINEL", "ANCESTOR_SENTINEL"):
                self.assertNotIn(forbidden, serialized)
            self.assertNotIn("context crop", prompt)

    def test_pending_batches_are_per_screenshot_and_never_exceed_ten_targets(self):
        first_image = [
            self.make_matched_target(f"avantage-target-{index:03d}-01", "first.png", index)
            for index in range(1, 12)
        ]
        second_image = [self.make_matched_target("avantage-target-012-01", "second.png", 12, "second-raw")]
        batches = list(MODULE.iter_pending_batches(first_image + second_image, {}))
        self.assertEqual([[item.target.image_name for item in batch] for batch in batches], [
            ["first.png"] * 10,
            ["first.png"],
            ["second.png"],
        ])

        completed = {first_image[0].target.checkpoint_key: "The File menu at the far left of the menu bar."}
        resumed_batches = list(MODULE.iter_pending_batches(first_image + second_image, completed))
        self.assertEqual([len(batch) for batch in resumed_batches], [10, 1])
        self.assertNotIn(first_image[0], resumed_batches[0])

        same_screenshot = [
            self.make_matched_target("avantage-target-013-01", "alias-a.png", 13, "shared-raw"),
            self.make_matched_target("avantage-target-014-01", "alias-b.png", 14, "shared-raw"),
        ]
        shared_batches = list(MODULE.iter_pending_batches(same_screenshot, {}))
        self.assertEqual([[item.target.image_name for item in batch] for batch in shared_batches], [
            ["alias-a.png", "alias-b.png"],
        ])

    def test_batch_response_requires_exact_ordinal_json_mapping(self):
        batch = [
            self.make_matched_target("avantage-target-001-01", "sample.png", 1),
            self.make_matched_target("avantage-target-002-01", "sample.png", 2),
        ]
        valid_response = json.dumps({
            "1": "The first control near the top of the window.",
            "2": "The second control near the top of the window.",
        })
        descriptions = MODULE.normalize_batch_descriptions(valid_response, batch)
        self.assertEqual(descriptions[batch[0].target.checkpoint_key], "The first control near the top of the window.")
        self.assertEqual(descriptions[batch[1].target.checkpoint_key], "The second control near the top of the window.")

        for invalid_response in (
            "not JSON",
            json.dumps(["The first control near the top of the window."]),
            json.dumps({"1": "The first control near the top of the window."}),
            json.dumps({"1": "The first control near the top of the window.", "2": 2}),
            json.dumps({"1": "The first control near the top of the window.", "2": "The second control near the top of the window.", "3": "Extra"}),
            '{"1": "The first control near the top of the window.", "1": "The second control near the top of the window.", "2": "The second control near the top of the window."}',
        ):
            with self.assertRaises(MODULE.GenerationError):
                MODULE.normalize_batch_descriptions(invalid_response, batch)

    def test_batch_request_scales_token_limit_to_target_count(self):
        batch = [
            self.make_matched_target("avantage-target-001-01", "sample.png", 1),
            self.make_matched_target("avantage-target-002-01", "sample.png", 2),
        ]

        class Completions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                        "1": "The first control near the top of the window.",
                        "2": "The second control near the top of the window.",
                    })))]
                )

        completions = Completions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        result = MODULE.request_descriptions(client, "model", [], 30, batch)
        self.assertEqual(completions.kwargs["max_tokens"], 320)
        self.assertEqual(len(result), 2)

    def test_generation_sends_one_multi_target_request_and_checkpoints_each_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_path = root / "raw.png"
            raw_path.write_bytes(b"full")
            source = MODULE.SourceImage(
                "sample.png", raw_path, raw_path, root / "uia.json", 100, 100, "raw", "uia"
            )
            first = MODULE.MatchedTarget(
                MODULE.Target("avantage-target-001-01", "sample.png", MODULE.Bbox(1, 2, 3, 4), "unknown"),
                source,
                {"content": "First"},
            )
            second = MODULE.MatchedTarget(
                MODULE.Target("avantage-target-002-01", "sample.png", MODULE.Bbox(5, 6, 7, 8), "unknown"),
                source,
                {"content": "Second"},
            )
            calls: list[dict[str, object]] = []

            class FakeOpenAI:
                def __init__(self, **kwargs):
                    self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

                def create(self, **kwargs):
                    calls.append(kwargs)
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                            "1": "The first control near the top of the window.",
                            "2": "The second control near the top of the window.",
                        })))]
                    )

            args = SimpleNamespace(
                output_dir=root / "output",
                model="model",
                api_key="key",
                base_url="url",
                timeout=30,
                max_retries=1,
                resume=False,
                overwrite=False,
            )
            with patch.object(MODULE, "require_generation_dependencies", return_value=FakeOpenAI), patch.object(
                MODULE, "append_checkpoint", wraps=MODULE.append_checkpoint
            ) as append_checkpoint:
                descriptions = MODULE.generate_descriptions(args, [first, second], {"sample.png": source})

            self.assertEqual(len(calls), 1)
            message_parts = calls[0]["messages"][1]["content"]
            self.assertEqual([part["type"] for part in message_parts], ["text", "image_url"])
            self.assertEqual(descriptions[first.target.checkpoint_key], "The first control near the top of the window.")
            self.assertEqual(descriptions[second.target.checkpoint_key], "The second control near the top of the window.")
            self.assertEqual(
                [call.args[1].identifier for call in append_checkpoint.call_args_list],
                [first.target.identifier, second.target.identifier],
            )

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
