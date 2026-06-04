import datetime
import json
import logging
import os
import time
from typing import *
from wrapt_timeout_decorator import *

logger = logging.getLogger("desktopenv.experiment")


def run_single_example(
    agent, env, example, max_steps, instruction, args, example_result_dir, scores
):
    runtime_logger = setup_logger(example, example_result_dir)
    try:
        agent.reset(runtime_logger)
    except Exception as e:
        agent.reset()

    env.reset(task_config=example)
    time.sleep(60)  # Wait for the environment to be ready
    obs = env._get_obs()  # Get the initial observation

    with open(os.path.join(example_result_dir, f"step_0.png"), "wb") as _f:
        _f.write(obs["screenshot"])

    with open(
        os.path.join(example_result_dir, "instruction.txt"), "w", encoding="utf-8"
    ) as f:
        f.write(instruction)

    done = False
    step_idx = 0
    # env.controller.start_recording()
    while not done and step_idx < max_steps:
        response, actions = agent.predict(instruction, obs)
        for action in actions:
            action_timestamp = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")
            logger.info("Step %d: %s", step_idx + 1, action)
            obs, reward, done, info = env.step(action, args.sleep_after_execution)

            logger.info("Reward: %.2f", reward)
            logger.info("Done: %s", done)
            # Save screenshot and trajectory information
            with open(
                os.path.join(
                    example_result_dir, f"step_{step_idx + 1}_{action_timestamp}.png"
                ),
                "wb",
            ) as _f:
                _f.write(obs["screenshot"])

            response.update(
                {
                    "step_num": step_idx + 1,
                    "action_timestamp": action_timestamp,
                    "action": action,
                    "reward": reward,
                    "done": done,
                    "info": info,
                    "screenshot_file": f"step_{step_idx + 1}_{action_timestamp}.png",
                }
            )
            with open(
                os.path.join(example_result_dir, "traj.jsonl"), "a", encoding="utf-8"
            ) as f:
                f.write(json.dumps(response, ensure_ascii=False))
                f.write("\n")
            if done:
                logger.info("The episode is done.")
                break
        step_idx += 1
    result = env.evaluate()
    logger.info("Result: %.2f", result)
    scores.append(result)
    with open(
        os.path.join(example_result_dir, "result.txt"), "w", encoding="utf-8"
    ) as f:
        f.write(f"{result}\n")
    # env.controller.end_recording(os.path.join(example_result_dir, "recording.mp4"))


def run_single_example_gpt54(
    agent, env, example, max_steps, instruction, args, example_result_dir, scores
):
    runtime_logger = setup_logger(example, example_result_dir)
    try:
        agent.reset(runtime_logger)
    except Exception as e:
        agent.reset()

    env.reset(task_config=example)
    time.sleep(getattr(args, "wait_after_reset", 60))  # Wait for the environment to be ready
    obs = env._get_obs()  # Get the initial observation

    with open(os.path.join(example_result_dir, "step_0.png"), "wb") as _f:
        _f.write(obs["screenshot"])

    with open(
        os.path.join(example_result_dir, "instruction.txt"), "w", encoding="utf-8"
    ) as f:
        f.write(instruction)

    done = False
    step_idx = 0
    action_idx = 0
    while not done and step_idx < max_steps:
        response, actions = agent.predict(instruction, obs)
        if not actions:
            logger.warning("GPT54Agent returned no actions; ending episode.")
            action_timestamp = datetime.datetime.now().strftime("%Y%m%d@%H%M%S_%f")
            response_record = dict(response)
            response_record.update(
                {
                    "step_num": step_idx + 1,
                    "action_timestamp": action_timestamp,
                    "action": None,
                    "reward": None,
                    "done": done,
                    "info": {"message": "No actions returned by GPT54Agent."},
                    "screenshot_file": None,
                }
            )
            with open(
                os.path.join(example_result_dir, "traj.jsonl"), "a", encoding="utf-8"
            ) as f:
                f.write(json.dumps(response_record, ensure_ascii=False))
                f.write("\n")
            break

        for action in actions:
            action_idx += 1
            action_timestamp = datetime.datetime.now().strftime("%Y%m%d@%H%M%S_%f")
            logger.info("Step %d action %d: %s", step_idx + 1, action_idx, action)
            obs, reward, done, info, step_info = agent.step(action)

            logger.info("Reward: %.2f", reward)
            logger.info("Done: %s", done)

            screenshot_file = f"step_{step_idx + 1}_{action_idx}_{action_timestamp}.png"
            with open(os.path.join(example_result_dir, screenshot_file), "wb") as _f:
                _f.write(obs["screenshot"])

            response_record = dict(response)
            response_record.update(
                {
                    "step_num": step_idx + 1,
                    "action_index": action_idx,
                    "action_timestamp": action_timestamp,
                    "action": action,
                    "reward": reward,
                    "done": done,
                    "info": info,
                    "step_info": step_info,
                    "screenshot_file": screenshot_file,
                }
            )
            with open(
                os.path.join(example_result_dir, "traj.jsonl"), "a", encoding="utf-8"
            ) as f:
                f.write(json.dumps(response_record, ensure_ascii=False))
                f.write("\n")
            if done:
                logger.info("The episode is done.")
                break
        step_idx += 1

    result = env.evaluate()
    logger.info("Result: %.2f", result)
    scores.append(result)
    with open(
        os.path.join(example_result_dir, "result.txt"), "w", encoding="utf-8"
    ) as f:
        f.write(f"{result}\n")


def setup_logger(example, example_result_dir):
    runtime_logger = logging.getLogger(f"desktopenv.example.{example['id']}")
    runtime_logger.setLevel(logging.DEBUG)
    runtime_logger.addHandler(
        logging.FileHandler(os.path.join(example_result_dir, "runtime.log"))
    )
    return runtime_logger
