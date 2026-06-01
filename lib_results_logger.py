#!/usr/bin/env python3
"""Thread-safe result summary logging for OSWorld evaluations."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from filelock import FileLock


def extract_domain_from_path(result_path: str) -> str:
    """Extract domain/application from a task result directory path."""
    path_parts = Path(result_path).parts
    if len(path_parts) >= 2:
        return path_parts[-2]
    return "unknown"


def append_task_result(
    task_id: str,
    domain: str,
    score: float,
    result_dir: str,
    args: Any,
    error_message: Optional[str] = None,
) -> None:
    """Append one task result to results.json using a cross-platform file lock."""
    result_entry = {
        "application": domain,
        "task_id": task_id,
        "status": "error" if error_message else "success",
        "score": score,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if error_message:
        result_entry["err_message"] = error_message

    summary_dir = Path(args.result_dir) / "summary"
    results_file = summary_dir / "results.json"
    lock_file = summary_dir / "results.json.lock"
    summary_dir.mkdir(parents=True, exist_ok=True)

    try:
        with FileLock(str(lock_file)):
            existing_results = []
            if results_file.exists():
                try:
                    loaded = json.loads(results_file.read_text(encoding="utf-8").strip() or "[]")
                    if isinstance(loaded, list):
                        existing_results = loaded
                except json.JSONDecodeError:
                    existing_results = []

            existing_results.append(result_entry)
            results_file.write_text(
                json.dumps(existing_results, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        print(f"Logged result: {domain}/{task_id} -> {result_entry['status']} (score: {score})")
    except Exception as exc:
        print(f"Failed to log result for {task_id}: {exc}")


def log_task_completion(example: Dict, result: float, result_dir: str, args: Any) -> None:
    """Log successful task completion."""
    task_id = example.get("id", "unknown")
    domain = extract_domain_from_path(result_dir)
    append_task_result(task_id, domain, result, result_dir, args)


def log_task_error(example: Dict, error_msg: str, result_dir: str, args: Any) -> None:
    """Log task failure without interrupting the main evaluation."""
    task_id = example.get("id", "unknown")
    domain = extract_domain_from_path(result_dir)
    append_task_result(task_id, domain, 0.0, result_dir, args, error_msg)
