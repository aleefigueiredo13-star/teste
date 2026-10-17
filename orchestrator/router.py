from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.handoff import PLAN_SCHEMA, parse_output_text, text_format
from tools.filesystem import append_event


def load_skill(skill_path: Path) -> tuple[dict[str, str], str]:
    raw = skill_path.read_text(encoding="utf-8")
    metadata: dict[str, str] = {}
    body = raw
    if raw.startswith("---\n"):
        _, header, body = raw.split("---\n", 2)
        for line in header.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    return metadata, body.strip()


def route_task(
    client: Any,
    *,
    root: Path,
    task: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    task_id = task["task_id"]
    if not task.get("auto_orchestrator", True):
        selected = [a for a in task.get("selected_agents", []) if a in {"estagiario", "junior", "senior"}]
        if not selected:
            selected = ["junior"]
        plan = {
            "objective": task["task"],
            "steps": [{"agent": agent, "task": task["task"]} for agent in selected],
        }
        append_event(task_id, "orchestrator", "plan_created", "Plano manual criado.", root=root)
        return plan

    _, instructions = load_skill(root / "agents" / "orchestrator" / "SKILL.md")
    append_event(task_id, "orchestrator", "planning", "Definindo fluxo da tarefa.", root=root)
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=json.dumps(
            {
                "task_id": task_id,
                "process": task.get("process"),
                "represented_as": task.get("represented_as"),
                "task": task.get("task"),
                "documents": task.get("documents", []),
            },
            ensure_ascii=False,
        ),
        text=text_format("workflow_plan", PLAN_SCHEMA),
        store=False,
    )
    plan = parse_output_text(response)
    append_event(
        task_id,
        "orchestrator",
        "plan_created",
        "Plano definido: " + " → ".join(step["agent"] for step in plan.get("steps", [])),
        metadata={"objective": plan.get("objective", "")},
        root=root,
    )
    return plan
