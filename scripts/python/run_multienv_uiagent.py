"""Run UIAgent on OSWorld tasks with multiple desktop environments."""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import time
import traceback
from datetime import datetime
from multiprocessing import Manager, Process, Queue, current_process, freeze_support
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from desktop_env.desktop_env import DesktopEnv
from scripts.python.uiagent.run_task import run_uiagent_task


logger = logging.getLogger("desktopenv.agent")


def configure_logging() -> None:
    logging.getLogger().setLevel(logging.INFO)
    if logging.getLogger().handlers:
        return

    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    datetime_str = datetime.now().strftime("%Y%m%d@%H%M%S")
    formatter = logging.Formatter(
        fmt="[%(asctime)s %(levelname)s %(module)s/%(lineno)d-%(processName)s] %(message)s"
    )

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(
        log_dir / f"uiagent-multienv-{datetime_str}.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(file_handler)


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _append_jsonl(path: Path, data: Dict[str, Any], lock: Any = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if lock is None:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, ensure_ascii=False))
            handle.write("\n")
        return

    with lock:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, ensure_ascii=False))
            handle.write("\n")


def _jsonable_args(args: argparse.Namespace) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for key, value in vars(args).items():
        data[key] = str(value) if isinstance(value, Path) else value
    return data


def _parse_ids(raw_ids: str) -> Optional[set[str]]:
    if not raw_ids:
        return None
    return {item.strip() for item in raw_ids.split(",") if item.strip()}


def _iter_examples(
    meta: Dict[str, List[str]], domain: str, ids: Optional[set[str]]
) -> Iterable[tuple[str, str]]:
    domains = [domain] if domain != "all" else list(meta.keys())
    for domain_name in domains:
        if domain_name not in meta:
            raise KeyError(f"Domain not found in meta file: {domain_name}")
        for example_id in meta[domain_name]:
            if ids and example_id not in ids:
                continue
            yield domain_name, example_id


def _task_snapshot(args: argparse.Namespace, example: Dict[str, Any]) -> str:
    return args.snapshot_name or example.get("snapshot") or "init_state"


def _example_config_path(args: argparse.Namespace, domain: str, example_id: str) -> Path:
    return (
        Path(args.test_config_base_dir)
        / args.examples_subdir
        / domain
        / f"{example_id}.json"
    )


def _example_result_dir(args: argparse.Namespace, domain: str, example_id: str) -> Path:
    return (
        Path(args.result_dir)
        / args.action_space
        / args.observation_type
        / args.model_dir_name
        / domain
        / example_id
    )


def _has_finished_result(args: argparse.Namespace, domain: str, example_id: str) -> bool:
    result_path = _example_result_dir(args, domain, example_id) / "result.txt"
    if not result_path.exists():
        return False
    try:
        float(result_path.read_text(encoding="utf-8").strip())
        return True
    except ValueError:
        return False


def get_unfinished(
    args: argparse.Namespace, tasks: Iterable[tuple[str, str]]
) -> List[tuple[str, str]]:
    if args.overwrite:
        return list(tasks)
    return [
        (domain, example_id)
        for domain, example_id in tasks
        if not _has_finished_result(args, domain, example_id)
    ]


def summarize_existing_results(
    args: argparse.Namespace, tasks: Iterable[tuple[str, str]]
) -> tuple[int, float]:
    scores: List[float] = []
    for domain, example_id in tasks:
        result_path = _example_result_dir(args, domain, example_id) / "result.txt"
        if not result_path.exists():
            continue
        try:
            scores.append(float(result_path.read_text(encoding="utf-8").strip()))
        except ValueError:
            logger.warning("Invalid result.txt ignored: %s", result_path)

    average = sum(scores) / len(scores) if scores else 0.0
    if scores:
        logger.info("Existing average score: %.4f (%s scored)", average, len(scores))
    else:
        logger.info("New experiment, no result yet.")
    return len(scores), average


def evaluate_current_vm(example: Dict[str, Any], env: Any) -> float:
    env._set_task_info(example)
    env.setup_controller.reset_cache_dir(env.cache_dir)
    return float(env.evaluate())


def write_uiagent_log_refs(example_dir: Path, uiagent_record: Dict[str, Any]) -> None:
    log_dir = str(uiagent_record.get("log_dir") or "").strip()
    if not log_dir:
        return
    (example_dir / "uiagent_log_dir.txt").write_text(f"{log_dir}\n", encoding="utf-8")
    _write_json(example_dir / "uiagent_run_result.json", uiagent_record)


def write_traj_summary(
    example_dir: Path,
    *,
    domain: str,
    example_id: str,
    uiagent_record: Dict[str, Any],
    score: Optional[float],
    error: Optional[str],
) -> None:
    row = {
        "domain": domain,
        "id": example_id,
        "uiagent_status": uiagent_record.get("status"),
        "uiagent_error": uiagent_record.get("error"),
        "uiagent_log_dir": uiagent_record.get("log_dir"),
        "score": score,
        "error": error,
    }
    _append_jsonl(example_dir / "traj.jsonl", row)


def run_one(
    args: argparse.Namespace,
    env: Any,
    domain: str,
    example_id: str,
    summary_path: Path,
    summary_lock: Any,
) -> Dict[str, Any]:
    example = _load_json(_example_config_path(args, domain, example_id))
    example_dir = _example_result_dir(args, domain, example_id)
    example_dir.mkdir(parents=True, exist_ok=True)

    result_path = example_dir / "result.txt"
    if not args.overwrite and _has_finished_result(args, domain, example_id):
        score = float(result_path.read_text(encoding="utf-8").strip())
        row = {
            "domain": domain,
            "id": example_id,
            "skipped": True,
            "score": score,
            "result_dir": str(example_dir),
        }
        _append_jsonl(summary_path, row, summary_lock)
        return row

    _write_json(example_dir / "task_config.json", example)
    (example_dir / "instruction.txt").write_text(
        example["instruction"], encoding="utf-8"
    )

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
                osworld_root=args.osworld_root,
                vmx=args.path_to_vm or "",
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
            )
            _write_json(example_dir / "uiagent_task.json", uiagent_record)
            write_uiagent_log_refs(example_dir, uiagent_record)

        if not args.no_evaluate:
            score = evaluate_current_vm(example, env)
            result_path.write_text(f"{score}\n", encoding="utf-8")

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        (example_dir / "error.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        logger.error("Failed %s/%s: %s", domain, example_id, error)
        logger.debug(traceback.format_exc())

    elapsed = time.time() - started
    write_traj_summary(
        example_dir,
        domain=domain,
        example_id=example_id,
        uiagent_record=uiagent_record,
        score=score,
        error=error,
    )

    row = {
        "domain": domain,
        "id": example_id,
        "snapshot": snapshot_name,
        "uiagent_status": uiagent_record.get("status"),
        "uiagent_error": uiagent_record.get("error"),
        "uiagent_log_dir": uiagent_record.get("log_dir"),
        "score": score,
        "elapsed_seconds": elapsed,
        "error": error,
        "result_dir": str(example_dir),
    }
    _append_jsonl(summary_path, row, summary_lock)
    logger.info("Finished %s/%s score=%s error=%s", domain, example_id, score, error)
    return row


def create_env(args: argparse.Namespace) -> DesktopEnv:
    initial_snapshot = args.snapshot_name or "init_state"
    return DesktopEnv(
        provider_name=args.provider_name,
        region=args.region,
        path_to_vm=args.path_to_vm or None,
        snapshot_name=initial_snapshot,
        action_space="pyautogui",
        screen_size=(args.screen_width, args.screen_height),
        headless=args.headless,
        require_a11y_tree=False,
        require_terminal=False,
        os_type=args.os_type,
        enable_proxy=False,
        client_password=args.client_password,
    )


def run_env_tasks(
    task_queue: Queue,
    args: argparse.Namespace,
    summary_path: str,
    summary_lock: Any,
) -> None:
    configure_logging()
    proc_name = current_process().name
    env: Optional[DesktopEnv] = None
    process_failed = False
    try:
        logger.info("%s starting DesktopEnv", proc_name)
        env = create_env(args)
        logger.info("%s started DesktopEnv at %s", proc_name, env.path_to_vm)
        while True:
            try:
                domain, example_id = task_queue.get(timeout=5)
            except queue.Empty:
                break
            except Exception:
                break

            logger.info("%s running %s/%s", proc_name, domain, example_id)
            run_one(args, env, domain, example_id, Path(summary_path), summary_lock)
    except Exception as exc:
        process_failed = True
        logger.error("%s process-level error: %s", proc_name, exc)
        logger.error(traceback.format_exc())
    finally:
        if env is not None:
            try:
                env.close()
                logger.info("%s closed DesktopEnv", proc_name)
            except Exception as exc:
                logger.error("%s failed to close DesktopEnv: %s", proc_name, exc)
    if process_failed:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run UIAgent on OSWorld Windows tasks with multiple environments."
    )
    parser.add_argument("--uiagent-root", default="")
    parser.add_argument("--osworld-root", default=str(PROJECT_ROOT))
    parser.add_argument("--provider_name", "--provider-name", dest="provider_name", default="vmware")
    parser.add_argument("--region", default=None)
    parser.add_argument("--path_to_vm", "--vmx", dest="path_to_vm", default=None)
    parser.add_argument("--snapshot_name", "--snapshot-name", dest="snapshot_name", default=None)
    parser.add_argument("--os_type", "--os-type", dest="os_type", default="Windows")
    parser.add_argument("--client_password", "--client-password", dest="client_password", default="")
    parser.add_argument("--num_envs", type=int, default=1)
    parser.add_argument("--screen_width", "--screen-width", dest="screen_width", type=int, default=1920)
    parser.add_argument("--screen_height", "--screen-height", dest="screen_height", type=int, default=1080)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--test_all_meta_path",
        type=str,
        default=str(PROJECT_ROOT / "evaluation_examples" / "test_omnic_windows.json"),
    )
    parser.add_argument(
        "--test_config_base_dir",
        type=str,
        default=str(PROJECT_ROOT / "evaluation_examples"),
    )
    parser.add_argument("--examples_subdir", type=str, default="examples_windows")
    parser.add_argument("--domain", type=str, default="all")
    parser.add_argument("--ids", default="", help="Comma-separated task ids to run.")
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N selected examples.")
    parser.add_argument("--result_dir", type=str, default=str(PROJECT_ROOT / "results" / "uiagent"))
    parser.add_argument("--model_dir_name", type=str, default="uiagent")
    parser.add_argument("--action_space", type=str, default="pyautogui")
    parser.add_argument("--observation_type", type=str, default="screenshot")
    parser.add_argument("--timeout_per_task", "--timeout-per-task", dest="timeout_per_task", type=float, default=1800.0)
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--ready_timeout", "--ready-timeout", dest="ready_timeout", type=float, default=None)
    parser.add_argument("--stream_uiagent", "--stream-uiagent", dest="stream_uiagent", action="store_true")
    parser.add_argument("--no_evaluate", "--no-evaluate", dest="no_evaluate", action="store_true")
    parser.add_argument("--evaluate_existing", "--evaluate-existing", dest="evaluate_existing", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Rerun tasks even when result.txt exists.")
    return parser


def finalize_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.num_envs < 1:
        raise ValueError("--num_envs must be >= 1")
    if args.action_space != "pyautogui":
        raise ValueError("UIAgent OSWorld bridge currently requires --action_space pyautogui")
    if args.path_to_vm and args.num_envs > 1 and args.provider_name in {"vmware", "virtualbox"}:
        raise ValueError(
            "Do not pass one local --path_to_vm with --num_envs > 1. "
            "Omit --path_to_vm so OSWorld can allocate free VMs, or use --num_envs 1."
        )
    args.result_dir = str(Path(args.result_dir))
    args.osworld_root = str(Path(args.osworld_root))
    args.test_config_base_dir = str(Path(args.test_config_base_dir))
    return args


def main() -> int:
    configure_logging()
    parser = build_parser()
    args = finalize_args(parser.parse_args())

    os.environ["OSWORLD_ROOT"] = args.osworld_root
    result_root = Path(args.result_dir) / args.action_space / args.observation_type / args.model_dir_name
    result_root.mkdir(parents=True, exist_ok=True)
    _write_json(result_root / "args.json", _jsonable_args(args))

    meta = _load_json(Path(args.test_all_meta_path))
    selected_tasks = list(_iter_examples(meta, args.domain, _parse_ids(args.ids)))
    if args.limit > 0:
        selected_tasks = selected_tasks[: args.limit]

    unfinished_tasks = get_unfinished(args, selected_tasks)
    summarize_existing_results(args, selected_tasks)

    logger.info("Selected tasks: %s", len(selected_tasks))
    logger.info("Unfinished tasks: %s", len(unfinished_tasks))
    logger.info("Result root: %s", result_root)
    if not unfinished_tasks:
        return 0

    summary_path = result_root / "summary.jsonl"
    with Manager() as manager:
        summary_lock = manager.Lock()
        task_queue: Queue = Queue()
        for item in unfinished_tasks:
            task_queue.put(item)

        processes: List[Process] = []
        for env_idx in range(args.num_envs):
            process = Process(
                target=run_env_tasks,
                args=(task_queue, args, str(summary_path), summary_lock),
                name=f"EnvProcess-{env_idx + 1}",
            )
            process.start()
            processes.append(process)
            logger.info("Started %s pid=%s", process.name, process.pid)

        failed = False
        for process in processes:
            process.join()
            if process.exitcode not in (0, None):
                failed = True
                logger.error("%s exited with code %s", process.name, process.exitcode)

    summarize_existing_results(args, selected_tasks)
    return 1 if failed else 0


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
