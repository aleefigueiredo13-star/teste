from __future__ import annotations

from typing import Any

from tools.web_search import WebSearcher


TRUSTED_LEGAL_DOMAINS = [
    "tst.jus.br",
    "trt1.jus.br",
    "trt2.jus.br",
    "stf.jus.br",
    "stj.jus.br",
    "planalto.gov.br",
]


def legal_search(
    searcher: WebSearcher,
    query: str,
    *,
    task_id: str,
    agent: str,
    limit: int = 5,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return searcher.search(
        query,
        task_id=task_id,
        agent=agent,
        limit=limit,
        allowed_domains=TRUSTED_LEGAL_DOMAINS,
    )
