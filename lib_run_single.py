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


def _is_done_action(action) -> bool:
    return action == "DONE" or (
        isinstance(action, dict) and action.get("action_type") == "DONE"
    )


def _verifier_plan_text(response) -> str:
    if isinstance(response, dict):
        for key in ("executor_plan", "plan", "thought", "response"):
            if response.get(key):
                return str(response[key])
        return json.dumps(response, ensure_ascii=False)
    return str(response)


def run_single_example_vlaa_gui(
    agent,
    env,
    example,
    max_steps,
    instruction,
    args,
    example_result_dir,
    scores,
    verifier_agent=None,
):
    runtime_logger = setup_logger(example, example_result_dir)
    try:
        agent.reset(runtime_logger)
    except Exception:
        agent.reset()

    previous_snapshot = getattr(env, "snapshot_name", None)
    task_snapshot = example.get("snapshot") or getattr(args, "snapshot_name", None)
    provider_name = (
        getattr(args, "provider_name", getattr(env, "provider_name", "")) or ""
    ).lower()
    use_task_snapshot = bool(task_snapshot) and provider_name in {"vmware", "virtualbox"}

    if use_task_snapshot:
        logger.info("Using task snapshot for VLAA GUI: %s", task_snapshot)
        env.snapshot_name = task_snapshot
        # DesktopEnv skips snapshot restore when it thinks the VM is clean. For
        # task-specific local snapshots, force the first reset to restore too.
        env.is_environment_used = True
    elif task_snapshot:
        logger.info(
            "Skipping task snapshot %s for provider %s; using configured snapshot %s.",
            task_snapshot,
            provider_name or "unknown",
            previous_snapshot,
        )

    try:
        env.reset(task_config=example)
        time.sleep(getattr(args, "wait_after_reset", 60))
        obs = env._get_obs()

        with open(os.path.join(example_result_dir, "step_0.png"), "wb") as _f:
            _f.write(obs["screenshot"])

        with open(
            os.path.join(example_result_dir, "instruction.txt"), "w", encoding="utf-8"
        ) as f:
            f.write(instruction)

        done = False
        step_idx = 0
        trajectory_lines = []

        while not done and step_idx < max_steps:
            response, actions = agent.predict(instruction, obs)
            if not actions:
                logger.warning("VLAA GUI agent returned no actions; ending episode.")
                response_record = dict(response) if isinstance(response, dict) else {}
                response_record.update(
                    {
                        "step_num": step_idx + 1,
                        "action_timestamp": datetime.datetime.now().strftime(
                            "%Y%m%d@%H%M%S"
                        ),
                        "action": None,
                        "reward": None,
                        "done": done,
                        "info": {"message": "No actions returned by VLAA GUI agent."},
                        "screenshot_file": None,
                    }
                )
                with open(
                    os.path.join(example_result_dir, "traj.jsonl"),
                    "a",
                    encoding="utf-8",
                ) as f:
                    f.write(json.dumps(response_record, ensure_ascii=False))
                    f.write("\n")
                break

            for action in actions:
                action_timestamp = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")

                if verifier_agent is not None and _is_done_action(action):
                    try:
                        verdict = verifier_agent.verify_completion(
                            instruction=instruction,
                            observation=obs,
                            trajectory="\n".join(trajectory_lines),
                            executor_plan=_verifier_plan_text(response),
                        )
                    except Exception as e:
                        logger.warning("Verifier failed; accepting DONE action: %s", e)
                        verdict = {"complete": True, "reason": f"Verifier error: {e}"}

                    if not verdict.get("complete", False):
                        logger.info("Verifier rejected DONE: %s", verdict)
                        if hasattr(agent, "force_replan_from_verifier"):
                            agent.force_replan_from_verifier(
                                reason=verdict.get("reason", ""),
                                missing_steps=verdict.get("missing_steps", ""),
                            )
                        response_record = (
                            dict(response) if isinstance(response, dict) else {}
                        )
                        response_record.update(
                            {
                                "step_num": step_idx + 1,
                                "action_timestamp": action_timestamp,
                                "action": action,
                                "reward": None,
                                "done": False,
                                "info": {
                                    "verifier_rejected_done": True,
                                    "verdict": verdict,
                                },
                                "screenshot_file": None,
                            }
                        )
                        with open(
                            os.path.join(example_result_dir, "traj.jsonl"),
                            "a",
                            encoding="utf-8",
                        ) as f:
                            f.write(json.dumps(response_record, ensure_ascii=False))
                            f.write("\n")
                        trajectory_lines.append(
                            f"Step {step_idx + 1}: DONE rejected by verifier: {verdict}"
                        )
                        break

                logger.info("Step %d: %s", step_idx + 1, action)
                obs, reward, done, info = env.step(action, args.sleep_after_execution)

                logger.info("Reward: %.2f", reward)
                logger.info("Done: %s", done)

                screenshot_file = f"step_{step_idx + 1}_{action_timestamp}.png"
                with open(os.path.join(example_result_dir, screenshot_file), "wb") as _f:
                    _f.write(obs["screenshot"])

                response_record = dict(response) if isinstance(response, dict) else {}
                response_record.update(
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
                with open(
                    os.path.join(example_result_dir, "traj.jsonl"),
                    "a",
                    encoding="utf-8",
                ) as f:
                    f.write(json.dumps(response_record, ensure_ascii=False))
                    f.write("\n")
                trajectory_lines.append(
                    f"Step {step_idx + 1}: action={action} reward={reward} done={done}"
                )
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
    finally:
        if use_task_snapshot:
            env.snapshot_name = previous_snapshot


def run_single_example_gpt54(
    agent, env, example, max_steps, instruction, args, example_result_dir, scores
):
    runtime_logger = setup_logger(example, example_result_dir)
    try:
        agent.reset(runtime_logger)
    except Exception as e:
        agent.reset()

    previous_snapshot = getattr(env, "snapshot_name", None)
    task_snapshot = example.get("snapshot")
    provider_name = (
        getattr(args, "provider_name", getattr(env, "provider_name", "")) or ""
    ).lower()
    use_task_snapshot = bool(task_snapshot) and provider_name in {"vmware", "virtualbox"}

    if use_task_snapshot:
        logger.info("Using task snapshot for GPT54Agent: %s", task_snapshot)
        env.snapshot_name = task_snapshot
    elif task_snapshot:
        logger.info(
            "Skipping task snapshot %s for provider %s; using configured snapshot %s.",
            task_snapshot,
            provider_name or "unknown",
            previous_snapshot,
        )

    try:
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
    finally:
        if use_task_snapshot:
            env.snapshot_name = previous_snapshot


def setup_logger(example, example_result_dir):
    runtime_logger = logging.getLogger(f"desktopenv.example.{example['id']}")
    runtime_logger.setLevel(logging.DEBUG)
    runtime_logger.addHandler(
        logging.FileHandler(os.path.join(example_result_dir, "runtime.log"))
    )
    return runtime_logger
