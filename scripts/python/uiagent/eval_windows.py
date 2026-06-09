from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.python.uiagent.run_task import run_uiagent_task


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _jsonable_args(args: argparse.Namespace) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for key, value in vars(args).items():
        data[key] = str(value) if isinstance(value, Path) else value
    return data


def _append_jsonl(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(data, ensure_ascii=False))
        handle.write("\n")


def _make_run_id(domain: str) -> str:
    safe_domain = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in domain)
    return f"{datetime.now().strftime('%Y%m%d@%H%M%S')}_uiagent_{safe_domain}"


def _iter_examples(meta: Dict[str, List[str]], domain: str, ids: Optional[set[str]]) -> Iterable[tuple[str, str]]:
    domains = [domain] if domain != "all" else list(meta.keys())
    for domain_name in domains:
        for example_id in meta.get(domain_name, []):
            if ids and example_id not in ids:
                continue
            yield domain_name, example_id


def _load_example(examples_dir: Path, domain: str, example_id: str) -> Dict[str, Any]:
    path = examples_dir / domain / f"{example_id}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return _load_json(path)


def _task_snapshot(args: argparse.Namespace, example: Dict[str, Any]) -> str:
    return args.snapshot_name or example.get("snapshot") or "init_state"


def evaluate_current_vm(
    example: Dict[str, Any],
    *,
    env: Any,
    path_to_vm: str,
    provider_name: str,
    snapshot_name: str,
    os_type: str,
    screen_width: int,
    screen_height: int,
    headless: bool,
    close_after_eval: bool,
) -> float:
    del path_to_vm, provider_name, snapshot_name, os_type, screen_width, screen_height, headless, close_after_eval
    env._set_task_info(example)
    env.setup_controller.reset_cache_dir(env.cache_dir)
    return float(env.evaluate())


def run_one(
    args: argparse.Namespace,
    env: Any,
    domain: str,
    example_id: str,
    summary_path: Path,
) -> Dict[str, Any]:
    example = _load_example(args.examples_dir, domain, example_id)
    example_dir = args.result_dir / domain / example_id
    example_dir.mkdir(parents=True, exist_ok=True)

    result_path = example_dir / "result.txt"
    if args.resume and result_path.exists():
        score_text = result_path.read_text(encoding="utf-8").strip()
        row = {
            "domain": domain,
            "id": example_id,
            "skipped": True,
            "score": float(score_text) if score_text else None,
            "result_dir": str(example_dir),
        }
        _append_jsonl(summary_path, row)
        return row

    _write_json(example_dir / "task_config.json", example)
    (example_dir / "instruction.txt").write_text(example["instruction"], encoding="utf-8")

    started = time.time()
    uiagent_record: Dict[str, Any] = {}
    score: Optional[float] = None
    error: Optional[str] = None
    snapshot_name = _task_snapshot(args, example)

    try:
        if not args.evaluate_existing:
            uiagent_record = run_uiagent_task(
                example["instruction"],
                uiagent_root=args.uiagent_root,
                osworld_root=str(args.osworld_root),
                vmx=str(args.vmx),
                snapshot_name=snapshot_name,
                os_type=args.os_type,
                ready_timeout=args.ready_timeout,
                task_config=example,
                timeout=args.timeout_per_task,
                poll=args.poll,
                stream=args.stream_uiagent,
                env=env,
                provider_name=args.provider_name,
                screen_width=args.screen_width,
                screen_height=args.screen_height,
                headless=args.headless,
                max_steps=args.max_steps,
            )
            _write_json(example_dir / "uiagent_task.json", uiagent_record)

        if not args.no_evaluate:
            score = evaluate_current_vm(
                example,
                env=env,
                path_to_vm=str(args.vmx),
                provider_name=args.provider_name,
                snapshot_name=snapshot_name,
                os_type=args.os_type,
                screen_width=args.screen_width,
                screen_height=args.screen_height,
                headless=args.headless,
                close_after_eval=False,
            )
            result_path.write_text(f"{score}\n", encoding="utf-8")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        (example_dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")

    elapsed = time.time() - started
    row = {
        "domain": domain,
        "id": example_id,
        "snapshot": snapshot_name,
        "uiagent_status": uiagent_record.get("status"),
        "uiagent_error": uiagent_record.get("error"),
        "score": score,
        "elapsed_seconds": elapsed,
        "error": error,
        "result_dir": str(example_dir),
    }
    _append_jsonl(summary_path, row)
    print(json.dumps(row, ensure_ascii=False))
    return row


def _parse_ids(raw_ids: str) -> Optional[set[str]]:
    if not raw_ids:
        return None
    return {item.strip() for item in raw_ids.split(",") if item.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run UIAgent on Windows OSWorld task configs and score with OSWorld evaluators.")
    parser.add_argument("--uiagent-root", default="", help="Optional UIAgent source root; omit if UIAgent is pip-installed.")
    parser.add_argument("--osworld-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--vmx", type=Path, default=PROJECT_ROOT / "vmware_vm_data" / "Windows0" / "Windows0.vmx")
    parser.add_argument("--snapshot-name", "--snapshot_name", dest="snapshot_name", default=None)
    parser.add_argument("--os-type", "--os_type", dest="os_type", default="Windows")
    parser.add_argument("--provider-name", default="vmware")
    parser.add_argument("--examples-dir", type=Path, default=PROJECT_ROOT / "evaluation_examples" / "examples_windows")
    parser.add_argument("--meta", type=Path, default=PROJECT_ROOT / "evaluation_examples" / "test_chrome_windows_easy.json")
    parser.add_argument("--domain", default="chrome")
    parser.add_argument("--ids", default="", help="Comma-separated task ids to run.")
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N selected examples.")
    parser.add_argument("--result-dir", type=Path, default=PROJECT_ROOT / "results" / "uiagent")
    parser.add_argument("--run-id", default="", help="Optional run id under --result-dir.")
    parser.add_argument("--timeout-per-task", type=float, default=1800.0)
    parser.add_argument("--max-steps", "--max_steps", dest="max_steps", type=int, default=0, help="Override UIAgent controller max turns per task. 0 uses UIAgent config.")
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--ready-timeout", type=float, default=None)
    parser.add_argument("--screen-width", type=int, default=1920)
    parser.add_argument("--screen-height", type=int, default=1080)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-evaluate", action="store_true", help="Run UIAgent only; do not call OSWorld evaluator.")
    parser.add_argument("--evaluate-existing", action="store_true", help="Skip UIAgent and evaluate the current VM state.")
    parser.add_argument("--stop-after-eval", action="store_true", help="Stop the shared VM after the evaluation run.")
    parser.add_argument("--stream-uiagent", action="store_true", help="Print UIAgent polling status for each task.")
    args = parser.parse_args()
    if args.max_steps < 0:
        parser.error("--max_steps must be >= 0")

    os.environ["OSWORLD_ROOT"] = str(args.osworld_root)
    args.run_id = args.run_id or _make_run_id(args.domain)
    args.result_dir = args.result_dir / args.run_id

    meta = _load_json(args.meta)
    selected = list(_iter_examples(meta, args.domain, _parse_ids(args.ids)))
    if args.limit > 0:
        selected = selected[: args.limit]

    args.result_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.result_dir / "args.json", _jsonable_args(args))
    summary_path = args.result_dir / "summary.jsonl"
    print(f"Selected tasks: {len(selected)}")
    print(f"Summary: {summary_path}")

    from desktop_env.desktop_env import DesktopEnv

    initial_snapshot = args.snapshot_name or "init_state"
    env = DesktopEnv(
        provider_name=args.provider_name,
        path_to_vm=str(args.vmx),
        snapshot_name=initial_snapshot,
        action_space="pyautogui",
        screen_size=(args.screen_width, args.screen_height),
        headless=args.headless,
        require_a11y_tree=False,
        require_terminal=False,
        os_type=args.os_type,
        enable_proxy=False,
    )
    try:
        rows = [run_one(args, env, domain, example_id, summary_path) for domain, example_id in selected]
    finally:
        if args.stop_after_eval:
            env.close()
    scored_rows = [row for row in rows if row.get("score") is not None]
    if scored_rows:
        average = sum(float(row["score"]) for row in scored_rows) / len(scored_rows)
        print(f"Average score: {average:.4f} ({len(scored_rows)}/{len(rows)} scored)")
    else:
        print("No scores recorded.")

    failures = [row for row in rows if row.get("error")]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
