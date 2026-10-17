from __future__ import annotations

from tools.filesystem import create_case, create_task, load_task


def test_task_creation_and_workspace_isolation(project_fixture) -> None:
    case_a = create_case("0001-TESTE", "Reclamada", root=project_fixture)
    case_b = create_case("0002-TESTE", "Reclamante", root=project_fixture)
    task_a, path_a = create_task(case_a, "Analisar sentença", "Reclamada", [])
    task_b, path_b = create_task(case_b, "Revisar recurso", "Reclamante", [])
    assert task_a == "task-001"
    assert task_b == "task-001"
    assert path_a != path_b
    assert load_task(path_a)["task"] == "Analisar sentença"
    assert load_task(path_b)["task"] == "Revisar recurso"
