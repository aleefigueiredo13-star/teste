from __future__ import annotations

from pathlib import Path

import tools.documents as documents


def test_txt_index_and_search(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "documents").mkdir(parents=True)
    (case / "research").mkdir()
    (case / "documents" / "sentenca.txt").write_text(
        "A sentença reconheceu horas extras.\nO pedido de dano moral foi indeferido.",
        encoding="utf-8",
    )
    results = documents.search_documents(case, "horas extras")
    assert results
    assert results[0]["document"] == "sentenca.txt"
    assert "horas extras" in results[0]["excerpt"].lower()


def test_pdf_parser_preserves_page_number(monkeypatch, tmp_path: Path) -> None:
    class Page:
        def __init__(self, text: str):
            self.text = text

        def extract_text(self):
            return self.text

    class Reader:
        def __init__(self, _path: str):
            self.pages = [Page("primeira página"), Page("segunda página com FGTS")]

    monkeypatch.setattr(documents, "PdfReader", Reader)
    pdf = tmp_path / "sentenca.pdf"
    pdf.write_bytes(b"%PDF-test")
    parsed = documents.parse_document(pdf)
    assert parsed["chunks"][0]["page"] == 1
    assert parsed["chunks"][1]["page"] == 2
    assert parsed["chunks"][1]["document"] if "document" in parsed["chunks"][1] else True
