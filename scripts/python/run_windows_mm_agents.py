from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


LOGGER = logging.getLogger("desktopenv.experiment")

DEFAULT_MODELS = {
    "prompt": "gpt-4o",
    "qwen25vl": "qwen2.5-vl-72b-instruct",
    "qwen3vl": "qwen3-vl",
    "o3": "o3",
}

DEFAULT_LM_PARAMS = {
    "prompt": {"temperature": 0.5, "top_p": 0.9, "max_tokens": 1500},
    "qwen25vl": {"temperature": 0.5, "top_p": 0.9, "max_tokens": 1500},
    "qwen3vl": {"temperature": 0.0, "top_p": 0.9, "max_tokens": 32768},
    "o3": {"temperature": 0.5, "top_p": 0.9, "max_tokens": 1500},
}


def load_dotenv_if_present() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        LOGGER.warning(".env exists but python-dotenv is not installed; skipping it.")
        return

    load_dotenv(env_file)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run mm_agents on Windows OMNIC tasks with one shared DesktopEnv."
        )
    )

    parser.add_argument(
        "--agent",
        choices=["prompt", "qwen25vl", "qwen3vl", "o3"],
        default="prompt",
        help="Agent implementation to run.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name. Defaults depend on --agent.",
    )

    # Environment config.
    parser.add_argument("--provider_name", default="vmware")
    parser.add_argument(
        "--path_to_vm",
        default=str(Path("vmware_vm_data") / "Windows0" / "Windows0.vmx"),
    )
    parser.add_argument("--os_type", default="Windows")
    parser.add_argument("--snapshot_name", default="init_state")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--client_password", default="")
    parser.add_argument("--screen_width", type=int, default=1920)
    parser.add_argument("--screen_height", type=int, default=1080)
    parser.add_argument(
        "--action_space",
        default="pyautogui",
        choices=["pyautogui", "computer_13"],
    )
    parser.add_argument(
        "--observation_type",
        default="screenshot",
        choices=["screenshot", "a11y_tree", "screenshot_a11y_tree", "som"],
    )
    parser.add_argument("--sleep_after_execution", type=float, default=2.0)
    parser.add_argument("--wait_after_reset", type=float, default=60.0)
    parser.add_argument("--max_steps", type=int, default=30)

    # Task config.
    parser.add_argument(
        "--examples_dir",
        default=str(Path("evaluation_examples") / "examples_windows"),
        help="Directory containing Windows task json files.",
    )
    parser.add_argument(
        "--test_all_meta_path",
        default=str(Path("evaluation_examples") / "test_omnic_windows.json"),
    )
    parser.add_argument("--domain", default="omnic")
    parser.add_argument(
        "--ids",
        default="",
        help="Comma/space-separated task IDs to run after domain filtering.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Run only the first N selected tasks. 0 means all.",
    )
    parser.add_argument("--resume", action="store_true")

    # LM/agent config.
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top_p", type=float, default=None)
    parser.add_argument("--max_tokens", type=int, default=None)
    parser.add_argument("--max_trajectory_length", type=int, default=3)
    parser.add_argument("--history_n", type=int, default=4)
    parser.add_argument("--add_thought_prefix", action="store_true")
    parser.add_argument(
        "--qwen3_api_backend",
        choices=["dashscope", "openai"],
        default="dashscope",
    )
    parser.add_argument(
        "--qwen3_coord",
        choices=["relative", "absolute"],
        default="relative",
    )
    parser.add_argument("--qwen3_enable_thinking", action="store_true")
    parser.add_argument("--qwen3_thinking_budget", type=int, default=32768)

    # Logging/result config.
    parser.add_argument(
        "--result_dir",
        default=str(Path("results") / "windows_mm_agents"),
    )
    parser.add_argument(
        "--log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
    )
    return parser


def finalize_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.model is None:
        args.model = DEFAULT_MODELS[args.agent]

    defaults = DEFAULT_LM_PARAMS[args.agent]
    if args.temperature is None:
        args.temperature = defaults["temperature"]
    if args.top_p is None:
        args.top_p = defaults["top_p"]
    if args.max_tokens is None:
        args.max_tokens = defaults["max_tokens"]

    return args


def configure_logging(log_level: str) -> Path:
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")
    log_path = logs_dir / f"windows-mm-agents-{timestamp}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="[%(asctime)s %(levelname)s %(name)s %(module)s/%(lineno)d] %(message)s"
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(getattr(logging, log_level.upper()))
    stdout_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(stdout_handler)
    return log_path


def safe_path_part(value: str) -> str:
    safe_value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe_value or "model"


def result_base_dir(args: argparse.Namespace) -> Path:
    return (
        PROJECT_ROOT
        / args.result_dir
        / args.agent
        / args.action_space
        / args.observation_type
        / safe_path_part(args.model)
    )


def example_result_dir(args: argparse.Namespace, domain: str, example_id: str) -> Path:
    return result_base_dir(args) / domain / example_id


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, default=str)


def parse_requested_ids(raw_ids: str) -> set[str]:
    if not raw_ids.strip():
        return set()
    return {item for item in re.split(r"[\s,;]+", raw_ids.strip()) if item}


def load_tasks(args: argparse.Namespace) -> list[tuple[str, str, dict[str, Any]]]:
    meta_path = PROJECT_ROOT / args.test_all_meta_path
    with meta_path.open("r", encoding="utf-8-sig") as handle:
        test_all_meta = json.load(handle)

    if args.domain != "all":
        if args.domain not in test_all_meta:
            raise ValueError(
                f"Domain {args.domain!r} not found in {args.test_all_meta_path}."
            )
        selected_meta = {args.domain: test_all_meta[args.domain]}
    else:
        selected_meta = test_all_meta

    requested_ids = parse_requested_ids(args.ids)
    selected_tasks: list[tuple[str, str, dict[str, Any]]] = []
    matched_ids: set[str] = set()

    examples_dir = PROJECT_ROOT / args.examples_dir
    for domain, example_ids in selected_meta.items():
        for example_id in example_ids:
            if requested_ids and example_id not in requested_ids:
                continue
            task_path = examples_dir / domain / f"{example_id}.json"
            with task_path.open("r", encoding="utf-8-sig") as handle:
                example = json.load(handle)
            selected_tasks.append((domain, example_id, example))
            matched_ids.add(example_id)

    if requested_ids:
        missing_ids = requested_ids - matched_ids
        if missing_ids:
            missing = ", ".join(sorted(missing_ids))
            raise ValueError(f"Requested IDs were not found: {missing}")

    if args.limit > 0:
        selected_tasks = selected_tasks[: args.limit]

    return selected_tasks


def filter_finished_tasks(
    args: argparse.Namespace,
    tasks: list[tuple[str, str, dict[str, Any]]],
) -> list[tuple[str, str, dict[str, Any]]]:
    if not args.resume:
        return tasks

    unfinished = []
    for domain, example_id, example in tasks:
        result_file = example_result_dir(args, domain, example_id) / "result.txt"
        if result_file.exists():
            LOGGER.info("Skipping finished task: %s/%s", domain, example_id)
            continue
        unfinished.append((domain, example_id, example))
    return unfinished


def check_credentials(args: argparse.Namespace) -> None:
    needs_openai = (
        args.agent == "o3"
        or (args.agent == "prompt" and args.model.startswith("gpt"))
        or (args.agent == "qwen3vl" and args.qwen3_api_backend == "openai")
    )
    needs_dashscope = (
        args.agent == "qwen25vl"
        or (args.agent == "qwen3vl" and args.qwen3_api_backend == "dashscope")
        or (args.agent == "prompt" and args.model.startswith("qwen"))
    )

    if needs_openai and not os.environ.get("OPENAI_API_KEY"):
        LOGGER.warning("OPENAI_API_KEY is not set.")
    if needs_dashscope and not os.environ.get("DASHSCOPE_API_KEY"):
        LOGGER.warning("DASHSCOPE_API_KEY is not set.")
    if args.agent == "o3" and os.environ.get("OPENAI_BASE_URL"):
        LOGGER.warning(
            "O3Agent currently ignores OPENAI_BASE_URL and uses the official OpenAI URL."
        )


def build_env(args: argparse.Namespace) -> Any:
    from desktop_env.desktop_env import DesktopEnv

    return DesktopEnv(
        provider_name=args.provider_name,
        path_to_vm=args.path_to_vm,
        snapshot_name=args.snapshot_name,
        action_space=args.action_space,
        screen_size=(args.screen_width, args.screen_height),
        headless=args.headless,
        os_type=args.os_type,
        require_a11y_tree=args.observation_type
        in ["a11y_tree", "screenshot_a11y_tree", "som"],
        enable_proxy=True,
        client_password=args.client_password,
    )


def build_agent(args: argparse.Namespace) -> Any:
    if args.agent == "prompt":
        from mm_agents.agent import PromptAgent

        return PromptAgent(
            platform="windows",
            model=args.model,
            max_tokens=args.max_tokens,
            top_p=args.top_p,
            temperature=args.temperature,
            action_space=args.action_space,
            observation_type=args.observation_type,
            max_trajectory_length=args.max_trajectory_length,
            client_password=args.client_password or "password",
        )

    if args.agent == "qwen25vl":
        from mm_agents.qwen25vl_agent import Qwen25VLAgent

        return Qwen25VLAgent(
            platform="windows",
            model=args.model,
            max_tokens=args.max_tokens,
            top_p=args.top_p,
            temperature=args.temperature,
            action_space=args.action_space,
            observation_type=args.observation_type,
            history_n=args.history_n,
            add_thought_prefix=args.add_thought_prefix,
        )

    if args.agent == "qwen3vl":
        from mm_agents.qwen3vl_agent import Qwen3VLAgent

        return Qwen3VLAgent(
            platform="windows",
            model=args.model,
            max_tokens=args.max_tokens,
            top_p=args.top_p,
            temperature=args.temperature,
            action_space=args.action_space,
            observation_type=args.observation_type,
            history_n=args.history_n,
            add_thought_prefix=args.add_thought_prefix,
            coordinate_type=args.qwen3_coord,
            api_backend=args.qwen3_api_backend,
            enable_thinking=args.qwen3_enable_thinking,
            thinking_budget=args.qwen3_thinking_budget,
        )

    if args.agent == "o3":
        from mm_agents.o3_agent import O3Agent

        return O3Agent(
            platform="windows",
            model=args.model,
            max_tokens=args.max_tokens,
            client_password=args.client_password or "password",
            action_space=args.action_space,
            observation_type=args.observation_type,
            max_steps=args.max_steps,
        )

    raise ValueError(f"Unsupported agent: {args.agent}")


def setup_task_logger(example_id: str, task_result_dir: Path) -> logging.Logger:
    runtime_logger = logging.getLogger(f"desktopenv.example.{example_id}")
    runtime_logger.setLevel(logging.DEBUG)
    runtime_logger.propagate = True

    runtime_log = task_result_dir / "runtime.log"
    for handler in list(runtime_logger.handlers):
        if (
            isinstance(handler, logging.FileHandler)
            and handler.baseFilename == str(runtime_log)
        ):
            return runtime_logger

    handler = logging.FileHandler(runtime_log, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter(
            fmt="[%(asctime)s %(levelname)s %(module)s/%(lineno)d] %(message)s"
        )
    )
    runtime_logger.addHandler(handler)
    return runtime_logger


def reset_agent(agent: Any, runtime_logger: logging.Logger, env: Any) -> None:
    try:
        agent.reset(runtime_logger, vm_ip=getattr(env, "vm_ip", None))
        return
    except TypeError:
        pass

    try:
        agent.reset(runtime_logger)
    except TypeError:
        agent.reset()


def save_screenshot(obs: dict[str, Any], screenshot_path: Path) -> str | None:
    screenshot = obs.get("screenshot")
    if screenshot is None:
        return None

    screenshot_path.write_bytes(screenshot)
    return screenshot_path.name


def normalize_response(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return dict(response)
    return {"response": response}


def normalize_actions(actions: Any) -> list[Any]:
    if actions is None:
        raise ValueError("Agent returned no actions.")
    if isinstance(actions, str):
        normalized = [actions]
    elif isinstance(actions, dict):
        normalized = [actions]
    else:
        try:
            normalized = list(actions)
        except TypeError:
            normalized = [actions]

    normalized = [
        action
        for action in normalized
        if action is not None and (not isinstance(action, str) or action.strip())
    ]
    if not normalized:
        raise ValueError("Agent returned no actions.")
    return normalized


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str))
        handle.write("\n")


def run_single_example(
    agent: Any,
    env: Any,
    example: dict[str, Any],
    args: argparse.Namespace,
    task_result_dir: Path,
    scores: list[float],
) -> float:
    task_result_dir.mkdir(parents=True, exist_ok=True)
    save_json(task_result_dir / "task_config.json", example)

    instruction = example["instruction"]
    (task_result_dir / "instruction.txt").write_text(instruction, encoding="utf-8")

    runtime_logger = setup_task_logger(example["id"], task_result_dir)
    reset_agent(agent, runtime_logger, env)

    previous_snapshot = getattr(env, "snapshot_name", None)
    task_snapshot = example.get("snapshot") or args.snapshot_name
    if task_snapshot:
        env.snapshot_name = task_snapshot

    try:
        obs = env.reset(task_config=example)
        if args.wait_after_reset > 0:
            time.sleep(args.wait_after_reset)
            obs = env._get_obs()

        save_screenshot(obs, task_result_dir / "step_0.png")

        done = False
        step_idx = 0
        while not done and step_idx < args.max_steps:
            response, raw_actions = agent.predict(instruction, obs)
            response_row = normalize_response(response)
            actions = normalize_actions(raw_actions)

            for action_idx, action in enumerate(actions, start=1):
                if args.action_space == "pyautogui" and not isinstance(action, str):
                    raise ValueError(
                        f"PyAutoGUI action must be a string, got {type(action).__name__}."
                    )

                action_timestamp = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")
                LOGGER.info("Step %d.%d: %s", step_idx + 1, action_idx, action)

                obs, reward, done, info = env.step(
                    action,
                    args.sleep_after_execution,
                )

                LOGGER.info("Reward: %.2f", reward)
                LOGGER.info("Done: %s", done)

                screenshot_file = save_screenshot(
                    obs,
                    task_result_dir
                    / f"step_{step_idx + 1}_{action_idx}_{action_timestamp}.png",
                )

                row = dict(response_row)
                row.update(
                    {
                        "step_num": step_idx + 1,
                        "action_index": action_idx,
                        "action_timestamp": action_timestamp,
                        "action": action,
                        "reward": reward,
                        "done": done,
                        "info": info,
                        "screenshot_file": screenshot_file,
                    }
                )
                append_jsonl(task_result_dir / "traj.jsonl", row)

                if done:
                    LOGGER.info("The episode is done.")
                    break

            step_idx += 1

        result = float(env.evaluate())
        LOGGER.info("Result: %.2f", result)
        scores.append(result)
        (task_result_dir / "result.txt").write_text(f"{result}\n", encoding="utf-8")
        return result
    finally:
        if previous_snapshot is not None:
            env.snapshot_name = previous_snapshot


def write_task_error(task_result_dir: Path, domain: str, example_id: str, exc: BaseException) -> None:
    task_result_dir.mkdir(parents=True, exist_ok=True)
    message = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    (task_result_dir / "error.txt").write_text(message, encoding="utf-8")
    append_jsonl(
        task_result_dir / "traj.jsonl",
        {"Error": f"{domain}/{example_id} - {exc}"},
    )


def main() -> int:
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    args = finalize_args(build_parser().parse_args())

    log_path = configure_logging(args.log_level)
    load_dotenv_if_present()
    check_credentials(args)

    base_dir = result_base_dir(args)
    save_json(base_dir / "args.json", vars(args))
    LOGGER.info("Log file: %s", log_path)
    LOGGER.info("Result base dir: %s", base_dir)

    tasks = load_tasks(args)
    tasks = filter_finished_tasks(args, tasks)
    if not tasks:
        LOGGER.info("No tasks to run.")
        return 0

    LOGGER.info("Selected %d task(s).", len(tasks))
    for domain, example_id, example in tasks:
        LOGGER.info(
            "Task: %s/%s snapshot=%s",
            domain,
            example_id,
            example.get("snapshot") or args.snapshot_name,
        )

    env = None
    scores: list[float] = []
    failures: list[dict[str, str]] = []

    try:
        env = build_env(args)
        agent = build_agent(args)

        for domain, example_id, example in tasks:
            task_result_dir = example_result_dir(args, domain, example_id)
            LOGGER.info("[Domain]: %s", domain)
            LOGGER.info("[Example ID]: %s", example_id)
            LOGGER.info("[Instruction]: %s", example["instruction"])

            try:
                run_single_example(agent, env, example, args, task_result_dir, scores)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                LOGGER.error(
                    "Exception while running %s/%s: %s",
                    domain,
                    example_id,
                    exc,
                    exc_info=True,
                )
                write_task_error(task_result_dir, domain, example_id, exc)
                failures.append(
                    {"domain": domain, "example_id": example_id, "error": str(exc)}
                )

        summary = {
            "num_selected": len(tasks),
            "num_finished": len(scores),
            "num_failed": len(failures),
            "scores": scores,
            "average_score": (sum(scores) / len(scores)) if scores else None,
            "failures": failures,
        }
        save_json(base_dir / "summary.json", summary)

        if scores:
            LOGGER.info(
                "Average score over %d finished task(s): %.4f",
                len(scores),
                sum(scores) / len(scores),
            )
        if failures:
            LOGGER.warning("%d task(s) failed. See summary.json/error.txt.", len(failures))
            return 1
        return 0
    finally:
        if env is not None:
            try:
                LOGGER.info("Closing environment.")
                env.close()
            except Exception as exc:
                LOGGER.error("Error while closing environment: %s", exc, exc_info=True)


if __name__ == "__main__":
    raise SystemExit(main())
