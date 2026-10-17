from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from orchestrator.handoff import HANDOFF_SCHEMA, SENIOR_REVIEW_SCHEMA, parse_output_text, text_format
from orchestrator.router import load_skill
from tools.documents import read_document, search_documents
from tools.filesystem import append_event, estimate_cost, load_task, set_agent_state
from tools.legal_search import legal_search
from tools.web_search import WebSearcher


TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "document_search": {
        "type": "function",
        "name": "document_search",
        "description": "Busca trechos relevantes nos documentos locais do processo. Retorna nome do documento, página quando existente e excerto.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "filenames": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 12},
            },
            "required": ["query", "filenames", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    "read_document": {
        "type": "function",
        "name": "read_document",
        "description": "Lê trechos indexados de um documento local específico. Para PDF, page pode selecionar uma página.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "page": {"type": ["integer", "null"]},
                "max_chars": {"type": "integer", "minimum": 500, "maximum": 12000},
            },
            "required": ["filename", "page", "max_chars"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    "web_search": {
        "type": "function",
        "name": "web_search",
        "description": "Pesquisa a web de verdade e retorna somente URLs realmente consultadas pelo mecanismo de busca.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 8},
            },
            "required": ["query", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    "legal_search": {
        "type": "function",
        "name": "legal_search",
        "description": "Pesquisa legislação e jurisprudência em fontes oficiais priorizadas. Nunca deve ser usada para inventar precedentes.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 8},
            },
            "required": ["query", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def _getattr_or(mapping_or_obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(mapping_or_obj, dict):
        return mapping_or_obj.get(name, default)
    return getattr(mapping_or_obj, name, default)


def response_usage(response: Any) -> dict[str, int]:
    usage = _getattr_or(response, "usage", {}) or {}
    input_tokens = int(_getattr_or(usage, "input_tokens", 0) or 0)
    output_tokens = int(_getattr_or(usage, "output_tokens", 0) or 0)
    details = _getattr_or(usage, "input_tokens_details", {}) or {}
    cached = int(_getattr_or(details, "cached_tokens", 0) or 0)
    cache_write = int(_getattr_or(details, "cache_write_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached,
        "cache_write_tokens": cache_write,
    }


def add_usage(total: dict[str, int], current: dict[str, int]) -> None:
    for key in ("input_tokens", "output_tokens", "cached_tokens", "cache_write_tokens"):
        total[key] = int(total.get(key, 0)) + int(current.get(key, 0))


def get_openai_client() -> Any:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY não configurada. Copie .env.example para .env e informe a chave.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Pacote 'openai' não instalado. Execute pip install -r requirements.txt") from exc
    return OpenAI()


class AgentRunner:
    def __init__(self, client: Any, *, root: Path, case_path: Path, task_path: Path):
        self.client = client
        self.root = root
        self.case_path = case_path
        self.task_path = task_path
        self.task = load_task(task_path)
        self.task_id = self.task["task_id"]
        self.max_tool_rounds = int(os.getenv("MAX_TOOL_ROUNDS", "10"))
        self._tool_usage_records: list[dict[str, Any]] = []

    def _skill(self, agent: str) -> tuple[dict[str, str], str]:
        return load_skill(self.root / "agents" / agent / "SKILL.md")

    def _model_for(self, metadata: dict[str, str], agent: str) -> str:
        env_name = metadata.get("model_env") or {
            "estagiario": "INTERN_MODEL",
            "junior": "JUNIOR_MODEL",
            "senior": "SENIOR_MODEL",
        }[agent]
        default = "gpt-6-luna" if agent == "estagiario" else "gpt-6.1-sol"
        return os.getenv(env_name, default)

    def _allowed_tools(self, metadata: dict[str, str]) -> list[str]:
        return [name.strip() for name in metadata.get("tools", "").split(",") if name.strip() in TOOL_DEFINITIONS]

    def _dispatch(self, agent: str, name: str, args: dict[str, Any]) -> Any:
        if name == "document_search":
            set_agent_state(self.task_path, agent, "READING", f"Buscando nos autos: {args['query']}", root=self.root)
            results = search_documents(
                self.case_path,
                args["query"],
                filenames=args.get("filenames") or None,
                limit=args.get("limit", int(os.getenv("DOCUMENT_SEARCH_LIMIT", "8"))),
            )
            append_event(
                self.task_id,
                agent,
                "document_search",
                f"Pesquisa documental por '{args['query']}' retornou {len(results)} trecho(s).",
                state="READING",
                metadata={"query": args["query"], "documents": sorted({r["document"] for r in results})},
                root=self.root,
            )
            return results
        if name == "read_document":
            set_agent_state(self.task_path, agent, "READING", f"Lendo {args['filename']}", root=self.root)
            result = read_document(
                self.case_path,
                args["filename"],
                page=args.get("page"),
                max_chars=args.get("max_chars", 7000),
            )
            append_event(
                self.task_id,
                agent,
                "document_read",
                f"Consultado {args['filename']}" + (f", página {args['page']}" if args.get("page") else ""),
                state="READING",
                metadata={"document": args["filename"], "page": args.get("page")},
                root=self.root,
            )
            return result
        searcher = WebSearcher(
            self.client,
            os.getenv("WEB_SEARCH_MODEL", "gpt-6-luna"),
            root=self.root,
            case_path=self.case_path,
        )
        if name == "web_search":
            set_agent_state(self.task_path, agent, "RESEARCHING", f"Pesquisando: {args['query']}", root=self.root)
            rows, tool_usage = searcher.search(args["query"], task_id=self.task_id, agent=agent, limit=args.get("limit", 5))
            self._tool_usage_records.append(tool_usage)
            return rows
        if name == "legal_search":
            set_agent_state(self.task_path, agent, "RESEARCHING", f"Pesquisa jurídica: {args['query']}", root=self.root)
            rows, tool_usage = legal_search(searcher, args["query"], task_id=self.task_id, agent=agent, limit=args.get("limit", 5))
            tool_usage["kind"] = "legal_search"
            self._tool_usage_records.append(tool_usage)
            return rows
        raise ValueError(f"Ferramenta não autorizada/desconhecida: {name}")

    def execute(
        self,
        agent: str,
        *,
        assignment: str,
        prior_work: list[dict[str, Any]],
        revision_instructions: list[str] | None = None,
        output_schema: dict[str, Any] | None = None,
        output_name: str | None = None,
        chat_question: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        metadata, instructions = self._skill(agent)
        model = self._model_for(metadata, agent)
        allowed_names = self._allowed_tools(metadata)
        tools = [TOOL_DEFINITIONS[name] for name in allowed_names]
        schema = output_schema or (SENIOR_REVIEW_SCHEMA if agent == "senior" else HANDOFF_SCHEMA)
        schema_name = output_name or ("senior_review" if agent == "senior" else "agent_handoff")

        context = {
            "task_id": self.task_id,
            "process": self.task.get("process"),
            "represented_as": self.task.get("represented_as"),
            "original_task": self.task.get("task"),
            "assignment": assignment,
            "available_documents": self.task.get("documents", []),
            "prior_work": prior_work,
            "revision_instructions": revision_instructions or [],
        }
        if chat_question:
            context["chat_question"] = chat_question

        history: list[Any] = [{"role": "user", "content": json.dumps(context, ensure_ascii=False)}]
        usage = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cache_write_tokens": 0}
        self._tool_usage_records = []

        for _round in range(self.max_tool_rounds + 1):
            response = self.client.responses.create(
                model=model,
                instructions=instructions,
                input=history,
                tools=tools,
                tool_choice="auto" if tools else "none",
                text=text_format(schema_name, schema),
                include=["reasoning.encrypted_content"],
                store=False,
            )
            add_usage(usage, response_usage(response))
            output_items = list(getattr(response, "output", []) or [])
            calls = [item for item in output_items if _getattr_or(item, "type") == "function_call"]
            if not calls:
                result = parse_output_text(response)
                main_call = {
                    **usage,
                    "model": model,
                    "estimated_cost": estimate_cost(
                        model, usage["input_tokens"], usage["output_tokens"],
                        usage["cached_tokens"], usage.get("cache_write_tokens", 0), root=self.root
                    ),
                    "kind": "agent",
                }
                total_usage = dict(usage)
                for tool_usage in self._tool_usage_records:
                    add_usage(total_usage, tool_usage)
                known_costs = [r.get("estimated_cost") for r in [main_call, *self._tool_usage_records]]
                estimated = None if any(v is None for v in known_costs) else round(sum(float(v) for v in known_costs), 6)
                usage_record = {
                    **total_usage,
                    "model": model,
                    "estimated_cost": estimated,
                    "calls": [main_call, *self._tool_usage_records],
                }
                return result, usage_record

            history.extend(output_items)
            for call in calls:
                name = _getattr_or(call, "name")
                if name not in allowed_names:
                    result: Any = {"error": f"Ferramenta '{name}' não permitida para {agent}."}
                else:
                    raw_args = _getattr_or(call, "arguments", "{}") or "{}"
                    try:
                        args = json.loads(raw_args)
                        result = self._dispatch(agent, name, args)
                    except Exception as exc:  # Tool failures are returned to the model, not hidden.
                        result = {"error": type(exc).__name__, "message": str(exc)}
                        append_event(self.task_id, agent, "tool_error", f"Erro em {name}: {exc}", state="ERROR", root=self.root)
                history.append({
                    "type": "function_call_output",
                    "call_id": _getattr_or(call, "call_id"),
                    "output": json.dumps(result, ensure_ascii=False),
                })

        raise RuntimeError(f"Limite de {self.max_tool_rounds} rodadas de ferramentas excedido por {agent}.")
