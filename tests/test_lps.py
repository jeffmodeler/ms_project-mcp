"""Tests for the LPS (Last Planner System) module."""
from __future__ import annotations

from pathlib import Path

import pytest

from lean_planning_mcp import lps, mspdi, sidecar

FIXTURE = Path(__file__).parent / "fixtures" / "sample.xml"


@pytest.fixture
def project(tmp_path: Path) -> mspdi.Project:
    data = FIXTURE.read_bytes()
    staged = tmp_path / "sample.xml"
    staged.write_bytes(data)
    return mspdi.parse_file(staged)


# ---------------------------------------------------------------- sidecar


def test_lps_sidecar_empty(project: mspdi.Project) -> None:
    payload = sidecar.load_lps(project.source_path)
    assert payload["phases"] == []
    assert payload["constraints"] == []
    assert payload["weekly_work_plans"] == []


def test_lps_and_awp_share_same_sidecar_dir(project: mspdi.Project) -> None:
    # Both sidecar files should be in the same directory
    awp_dir = sidecar.awp_file(project.source_path).parent
    lps_dir = sidecar.lps_file(project.source_path).parent
    assert awp_dir == lps_dir


# ---------------------------------------------------------------- Phases


def test_upsert_phase_create_then_update(project: mspdi.Project) -> None:
    created = lps.upsert_phase(project, "PH-01", "Fundações", "2026-01-05", "2026-03-30")
    assert created["action"] == "created"
    updated = lps.upsert_phase(project, "PH-01", "Fundações e Contenções")
    assert updated["action"] == "updated"
    assert updated["phase"]["name"] == "Fundações e Contenções"
    assert lps.list_phases(project)["count"] == 1


def test_set_pull_plan_validates_task_uids(project: mspdi.Project) -> None:
    lps.upsert_phase(project, "PH-01", "Fase Teste")
    result = lps.set_pull_plan(project, "PH-01", task_uids=[1, 2, 99999])
    assert result["sequence_count"] == 2
    assert 99999 in result["unknown_task_uids"]


def test_get_pull_plan_returns_sequence(project: mspdi.Project) -> None:
    lps.upsert_phase(project, "PH-01", "Fase")
    lps.set_pull_plan(project, "PH-01", task_uids=[1, 2, 3])
    retrieved = lps.get_pull_plan(project, "PH-01")
    assert len(retrieved["pull_plan"]) == 3
    assert retrieved["pull_plan"][0]["task_uid"] == 1


def test_set_pull_plan_unknown_phase(project: mspdi.Project) -> None:
    result = lps.set_pull_plan(project, "PH-GHOST", task_uids=[1])
    assert "error" in result


# ---------------------------------------------------------------- Constraints


def test_register_constraint_happy_path(project: mspdi.Project) -> None:
    result = lps.register_constraint(
        project, task_uid=1, constraint_type="material",
        description="Aço CA-50 não chegou", owner="compras@obra.com",
        due_date="2026-02-10",
    )
    assert result["registered"] is True
    c = result["constraint"]
    assert c["status"] == "open"
    assert c["task_uid"] == 1
    assert c["id"].startswith("CST-")


def test_register_constraint_rejects_invalid_type(project: mspdi.Project) -> None:
    result = lps.register_constraint(project, 1, "xpto-type", "descr")
    assert "error" in result


def test_register_constraint_rejects_missing_task(project: mspdi.Project) -> None:
    result = lps.register_constraint(project, 99999, "material", "descr")
    assert "error" in result


def test_clear_constraint_flow(project: mspdi.Project) -> None:
    reg = lps.register_constraint(project, 1, "material", "aço")
    cid = reg["constraint"]["id"]
    cleared = lps.clear_constraint(project, cid)
    assert cleared["cleared"] is True
    assert cleared["constraint"]["status"] == "cleared"
    assert cleared["constraint"]["resolved_date"] is not None
    # Idempotent
    again = lps.clear_constraint(project, cid)
    assert "already_cleared" in again


def test_list_constraints_filters(project: mspdi.Project) -> None:
    lps.register_constraint(project, 1, "material", "aço")
    lps.register_constraint(project, 1, "document", "AR-01")
    lps.register_constraint(project, 2, "labor", "falta pedreiro")
    assert lps.list_constraints(project)["count"] == 3
    assert lps.list_constraints(project, task_uid=1)["count"] == 2
    assert lps.list_constraints(project, constraint_type="material")["count"] == 1
    assert lps.list_constraints(project, status="open")["count"] == 3
    assert lps.list_constraints(project, status="cleared")["count"] == 0


# ---------------------------------------------------------------- Lookahead


def test_lookahead_returns_upcoming_tasks(project: mspdi.Project) -> None:
    # Fixture tasks start 2026-01-05. Pin from_date so test is deterministic.
    result = lps.lookahead(project, weeks=4, from_date="2026-01-01")
    assert result["task_count"] >= 1
    assert result["origin"] == "2026-01-01"


def test_lookahead_marks_task_blocked_by_constraint(project: mspdi.Project) -> None:
    lps.register_constraint(project, task_uid=1, constraint_type="material", description="aço")
    result = lps.lookahead(project, weeks=8, from_date="2026-01-01")
    task = next((t for t in result["tasks"] if t["task_uid"] == 1), None)
    assert task is not None
    assert task["ready"] is False
    assert task["constraint_count"] == 1


def test_lookahead_beyond_schedule(project: mspdi.Project) -> None:
    # Move origin past the fixture horizon
    result = lps.lookahead(project, weeks=1, from_date="2030-01-01")
    assert result["task_count"] == 0


# ---------------------------------------------------------------- WWP + PPC


def test_add_commitment_creates_wwp(project: mspdi.Project) -> None:
    result = lps.add_commitment(project, "2026-W02", task_uid=1,
                                 committed_by="time-arq", promised_hours=40.0)
    assert result["action"] == "added"
    wwp = lps.get_wwp(project, "2026-W02")
    assert wwp["commitment_count"] == 1


def test_add_commitment_updates_existing(project: mspdi.Project) -> None:
    lps.add_commitment(project, "2026-W02", 1, committed_by="A", promised_hours=20)
    updated = lps.add_commitment(project, "2026-W02", 1, committed_by="B", promised_hours=30)
    assert updated["action"] == "updated"
    assert updated["commitment"]["committed_by"] == "B"


def test_mark_complete_requires_variance_reason_when_incomplete(project: mspdi.Project) -> None:
    lps.add_commitment(project, "2026-W02", 1)
    result = lps.mark_complete(project, "2026-W02", 1, complete=False)
    assert "error" in result


def test_mark_complete_rejects_invalid_variance(project: mspdi.Project) -> None:
    lps.add_commitment(project, "2026-W02", 1)
    result = lps.mark_complete(project, "2026-W02", 1, complete=False, variance_reason="bad-reason")
    assert "error" in result


def test_mark_complete_flow(project: mspdi.Project) -> None:
    lps.add_commitment(project, "2026-W02", 1)
    result = lps.mark_complete(project, "2026-W02", 1, complete=True, actual_hours=42.0)
    assert result["updated"] is True
    assert result["commitment"]["complete"] is True
    assert result["commitment"]["actual_hours"] == 42.0


def test_ppc_single_week(project: mspdi.Project) -> None:
    for uid in (1, 2, 3):
        lps.add_commitment(project, "2026-W02", uid)
    lps.mark_complete(project, "2026-W02", 1, complete=True)
    lps.mark_complete(project, "2026-W02", 2, complete=True)
    lps.mark_complete(project, "2026-W02", 3, complete=False, variance_reason="weather")
    result = lps.calculate_ppc(project, week="2026-W02")
    assert result["committed"] == 3
    assert result["complete"] == 2
    assert result["ppc"] == pytest.approx(66.7, abs=0.1)
    assert result["variance_reasons"].get("weather") == 1


def test_ppc_series(project: mspdi.Project) -> None:
    # Week 1 — 100% (1/1)
    lps.add_commitment(project, "2026-W02", 1)
    lps.mark_complete(project, "2026-W02", 1, complete=True)
    # Week 2 — 0% (0/1)
    lps.add_commitment(project, "2026-W03", 2)
    lps.mark_complete(project, "2026-W03", 2, complete=False, variance_reason="material_delay")
    series = lps.calculate_ppc(project, weeks_back=4)
    assert series["weeks_included"] == 2
    assert series["average_ppc"] == 50.0
    assert series["series"][0]["ppc"] == 100.0
    assert series["series"][1]["ppc"] == 0.0


def test_ppc_empty_state(project: mspdi.Project) -> None:
    result = lps.calculate_ppc(project)
    assert result["series"] == []


# ------------------------------------------------- Shielding production gate


def test_add_commitment_blocks_constrained_task(project: mspdi.Project) -> None:
    lps.register_constraint(project, task_uid=1, constraint_type="material", description="aço")
    result = lps.add_commitment(project, "2026-W02", task_uid=1)
    assert "error" in result
    assert len(result["open_constraints"]) == 1


def test_add_commitment_override_records_risk(project: mspdi.Project) -> None:
    lps.register_constraint(project, task_uid=1, constraint_type="material", description="aço")
    result = lps.add_commitment(project, "2026-W02", task_uid=1, allow_constrained=True)
    assert result["action"] == "added"
    assert result["commitment"]["constrained_override"] is True
    assert "warning" in result


def test_add_commitment_allowed_after_clearing(project: mspdi.Project) -> None:
    reg = lps.register_constraint(
        project, task_uid=1, constraint_type="material", description="aço"
    )
    lps.clear_constraint(project, reg["constraint"]["id"])
    result = lps.add_commitment(project, "2026-W02", task_uid=1)
    assert result["action"] == "added"
    assert result["commitment"]["constrained_override"] is False


def test_add_commitment_rejects_bad_week_format(project: mspdi.Project) -> None:
    result = lps.add_commitment(project, "semana 2", task_uid=1)
    assert "error" in result


# ------------------------------------------------- Late-constraint alert


def test_lookahead_flags_constraint_due_after_task_start(project: mspdi.Project) -> None:
    # Fixture task 1 starts 2026-01-05; constraint promised only for Feb
    reg = lps.register_constraint(
        project, task_uid=1, constraint_type="material",
        description="aço", due_date="2026-02-10",
    )
    result = lps.lookahead(project, weeks=8, from_date="2026-01-01")
    task = next(t for t in result["tasks"] if t["task_uid"] == 1)
    assert reg["constraint"]["id"] in task["late_constraint_ids"]
    assert result["late_constraint_task_count"] >= 1


def test_lookahead_no_late_flag_when_due_before_start(project: mspdi.Project) -> None:
    lps.register_constraint(
        project, task_uid=1, constraint_type="material",
        description="aço", due_date="2026-01-02",
    )
    result = lps.lookahead(project, weeks=8, from_date="2026-01-01")
    task = next(t for t in result["tasks"] if t["task_uid"] == 1)
    assert task["late_constraint_ids"] == []


# ------------------------------------------------- Snapshots + TA/TMR


def test_snapshot_lookahead_persists(project: mspdi.Project) -> None:
    result = lps.snapshot_lookahead(project, weeks=8, from_date="2026-01-01")
    assert result["anticipated_count"] >= 1
    payload = sidecar.load_lps(project.source_path)
    assert len(payload["lookahead_snapshots"]) == 1


def test_reliability_requires_snapshots(project: mspdi.Project) -> None:
    result = lps.reliability(project)
    assert result["series"] == []
    assert "note" in result


def test_reliability_computes_ta_tmr(project: mspdi.Project) -> None:
    # Snapshot taken 2026-01-01 anticipates fixture tasks starting 2026-01-05 (W02)
    lps.snapshot_lookahead(project, weeks=8, from_date="2026-01-01")
    lps.add_commitment(project, "2026-W02", task_uid=1)
    result = lps.reliability(project, weeks_back=4)
    assert result["weeks_included"] == 1
    week = result["series"][0]
    assert week["week"] == "2026-W02"
    assert week["ta_percent"] == 100.0  # committed task was anticipated
    assert week["tmr_percent"] is not None


# ------------------------------------------------- Workable backlog


def test_workable_backlog_excludes_committed(project: mspdi.Project) -> None:
    lps.add_commitment(project, "2026-W02", task_uid=1)
    result = lps.workable_backlog(project, week="2026-W02", weeks=8)
    uids = [t["task_uid"] for t in result["backlog"]]
    assert 1 not in uids
    assert result["committed_count"] == 1


# ------------------------------------------------- Daily huddle


def test_log_daily_and_get(project: mspdi.Project) -> None:
    lps.add_commitment(project, "2026-W02", task_uid=1)
    logged = lps.log_daily(
        project, "2026-W02", task_uid=1,
        note="Formas 60% concluídas", day="2026-01-06", blocked=False,
    )
    assert logged["logged"] is True
    log = lps.get_daily_log(project, "2026-W02")
    assert log["entry_count"] == 1
    assert log["blocked_count"] == 0
    filtered = lps.get_daily_log(project, "2026-W02", day="2026-01-07")
    assert filtered["entry_count"] == 0


def test_log_daily_requires_commitment(project: mspdi.Project) -> None:
    lps.add_commitment(project, "2026-W02", task_uid=1)
    result = lps.log_daily(project, "2026-W02", task_uid=2, note="x")
    assert "error" in result


# ------------------------------------------------- Pull-plan annotations


def test_annotate_pull_plan_handoff(project: mspdi.Project) -> None:
    lps.upsert_phase(project, "PH-01", "Fase")
    lps.set_pull_plan(project, "PH-01", task_uids=[1, 2])
    result = lps.annotate_pull_plan(
        project, "PH-01", task_uid=1,
        handoff_to="equipe-alvenaria",
        conditions_of_satisfaction="Fundação curada e liberada pela fiscalização",
    )
    assert result["annotated"] is True
    plan = lps.get_pull_plan(project, "PH-01")
    entry = next(e for e in plan["pull_plan"] if e["task_uid"] == 1)
    assert entry["handoff_to"] == "equipe-alvenaria"


def test_annotate_pull_plan_unknown_entry(project: mspdi.Project) -> None:
    lps.upsert_phase(project, "PH-01", "Fase")
    lps.set_pull_plan(project, "PH-01", task_uids=[1])
    result = lps.annotate_pull_plan(project, "PH-01", task_uid=3, handoff_to="x")
    assert "error" in result
