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


def _status_snapshot(current: dict) -> dict:
    return {
        "status": current.get("status"),
        "stage": current.get("current_stage"),
        "error": current.get("error"),
        "current_step": current.get("current_step"),
        "total_steps": current.get("total_steps"),
    }


def _format_progress_line(snapshot: dict) -> str:
    status = snapshot.get("status") or "unknown"
    stage = snapshot.get("stage") or "unknown"
    current_step = snapshot.get("current_step")
    total_steps = snapshot.get("total_steps")
    step_text = ""
    if current_step not in (None, "") or total_steps not in (None, ""):
        step_text = f" step={current_step or 0}/{total_steps or 0}"
    error = snapshot.get("error")
    error_text = f" error={error}" if error else ""
    return f"Progress: status={status} stage={stage}{step_text}{error_text}"


def _print_start_summary(task_id: str, log_dir: str | None) -> None:
    print(f"Started UIAgent task {task_id}")
    if log_dir:
        print(f"Log: {log_dir}")


def _write_final_record(current: dict) -> str | None:
    log_dir = str(current.get("log_dir") or "").strip()
    if not log_dir:
        return None
    result_path = Path(log_dir) / "uiagent_run_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(result_path)


def _print_final_summary(current: dict, result_path: str | None = None) -> None:
    print(f"Finished: {current.get('status') or 'unknown'}")
    if current.get("error"):
        print(f"Error: {current.get('error')}")
    if current.get("log_dir"):
        print(f"Log: {current.get('log_dir')}")
    if result_path:
        print(f"Result: {result_path}")


def poll_uiagent_execution(
    service,
    store,
    task_id: str,
    timeout: float,
    poll: float,
    stream: bool = True,
    verbose: bool = False,
) -> dict:
    deadline = time.time() + timeout
    last_current = {}
    last_status_line = None
    while time.time() < deadline:
        current = store.get_task("execution_tasks", task_id) or {}
        last_current = current
        status_line = _status_snapshot(current)
        if stream:
            if verbose:
                print(json.dumps(status_line, ensure_ascii=False))
            elif status_line != last_status_line:
                print(_format_progress_line(status_line))
                last_status_line = dict(status_line)
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
    verbose: bool = False,
) -> dict:
    configure_osworld_environment(osworld_root, vmx, snapshot_name, os_type, ready_timeout)
    ExecutionService, store = import_uiagent_services(uiagent_root)
    service = ExecutionService()
    task_record = start_uiagent_execution(service, task, task_config)
    task_id = task_record["task_id"]
    if stream:
        if verbose:
            print(json.dumps({"task_id": task_id, "log_dir": task_record.get("log_dir")}, ensure_ascii=False))
        else:
            _print_start_summary(task_id, task_record.get("log_dir"))
    final_record = poll_uiagent_execution(service, store, task_id, timeout, poll, stream=stream, verbose=verbose)
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
    parser.add_argument("--verbose", action="store_true", help="Print detailed JSON status updates and final task record.")
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
        verbose=args.verbose,
    )
    result_path = None
    try:
        result_path = _write_final_record(current)
    except Exception as exc:
        print(f"Warning: failed to write final result into UIAgent log: {exc}")
    if args.verbose:
        print(json.dumps(current, ensure_ascii=False, indent=2))
    else:
        _print_final_summary(current, result_path)
    if current.get("error") == "uiagent_run.py timeout":
        return 2
    return 0 if current.get("status") == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
