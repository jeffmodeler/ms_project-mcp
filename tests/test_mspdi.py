"""Tests for the MSPDI parser."""
from pathlib import Path

import pytest

from lean_planning_mcp import mspdi

FIXTURE = Path(__file__).parent / "fixtures" / "sample.xml"


@pytest.fixture
def project() -> mspdi.Project:
    return mspdi.parse_file(FIXTURE)


def test_project_metadata(project: mspdi.Project) -> None:
    assert project.title == "Sample Construction Project"
    assert project.author == "Test Author"
    assert project.company == "Test Co"
    assert project.currency_code == "BRL"
    assert project.start_date == "2026-01-05T08:00:00"


def test_task_count(project: mspdi.Project) -> None:
    assert len(project.tasks) == 5  # 1 summary + 3 work + 1 milestone


def test_summary_and_milestone_flags(project: mspdi.Project) -> None:
    summary = project.task_by_uid(0)
    assert summary is not None
    assert summary.is_summary
    milestone = project.task_by_uid(4)
    assert milestone is not None
    assert milestone.is_milestone


def test_critical_path(project: mspdi.Project) -> None:
    critical = [t for t in project.tasks if t.is_critical and not t.is_summary]
    assert {t.name for t in critical} == {"Foundation", "Structure", "Project Handover"}


def test_predecessors(project: mspdi.Project) -> None:
    structure = project.task_by_name("Structure")
    assert structure is not None
    assert len(structure.predecessors) == 1
    assert structure.predecessors[0]["link_type"] == "FS"
    assert structure.predecessors[0]["predecessor_uid"] == 1


def test_resource_overallocation(project: mspdi.Project) -> None:
    overallocated = [r for r in project.resources if r.overallocated]
    assert len(overallocated) == 1
    assert overallocated[0].name == "Finishing Crew"


def test_resource_types(project: mspdi.Project) -> None:
    types = {r.name: r.type for r in project.resources}
    assert types["Civil Crew"] == "Work"
    assert types["Concrete"] == "Material"


def test_assignments_total_cost(project: mspdi.Project) -> None:
    total_cost = sum(a.cost for a in project.assignments)
    assert total_cost == 31700.0


def test_baseline_variance_structure(project: mspdi.Project) -> None:
    structure = project.task_by_name("Structure")
    assert structure is not None
    variance_hours = structure.duration_hours - structure.baseline_duration_hours
    assert variance_hours == 40.0


def test_iso_duration_parser() -> None:
    assert mspdi.iso_duration_to_hours("PT8H0M0S") == 8.0
    assert mspdi.iso_duration_to_hours("PT0H30M0S") == 0.5
    assert mspdi.iso_duration_to_hours("P1DT4H") == 28.0
    assert mspdi.iso_duration_to_hours(None) == 0.0
    assert mspdi.iso_duration_to_hours("garbage") == 0.0
