from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def project_fixture(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1]
    for rel in ("agents",):
        shutil.copytree(source / rel, tmp_path / rel)
    shutil.copy2(source / "pricing.json", tmp_path / "pricing.json")
    for rel in ("workspace/processos", "workspace/tarefas", "workspace/outputs", "logs"):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    return tmp_path
