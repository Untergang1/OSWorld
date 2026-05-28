from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _insert_uiagent_path(path: str) -> None:
    if not path:
        return
    root = str(Path(path).expanduser().resolve())
    if root not in sys.path:
        sys.path.insert(0, root)


def _insert_source_root_if_present() -> None:
    script_path = Path(__file__).resolve()
    for parent in script_path.parents:
        has_execution_service = (parent / "services" / "execution_service.py").exists()
        has_osworld_backend = (parent / "backend" / "osworld_windows").exists()
        if has_execution_service and has_osworld_backend:
            _insert_uiagent_path(str(parent))
            return


def main() -> int:
    parser = argparse.ArgumentParser(description="Run UIAgent against the OSWorld Windows VM.")
    parser.add_argument("task", help="Natural-language task for UIAgent.")
    parser.add_argument(
        "--uiagent-root",
        default="",
        help="Optional UIAgent source root. Leave empty when UIAgent was installed with `pip install -e .`.",
    )
    parser.add_argument("--osworld-root", default=r"C:\Users\unter\OSWorld")
    parser.add_argument("--vmx", default=r"C:\Users\unter\OSWorld\vmware_vm_data\Windows0\Windows0.vmx")
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--ready-timeout", type=float, default=None, help="Seconds to wait for the OSWorld screenshot endpoint before failing.")
    parser.add_argument("--task-config", default="", help="Optional JSON file with an OSWorld task_config.")
    args = parser.parse_args()

    _insert_source_root_if_present()
    _insert_uiagent_path(args.uiagent_root)
    os.environ["DESKTOP_BACKEND"] = "osworld_windows"
    os.environ["OSWORLD_ROOT"] = args.osworld_root
    os.environ["OSWORLD_PATH_TO_VM"] = args.vmx
    if args.ready_timeout is not None:
        os.environ["OSWORLD_READY_TIMEOUT"] = str(args.ready_timeout)

    from services.execution_service import ExecutionService
    from services.support.task_store import store

    task_parameters = {}
    if args.task_config:
        with open(args.task_config, "r", encoding="utf-8") as handle:
            task_parameters["osworld_task_config"] = json.load(handle)

    service = ExecutionService()
    task = service.start_execution(
        task=args.task,
        device="osworld-windows",
        task_parameters=task_parameters,
        learn_routine_on_success=True,
    )
    task_id = task["task_id"]
    print(json.dumps({"task_id": task_id, "log_dir": task.get("log_dir")}, ensure_ascii=False))

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        current = store.get_task("execution_tasks", task_id) or {}
        print(json.dumps({"status": current.get("status"), "stage": current.get("current_stage"), "error": current.get("error")}, ensure_ascii=False))
        if current.get("status") in {"succeeded", "failed", "stopped"}:
            print(json.dumps(current, ensure_ascii=False, indent=2))
            return 0 if current.get("status") == "succeeded" else 1
        time.sleep(args.poll)
    service.stop_execution(task_id, reason="uiagent_run.py timeout")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
