import json
import tempfile
import time
import unittest
from pathlib import Path

from scripts.python.uiagent.log_collection import (
    find_matching_uiagent_run,
    sync_uiagent_run_artifacts,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class UIAgentLogCollectionTests(unittest.TestCase):
    def test_find_matching_run_uses_osworld_task_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "20260610_120000_abcd1234"
            write_json(
                run_dir / "execution_episode.json",
                {
                    "task": "do the task",
                    "task_parameters": {"osworld_task_config": {"id": "task-1"}},
                    "steps": [],
                },
            )

            match = find_matching_uiagent_run(
                root,
                example_id="task-1",
                instruction="different text",
                started_after=time.time() - 5,
            )

            self.assertEqual(run_dir, match)

    def test_sync_exports_screenshots_traj_and_raw_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "execute" / "20260610_120000_abcd1234"
            screenshots = run_dir / "screenshots"
            screenshots.mkdir(parents=True)
            initial = screenshots / "initial_capture_001.png"
            after = screenshots / "step_001_after_capture_002.png"
            initial.write_bytes(b"initial-png")
            after.write_bytes(b"after-png")
            write_json(
                run_dir / "execution_episode.json",
                {
                    "schema_version": "execution_episode.v1",
                    "run_id": run_dir.name,
                    "task": "do the task",
                    "task_parameters": {"osworld_task_config": {"id": "task-1"}},
                    "start_page": {"screenshot": str(initial)},
                    "steps": [
                        {
                            "step_index": 1,
                            "controller_turn": 1,
                            "decision": "atomic_operation",
                            "decision_payload": {
                                "atomic_operation_type": "key_press",
                                "params": {"key": "A"},
                            },
                            "atomic_operation_type": "key_press",
                            "params": {"key": "A"},
                            "before": {"screenshot": str(initial)},
                            "after": {"screenshot": str(after)},
                            "result": {"status": "success"},
                            "created_at": "2026-06-10T12:00:01",
                        }
                    ],
                },
            )
            (run_dir / "execution_log.md").write_text("# log\n", encoding="utf-8")
            example_dir = root / "results" / "task-1"

            synced = sync_uiagent_run_artifacts(
                run_dir=run_dir,
                example_dir=example_dir,
                artifact_mode="copy",
            )

            self.assertTrue(synced)
            self.assertEqual(initial.read_bytes(), (example_dir / "step_0.png").read_bytes())
            self.assertEqual(after.read_bytes(), (example_dir / "step_1_20260610@120001.png").read_bytes())
            self.assertTrue((example_dir / "uiagent_artifacts" / run_dir.name / "execution_log.md").exists())
            self.assertEqual(f"{run_dir}\n", (example_dir / "uiagent_log_dir.txt").read_text(encoding="utf-8"))

            rows = [
                json.loads(line)
                for line in (example_dir / "traj.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(1, len(rows))
            self.assertEqual("key_press({\"key\": \"A\"})", rows[0]["action"])
            self.assertEqual("step_1_20260610@120001.png", rows[0]["screenshot_file"])
            self.assertEqual("partial", json.loads((example_dir / "uiagent_run_result.json").read_text(encoding="utf-8"))["status"])


if __name__ == "__main__":
    unittest.main()
