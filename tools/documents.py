from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from docx import Document
from pypdf import PdfReader

from tools.filesystem import atomic_write_json, read_json

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text)


def _tokens(text: str) -> list[str]:
    return [t for t in _normalize(text).split() if len(t) > 1]


def _chunk_text(text: str, *, size: int = 1800, overlap: int = 220) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            split = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
            if split > start + size // 2:
                end = split + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return [c for c in chunks if c]


def parse_document(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Formato não suportado: {suffix}")

    records: list[dict[str, Any]] = []
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        for page_no, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for chunk_no, chunk in enumerate(_chunk_text(text), start=1):
                records.append({
                    "page": page_no,
                    "locator": f"p.{page_no}/trecho-{chunk_no}",
                    "text": chunk,
                })
    elif suffix == ".docx":
        doc = Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        for chunk_no, chunk in enumerate(_chunk_text(text), start=1):
            records.append({"page": None, "locator": f"bloco-{chunk_no}", "text": chunk})
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        for chunk_no, chunk in enumerate(_chunk_text(text), start=1):
            records.append({"page": None, "locator": f"bloco-{chunk_no}", "text": chunk})

    return {
        "document": path.name,
        "path": str(path),
        "type": suffix.lstrip("."),
        "chunks": records,
    }


def build_index(case_path: str | Path, *, force: bool = False) -> dict[str, Any]:
    case_path = Path(case_path)
    docs_dir = case_path / "documents"
    index_path = case_path / "research" / "document_index.json"
    current = sorted(
        (p.name, p.stat().st_mtime_ns, p.stat().st_size)
        for p in docs_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ) if docs_dir.exists() else []
    existing = read_json(index_path, {}) or {}
    if not force and existing.get("fingerprint") == current:
        return existing

    documents: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    for filename, _, _ in current:
        parsed = parse_document(docs_dir / filename)
        documents.append({"document": filename, "type": parsed["type"], "chunk_count": len(parsed["chunks"])})
        for item in parsed["chunks"]:
            chunks.append({"document": filename, **item})

    data = {"fingerprint": current, "documents": documents, "chunks": chunks}
    atomic_write_json(index_path, data)
    return data


def search_documents(
    case_path: str | Path,
    query: str,
    *,
    filenames: list[str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    index = build_index(case_path)
    qtokens = _tokens(query)
    if not qtokens:
        return []
    allowed = set(filenames or [])
    chunks = [c for c in index.get("chunks", []) if not allowed or c["document"] in allowed]
    if not chunks:
        return []

    docfreq: Counter[str] = Counter()
    tokenized: list[list[str]] = []
    for chunk in chunks:
        toks = _tokens(chunk.get("text", ""))
        tokenized.append(toks)
        for token in set(toks):
            docfreq[token] += 1

    total = len(chunks)
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk, toks in zip(chunks, tokenized):
        counts = Counter(toks)
        score = 0.0
        for q in qtokens:
            if counts[q]:
                idf = math.log((total + 1) / (docfreq[q] + 1)) + 1
                score += (1 + math.log(counts[q])) * idf
        phrase = _normalize(query)
        if phrase and phrase in _normalize(chunk.get("text", "")):
            score += 4.0
        if score > 0:
            text = chunk.get("text", "")
            scored.append((score, {
                "document": chunk["document"],
                "page": chunk.get("page"),
                "locator": chunk.get("locator"),
                "excerpt": text[:2400],
                "score": round(score, 4),
            }))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _, row in scored[: max(1, limit)]]


def read_document(
    case_path: str | Path,
    filename: str,
    *,
    page: int | None = None,
    max_chars: int = 7000,
) -> dict[str, Any]:
    index = build_index(case_path)
    matches = []
    for chunk in index.get("chunks", []):
        if chunk["document"] != filename:
            continue
        if page is not None and chunk.get("page") != page:
            continue
        matches.append(chunk)
    text = "\n\n".join(c.get("text", "") for c in matches)
    return {
        "document": filename,
        "page": page,
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
        "available_chunks": len(matches),
    }
