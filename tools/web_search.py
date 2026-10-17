from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.filesystem import append_event, append_jsonl, estimate_cost


def _dump(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_none=True)
    if isinstance(obj, dict):
        return obj
    data: dict[str, Any] = {}
    for key in ("type", "action", "content", "url", "title"):
        if hasattr(obj, key):
            value = getattr(obj, key)
            if hasattr(value, "model_dump"):
                value = value.model_dump(exclude_none=True)
            data[key] = value
    return data


def _extract_sources(response: Any) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for raw in getattr(response, "output", []) or []:
        item = _dump(raw)
        if item.get("type") == "web_search_call":
            action = item.get("action") or {}
            if hasattr(action, "model_dump"):
                action = action.model_dump(exclude_none=True)
            for source in action.get("sources") or []:
                if hasattr(source, "model_dump"):
                    source = source.model_dump(exclude_none=True)
                url = source.get("url")
                if url:
                    found[url] = {"url": url, "title": source.get("title") or ""}
        if item.get("type") == "message":
            content_items = item.get("content") or []
            for content in content_items:
                if hasattr(content, "model_dump"):
                    content = content.model_dump(exclude_none=True)
                for ann in content.get("annotations") or []:
                    if hasattr(ann, "model_dump"):
                        ann = ann.model_dump(exclude_none=True)
                    if ann.get("type") == "url_citation" and ann.get("url"):
                        found[ann["url"]] = {
                            "url": ann["url"],
                            "title": ann.get("title") or found.get(ann["url"], {}).get("title", ""),
                        }
    return list(found.values())


class WebSearcher:
    def __init__(self, client: Any, model: str, *, root: Path, case_path: Path):
        self.client = client
        self.model = model
        self.root = root
        self.case_path = case_path

    def search(
        self,
        query: str,
        *,
        task_id: str,
        agent: str,
        limit: int = 5,
        allowed_domains: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        append_event(
            task_id,
            agent,
            "web_search",
            f"Pesquisando na web: {query}",
            state="RESEARCHING",
            metadata={"query": query},
            root=self.root,
        )
        tool: dict[str, Any] = {"type": "web_search", "external_web_access": True}
        if allowed_domains:
            tool["filters"] = {"allowed_domains": allowed_domains}
        response = self.client.responses.create(
            model=self.model,
            input=(
                "Pesquise a consulta abaixo usando web search. Responda de forma curta e cite as fontes consultadas. "
                "Não crie URLs, decisões, números de processo ou datas que não apareçam nas fontes.\n\n"
                f"Consulta: {query}"
            ),
            tools=[tool],
            tool_choice="required",
            include=["web_search_call.action.sources", "web_search_call.results"],
            store=False,
        )
        sources = _extract_sources(response)[: max(1, limit)]
        accessed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        summary = getattr(response, "output_text", "") or ""
        rows = [{
            "query": query,
            "title": src.get("title", ""),
            "url": src["url"],
            "date": "",
            "snippet": summary[:900],
            "accessed_at": accessed,
        } for src in sources]
        research_file = self.case_path / "research" / "web_search.jsonl"
        for row in rows:
            append_jsonl(research_file, {"task_id": task_id, "agent": agent, **row})

        usage_obj = getattr(response, "usage", None)
        input_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0) if usage_obj else 0
        output_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0) if usage_obj else 0
        details = getattr(usage_obj, "input_tokens_details", None) if usage_obj else None
        cached_tokens = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
        cache_write_tokens = int(getattr(details, "cache_write_tokens", 0) or 0) if details else 0
        web_call_count = sum(1 for item in (getattr(response, "output", []) or []) if _dump(item).get("type") == "web_search_call")
        token_cost = estimate_cost(
            self.model, input_tokens, output_tokens, cached_tokens, cache_write_tokens, root=self.root
        )
        pricing = __import__("tools.filesystem", fromlist=["load_pricing"]).load_pricing(root=self.root)
        tool_fee = web_call_count * float(pricing.get("tools", {}).get("web_search_per_call", 0.0))
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "cache_write_tokens": cache_write_tokens,
            "model": self.model,
            "estimated_cost": None if token_cost is None else round(token_cost + tool_fee, 6),
            "tool_call_count": web_call_count,
            "tool_fee": round(tool_fee, 6),
            "kind": "web_search",
        }
        return rows, usage
