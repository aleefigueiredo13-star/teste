from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def project_root(root: str | Path | None = None) -> Path:
    if root:
        return Path(root).resolve()
    env_root = os.getenv("PIXEL_LEGAL_HOME")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parents[1]


def ensure_project_layout(root: str | Path | None = None) -> Path:
    base = project_root(root)
    for rel in (
        "workspace/processos",
        "workspace/tarefas",
        "workspace/outputs",
        "logs",
    ):
        (base / rel).mkdir(parents=True, exist_ok=True)
    return base


def safe_case_id(value: str) -> str:
    value = value.strip()
    if not value:
        return "SEM-NUMERO"
    cleaned = re.sub(r"[^0-9A-Za-zÀ-ÿ._-]+", "-", value)
    return cleaned.strip("-.")[:120] or "SEM-NUMERO"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_event(
    task_id: str,
    agent: str,
    event: str,
    description: str,
    *,
    state: str | None = None,
    metadata: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = ensure_project_layout(root)
    record: dict[str, Any] = {
        "timestamp": now_iso(),
        "task_id": task_id,
        "agent": agent,
        "event": event,
        "description": description,
    }
    if state:
        record["state"] = state
    if metadata:
        record["metadata"] = metadata
    append_jsonl(base / "logs" / "activity.jsonl", record)
    return record


def read_events(
    task_id: str | None = None,
    *,
    limit: int = 500,
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    path = project_root(root) / "logs" / "activity.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if task_id is None or row.get("task_id") == task_id:
                rows.append(row)
    return rows[-limit:]


def case_dir(case_id: str, root: str | Path | None = None) -> Path:
    return project_root(root) / "workspace" / "processos" / safe_case_id(case_id)


def create_case(
    process_number: str,
    represented_as: str,
    *,
    root: str | Path | None = None,
) -> Path:
    base = case_dir(process_number, root)
    for rel in ("documents", "tasks", "research", "outputs"):
        (base / rel).mkdir(parents=True, exist_ok=True)
    case_file = base / "case.json"
    data = read_json(case_file, {}) or {}
    if not data:
        data = {
            "process": process_number.strip() or base.name,
            "case_id": base.name,
            "represented_as": represented_as,
            "created_at": now_iso(),
        }
    else:
        data["represented_as"] = represented_as or data.get("represented_as", "Outro")
        data["updated_at"] = now_iso()
    atomic_write_json(case_file, data)
    return base


def _unique_destination(folder: Path, filename: str) -> Path:
    target = folder / Path(filename).name
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    i = 2
    while True:
        candidate = folder / f"{stem}-{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def attach_documents(case_path: Path, files: Iterable[str | Path]) -> list[str]:
    docs = case_path / "documents"
    docs.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for item in files:
        src = Path(item)
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(src)
        dst = _unique_destination(docs, src.name)
        shutil.copy2(src, dst)
        names.append(dst.name)
    return names


def next_task_id(case_path: Path) -> str:
    tasks = case_path / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    nums = []
    for child in tasks.glob("task-*"):
        try:
            nums.append(int(child.name.split("-")[-1]))
        except ValueError:
            pass
    return f"task-{(max(nums, default=0) + 1):03d}"


def create_task(
    case_path: Path,
    task_text: str,
    represented_as: str,
    documents: list[str],
    *,
    auto_orchestrator: bool = True,
    selected_agents: list[str] | None = None,
) -> tuple[str, Path]:
    task_id = next_task_id(case_path)
    task_path = case_path / "tasks" / task_id
    task_path.mkdir(parents=True, exist_ok=False)
    data = {
        "task_id": task_id,
        "process": read_json(case_path / "case.json", {}).get("process", case_path.name),
        "represented_as": represented_as,
        "task": task_text.strip(),
        "documents": documents,
        "auto_orchestrator": bool(auto_orchestrator),
        "selected_agents": selected_agents or [],
        "status": "queued",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "agent_states": {
            "estagiario": "IDLE",
            "junior": "IDLE",
            "senior": "IDLE",
        },
        "usage": {},
        "final_artifact": None,
    }
    atomic_write_json(task_path / "task.json", data)
    append_event(task_id, "orchestrator", "task_created", "Tarefa criada.", root=case_path.parents[2])
    return task_id, task_path


def find_task(task_id: str, *, root: str | Path | None = None) -> tuple[Path, Path]:
    process_root = project_root(root) / "workspace" / "processos"
    for task_file in process_root.glob(f"*/tasks/{task_id}/task.json"):
        return task_file.parents[2], task_file.parent
    raise FileNotFoundError(f"Tarefa {task_id} não encontrada")


def load_task(task_path: Path) -> dict[str, Any]:
    data = read_json(task_path / "task.json")
    if not isinstance(data, dict):
        raise FileNotFoundError(task_path / "task.json")
    return data


def update_task(task_path: Path, **changes: Any) -> dict[str, Any]:
    data = load_task(task_path)
    data.update(changes)
    data["updated_at"] = now_iso()
    atomic_write_json(task_path / "task.json", data)
    return data


def set_agent_state(task_path: Path, agent: str, state: str, description: str | None = None, *, root: str | Path | None = None) -> None:
    data = load_task(task_path)
    states = dict(data.get("agent_states", {}))
    states[agent] = state
    data["agent_states"] = states
    data["updated_at"] = now_iso()
    atomic_write_json(task_path / "task.json", data)
    if description:
        append_event(data["task_id"], agent, "state_changed", description, state=state, root=root)


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def list_tasks(*, root: str | Path | None = None) -> list[dict[str, Any]]:
    base = project_root(root) / "workspace" / "processos"
    out: list[dict[str, Any]] = []
    for task_file in base.glob("*/tasks/task-*/task.json"):
        data = read_json(task_file, {})
        if data:
            data = dict(data)
            data["_task_path"] = str(task_file.parent)
            data["_case_path"] = str(task_file.parents[2])
            out.append(data)
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def load_pricing(*, root: str | Path | None = None) -> dict[str, Any]:
    return read_json(project_root(root) / "pricing.json", {"models": {}}) or {"models": {}}


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
    *,
    root: str | Path | None = None,
) -> float | None:
    model_rates = load_pricing(root=root).get("models", {}).get(model)
    if not model_rates:
        return None
    uncached = max(0, input_tokens - cached_tokens - cache_write_tokens)
    cost = (
        uncached * float(model_rates["input"])
        + cached_tokens * float(model_rates.get("cached_input", model_rates["input"]))
        + cache_write_tokens * float(model_rates.get("cache_write", model_rates["input"]))
        + output_tokens * float(model_rates["output"])
    ) / 1_000_000
    return round(cost, 6)
