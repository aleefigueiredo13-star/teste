from __future__ import annotations

from typing import Any


AGENT_NAMES = {
    "estagiario": "ESTAGIÁRIO",
    "junior": "ADVOGADO JÚNIOR",
    "senior": "ADVOGADO SÊNIOR",
}

STATE_NAMES = {
    "IDLE": "Livre",
    "READING": "Lendo",
    "RESEARCHING": "Pesquisando",
    "WRITING": "Redigindo",
    "REVIEWING": "Revisando",
    "WAITING": "Aguardando",
    "REVISING": "Corrigindo",
    "DONE": "Concluído",
    "ERROR": "Erro",
}


def format_task_panel(task: dict[str, Any], plan: dict[str, Any] | None = None) -> str:
    if not task:
        return "Nenhuma tarefa selecionada."
    lines = [
        task.get("task_id", "").upper(),
        "",
        task.get("task", ""),
        "",
        f"Processo: {task.get('process', '')}",
        f"Representamos: {task.get('represented_as', '')}",
        f"Status: {task.get('status', '')}",
        *(["TRABALHO CONCLUÍDO."] if task.get("status") == "completed" else []),
        "",
        "FLUXO",
    ]
    steps = [step.get("agent") for step in (plan or {}).get("steps", [])]
    states = task.get("agent_states", {})
    for agent in ("estagiario", "junior", "senior"):
        if agent not in steps and states.get(agent, "IDLE") == "IDLE":
            continue
        state = states.get(agent, "IDLE")
        if state == "DONE":
            marker = "✓"
        elif state == "REVISING":
            marker = "↻"
        elif state == "ERROR":
            marker = "!"
        elif state not in {"IDLE", "WAITING"}:
            marker = "●"
        else:
            marker = "○"
        lines.append(f"{marker} {AGENT_NAMES[agent]} — {STATE_NAMES.get(state, state)}")

    usage = task.get("usage", {})
    if usage:
        lines += ["", "USO"]
        total = 0
        total_cost = 0.0
        cost_known = True
        for agent, row in usage.items():
            tokens = int(row.get("input_tokens", 0)) + int(row.get("output_tokens", 0))
            total += tokens
            cost = row.get("estimated_cost")
            if cost is None:
                cost_known = False
            else:
                total_cost += float(cost)
            lines.append(f"{AGENT_NAMES.get(agent, agent)}: {tokens:,} tokens".replace(",", "."))
        lines.append(f"TOTAL: {total:,} tokens".replace(",", "."))
        if cost_known:
            lines.append(f"Estimativa: US$ {total_cost:.4f}")
    final_artifact = task.get("final_artifact")
    if final_artifact:
        lines += ["", f"Arquivo final: {final_artifact}"]
    return "\n".join(lines)


def format_employee_panel(agent: str, task: dict[str, Any], events: list[dict[str, Any]]) -> str:
    state = task.get("agent_states", {}).get(agent, "IDLE") if task else "IDLE"
    agent_events = [e for e in events if e.get("agent") == agent]
    activity = agent_events[-1].get("description", "") if agent_events else "Sem atividade registrada."
    docs: set[str] = set()
    for event in agent_events:
        metadata = event.get("metadata") or {}
        if metadata.get("document"):
            docs.add(metadata["document"])
        docs.update(metadata.get("documents") or [])
    outputs = []
    if task:
        if agent == "estagiario":
            outputs = ["result.json", "result.md"]
        elif agent == "junior":
            outputs = ["result.json", "minuta.md"]
        else:
            outputs = ["review.json", "final.md"]
    lines = [
        AGENT_NAMES[agent],
        "",
        f"STATUS: {STATE_NAMES.get(state, state)}",
        f"TAREFA: {task.get('task', '') if task else '-'}",
        f"ATIVIDADE: {activity}",
        "",
        "DOCUMENTOS CONSULTADOS:",
        *(sorted(docs) or ["Nenhum registrado."]),
        "",
        "RESULTADOS PRODUZIDOS:",
        *outputs,
    ]
    return "\n".join(lines)
