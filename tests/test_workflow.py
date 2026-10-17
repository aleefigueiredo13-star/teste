from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from orchestrator.workflow import AgentRunner, WorkflowEngine
from tools.filesystem import attach_documents, create_case, create_task, load_task, read_events


@dataclass
class FakeResponse:
    output_text: str = ""
    output: list | None = None
    usage: object | None = None

    def __post_init__(self):
        if self.output is None:
            self.output = []
        if self.usage is None:
            self.usage = SimpleNamespace(
                input_tokens=100,
                output_tokens=50,
                input_tokens_details=SimpleNamespace(cached_tokens=10),
            )


class FakeResponses:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("FakeResponses sem resposta configurada")
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.responses = FakeResponses(responses)


def handoff(agent: str, task_id: str, text: str) -> dict:
    return {
        "agent": agent,
        "task_id": task_id,
        "status": "completed",
        "summary": text,
        "findings": [],
        "sources": [],
        "risks": [],
        "open_questions": [],
        "artifacts": [],
        "deliverable_markdown": f"# {text}",
        "recommended_next_step": "senior_review" if agent == "junior" else "junior_analysis",
    }


def review(task_id: str, approved: bool, label: str) -> dict:
    return {
        "agent": "senior",
        "task_id": task_id,
        "status": "completed",
        "approved": approved,
        "summary": label,
        "problems": [] if approved else ["Fundamentação sem fonte documental."],
        "instructions_to_junior": [] if approved else ["Localizar e citar o trecho da sentença."],
        "sources": [],
        "risks": [],
        "final_markdown": "# Versão final aprovada" if approved else "",
    }


def test_agent_execution_with_real_document_tool(project_fixture: Path) -> None:
    case = create_case("0100", "Reclamada", root=project_fixture)
    doc = project_fixture / "origem.txt"
    doc.write_text("A sentença deferiu horas extras e indeferiu dano moral.", encoding="utf-8")
    names = attach_documents(case, [doc])
    task_id, task_path = create_task(case, "Mapear a sentença", "Reclamada", names, auto_orchestrator=False, selected_agents=["estagiario"])

    tool_call = {
        "type": "function_call",
        "name": "document_search",
        "arguments": json.dumps({"query": "horas extras", "filenames": [], "limit": 5}),
        "call_id": "call-1",
    }
    final = handoff("estagiario", task_id, "Relatório concluído")
    client = FakeClient([
        FakeResponse(output=[tool_call]),
        FakeResponse(output_text=json.dumps(final, ensure_ascii=False)),
    ])
    runner = AgentRunner(client, root=project_fixture, case_path=case, task_path=task_path)
    result, usage = runner.execute("estagiario", assignment="Mapear", prior_work=[])
    assert result["summary"] == "Relatório concluído"
    assert usage["input_tokens"] == 200
    events = read_events(task_id, root=project_fixture)
    assert any(e["event"] == "document_search" for e in events)


def test_handoff_rejection_revision_and_final_approval(project_fixture: Path) -> None:
    case = create_case("0200", "Reclamada", root=project_fixture)
    doc = project_fixture / "sentenca.txt"
    doc.write_text("Sentença líquida. Há capítulo de horas extras.", encoding="utf-8")
    names = attach_documents(case, [doc])
    task_id, task_path = create_task(
        case,
        "Analise a sentença e verifique matéria para ED.",
        "Reclamada",
        names,
        auto_orchestrator=True,
    )
    plan = {
        "objective": "identificar matérias para ED",
        "steps": [
            {"agent": "estagiario", "task": "mapear sentença"},
            {"agent": "junior", "task": "analisar vícios"},
            {"agent": "senior", "task": "revisar estratégia"},
        ],
    }
    fake = FakeClient([
        FakeResponse(output_text=json.dumps(plan, ensure_ascii=False)),
        FakeResponse(output_text=json.dumps(handoff("estagiario", task_id, "Mapa"), ensure_ascii=False)),
        FakeResponse(output_text=json.dumps(handoff("junior", task_id, "Minuta inicial"), ensure_ascii=False)),
        FakeResponse(output_text=json.dumps(review(task_id, False, "Rejeitado"), ensure_ascii=False)),
        FakeResponse(output_text=json.dumps(handoff("junior", task_id, "Minuta corrigida"), ensure_ascii=False)),
        FakeResponse(output_text=json.dumps(review(task_id, True, "Aprovado"), ensure_ascii=False)),
    ])
    engine = WorkflowEngine(fake, root=project_fixture)
    result = engine.run_task(case, task_id)
    assert result["status"] == "completed"
    task = load_task(task_path)
    assert task["status"] == "completed"
    assert (task_path / "junior" / "minuta-rev-01.md").exists()
    assert (task_path / "senior" / "review-01.json").exists()
    assert (task_path / "senior" / "final.md").read_text(encoding="utf-8").startswith("# Versão final")
    assert (case / "outputs" / f"{task_id}-versao_final.md").exists()
    events = read_events(task_id, root=project_fixture)
    assert any(e["event"] == "review_rejected" for e in events)
    assert any(e["event"] == "handoff" for e in events)
    assert any(e["event"] == "task_completed" for e in events)


def test_senior_rejection_stops_at_cycle_limit(project_fixture: Path, monkeypatch) -> None:
    monkeypatch.setenv("MAX_REVISION_CYCLES", "1")
    case = create_case("0300", "Reclamada", root=project_fixture)
    task_id, task_path = create_task(case, "Auditar", "Reclamada", [], auto_orchestrator=False, selected_agents=["junior", "senior"])
    fake = FakeClient([
        FakeResponse(output_text=json.dumps(handoff("junior", task_id, "Minuta"), ensure_ascii=False)),
        FakeResponse(output_text=json.dumps(review(task_id, False, "Rejeitado 1"), ensure_ascii=False)),
        FakeResponse(output_text=json.dumps(handoff("junior", task_id, "Revisão"), ensure_ascii=False)),
        FakeResponse(output_text=json.dumps(review(task_id, False, "Rejeitado 2"), ensure_ascii=False)),
    ])
    engine = WorkflowEngine(fake, root=project_fixture)
    result = engine.run_task(case, task_id)
    assert result["status"] == "needs_human_review"
    assert load_task(task_path)["status"] == "needs_human_review"
