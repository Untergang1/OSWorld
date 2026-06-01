from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_AGENT_S_ROOT = Path(r"C:\Users\unter\Agent-S")


def make_run_id(agent: str, domain: str, model: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d@%H%M%S")
    safe_domain = _safe_part(domain or "all")
    safe_model = _safe_part(model or "model")
    return f"{timestamp}_{_safe_part(agent)}_{safe_domain}_{safe_model}"


def _safe_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value)


def resolve_log_dir(run_id: str, requested_log_dir: str | None = None) -> Path:
    candidates: list[Path] = []
    if requested_log_dir:
        candidates.append(Path(requested_log_dir).expanduser())
    if DEFAULT_AGENT_S_ROOT.exists():
        candidates.append(DEFAULT_AGENT_S_ROOT / "logs" / "osworld" / run_id)
    candidates.append(Path("logs") / "agent_s" / run_id)

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue

    fallback = Path("logs") / "agent_s" / run_id
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def configure_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt="[%(asctime)s %(levelname)s %(module)s/%(lineno)d-%(processName)s] %(message)s"
    )
    requested_level = getattr(logging, level.upper(), logging.INFO)

    run_handler = logging.FileHandler(log_dir / "run.log", encoding="utf-8")
    run_handler.setLevel(logging.INFO)
    run_handler.setFormatter(formatter)

    debug_handler = logging.FileHandler(log_dir / "debug.log", encoding="utf-8")
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(formatter)

    desktop_handler = logging.FileHandler(log_dir / "desktop_env.log", encoding="utf-8")
    desktop_handler.setLevel(logging.DEBUG)
    desktop_handler.setFormatter(formatter)
    desktop_handler.addFilter(logging.Filter("desktopenv"))

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(requested_level)
    stdout_handler.setFormatter(formatter)

    root_logger.addHandler(run_handler)
    root_logger.addHandler(debug_handler)
    root_logger.addHandler(desktop_handler)
    root_logger.addHandler(stdout_handler)

    return logging.getLogger("desktopenv.experiment")


def write_args(log_dir: Path, args: Any) -> None:
    data = vars(args).copy() if hasattr(args, "__dict__") else dict(args)
    with (log_dir / "args.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
