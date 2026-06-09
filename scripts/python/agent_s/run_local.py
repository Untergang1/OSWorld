"""Run Agent-S on OSWorld tasks.

This entrypoint is intentionally kept under scripts/python/agent_s because it is
specific to the external Agent-S package and its OSWorld adapter.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from desktop_env.desktop_env import DesktopEnv
from gui_agents.s3.agents.agent_s import AgentS3
from gui_agents.s3.agents.grounding import OSWorldACI
from scripts.python.agent_s import run_single
from scripts.python.agent_s.logging_config import (
    configure_logging,
    make_run_id,
    resolve_log_dir,
    write_args,
)

load_dotenv()

DEFAULT_GROUNDING_MAX_DIM = 2400
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")
DEFAULT_SNAPSHOT_NAME = "init_state"
logger = logging.getLogger("desktopenv.experiment")

BUILTIN_DEFAULTS: dict[str, Any] = {
    "path_to_vm": None,
    "provider_name": "vmware",
    "headless": False,
    "action_space": "pyautogui",
    "observation_type": "screenshot",
    "screen_width": 1920,
    "screen_height": 1080,
    "sleep_after_execution": 3.0,
    "wait_after_reset": 60.0,
    "max_steps": 15,
    "os_type": "Ubuntu",
    "client_password": "",
    "max_trajectory_length": 3,
    "test_config_base_dir": "evaluation_examples",
    "examples_dir": None,
    "model": "gpt-4o",
    "temperature": 1.0,
    "model_provider": "openai",
    "model_url": "",
    "model_temperature": None,
    "ground_provider": None,
    "ground_url": None,
    "ground_model": None,
    "grounding_width": None,
    "grounding_height": None,
    "limit": 0,
    "resume": False,
    "result_dir": str(Path("results") / "agent_s"),
    "log_dir": None,
    "run_id": None,
    "log_level": "INFO",
}

CLI_ONLY_DEFAULTS: dict[str, Any] = {
    "config": None,
    "task_config_path": None,
    "test_all_meta_path": None,
    "domain": "all",
    "model_api_key": "",
    "ground_api_key": "",
}

FORBIDDEN_CONFIG_KEYS = {
    "agent_platform",
    "snapshot_name",
    "disable_proxy",
    "model_api_key",
    "ground_api_key",
    "task_config_path",
    "test_all_meta_path",
    "domain",
}

ALLOWED_CONFIG_KEYS = set(BUILTIN_DEFAULTS)


def scale_screen_dimensions(width: int, height: int, max_dim_size: int) -> tuple[int, int]:
    scale_factor = min(max_dim_size / width, max_dim_size / height, 1)
    return int(width * scale_factor), int(height * scale_factor)


def resolve_grounding_dimensions(args: argparse.Namespace) -> tuple[int, int]:
    has_width = args.grounding_width is not None
    has_height = args.grounding_height is not None
    if has_width != has_height:
        raise ValueError("--grounding_width and --grounding_height must be provided together.")
    if has_width and has_height:
        if args.grounding_width <= 0 or args.grounding_height <= 0:
            raise ValueError("--grounding_width and --grounding_height must be positive integers.")
        return args.grounding_width, args.grounding_height
    return scale_screen_dimensions(
        args.screen_width, args.screen_height, DEFAULT_GROUNDING_MAX_DIM
    )


def infer_agent_platform(os_type: str) -> str:
    normalized = os_type.strip().lower()
    if normalized in {"windows", "win32"}:
        return "windows"
    if normalized in {"darwin", "mac", "macos"}:
        return "darwin"
    return "linux"


def resolve_api_key(explicit_key: str, provider: str | None) -> str:
    if explicit_key:
        return explicit_key
    if (provider or "").strip().lower() == "qwen":
        return os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or ""
    return ""


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")
    return data


def resolve_config_path(requested_config: str | None) -> Path | None:
    if requested_config:
        path = Path(requested_config).expanduser()
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    return DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None


def validate_config(config: dict[str, Any], parser: argparse.ArgumentParser) -> None:
    unknown_keys = sorted(set(config) - ALLOWED_CONFIG_KEYS - FORBIDDEN_CONFIG_KEYS)
    if unknown_keys:
        parser.error(f"Unknown config key(s): {', '.join(unknown_keys)}")

    forbidden_keys = sorted(set(config) & FORBIDDEN_CONFIG_KEYS)
    if forbidden_keys:
        parser.error(
            "These keys are CLI-only, task-owned, or derived and cannot be set in config: "
            + ", ".join(forbidden_keys)
        )


def build_parser(defaults: dict[str, Any], config_parent: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Agent-S on OSWorld tasks.",
        parents=[config_parent],
    )

    parser.add_argument("--path_to_vm", type=str, default=defaults["path_to_vm"])
    parser.add_argument(
        "--provider_name",
        type=str,
        default=defaults["provider_name"],
        help="Virtualization provider (vmware, docker, aws, azure, gcp, virtualbox).",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=defaults["headless"],
        help="Run the VM headlessly.",
    )
    parser.add_argument("--action_space", type=str, default=defaults["action_space"])
    parser.add_argument(
        "--observation_type",
        choices=["screenshot", "a11y_tree", "screenshot_a11y_tree", "som"],
        default=defaults["observation_type"],
    )
    parser.add_argument("--screen_width", type=int, default=defaults["screen_width"])
    parser.add_argument("--screen_height", type=int, default=defaults["screen_height"])
    parser.add_argument("--sleep_after_execution", type=float, default=defaults["sleep_after_execution"])
    parser.add_argument("--wait_after_reset", type=float, default=defaults["wait_after_reset"])
    parser.add_argument("--max_steps", type=int, default=defaults["max_steps"])
    parser.add_argument("--os_type", type=str, default=defaults["os_type"])
    parser.add_argument("--client_password", type=str, default=defaults["client_password"])

    parser.add_argument("--max_trajectory_length", type=int, default=defaults["max_trajectory_length"])
    parser.add_argument("--test_config_base_dir", type=str, default=defaults["test_config_base_dir"])
    parser.add_argument(
        "--examples_dir",
        type=str,
        default=defaults["examples_dir"],
        help="Examples root, e.g. evaluation_examples/examples_windows. Defaults to <test_config_base_dir>/examples.",
    )

    parser.add_argument("--model", type=str, default=defaults["model"])
    parser.add_argument("--temperature", type=float, default=defaults["temperature"])
    parser.add_argument("--model_provider", type=str, default=defaults["model_provider"])
    parser.add_argument("--model_url", type=str, default=defaults["model_url"])
    parser.add_argument("--model_api_key", type=str, default=CLI_ONLY_DEFAULTS["model_api_key"])
    parser.add_argument(
        "--model_temperature",
        type=float,
        default=defaults["model_temperature"],
        help="Generation model temperature; omit to use the Agent-S default.",
    )

    parser.add_argument("--ground_provider", type=str, default=defaults["ground_provider"])
    parser.add_argument("--ground_url", type=str, default=defaults["ground_url"])
    parser.add_argument("--ground_api_key", type=str, default=CLI_ONLY_DEFAULTS["ground_api_key"])
    parser.add_argument("--ground_model", type=str, default=defaults["ground_model"])
    parser.add_argument("--grounding_width", type=int, default=defaults["grounding_width"])
    parser.add_argument("--grounding_height", type=int, default=defaults["grounding_height"])

    parser.add_argument(
        "--task_config_path",
        type=str,
        default=CLI_ONLY_DEFAULTS["task_config_path"],
        help="Run one task JSON directly instead of a batch meta JSON.",
    )
    parser.add_argument("--domain", type=str, default=CLI_ONLY_DEFAULTS["domain"])
    parser.add_argument(
        "--test_all_meta_path",
        type=str,
        default=CLI_ONLY_DEFAULTS["test_all_meta_path"],
        help="Batch meta JSON shaped as {domain: [task_id, ...]}. Required unless --task_config_path is set.",
    )
    parser.add_argument("--limit", type=int, default=defaults["limit"], help="Run only the first N selected tasks.")
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=defaults["resume"],
        help="Skip tasks with result.txt in this run dir.",
    )

    parser.add_argument("--result_dir", type=str, default=defaults["result_dir"])
    parser.add_argument("--log_dir", type=str, default=defaults["log_dir"])
    parser.add_argument("--run_id", type=str, default=defaults["run_id"])
    parser.add_argument(
        "--log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=defaults["log_level"],
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    config_parent = argparse.ArgumentParser(add_help=False)
    config_parent.add_argument(
        "--config",
        type=str,
        default=CLI_ONLY_DEFAULTS["config"],
        help=f"YAML config file. Defaults to {DEFAULT_CONFIG_PATH} if it exists.",
    )

    config_args, _ = config_parent.parse_known_args(argv)
    try:
        config_path = resolve_config_path(config_args.config)
    except OSError as exc:
        config_parent.error(f"Failed to resolve --config: {exc}")
    config: dict[str, Any] = {}

    defaults = BUILTIN_DEFAULTS.copy()
    parser = build_parser(defaults, config_parent)
    if config_path:
        try:
            config = load_config(config_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            parser.error(f"Failed to load config {config_path}: {exc}")
        validate_config(config, parser)
        defaults.update(config)
        parser = build_parser(defaults, config_parent)

    args = parser.parse_args(argv)
    args.config = str(config_path) if config_path else None

    for required_key in ["ground_provider", "ground_url", "ground_model"]:
        if not getattr(args, required_key):
            parser.error(f"--{required_key} is required unless it is set in the config file.")

    if args.task_config_path and args.test_all_meta_path:
        parser.error("--task_config_path cannot be used together with --test_all_meta_path.")
    if not args.task_config_path and not args.test_all_meta_path:
        parser.error("Either --task_config_path or --test_all_meta_path is required.")
    if args.task_config_path and not Path(args.task_config_path).exists():
        parser.error(f"--task_config_path does not exist: {args.task_config_path}")
    if args.test_all_meta_path and not Path(args.test_all_meta_path).exists():
        parser.error(f"--test_all_meta_path does not exist: {args.test_all_meta_path}")

    try:
        args.grounding_width, args.grounding_height = resolve_grounding_dimensions(args)
    except ValueError as exc:
        parser.error(str(exc))

    args.agent_platform = infer_agent_platform(args.os_type)
    run_domain = infer_task_domain(args.task_config_path) if args.task_config_path else args.domain
    args.run_id = args.run_id or make_run_id("agent_s", run_domain, args.model)
    args.base_result_dir = str(Path(args.result_dir))
    args.result_dir = str(Path(args.result_dir) / args.run_id)
    args.examples_dir = str(Path(args.examples_dir)) if args.examples_dir else str(
        Path(args.test_config_base_dir) / "examples"
    )
    return args


def load_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def infer_task_domain(task_config_path: str | os.PathLike[str] | None) -> str:
    if not task_config_path:
        return "single"
    parent_name = Path(task_config_path).parent.name
    return parent_name or "single"


def iter_tasks(
    test_all_meta: dict[str, list[str]],
    domain: str,
    limit: int,
) -> list[tuple[str, str, Path | None]]:
    domains = [domain] if domain != "all" else list(test_all_meta.keys())
    tasks = [
        (domain_name, example_id, None)
        for domain_name in domains
        for example_id in test_all_meta[domain_name]
    ]
    if limit > 0:
        return tasks[:limit]
    return tasks


def resolve_example_path(
    args: argparse.Namespace,
    domain: str,
    example_id: str,
    config_file: Path | None,
) -> Path:
    if config_file is not None:
        return config_file
    config_file = Path(args.examples_dir) / domain / f"{example_id}.json"
    if not config_file.exists():
        raise FileNotFoundError(config_file)
    return config_file


def load_example(
    args: argparse.Namespace,
    domain: str,
    example_id: str,
    config_file: Path | None,
) -> dict[str, Any]:
    config_file = resolve_example_path(args, domain, example_id, config_file)
    return load_json(config_file)


def select_tasks(
    args: argparse.Namespace,
    test_all_meta: dict[str, list[str]] | None,
) -> list[tuple[str, str, Path | None]]:
    if args.task_config_path:
        config_file = Path(args.task_config_path)
        if not config_file.exists():
            raise FileNotFoundError(config_file)
        example = load_json(config_file)
        example_id = str(example.get("id") or config_file.stem)
        return [(infer_task_domain(config_file), example_id, config_file)]

    assert test_all_meta is not None
    return iter_tasks(test_all_meta, args.domain, args.limit)


def is_finished(args: argparse.Namespace, domain: str, example_id: str) -> bool:
    result_path = (
        Path(args.result_dir)
        / args.action_space
        / args.observation_type
        / args.model
        / domain
        / example_id
        / "result.txt"
    )
    return result_path.exists()


def get_result_dir(args: argparse.Namespace, domain: str, example_id: str) -> Path:
    return (
        Path(args.result_dir)
        / args.action_space
        / args.observation_type
        / args.model
        / domain
        / example_id
    )


def build_agent_and_env(args: argparse.Namespace) -> tuple[AgentS3, DesktopEnv]:
    model_api_key = resolve_api_key(args.model_api_key, args.model_provider)
    ground_api_key = resolve_api_key(args.ground_api_key, args.ground_provider)
    engine_params = {
        "engine_type": args.model_provider,
        "model": args.model,
        "base_url": args.model_url,
        "api_key": model_api_key,
        "temperature": args.model_temperature,
    }
    engine_params_for_grounding = {
        "engine_type": args.ground_provider,
        "model": args.ground_model,
        "base_url": args.ground_url,
        "api_key": ground_api_key,
        "grounding_width": args.grounding_width,
        "grounding_height": args.grounding_height,
    }

    env = DesktopEnv(
        provider_name=args.provider_name,
        path_to_vm=args.path_to_vm,
        snapshot_name=DEFAULT_SNAPSHOT_NAME,
        action_space=args.action_space,
        screen_size=(args.screen_width, args.screen_height),
        headless=args.headless,
        os_type=args.os_type,
        require_a11y_tree=args.observation_type
        in ["a11y_tree", "screenshot_a11y_tree", "som"],
        enable_proxy=True,
        client_password=args.client_password,
    )

    grounding_agent = OSWorldACI(
        env=env,
        platform=args.agent_platform,
        engine_params_for_generation=engine_params,
        engine_params_for_grounding=engine_params_for_grounding,
        width=args.screen_width,
        height=args.screen_height,
    )
    agent = AgentS3(
        engine_params,
        grounding_agent,
        platform=args.agent_platform,
        max_trajectory_length=args.max_trajectory_length,
    )
    return agent, env


def run(args: argparse.Namespace, selected_tasks: list[tuple[str, str, Path | None]]) -> int:
    scores: list[float] = []
    logger.info("Selected tasks: %d", len(selected_tasks))
    logger.info("Examples dir: %s", args.examples_dir)
    logger.info("Result dir: %s", args.result_dir)

    agent, env = build_agent_and_env(args)
    try:
        for domain, example_id, config_file in tqdm(selected_tasks, desc="Task"):
            if args.resume and is_finished(args, domain, example_id):
                logger.info("Skipping finished task: %s/%s", domain, example_id)
                continue

            example_result_dir = get_result_dir(args, domain, example_id)
            example_result_dir.mkdir(parents=True, exist_ok=True)

            try:
                example = load_example(args, domain, example_id, config_file)
                example_id = str(example.get("id") or example_id)
                logger.info("[Domain]: %s", domain)
                logger.info("[Example ID]: %s", example_id)
                logger.info("[Snapshot]: %s", example.get("snapshot", DEFAULT_SNAPSHOT_NAME))
                logger.info("[Instruction]: %s", example["instruction"])
                (example_result_dir / "task_config.json").write_text(
                    json.dumps(example, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

                run_single.run_single_example(
                    agent,
                    env,
                    example,
                    args.max_steps,
                    example["instruction"],
                    args,
                    example_result_dir,
                    scores,
                )
            except Exception as exc:
                logger.error("Exception in %s/%s: %s", domain, example_id, exc)
                logger.error(traceback.format_exc())
                with (example_result_dir / "traj.jsonl").open(
                    "a", encoding="utf-8", newline="\n"
                ) as handle:
                    handle.write(json.dumps({"Error": f"{domain}/{example_id} - {exc}"}))
                    handle.write("\n")
                (example_result_dir / "error.txt").write_text(
                    traceback.format_exc(), encoding="utf-8"
                )
    finally:
        env.close()

    if scores:
        logger.info("Average score: %.4f", sum(scores) / len(scores))
    else:
        logger.info("Average score: no completed tasks")
    return 0


def main() -> int:
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    args = parse_args()
    log_dir = resolve_log_dir(args.run_id, args.log_dir)
    args.log_dir = str(log_dir)

    global logger
    logger = configure_logging(log_dir, args.log_level)
    write_args(log_dir, args)

    args_path = Path(args.result_dir) / args.action_space / args.observation_type / args.model / "args.json"
    args_path.parent.mkdir(parents=True, exist_ok=True)
    args_path.write_text(json.dumps(vars(args), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    test_all_meta = None
    if args.test_all_meta_path:
        test_all_meta = load_json(args.test_all_meta_path)
        if args.domain != "all" and args.domain not in test_all_meta:
            raise KeyError(f"Domain {args.domain!r} not found in {args.test_all_meta_path}")
    selected_tasks = select_tasks(args, test_all_meta)
    return run(args, selected_tasks)


if __name__ == "__main__":
    raise SystemExit(main())
