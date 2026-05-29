from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List


EASY_CHROME_TASK_IDS = [
    "030eeff7-b492-4218-b312-701ec99ee0cc",
    "2ad9387a-65d8-4e33-ad5b-7580065a27ca",
    "2ae9ba84-3a0d-4d4c-8338-3a1478dc5fe3",
    "af630914-714e-4a24-a7bb-f9af687d3b91",
    "bb5e4c0d-f964-439c-97b6-bdb9747de3f4",
    "99146c54-4f37-4ab8-9327-5f3291665e1e",
    "12086550-11c0-466b-b367-1d9e75b3910e",
    "9656a811-9b5b-4ddf-99c7-5117bcef0626",
]

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _chrome_launch_step() -> Dict[str, Any]:
    return {
        "type": "launch",
        "parameters": {
            "command": [
                CHROME_EXE,
                "--remote-debugging-port=9222",
                "--remote-debugging-address=0.0.0.0",
                "--no-first-run",
                "--disable-features=ChromeWhatsNewUI",
            ]
        },
    }


def _chrome_kill_step() -> Dict[str, Any]:
    return {
        "type": "launch",
        "parameters": {
            "command": ["taskkill", "/IM", "chrome.exe", "/F", "/T"],
        },
    }


def _sleep_step(seconds: float) -> Dict[str, Any]:
    return {"type": "sleep", "parameters": {"seconds": seconds}}


def _safe_browsing_init_step() -> Dict[str, Any]:
    script = r"""
import json
import os

profile_dir = os.path.join(
    os.environ["LOCALAPPDATA"],
    "Google",
    "Chrome",
    "User Data",
    "Default",
)
os.makedirs(profile_dir, exist_ok=True)
pref_path = os.path.join(profile_dir, "Preferences")
try:
    with open(pref_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
except Exception:
    data = {}

data["safebrowsing"] = {"enabled": False, "enhanced": False}
with open(pref_path, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
"""
    return {
        "type": "execute",
        "parameters": {
            "command": ["python", "-c", script],
            "shell": False,
        },
    }


def _windows_config_for_task(task_id: str) -> List[Dict[str, Any]]:
    config: List[Dict[str, Any]] = []
    if task_id == "9656a811-9b5b-4ddf-99c7-5117bcef0626":
        config.append(_safe_browsing_init_step())
    config.append(_chrome_launch_step())
    return config


def _rewrite_postconfig(evaluator: Dict[str, Any]) -> Dict[str, Any]:
    evaluator = deepcopy(evaluator)
    postconfig = evaluator.get("postconfig")
    if not postconfig:
        return evaluator

    rewritten: List[Dict[str, Any]] = []
    for step in postconfig:
        command = step.get("parameters", {}).get("command", [])
        if step.get("type") == "launch" and command:
            executable = command[0] if isinstance(command, list) else command
            if executable in {"pkill", "killall"}:
                rewritten.append(_chrome_kill_step())
                continue
            if executable == "google-chrome":
                rewritten.append(_chrome_launch_step())
                continue
        rewritten.append(deepcopy(step))
    evaluator["postconfig"] = rewritten
    return evaluator


def migrate_task(source: Dict[str, Any]) -> Dict[str, Any]:
    task_id = source["id"]
    migrated = deepcopy(source)
    migrated["snapshot"] = "chrome"
    migrated["config"] = _windows_config_for_task(task_id)
    migrated["evaluator"] = _rewrite_postconfig(source["evaluator"])
    migrated["proxy"] = False
    migrated["fixed_ip"] = False
    migrated["windows_migration"] = {
        "source": "evaluation_examples/examples/chrome",
        "strategy": "easy_local_chrome_subset",
    }
    return migrated


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _parse_ids(raw_ids: str | None) -> List[str]:
    if not raw_ids:
        return EASY_CHROME_TASK_IDS
    return [item.strip() for item in raw_ids.split(",") if item.strip()]


def migrate(
    ids: Iterable[str],
    source_dir: Path,
    target_dir: Path,
    meta_path: Path,
    write: bool,
    force: bool,
) -> None:
    migrated_ids: List[str] = []
    for task_id in ids:
        source_path = source_dir / f"{task_id}.json"
        target_path = target_dir / f"{task_id}.json"
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        if target_path.exists() and write and not force:
            raise FileExistsError(f"{target_path} already exists; pass --force to overwrite.")

        source = _load_json(source_path)
        migrated = migrate_task(source)
        migrated_ids.append(task_id)

        print(f"{task_id}: {source_path} -> {target_path}")
        print(f"  config: {[step['type'] for step in source.get('config', [])]} -> {[step['type'] for step in migrated['config']]}")
        postconfig = migrated.get("evaluator", {}).get("postconfig", [])
        if postconfig:
            print(f"  postconfig: {[step['type'] for step in postconfig]}")
        if write:
            _write_json(target_path, migrated)

    meta = {"chrome": migrated_ids}
    print(f"meta: {meta_path}")
    if write:
        _write_json(meta_path, meta)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate an easy Chrome task subset to Windows OSWorld JSON.")
    parser.add_argument("--source-dir", type=Path, default=Path("evaluation_examples/examples/chrome"))
    parser.add_argument("--target-dir", type=Path, default=Path("evaluation_examples/examples_windows/chrome"))
    parser.add_argument("--meta-path", type=Path, default=Path("evaluation_examples/test_chrome_windows_easy.json"))
    parser.add_argument("--ids", default="", help="Comma-separated task ids. Defaults to the curated easy subset.")
    parser.add_argument("--dry-run", action="store_true", help="Preview only. This is the default unless --write is passed.")
    parser.add_argument("--write", action="store_true", help="Write migrated JSON files and meta file.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing migrated JSON files.")
    args = parser.parse_args()

    migrate(
        ids=_parse_ids(args.ids),
        source_dir=args.source_dir,
        target_dir=args.target_dir,
        meta_path=args.meta_path,
        write=args.write,
        force=args.force,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
