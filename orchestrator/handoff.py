from __future__ import annotations

import json
from typing import Any


SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["document", "web", "legal", "other"]},
        "document": {"type": "string"},
        "page": {"type": ["integer", "null"]},
        "locator": {"type": "string"},
        "url": {"type": "string"},
        "title": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["kind", "document", "page", "locator", "url", "title", "note"],
    "additionalProperties": False,
}

FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["FATO", "PROVA", "TESE", "INFERÊNCIA", "RISCO", "JURISPRUDÊNCIA", "OUTRO"],
        },
        "statement": {"type": "string"},
        "source_refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["category", "statement", "source_refs"],
    "additionalProperties": False,
}

HANDOFF_SCHEMA = {
    "type": "object",
    "properties": {
        "agent": {"type": "string"},
        "task_id": {"type": "string"},
        "status": {"type": "string", "enum": ["completed", "blocked"]},
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": FINDING_SCHEMA},
        "sources": {"type": "array", "items": SOURCE_SCHEMA},
        "risks": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "deliverable_markdown": {"type": "string"},
        "recommended_next_step": {"type": "string"},
    },
    "required": [
        "agent", "task_id", "status", "summary", "findings", "sources",
        "risks", "open_questions", "artifacts", "deliverable_markdown",
        "recommended_next_step"
    ],
    "additionalProperties": False,
}

SENIOR_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "agent": {"type": "string", "enum": ["senior"]},
        "task_id": {"type": "string"},
        "status": {"type": "string", "enum": ["completed", "blocked"]},
        "approved": {"type": "boolean"},
        "summary": {"type": "string"},
        "problems": {"type": "array", "items": {"type": "string"}},
        "instructions_to_junior": {"type": "array", "items": {"type": "string"}},
        "sources": {"type": "array", "items": SOURCE_SCHEMA},
        "risks": {"type": "array", "items": {"type": "string"}},
        "final_markdown": {"type": "string"},
    },
    "required": [
        "agent", "task_id", "status", "approved", "summary", "problems",
        "instructions_to_junior", "sources", "risks", "final_markdown"
    ],
    "additionalProperties": False,
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {"type": "string"},
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "enum": ["estagiario", "junior", "senior"]},
                    "task": {"type": "string"},
                },
                "required": ["agent", "task"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["objective", "steps"],
    "additionalProperties": False,
}

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "sources": {"type": "array", "items": SOURCE_SCHEMA},
    },
    "required": ["answer", "sources"],
    "additionalProperties": False,
}


def text_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "strict": True,
            "schema": schema,
        }
    }


def parse_output_text(response: Any) -> dict[str, Any]:
    text = getattr(response, "output_text", None)
    if not text:
        raise ValueError("A resposta do modelo não contém output_text estruturado.")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Structured output inválido: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Structured output deveria ser um objeto JSON.")
    return value


def result_to_markdown(result: dict[str, Any]) -> str:
    lines = [f"# {result.get('agent', 'agente').title()} — resultado", "", result.get("summary", "")]
    findings = result.get("findings") or []
    if findings:
        lines += ["", "## Achados"]
        for item in findings:
            refs = ", ".join(item.get("source_refs") or [])
            suffix = f" — Fonte: {refs}" if refs else ""
            lines.append(f"- **{item.get('category', 'OUTRO')}**: {item.get('statement', '')}{suffix}")
    risks = result.get("risks") or []
    if risks:
        lines += ["", "## Riscos"] + [f"- {risk}" for risk in risks]
    questions = result.get("open_questions") or []
    if questions:
        lines += ["", "## Questões em aberto"] + [f"- {question}" for question in questions]
    deliverable = result.get("deliverable_markdown", "").strip()
    if deliverable:
        lines += ["", "## Entrega", "", deliverable]
    return "\n".join(lines).rstrip() + "\n"
