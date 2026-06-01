from __future__ import annotations

import datetime
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("desktopenv.experiment")


def run_single_example(
    agent: Any,
    env: Any,
    example: dict[str, Any],
    max_steps: int,
    instruction: str,
    args: Any,
    example_result_dir: str | os.PathLike[str],
    scores: list[float],
) -> float:
    example_dir = Path(example_result_dir)
    example_dir.mkdir(parents=True, exist_ok=True)

    runtime_logger = setup_logger(example, example_dir)
    try:
        agent.reset(runtime_logger)
    except TypeError:
        agent.reset()

    previous_snapshot = getattr(env, "snapshot_name", None)
    task_snapshot = example.get("snapshot") or getattr(args, "snapshot_name", None)
    if task_snapshot:
        env.snapshot_name = task_snapshot

    try:
        obs = env.reset(task_config=example)
        time.sleep(getattr(args, "wait_after_reset", 60.0))
        obs = env._get_obs()

        (example_dir / "step_0.png").write_bytes(obs["screenshot"])
        (example_dir / "instruction.txt").write_text(instruction, encoding="utf-8")

        done = False
        step_idx = 0
        while not done and step_idx < max_steps:
            response, actions = agent.predict(instruction, obs)
            if not isinstance(response, dict):
                response = {"response": response}

            for action in actions:
                action_timestamp = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")
                logger.info("Step %d: %s", step_idx + 1, action)
                obs, reward, done, info = env.step(
                    action, getattr(args, "sleep_after_execution", 0.0)
                )

                logger.info("Reward: %.2f", reward)
                logger.info("Done: %s", done)

                screenshot_file = f"step_{step_idx + 1}_{action_timestamp}.png"
                (example_dir / screenshot_file).write_bytes(obs["screenshot"])

                row = dict(response)
                row.update(
                    {
                        "step_num": step_idx + 1,
                        "action_timestamp": action_timestamp,
                        "action": action,
                        "reward": reward,
                        "done": done,
                        "info": info,
                        "screenshot_file": screenshot_file,
                    }
                )
                with (example_dir / "traj.jsonl").open(
                    "a", encoding="utf-8", newline="\n"
                ) as handle:
                    handle.write(json.dumps(row, ensure_ascii=False))
                    handle.write("\n")

                if done:
                    logger.info("The episode is done.")
                    break
            step_idx += 1

        result = float(env.evaluate())
        logger.info("Result: %.2f", result)
        scores.append(result)
        (example_dir / "result.txt").write_text(f"{result}\n", encoding="utf-8")
        return result
    finally:
        if previous_snapshot is not None:
            env.snapshot_name = previous_snapshot


def setup_logger(example: dict[str, Any], example_result_dir: Path) -> logging.Logger:
    runtime_logger = logging.getLogger(f"desktopenv.example.{example['id']}")
    runtime_logger.setLevel(logging.DEBUG)
    runtime_logger.propagate = True

    runtime_log = example_result_dir / "runtime.log"
    for handler in list(runtime_logger.handlers):
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == str(runtime_log):
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
