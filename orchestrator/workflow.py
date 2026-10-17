from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from orchestrator.agent import AgentRunner, get_openai_client
from orchestrator.handoff import CHAT_SCHEMA, result_to_markdown
from orchestrator.router import route_task
from tools.filesystem import (
    append_event, append_jsonl, atomic_write_json, estimate_cost, load_task, now_iso,
    project_root, set_agent_state, update_task, write_text,
)


class WorkflowEngine:
    def __init__(self, client: Any | None = None, *, root: str | Path | None = None):
        self.root = project_root(root)
        self._client = client
        self._lock = threading.Lock()

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = get_openai_client()
        return self._client

    def _save_usage(self, task_path: Path, agent: str, usage: dict[str, Any]) -> None:
        task = load_task(task_path)
        all_usage = dict(task.get("usage", {}))
        previous = all_usage.get(agent, {})
        if previous:
            merged = {
                "input_tokens": previous.get("input_tokens", 0) + usage.get("input_tokens", 0),
                "output_tokens": previous.get("output_tokens", 0) + usage.get("output_tokens", 0),
                "cached_tokens": previous.get("cached_tokens", 0) + usage.get("cached_tokens", 0),
                "cache_write_tokens": previous.get("cache_write_tokens", 0) + usage.get("cache_write_tokens", 0),
                "model": usage.get("model") or previous.get("model"),
                "calls": [*(previous.get("calls") or []), *(usage.get("calls") or [])],
            }
            prev_cost = previous.get("estimated_cost")
            new_cost = usage.get("estimated_cost")
            merged["estimated_cost"] = None if prev_cost is None or new_cost is None else round(float(prev_cost) + float(new_cost), 6)
            all_usage[agent] = merged
        else:
            all_usage[agent] = usage
        update_task(task_path, usage=all_usage)

    def _save_agent_result(self, task_path: Path, agent: str, result: dict[str, Any], *, revision: int = 0) -> None:
        folder = task_path / agent
        folder.mkdir(parents=True, exist_ok=True)
        if agent == "estagiario":
            atomic_write_json(folder / "result.json", result)
            write_text(folder / "result.md", result_to_markdown(result))
        elif agent == "junior":
            atomic_write_json(folder / "result.json", result)
            if revision:
                atomic_write_json(folder / f"result-rev-{revision:02d}.json", result)
                write_text(folder / f"minuta-rev-{revision:02d}.md", result.get("deliverable_markdown", ""))
            write_text(folder / "minuta.md", result.get("deliverable_markdown", ""))
        elif agent == "senior":
            atomic_write_json(folder / "review.json", result)
            review_lines = [
                "# Revisão do Advogado Sênior",
                "",
                f"**Status:** {'APROVADO' if result.get('approved') else 'REJEITADO'}",
                "",
                result.get("summary", ""),
            ]
            if result.get("problems"):
                review_lines += ["", "## Problemas"] + [f"- {item}" for item in result.get("problems", [])]
            if result.get("instructions_to_junior"):
                review_lines += ["", "## Instruções ao Júnior"] + [f"- {item}" for item in result.get("instructions_to_junior", [])]
            if result.get("risks"):
                review_lines += ["", "## Riscos"] + [f"- {item}" for item in result.get("risks", [])]
            write_text(folder / "revisao_senior.md", "\n".join(review_lines).rstrip() + "\n")
            if revision:
                atomic_write_json(folder / f"review-{revision:02d}.json", result)
            if result.get("approved"):
                write_text(folder / "final.md", result.get("final_markdown", ""))

    def _mark_plan_waiting(self, task_path: Path, plan: dict[str, Any]) -> None:
        for step in plan.get("steps", []):
            agent = step.get("agent")
            if agent in {"estagiario", "junior", "senior"}:
                set_agent_state(task_path, agent, "WAITING")

    def _finalize_from_result(self, case_path: Path, task_path: Path, result: dict[str, Any], filename: str = "versao_final.md") -> str:
        content = result.get("final_markdown") or result.get("deliverable_markdown") or result_to_markdown(result)
        write_text(task_path / filename, content)
        output_name = f"{task_path.name}-{filename}"
        output_path = case_path / "outputs" / output_name
        write_text(output_path, content)
        update_task(task_path, status="completed", final_artifact=str(output_path.relative_to(case_path)))
        append_event(load_task(task_path)["task_id"], "orchestrator", "task_completed", "Trabalho concluído.", state="DONE", root=self.root)
        return str(output_path)

    def run_task(self, case_path: str | Path, task_id: str) -> dict[str, Any]:
        case_path = Path(case_path)
        task_path = case_path / "tasks" / task_id
        task = load_task(task_path)
        try:
            update_task(task_path, status="running", started_at=now_iso())
            plan = route_task(
                self.client,
                root=self.root,
                task=task,
                model=os.getenv("ORCHESTRATOR_MODEL", "gpt-6-luna"),
            )
            atomic_write_json(task_path / "plan.json", plan)
            self._mark_plan_waiting(task_path, plan)
            runner = AgentRunner(self.client, root=self.root, case_path=case_path, task_path=task_path)
            prior: list[dict[str, Any]] = []
            junior_result: dict[str, Any] | None = None
            last_result: dict[str, Any] | None = None
            senior_result: dict[str, Any] | None = None

            steps = plan.get("steps", [])
            for index, step in enumerate(steps):
                agent = step["agent"]
                assignment = step["task"]
                initial_state = {"estagiario": "READING", "junior": "WRITING", "senior": "REVIEWING"}[agent]
                set_agent_state(task_path, agent, initial_state, f"Executando: {assignment}", root=self.root)
                append_event(task_id, agent, "agent_started", assignment, state=initial_state, root=self.root)
                result, usage = runner.execute(agent, assignment=assignment, prior_work=prior)
                self._save_usage(task_path, agent, usage)
                self._save_agent_result(task_path, agent, result)
                if agent == "senior" and not result.get("approved"):
                    set_agent_state(task_path, agent, "WAITING", "Revisão rejeitada; aguardando correção do Júnior.", root=self.root)
                    append_event(task_id, agent, "review_rejected", result.get("summary", "Revisão rejeitada."), state="WAITING", root=self.root)
                    completed_state = "WAITING"
                else:
                    set_agent_state(task_path, agent, "DONE", "Etapa concluída.", root=self.root)
                    completed_state = "DONE"
                append_event(task_id, agent, "agent_completed", result.get("summary", "Etapa concluída."), state=completed_state, root=self.root)
                prior.append(result)
                last_result = result
                if agent == "junior":
                    junior_result = result
                if agent == "senior":
                    senior_result = result
                if index + 1 < len(steps):
                    next_agent = steps[index + 1]["agent"]
                    append_event(
                        task_id,
                        agent,
                        "handoff",
                        f"Entrega encaminhada para {next_agent}.",
                        state="DONE",
                        metadata={"to": next_agent},
                        root=self.root,
                    )

            max_cycles = int(os.getenv("MAX_REVISION_CYCLES", "2"))
            cycle = 0
            while senior_result is not None and not senior_result.get("approved") and junior_result is not None and cycle < max_cycles:
                cycle += 1
                instructions = senior_result.get("instructions_to_junior") or senior_result.get("problems") or []
                set_agent_state(task_path, "junior", "REVISING", "Corrigindo conforme revisão do Sênior.", root=self.root)
                revised, usage = runner.execute(
                    "junior",
                    assignment="Revisar a entrega anterior conforme as determinações do Advogado Sênior.",
                    prior_work=prior,
                    revision_instructions=instructions,
                )
                self._save_usage(task_path, "junior", usage)
                self._save_agent_result(task_path, "junior", revised, revision=cycle)
                junior_result = revised
                prior.append(revised)
                set_agent_state(task_path, "junior", "DONE", "Revisão concluída e reenviada ao Sênior.", root=self.root)
                append_event(task_id, "junior", "handoff", "Versão revisada encaminhada ao Sênior.", state="DONE", root=self.root)

                set_agent_state(task_path, "senior", "REVIEWING", "Revisando versão corrigida.", root=self.root)
                reviewed, usage = runner.execute(
                    "senior",
                    assignment="Revisar novamente a versão corrigida e aprovar apenas se os problemas estiverem sanados.",
                    prior_work=prior,
                )
                self._save_usage(task_path, "senior", usage)
                self._save_agent_result(task_path, "senior", reviewed, revision=cycle)
                senior_result = reviewed
                prior.append(reviewed)
                if reviewed.get("approved"):
                    set_agent_state(task_path, "senior", "DONE", "Revisão aprovada.", root=self.root)
                else:
                    set_agent_state(task_path, "senior", "WAITING", "Revisão rejeitada; aguardando nova correção.", root=self.root)
                    append_event(task_id, "senior", "review_rejected", reviewed.get("summary", "Revisão rejeitada."), state="WAITING", root=self.root)

            if senior_result is not None:
                if senior_result.get("approved"):
                    final_path = self._finalize_from_result(case_path, task_path, senior_result)
                    return {"status": "completed", "final_path": final_path, "review": senior_result}
                update_task(task_path, status="needs_human_review", completed_at=now_iso())
                set_agent_state(task_path, "senior", "ERROR", "Limite de revisão atingido; revisão humana necessária.", root=self.root)
                append_event(task_id, "senior", "revision_limit", "Limite de ciclos atingido ou não há Júnior para correção. Revisão humana necessária.", state="ERROR", root=self.root)
                return {"status": "needs_human_review", "review": senior_result}

            if last_result is None:
                raise RuntimeError("O plano não produziu nenhuma etapa executável.")
            final_path = self._finalize_from_result(case_path, task_path, last_result)
            return {"status": "completed", "final_path": final_path, "result": last_result}
        except Exception as exc:
            update_task(task_path, status="error", error=f"{type(exc).__name__}: {exc}")
            for agent, state in load_task(task_path).get("agent_states", {}).items():
                if state not in {"DONE", "IDLE"}:
                    set_agent_state(task_path, agent, "ERROR")
            append_event(task_id, "orchestrator", "task_error", f"{type(exc).__name__}: {exc}", state="ERROR", root=self.root)
            raise

    def chat_with_agent(self, case_path: str | Path, task_id: str, agent: str, question: str) -> dict[str, Any]:
        case_path = Path(case_path)
        task_path = case_path / "tasks" / task_id
        if agent not in {"estagiario", "junior", "senior"}:
            raise ValueError("Agente inválido")
        context: list[dict[str, Any]] = []
        for candidate in ("estagiario/result.json", "junior/result.json", "senior/review.json"):
            path = task_path / candidate
            if path.exists():
                context.append(json.loads(path.read_text(encoding="utf-8")))
        runner = AgentRunner(self.client, root=self.root, case_path=case_path, task_path=task_path)
        result, usage = runner.execute(
            agent,
            assignment="Responder à pergunta do usuário sobre esta tarefa, sem revelar chain-of-thought. Dê apenas justificativa final verificável.",
            prior_work=context,
            output_schema=CHAT_SCHEMA,
            output_name="employee_chat",
            chat_question=question,
        )
        self._save_usage(task_path, agent, usage)
        append_jsonl(task_path / "chat" / f"{agent}.jsonl", {
            "timestamp": now_iso(),
            "question": question,
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
        })
        append_event(task_id, agent, "chat_answer", "Pergunta direta respondida.", root=self.root)
        return result
