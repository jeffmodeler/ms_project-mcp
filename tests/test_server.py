"""Tests for the MCP tool functions exposed in server.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lean_planning_mcp import mspdi, server

FIXTURE = Path(__file__).parent / "fixtures" / "sample.xml"


@pytest.fixture(autouse=True)
def reset_state() -> None:
    """server._state is module-level global — isolate it between tests."""
    server._state["project"] = None
    yield
    server._state["project"] = None


@pytest.fixture
def staged_xml(tmp_path: Path) -> Path:
    staged = tmp_path / "sample.xml"
    staged.write_bytes(FIXTURE.read_bytes())
    return staged


@pytest.fixture
def loaded(staged_xml: Path) -> Path:
    """Load the fixture project into module state and return its path."""
    server.load_project(str(staged_xml))
    return staged_xml


def _parse(result: str) -> dict:
    return json.loads(result)


# ---------------------------------------------------------------- state


def test_project_raises_when_nothing_loaded() -> None:
    with pytest.raises(RuntimeError, match="No project loaded"):
        server._project()


# ---------------------------------------------------------------- load_project


def test_load_project_success(staged_xml: Path) -> None:
    result = _parse(server.load_project(str(staged_xml)))
    assert result["loaded"] is True
    assert result["title"] == "Sample Construction Project"
    assert result["tasks_count"] == 5
    assert result["resources_count"] == 3


def test_load_project_file_not_found(tmp_path: Path) -> None:
    result = _parse(server.load_project(str(tmp_path / "missing.xml")))
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_load_project_unsupported_extension(tmp_path: Path) -> None:
    bogus = tmp_path / "schedule.txt"
    bogus.write_text("not a project file")
    result = _parse(server.load_project(str(bogus)))
    assert "error" in result
    assert "Unsupported file extension" in result["error"]


@pytest.mark.parametrize("suffix", [".xer", ".sp", ".pp", ".pmxml", ".mpx"])
def test_load_project_routes_universal_formats(tmp_path: Path, suffix: str) -> None:
    """P6/Synchro/Asta extensions must reach the universal loader, not be
    rejected as unsupported. Without the `mpp` extra installed the loader
    returns the install hint; with it, mpxj fails on the bogus content."""
    bogus = tmp_path / f"schedule{suffix}"
    bogus.write_text("bogus content")
    result = _parse(server.load_project(str(bogus)))
    assert "error" in result
    assert "Unsupported file extension" not in result["error"]
    assert "'mpp' extra" in result["error"] or "could not read" in result["error"]


def test_load_project_non_mspdi_xml_falls_back(tmp_path: Path) -> None:
    """A .xml that is not MSPDI (e.g. P6 PMXML) must not silently load as an
    empty project — it retries via the universal reader and surfaces a clear
    error when that also fails."""
    pmxml = tmp_path / "p6-export.xml"
    pmxml.write_text(
        '<?xml version="1.0"?>'
        '<APIBusinessObjects xmlns="http://xmlns.oracle.com/Primavera/P6">'
        "<Project><Id>P6-DEMO</Id></Project></APIBusinessObjects>"
    )
    result = _parse(server.load_project(str(pmxml)))
    if "error" in result:
        assert "MSPDI" in result["error"]
    else:
        # mpp extra + Java present: mpxj actually parsed it
        assert result["loaded"] is True


# ---------------------------------------------------------------- project_info


def test_project_info(loaded: Path) -> None:
    result = _parse(server.project_info())
    assert result["title"] == "Sample Construction Project"
    assert result["counts"]["tasks_total"] == 5
    assert result["counts"]["resources"] == 3
    assert "totals" in result


# ---------------------------------------------------------------- list_tasks


def test_list_tasks_returns_all_by_default(loaded: Path) -> None:
    result = _parse(server.list_tasks())
    assert result["count"] == 5


def test_list_tasks_name_contains_filter(loaded: Path) -> None:
    result = _parse(server.list_tasks(name_contains="found"))
    assert result["count"] == 1
    assert result["tasks"][0]["name"] == "Foundation"


def test_list_tasks_top_n(loaded: Path) -> None:
    result = _parse(server.list_tasks(top_n=2))
    assert result["count"] == 2


def test_list_tasks_only_critical(loaded: Path) -> None:
    all_tasks = _parse(server.list_tasks())
    critical = _parse(server.list_tasks(only_critical=True))
    assert critical["count"] <= all_tasks["count"]
    assert all(t["is_critical"] for t in critical["tasks"])


# ---------------------------------------------------------------- get_task


def test_get_task_by_name(loaded: Path) -> None:
    result = _parse(server.get_task(name="Foundation"))
    assert result["name"] == "Foundation"
    assert "assignments" in result


def test_get_task_by_uid_matches_by_name(loaded: Path) -> None:
    by_name = _parse(server.get_task(name="Foundation"))
    by_uid = _parse(server.get_task(uid=by_name["uid"]))
    assert by_uid["name"] == "Foundation"


def test_get_task_not_found(loaded: Path) -> None:
    result = _parse(server.get_task(name="Nonexistent Task"))
    assert "error" in result


def test_get_task_no_args(loaded: Path) -> None:
    result = _parse(server.get_task())
    assert "error" in result
    assert "Provide one of" in result["error"]


# ---------------------------------------------------------------- list_resources


def test_list_resources_returns_all(loaded: Path) -> None:
    result = _parse(server.list_resources())
    assert result["count"] == 3


def test_list_resources_type_filter(loaded: Path) -> None:
    result = _parse(server.list_resources(type_filter="Material"))
    assert all(r["type"] == "Material" for r in result["resources"])


# ---------------------------------------------------------------- get_resource_assignments


def test_get_resource_assignments_all(loaded: Path) -> None:
    result = _parse(server.get_resource_assignments())
    assert result["count"] == 3


def test_get_resource_assignments_by_name(loaded: Path) -> None:
    result = _parse(server.get_resource_assignments(resource_name="Civil Crew"))
    assert all(a["resource_name"] == "Civil Crew" for a in result["assignments"])


def test_get_resource_assignments_name_not_found(loaded: Path) -> None:
    result = _parse(server.get_resource_assignments(resource_name="Ghost Crew"))
    assert "error" in result


# ---------------------------------------------------------------- find_overallocated_resources


def test_find_overallocated_resources(loaded: Path) -> None:
    result = _parse(server.find_overallocated_resources())
    assert "overallocated" in result
    assert all(r["overallocated"] for r in result["overallocated"])


# ---------------------------------------------------------------- get_critical_path


def test_get_critical_path(loaded: Path) -> None:
    result = _parse(server.get_critical_path())
    assert all(t["is_critical"] for t in result["tasks"])
    assert all(not t["is_summary"] for t in result["tasks"])


# ---------------------------------------------------------------- get_predecessors_successors


def test_get_predecessors_successors_found(loaded: Path) -> None:
    structure = _parse(server.get_task(name="Structure"))
    result = _parse(server.get_predecessors_successors(structure["uid"]))
    assert result["task"]["name"] == "Structure"
    assert "predecessors" in result
    assert "successors" in result


def test_get_predecessors_successors_not_found(loaded: Path) -> None:
    result = _parse(server.get_predecessors_successors(99999))
    assert "error" in result


# ---------------------------------------------------------------- get_baseline_variance


def test_get_baseline_variance(loaded: Path) -> None:
    result = _parse(server.get_baseline_variance())
    assert "tasks" in result
    for row in result["tasks"]:
        assert "duration_variance_hours" in row


# ---------------------------------------------------------------- get_gantt_data


def test_get_gantt_data(loaded: Path) -> None:
    result = _parse(server.get_gantt_data())
    assert result["count"] == 5
    assert all("dependencies" in g for g in result["gantt"])


def test_get_gantt_data_exclude_summaries(loaded: Path) -> None:
    result = _parse(server.get_gantt_data(exclude_summaries=True))
    assert all(not g["is_summary"] for g in result["gantt"])


# ---------------------------------------------------------------- export_to_json


def test_export_to_json_inline(loaded: Path) -> None:
    result = _parse(server.export_to_json())
    assert "tasks" in result
    assert "resources" in result
    assert "assignments" in result


def test_export_to_json_to_file(loaded: Path, tmp_path: Path) -> None:
    out_file = tmp_path / "export" / "out.json"
    result = _parse(server.export_to_json(str(out_file)))
    assert result["exported"] is True
    assert out_file.exists()
    on_disk = json.loads(out_file.read_text(encoding="utf-8"))
    assert "tasks" in on_disk


# ---------------------------------------------------------------- open_in_ms_project


def test_open_in_ms_project_no_project_no_path() -> None:
    result = _parse(server.open_in_ms_project())
    assert "error" in result


def test_open_in_ms_project_file_not_found(tmp_path: Path) -> None:
    result = _parse(server.open_in_ms_project(str(tmp_path / "missing.xml")))
    assert "error" in result


def test_open_in_ms_project_launches_subprocess(
    loaded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    class _FakePopen:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(server.subprocess, "Popen", _FakePopen)
    result = _parse(server.open_in_ms_project())
    assert result["opened"] is True
    assert len(calls) == 1


# ---------------------------------------------------------------- generate_pbip_dashboard


def test_generate_pbip_dashboard_uses_loaded_project(
    loaded: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.os, "startfile", lambda path: None, raising=False)
    out_dir = tmp_path / "dash"
    result = _parse(server.generate_pbip_dashboard(str(out_dir), project_name="Dash"))
    assert result["tables_written"] == 3
    assert (out_dir / "Dash.pbip").exists()


def test_generate_pbip_dashboard_no_project_no_xml_path() -> None:
    with pytest.raises(RuntimeError, match="No project loaded"):
        server.generate_pbip_dashboard("/tmp/wont-be-used")


def test_generate_pbip_dashboard_with_xml_path(
    staged_xml: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.os, "startfile", lambda path: None, raising=False)
    out_dir = tmp_path / "dash2"
    result = _parse(
        server.generate_pbip_dashboard(str(out_dir), project_name="Dash2", xml_path=str(staged_xml))
    )
    assert result["tables_written"] == 3
    assert isinstance(server._state["project"], mspdi.Project)


def test_generate_pbip_dashboard_open_in_power_bi_false(loaded: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "dash3"
    result = _parse(server.generate_pbip_dashboard(str(out_dir), open_in_power_bi=False))
    assert result["opened_in_power_bi"] is False


# ---------------------------------------------------------------- AWP tool wrappers
# Business rules already covered at the awp.py unit-test level — these just
# verify the thin @mcp.tool wrappers in server.py wire arguments and JSON
# serialization correctly end-to-end through a full CWA -> CWP -> IWP flow.


def test_awp_tool_wrappers_full_flow(loaded: Path) -> None:
    foundation = _parse(server.get_task(name="Foundation"))

    cwa = _parse(server.awp_upsert_cwa("CWA-01", "Fundacoes"))
    assert cwa["action"] == "created"
    assert cwa["cwa"]["id"] == "CWA-01"

    assert _parse(server.awp_list_cwa())["count"] == 1

    cwp = _parse(server.awp_upsert_cwp("CWP-01.01", "Sapatas", "CWA-01"))
    assert "error" not in cwp

    assert "error" not in _parse(server.awp_list_cwp())
    assert "error" not in _parse(server.awp_list_cwp(cwa_id="CWA-01"))

    assign = _parse(server.awp_assign_task_to_cwp(foundation["uid"], "CWP-01.01"))
    assert "error" not in assign

    reqs = _parse(server.awp_set_cwp_requirements(
        "CWP-01.01", materials=["aco"], documents=["projeto"], access=["licenca"]
    ))
    assert "error" not in reqs

    readiness = _parse(server.awp_readiness_check("CWP-01.01"))
    assert "ready" in readiness

    assert "error" not in _parse(server.awp_path_of_construction())

    iwps = _parse(server.awp_generate_iwps("CWP-01.01", max_hours_per_iwp=40.0))
    assert "error" not in iwps

    wpr = _parse(server.awp_export_wpr("CWP-01.01"))
    assert "error" not in wpr


# ---------------------------------------------------------------- LPS tool wrappers
# Same rationale as the AWP block above: exercise the server.py wrappers
# through a full phase -> pull-plan -> constraint -> WWP -> PPC flow.


def test_lps_tool_wrappers_full_flow(loaded: Path) -> None:
    foundation = _parse(server.get_task(name="Foundation"))

    phase = _parse(server.lps_upsert_phase("PH-01", "Fundacoes"))
    assert "error" not in phase

    assert "error" not in _parse(server.lps_list_phases())

    pull_plan = _parse(server.lps_set_pull_plan("PH-01", [foundation["uid"]]))
    assert "error" not in pull_plan

    assert "error" not in _parse(server.lps_get_pull_plan("PH-01"))

    constraint = _parse(server.lps_register_constraint(
        foundation["uid"], "material", "aco CA-50 atrasado", owner="suprimentos"
    ))
    assert constraint["registered"] is True
    constraint_id = constraint["constraint"]["id"]

    assert "error" not in _parse(server.lps_list_constraints())
    assert "error" not in _parse(server.lps_list_constraints(task_uid=foundation["uid"]))

    cleared = _parse(server.lps_clear_constraint(constraint_id))
    assert "error" not in cleared

    assert "error" not in _parse(server.lps_lookahead(weeks=8))

    week = "2025-W03"
    commitment = _parse(server.lps_add_commitment(
        week, foundation["uid"], committed_by="Civil Crew", promised_hours=40.0
    ))
    assert "error" not in commitment

    complete = _parse(
        server.lps_mark_complete(week, foundation["uid"], complete=True, actual_hours=38.0)
    )
    assert "error" not in complete

    assert "error" not in _parse(server.lps_get_wwp(week))
    assert "error" not in _parse(server.lps_ppc(week=week))
    assert "error" not in _parse(server.lps_ppc())
