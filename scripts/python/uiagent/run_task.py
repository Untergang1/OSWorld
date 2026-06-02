from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _prepend_python_path(path: str | Path) -> None:
    root = str(Path(path).expanduser().resolve())
    if not root:
        return
    sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != root]
    sys.path.insert(0, root)


def _is_uiagent_root(path: Path) -> bool:
    return (
        (path / "services" / "execution_service.py").exists()
        and (path / "backend" / "osworld_windows").exists()
    )


def _insert_source_root_if_present() -> None:
    script_path = Path(__file__).resolve()
    for parent in script_path.parents:
        if _is_uiagent_root(parent):
            _prepend_python_path(parent)
            return


def _resolve_uiagent_root(explicit_root: str = "") -> Path | None:
    if explicit_root:
        root = Path(explicit_root).expanduser().resolve()
        if not _is_uiagent_root(root):
            raise FileNotFoundError(f"--uiagent-root does not look like a UIAgent checkout: {root}")
        return root

    _insert_source_root_if_present()
    spec = importlib.util.find_spec("services.execution_service")
    if not spec or not spec.origin:
        return None
    root = Path(spec.origin).resolve().parents[1]
    return root if _is_uiagent_root(root) else None


def _same_path(left: str | None, right: Path) -> bool:
    if not left:
        return False
    try:
        return Path(left).resolve() == right.resolve()
    except OSError:
        return False


def _ensure_uiagent_config(uiagent_root: Path | None) -> None:
    expected_config = uiagent_root / "config.py" if uiagent_root else None
    if uiagent_root:
        _prepend_python_path(uiagent_root)

    loaded_config = sys.modules.get("config")
    loaded_path = getattr(loaded_config, "__file__", None)
    if expected_config and loaded_config is not None and not _same_path(loaded_path, expected_config):
        del sys.modules["config"]

    config_module = importlib.import_module("config")
    config_path = getattr(config_module, "__file__", None)
    if expected_config and not _same_path(config_path, expected_config):
        raise RuntimeError(
            "UIAgent config resolution failed: expected "
            f"{expected_config}, but imported {config_path or '<unknown>'}. "
            "Pass --uiagent-root C:\\Users\\unter\\UIAgent or reinstall UIAgent in editable mode."
        )

    missing = [name for name in ("LLM_BASE_URL", "LLM_MODEL") if not hasattr(config_module, name)]
    if missing:
        raise RuntimeError(
            "UIAgent config is missing required LLM setting(s): "
            f"{', '.join(missing)}. Loaded config: {config_path or '<unknown>'}. "
            "Check UIAgent config.py or pass --uiagent-root C:\\Users\\unter\\UIAgent."
        )


def configure_uiagent_osworld_environment(
    osworld_root: str,
    env: Any,
    os_type: str = "Windows",
    ready_timeout: float | None = None,
) -> None:
    os.environ["DESKTOP_BACKEND"] = "osworld_windows"
    os.environ["OSWORLD_ROOT"] = osworld_root
    os.environ["OSWORLD_VM_IP"] = str(env.vm_ip)
    os.environ["OSWORLD_SERVER_PORT"] = str(getattr(env, "server_port", 5000))
    os.environ["OSWORLD_OS_TYPE"] = os_type
    if ready_timeout is not None:
        os.environ["OSWORLD_READY_TIMEOUT"] = str(ready_timeout)


def import_uiagent_services(uiagent_root: str = ""):
    resolved_uiagent_root = _resolve_uiagent_root(uiagent_root)
    _ensure_uiagent_config(resolved_uiagent_root)

    from backend.osworld_windows import client as osworld_client
    from services.execution_service import ExecutionService
    from services.support.task_store import store

    return ExecutionService, store, osworld_client


def create_desktop_env(
    *,
    provider_name: str,
    vmx: str,
    snapshot_name: str,
    os_type: str,
    screen_width: int,
    screen_height: int,
    headless: bool,
):
    from desktop_env.desktop_env import DesktopEnv

    return DesktopEnv(
        provider_name=provider_name,
        path_to_vm=vmx,
        snapshot_name=snapshot_name,
        action_space="pyautogui",
        screen_size=(screen_width, screen_height),
        headless=headless,
        require_a11y_tree=False,
        require_terminal=False,
        os_type=os_type,
        enable_proxy=False,
    )


def reset_osworld_env(env: Any, snapshot_name: str, task_config: dict | None) -> dict:
    env.snapshot_name = snapshot_name
    if hasattr(env, "is_environment_used"):
        env.is_environment_used = True
    return env.reset(task_config=task_config)


def start_uiagent_execution(service: Any, task: str, task_config: dict | None = None) -> dict:
    task_parameters = {}
    if task_config:
        task_parameters["osworld_task_config"] = task_config

    return service.run_execution_inline(
        task=task,
        device="osworld-windows",
        task_parameters=task_parameters,
        learn_routine_on_success=True,
    )


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


def run_uiagent_task(
    task: str,
    *,
    uiagent_root: str = "",
    osworld_root: str = str(PROJECT_ROOT),
    vmx: str = str(PROJECT_ROOT / "vmware_vm_data" / "Windows0" / "Windows0.vmx"),
    snapshot_name: str = "init_state",
    os_type: str = "Windows",
    ready_timeout: float | None = None,
    task_config: dict | None = None,
    timeout: float = 1800.0,
    poll: float = 2.0,
    stream: bool = True,
    verbose: bool = False,
    env: Any = None,
    provider_name: str = "vmware",
    screen_width: int = 1920,
    screen_height: int = 1080,
    headless: bool = False,
) -> dict:
    del timeout, poll  # Inline mode runs in-process; controller limits and API timeouts govern duration.
    owns_env = env is None
    if env is None:
        env = create_desktop_env(
            provider_name=provider_name,
            vmx=vmx,
            snapshot_name=snapshot_name,
            os_type=os_type,
            screen_width=screen_width,
            screen_height=screen_height,
            headless=headless,
        )

    previous_snapshot = getattr(env, "snapshot_name", None)
    try:
        if stream:
            print(f"Resetting OSWorld VM to snapshot {snapshot_name}...")
        reset_osworld_env(env, snapshot_name, task_config)
        configure_uiagent_osworld_environment(osworld_root, env, os_type, ready_timeout)
        ExecutionService, _store, osworld_client = import_uiagent_services(uiagent_root)
        osworld_client.reset_connection()
        service = ExecutionService()
        if stream:
            print("Running UIAgent inline against the OSWorld-managed VM...")
        final_record = start_uiagent_execution(service, task, task_config)
        if verbose:
            print(json.dumps(final_record, ensure_ascii=False, indent=2))
        return final_record
    finally:
        if previous_snapshot is not None:
            env.snapshot_name = previous_snapshot
        if owns_env and os.environ.get("OSWORLD_CLOSE_ENV_AFTER_UIAGENT", "").strip().casefold() in {"1", "true", "yes", "on"}:
            env.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run UIAgent against an OSWorld-managed Windows VM.")
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
    parser.add_argument("--osworld-root", default=str(PROJECT_ROOT))
    parser.add_argument("--vmx", default=str(PROJECT_ROOT / "vmware_vm_data" / "Windows0" / "Windows0.vmx"))
    parser.add_argument("--provider-name", default="vmware")
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
        help="OS type passed to the OSWorld environment.",
    )
    parser.add_argument("--screen-width", type=int, default=1920)
    parser.add_argument("--screen-height", type=int, default=1080)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--poll", type=float, default=2.0, help="Accepted for compatibility; inline mode does not poll.")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Accepted for compatibility; inline mode is not hard-killed.")
    parser.add_argument("--ready-timeout", type=float, default=None, help="Seconds to wait for the OSWorld screenshot endpoint before failing.")
    parser.add_argument("--task-config", default="", help="Optional JSON file with an OSWorld task_config.")
    parser.add_argument("--verbose", action="store_true", help="Print detailed final task record.")
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
        provider_name=args.provider_name,
        screen_width=args.screen_width,
        screen_height=args.screen_height,
        headless=args.headless,
    )
    result_path = None
    try:
        result_path = _write_final_record(current)
    except Exception as exc:
        print(f"Warning: failed to write final result into UIAgent log: {exc}")
    if not args.verbose:
        _print_final_summary(current, result_path)
    return 0 if current.get("status") == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
