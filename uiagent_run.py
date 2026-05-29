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


def configure_osworld_environment(
    osworld_root: str,
    vmx: str,
    snapshot_name: str,
    os_type: str = "Windows",
    ready_timeout: float | None = None,
) -> None:
    os.environ["DESKTOP_BACKEND"] = "osworld_windows"
    os.environ["OSWORLD_ROOT"] = osworld_root
    os.environ["OSWORLD_PATH_TO_VM"] = vmx
    os.environ["OSWORLD_SNAPSHOT_NAME"] = snapshot_name
    os.environ["OSWORLD_OS_TYPE"] = os_type
    if ready_timeout is not None:
        os.environ["OSWORLD_READY_TIMEOUT"] = str(ready_timeout)


def import_uiagent_services(uiagent_root: str = ""):
    _insert_source_root_if_present()
    _insert_uiagent_path(uiagent_root)

    from services.execution_service import ExecutionService
    from services.support.task_store import store

    return ExecutionService, store


def start_uiagent_execution(service, task: str, task_config: dict | None = None) -> dict:
    task_parameters = {}
    if task_config:
        task_parameters["osworld_task_config"] = task_config

    return service.start_execution(
        task=task,
        device="osworld-windows",
        task_parameters=task_parameters,
        learn_routine_on_success=True,
    )


def poll_uiagent_execution(service, store, task_id: str, timeout: float, poll: float, stream: bool = True) -> dict:
    deadline = time.time() + timeout
    last_current = {}
    while time.time() < deadline:
        current = store.get_task("execution_tasks", task_id) or {}
        last_current = current
        status_line = {
            "status": current.get("status"),
            "stage": current.get("current_stage"),
            "error": current.get("error"),
        }
        if stream:
            print(json.dumps(status_line, ensure_ascii=False))
        if current.get("status") in {"succeeded", "failed", "stopped"}:
            return current
        time.sleep(poll)

    service.stop_execution(task_id, reason="uiagent_run.py timeout")
    timed_out = dict(last_current)
    timed_out.update({"status": "stopped", "error": "uiagent_run.py timeout", "task_id": task_id})
    return timed_out


def run_uiagent_task(
    task: str,
    *,
    uiagent_root: str = "",
    osworld_root: str = r"C:\Users\unter\OSWorld",
    vmx: str = r"C:\Users\unter\OSWorld\vmware_vm_data\Windows0\Windows0.vmx",
    snapshot_name: str = "init_state",
    os_type: str = "Windows",
    ready_timeout: float | None = None,
    task_config: dict | None = None,
    timeout: float = 1800.0,
    poll: float = 2.0,
    stream: bool = True,
) -> dict:
    configure_osworld_environment(osworld_root, vmx, snapshot_name, os_type, ready_timeout)
    ExecutionService, store = import_uiagent_services(uiagent_root)
    service = ExecutionService()
    task_record = start_uiagent_execution(service, task, task_config)
    task_id = task_record["task_id"]
    if stream:
        print(json.dumps({"task_id": task_id, "log_dir": task_record.get("log_dir")}, ensure_ascii=False))
    final_record = poll_uiagent_execution(service, store, task_id, timeout, poll, stream=stream)
    final_record.setdefault("task_id", task_id)
    final_record.setdefault("log_dir", task_record.get("log_dir"))
    return final_record


def main() -> int:
    parser = argparse.ArgumentParser(description="Run UIAgent against the OSWorld Windows VM.")
    parser.add_argument(
        "task",
        nargs="?",
        help="Natural-language task for UIAgent. If omitted, --task-config must contain an instruction field.",
    )
    parser.add_argument(
        "--uiagent-root",
        default="",
        help="Optional UIAgent source root. Leave empty when UIAgent was installed with `pip install -e .`.",
    )
    parser.add_argument("--osworld-root", default=r"C:\Users\unter\OSWorld")
    parser.add_argument("--vmx", default=r"C:\Users\unter\OSWorld\vmware_vm_data\Windows0\Windows0.vmx")
    parser.add_argument(
        "--snapshot-name",
        "--snapshot_name",
        dest="snapshot_name",
        default=None,
        help="OSWorld/VMware snapshot name to restore before running UIAgent. Defaults to task-config snapshot, then init_state.",
    )
    parser.add_argument(
        "--os-type",
        "--os_type",
        dest="os_type",
        default="Windows",
        help="OS type passed to the OSWorld backend.",
    )
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--ready-timeout", type=float, default=None, help="Seconds to wait for the OSWorld screenshot endpoint before failing.")
    parser.add_argument("--task-config", default="", help="Optional JSON file with an OSWorld task_config.")
    args = parser.parse_args()

    task_config = None
    if args.task_config:
        with open(args.task_config, "r", encoding="utf-8") as handle:
            task_config = json.load(handle)

    task_text = args.task
    if not task_text and task_config:
        task_text = task_config.get("instruction")
    if not task_text:
        parser.error("task is required unless --task-config contains an instruction field.")

    snapshot_name = args.snapshot_name
    if snapshot_name is None and task_config:
        snapshot_name = task_config.get("snapshot")
    if not snapshot_name:
        snapshot_name = "init_state"

    current = run_uiagent_task(
        task=task_text,
        uiagent_root=args.uiagent_root,
        osworld_root=args.osworld_root,
        vmx=args.vmx,
        snapshot_name=snapshot_name,
        os_type=args.os_type,
        ready_timeout=args.ready_timeout,
        task_config=task_config,
        timeout=args.timeout,
        poll=args.poll,
        stream=True,
    )
    print(json.dumps(current, ensure_ascii=False, indent=2))
    if current.get("error") == "uiagent_run.py timeout":
        return 2
    return 0 if current.get("status") == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
