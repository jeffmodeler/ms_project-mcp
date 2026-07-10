"""Tests for the PBIP (Power BI Project) writer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_mcp import mspdi
from project_mcp.pbip_writer import PbipWriter

FIXTURE = Path(__file__).parent / "fixtures" / "sample.xml"


@pytest.fixture
def project() -> mspdi.Project:
    return mspdi.parse_file(FIXTURE)


@pytest.fixture
def written(project: mspdi.Project, tmp_path: Path) -> tuple[dict, Path]:
    writer = PbipWriter(project, tmp_path, project_name="TestDash")
    result = writer.write()
    return result, tmp_path


def test_write_returns_expected_metadata(
    written: tuple[dict, Path], project: mspdi.Project
) -> None:
    result, _ = written
    assert result["tables_written"] == 3
    assert result["measures_written"] == 10
    assert result["relationships_written"] == 2
    assert result["leaf_tasks_in_data"] == sum(1 for t in project.tasks if not t.is_summary)
    assert result["resources_in_data"] == len(project.resources)
    assert result["assignments_in_data"] == len(project.assignments)


def test_write_creates_pbip_root_file(written: tuple[dict, Path]) -> None:
    _, out_dir = written
    pbip_file = out_dir / "TestDash.pbip"
    assert pbip_file.exists()
    data = json.loads(pbip_file.read_text(encoding="utf-8"))
    assert data["artifacts"][0]["report"]["path"] == "TestDash.Report"


def test_write_creates_gitignore(written: tuple[dict, Path]) -> None:
    _, out_dir = written
    gitignore = out_dir / ".gitignore"
    assert gitignore.exists()
    assert ".pbi/cache.abf" in gitignore.read_text(encoding="utf-8")


def test_write_creates_semantic_model_structure(written: tuple[dict, Path]) -> None:
    _, out_dir = written
    sm_dir = out_dir / "TestDash.SemanticModel"
    assert (sm_dir / "definition" / "database.tmdl").exists()
    assert (sm_dir / "definition" / "model.tmdl").exists()
    assert (sm_dir / "definition" / "relationships.tmdl").exists()
    tables_dir = sm_dir / "definition" / "tables"
    written_tables = {p.stem for p in tables_dir.glob("*.tmdl")}
    assert written_tables == {"Tarefas", "Recursos", "Atribuicoes"}


def test_write_creates_report_structure(written: tuple[dict, Path]) -> None:
    _, out_dir = written
    report_dir = out_dir / "TestDash.Report"
    assert report_dir.exists()
    assert (report_dir / "definition" / "pages").exists()


def test_tarefas_tmdl_contains_task_names(
    written: tuple[dict, Path], project: mspdi.Project
) -> None:
    _, out_dir = written
    tables_dir = out_dir / "TestDash.SemanticModel" / "definition" / "tables"
    tarefas_tmdl = (tables_dir / "Tarefas.tmdl").read_text(encoding="utf-8")
    leaf_task = next(t for t in project.tasks if not t.is_summary)
    assert leaf_task.name in tarefas_tmdl


def test_write_is_idempotent_directory_creation(project: mspdi.Project, tmp_path: Path) -> None:
    """Calling write() twice into the same output_dir should not raise."""
    PbipWriter(project, tmp_path, project_name="TestDash").write()
    result = PbipWriter(project, tmp_path, project_name="TestDash").write()
    assert result["tables_written"] == 3
