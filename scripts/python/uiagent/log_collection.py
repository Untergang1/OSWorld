from __future__ import annotations

import json
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


SUPPORTED_ARTIFACT_MODES = {"copy", "off"}


def resolve_uiagent_log_root(uiagent_root: str = "", uiagent_log_root: str = "") -> Path:
    if uiagent_log_root:
        return Path(uiagent_log_root).expanduser().resolve()
    if uiagent_root:
        return (Path(uiagent_root).expanduser().resolve() / "log" / "execute")
    env_root = Path.home() / "UIAgent" / "log" / "execute"
    return env_root.resolve()


def _safe_json_load(path: Path) -> Optional[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _safe_write_text(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        return


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        return


def _safe_copy_file(src: Path, dst: Path) -> bool:
    try:
        if not src.is_file():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except OSError:
        return False


def _copy_tree_incremental(src_dir: Path, dst_dir: Path) -> None:
    if not src_dir.is_dir():
        return
    for src in src_dir.rglob("*"):
        if not src.is_file():
            continue
        rel_path = src.relative_to(src_dir)
        _safe_copy_file(src, dst_dir / rel_path)


def _episode_task_id(episode: dict[str, Any]) -> str:
    task_parameters = episode.get("task_parameters")
    if not isinstance(task_parameters, dict):
        return ""
    task_config = task_parameters.get("osworld_task_config")
    if not isinstance(task_config, dict):
        return ""
    return str(task_config.get("id") or "").strip()


def _episode_instruction(episode: dict[str, Any]) -> str:
    return str(episode.get("task") or "").strip()


def _timestamp_for_filename(value: Any) -> str:
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text)
            return parsed.strftime("%Y%m%d@%H%M%S")
        except ValueError:
            return "".join(ch if ch.isalnum() else "_" for ch in text)[:32]
    return datetime.now().strftime("%Y%m%d@%H%M%S")


def _relative_copied_path(path_text: Any, run_dir: Path, artifact_dir: Path) -> Optional[str]:
    if not path_text:
        return None
    try:
        src = Path(str(path_text))
        rel = src.resolve().relative_to(run_dir.resolve())
        return str((artifact_dir / rel).relative_to(artifact_dir.parent))
    except (OSError, ValueError):
        return str(path_text)


def _action_text(step: dict[str, Any]) -> str:
    payload = step.get("decision_payload")
    if isinstance(payload, dict):
        if payload.get("action_code"):
            return str(payload["action_code"])
        operation = payload.get("atomic_operation_type") or step.get("atomic_operation_type")
        params = payload.get("params") or step.get("params") or {}
        if operation:
            return f"{operation}({json.dumps(params, ensure_ascii=False, default=str)})"
    operation = step.get("atomic_operation_type")
    if operation:
        return f"{operation}({json.dumps(step.get('params') or {}, ensure_ascii=False, default=str)})"
    return str(step.get("decision") or "")


def find_matching_uiagent_run(
    log_root: Path,
    *,
    example_id: str,
    instruction: str,
    started_after: float,
    grace_seconds: float = 60.0,
) -> Optional[Path]:
    if not log_root.is_dir():
        return None

    candidates = [path for path in log_root.iterdir() if path.is_dir()]
    candidates.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)

    exact_instruction_match: Optional[Path] = None
    for run_dir in candidates:
        try:
            if run_dir.stat().st_mtime < started_after - grace_seconds:
                continue
        except OSError:
            continue

        episode = _safe_json_load(run_dir / "execution_episode.json")
        if not episode:
            continue
        if example_id and _episode_task_id(episode) == example_id:
            return run_dir
        if instruction and _episode_instruction(episode) == instruction:
            exact_instruction_match = exact_instruction_match or run_dir

    return exact_instruction_match


def sync_uiagent_run_artifacts(
    *,
    run_dir: Path,
    example_dir: Path,
    artifact_mode: str = "copy",
    final_record: Optional[dict[str, Any]] = None,
) -> bool:
    if artifact_mode not in SUPPORTED_ARTIFACT_MODES:
        raise ValueError(f"Unsupported UIAgent artifact mode: {artifact_mode}")
    if not run_dir.is_dir():
        return False

    example_dir.mkdir(parents=True, exist_ok=True)
    _safe_write_text(example_dir / "uiagent_log_dir.txt", f"{run_dir}\n")

    artifact_dir = example_dir / "uiagent_artifacts" / run_dir.name
    if artifact_mode == "copy":
        _copy_tree_incremental(run_dir, artifact_dir)
        _safe_write_text(example_dir / "uiagent_artifacts_latest.txt", f"{artifact_dir}\n")

    episode = _safe_json_load(run_dir / "execution_episode.json")
    if not episode:
        return False

    start_page = episode.get("start_page") if isinstance(episode.get("start_page"), dict) else {}
    start_screenshot = start_page.get("screenshot") if isinstance(start_page, dict) else None
    if start_screenshot:
        _safe_copy_file(Path(str(start_screenshot)), example_dir / "step_0.png")

    rows: list[dict[str, Any]] = []
    for step in episode.get("steps") or []:
        if not isinstance(step, dict):
            continue

        step_index = int(step.get("step_index") or len(rows) + 1)
        timestamp = _timestamp_for_filename(step.get("created_at"))
        screenshot_file = None
        after = step.get("after") if isinstance(step.get("after"), dict) else {}
        after_screenshot = after.get("screenshot") if isinstance(after, dict) else None
        if after_screenshot:
            screenshot_name = f"step_{step_index}_{timestamp}.png"
            if _safe_copy_file(Path(str(after_screenshot)), example_dir / screenshot_name):
                screenshot_file = screenshot_name

        before = step.get("before") if isinstance(step.get("before"), dict) else {}
        before_screenshot = before.get("screenshot") if isinstance(before, dict) else None
        after_screenshot_text = after.get("screenshot") if isinstance(after, dict) else None
        row = {
            "step_num": step_index,
            "controller_turn": step.get("controller_turn"),
            "action_timestamp": timestamp,
            "decision": step.get("decision"),
            "decision_payload": step.get("decision_payload"),
            "atomic_operation_type": step.get("atomic_operation_type"),
            "params": step.get("params"),
            "target": step.get("target"),
            "result": step.get("result"),
            "action": _action_text(step),
            "before_screenshot": _relative_copied_path(before_screenshot, run_dir, artifact_dir)
            if artifact_mode == "copy"
            else before_screenshot,
            "after_screenshot": _relative_copied_path(after_screenshot_text, run_dir, artifact_dir)
            if artifact_mode == "copy"
            else after_screenshot_text,
            "screenshot_file": screenshot_file,
            "uiagent_log_dir": str(run_dir),
        }
        rows.append(row)

    if rows:
        try:
            traj_path = example_dir / "traj.jsonl"
            tmp_path = traj_path.with_suffix(".jsonl.tmp")
            with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, default=str))
                    handle.write("\n")
            tmp_path.replace(traj_path)
        except OSError:
            pass

    record = dict(final_record or {})
    if not record:
        record = {
            "status": "partial",
            "log_dir": str(run_dir),
            "execution_episode_path": str(run_dir / "execution_episode.json"),
            "execution_perf_path": str(run_dir / "execution_perf.json"),
            "latest_screenshot": str(start_screenshot or ""),
            "controller_turn": len(rows),
        }
    else:
        record.setdefault("log_dir", str(run_dir))
    _safe_write_json(example_dir / "uiagent_run_result.json", record)
    return True


class UIAgentArtifactCollector:
    def __init__(
        self,
        *,
        log_root: Path,
        example_dir: Path,
        example_id: str,
        instruction: str,
        artifact_mode: str = "copy",
        sync_interval: float = 5.0,
        started_after: Optional[float] = None,
    ) -> None:
        self.log_root = log_root
        self.example_dir = example_dir
        self.example_id = example_id
        self.instruction = instruction
        self.artifact_mode = artifact_mode
        self.sync_interval = max(0.5, float(sync_interval or 5.0))
        self.started_after = time.time() if started_after is None else started_after
        self.run_dir: Optional[Path] = None
        self.last_error: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.artifact_mode not in SUPPORTED_ARTIFACT_MODES:
            raise ValueError(f"Unsupported UIAgent artifact mode: {self.artifact_mode}")
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="UIAgentArtifactCollector", daemon=True)
        self._thread.start()

    def stop(self, final_record: Optional[dict[str, Any]] = None, timeout: float = 10.0) -> None:
        self.sync_once(final_record=final_record)
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def sync_once(
        self,
        *,
        final_record: Optional[dict[str, Any]] = None,
        run_dir: Optional[Path] = None,
    ) -> bool:
        if run_dir is not None:
            self.run_dir = run_dir
        if self.run_dir is None:
            self.run_dir = find_matching_uiagent_run(
                self.log_root,
                example_id=self.example_id,
                instruction=self.instruction,
                started_after=self.started_after,
            )
        if self.run_dir is None:
            return False
        return sync_uiagent_run_artifacts(
            run_dir=self.run_dir,
            example_dir=self.example_dir,
            artifact_mode=self.artifact_mode,
            final_record=final_record,
        )

    def _run(self) -> None:
        while not self._stop_event.wait(self.sync_interval):
            try:
                self.sync_once()
            except Exception as exc:  # pragma: no cover - best-effort background logging
                self.last_error = f"{type(exc).__name__}: {exc}"
