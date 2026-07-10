"""Last Planner System (LPS) — Lean Construction methodology.

Five planning levels — all implemented:

    Master → Phase (pull plan) → Lookahead (N weeks, clears constraints)
          → WWP (Weekly Work Plan, commitments) → Daily huddle (log_daily)

Metrics: PPC (Percent Plan Complete), TA (Tasks Anticipated) and TMR (Tasks
Made Ready) — the latter two computed from lookahead snapshots, measuring the
health of the make-ready process, not just last week's reliability.

Core rule enforced: only constraint-free (sound) tasks enter the WWP —
`add_commitment` blocks tasks with open constraints unless explicitly
overridden (shielding production, Ballard 1998).

State persisted in the LPS sidecar (see `sidecar.py`). The `.mpp` schedule
remains authoritative for tasks; LPS layer adds phases, constraints, weekly
commitments, and completion tracking.

All public functions return plain `dict`s for MCP tool serialization.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from lean_planning_mcp import mspdi, sidecar

logger = logging.getLogger(__name__)

VALID_CONSTRAINT_TYPES = {
    "material", "document", "information", "design",
    "labor", "equipment", "access", "permit",
    "prerequisite", "other",
}

VALID_CONSTRAINT_STATUS = {"open", "cleared"}

VALID_VARIANCE_REASONS = {
    "weather", "design_change", "material_delay", "labor_unavailable",
    "equipment_breakdown", "rework", "permit", "prerequisite_incomplete",
    "scope_change", "other",
}


def _find_phase(payload: dict[str, Any], phase_id: str) -> dict[str, Any] | None:
    return next((p for p in payload["phases"] if p["id"] == phase_id), None)


def _find_constraint(payload: dict[str, Any], constraint_id: str) -> dict[str, Any] | None:
    return next((c for c in payload["constraints"] if c["id"] == constraint_id), None)


def _find_wwp(payload: dict[str, Any], week: str) -> dict[str, Any] | None:
    return next((w for w in payload["weekly_work_plans"] if w["week"] == week), None)


def _today_iso() -> str:
    return date.today().isoformat()


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _iso_week(d: date) -> str:
    """Return ISO week string like '2025-W03' for a date."""
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _week_start(week: str) -> date | None:
    """Return the Monday of an ISO week string like '2025-W03'."""
    try:
        year_s, week_s = week.split("-W")
        return date.fromisocalendar(int(year_s), int(week_s), 1)
    except (ValueError, TypeError):
        return None


def _open_constraints_for_task(payload: dict[str, Any], task_uid: int) -> list[dict[str, Any]]:
    return [
        c for c in payload["constraints"]
        if int(c.get("task_uid", -1)) == task_uid and c.get("status") == "open"
    ]


# ======================================================================
# Phases & Pull Plan
# ======================================================================


def list_phases(project: mspdi.Project) -> dict[str, Any]:
    """Return all project phases defined in the sidecar."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    return {"count": len(payload["phases"]), "phases": payload["phases"]}


def upsert_phase(
    project: mspdi.Project,
    phase_id: str,
    name: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Create or update a project phase (used as container for pull plans)."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    existing = _find_phase(payload, phase_id)
    if existing is None:
        record = {
            "id": phase_id, "name": name,
            "start_date": start_date, "end_date": end_date,
            "pull_plan": [],
        }
        payload["phases"].append(record)
        action = "created"
    else:
        existing.update({"name": name, "start_date": start_date, "end_date": end_date})
        record = existing
        action = "updated"
    sidecar.save_lps(project.source_path, payload)
    return {"action": action, "phase": record}


def set_pull_plan(
    project: mspdi.Project,
    phase_id: str,
    task_uids: list[int],
) -> dict[str, Any]:
    """Set the pull-plan sequence for a phase.

    Pull planning works backwards from the phase milestone. `task_uids` should
    be in the order the team committed to — first item executes first. Each
    entry is validated against the project tasks.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    phase = _find_phase(payload, phase_id)
    if phase is None:
        return {"error": f"Phase '{phase_id}' does not exist. Create it with upsert_phase first."}
    sequence = []
    unknown: list[int] = []
    for uid in task_uids:
        task = project.task_by_uid(uid)
        if task is None:
            unknown.append(uid)
            continue
        sequence.append({
            "task_uid": uid, "name": task.name,
            "duration_hours": task.duration_hours,
            "is_milestone": task.is_milestone,
            "handoff_to": None,
            "conditions_of_satisfaction": None,
        })
    phase["pull_plan"] = sequence
    sidecar.save_lps(project.source_path, payload)
    return {
        "phase_id": phase_id, "sequence_count": len(sequence),
        "unknown_task_uids": unknown, "pull_plan": sequence,
    }


def annotate_pull_plan(
    project: mspdi.Project,
    phase_id: str,
    task_uid: int,
    handoff_to: str | None = None,
    conditions_of_satisfaction: str | None = None,
) -> dict[str, Any]:
    """Annotate a pull-plan entry with its handoff and conditions of satisfaction.

    Pull planning is a network of promises between specialists: each entry
    hands work off to a receiving team, and the handoff has explicit
    conditions of satisfaction agreed in the pull-planning session.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    phase = _find_phase(payload, phase_id)
    if phase is None:
        return {"error": f"Phase '{phase_id}' does not exist."}
    entry = next(
        (e for e in phase.get("pull_plan", []) if e.get("task_uid") == task_uid), None
    )
    if entry is None:
        return {"error": f"Task UID {task_uid} is not in the pull plan of '{phase_id}'."}
    if handoff_to is not None:
        entry["handoff_to"] = handoff_to
    if conditions_of_satisfaction is not None:
        entry["conditions_of_satisfaction"] = conditions_of_satisfaction
    sidecar.save_lps(project.source_path, payload)
    return {"annotated": True, "phase_id": phase_id, "entry": entry}


def get_pull_plan(project: mspdi.Project, phase_id: str) -> dict[str, Any]:
    """Get the pull plan for a phase."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    phase = _find_phase(payload, phase_id)
    if phase is None:
        return {"error": f"Phase '{phase_id}' does not exist."}
    return {
        "phase_id": phase_id, "name": phase.get("name"),
        "start_date": phase.get("start_date"), "end_date": phase.get("end_date"),
        "pull_plan": phase.get("pull_plan", []),
    }


# ======================================================================
# Constraints
# ======================================================================


def register_constraint(
    project: mspdi.Project,
    task_uid: int,
    constraint_type: str,
    description: str,
    owner: str | None = None,
    due_date: str | None = None,
) -> dict[str, Any]:
    """Register a constraint blocking a task.

    Types: material | document | information | design | labor | equipment |
           access | permit | prerequisite | other
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    if constraint_type not in VALID_CONSTRAINT_TYPES:
        return {
            "error": f"Invalid type '{constraint_type}'",
            "valid_types": sorted(VALID_CONSTRAINT_TYPES),
        }
    task = project.task_by_uid(task_uid)
    if task is None:
        return {"error": f"Task UID {task_uid} not found in project."}
    payload = sidecar.load_lps(project.source_path)
    constraint = {
        "id": f"CST-{uuid4().hex[:8].upper()}",
        "task_uid": task_uid,
        "task_name": task.name,
        "type": constraint_type,
        "description": description,
        "owner": owner,
        "registered_date": _today_iso(),
        "due_date": due_date,
        "resolved_date": None,
        "status": "open",
    }
    payload["constraints"].append(constraint)
    sidecar.save_lps(project.source_path, payload)
    return {"registered": True, "constraint": constraint}


def clear_constraint(project: mspdi.Project, constraint_id: str) -> dict[str, Any]:
    """Mark a constraint as cleared (resolved)."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    constraint = _find_constraint(payload, constraint_id)
    if constraint is None:
        return {"error": f"Constraint '{constraint_id}' not found."}
    if constraint["status"] == "cleared":
        return {"already_cleared": True, "constraint": constraint}
    constraint["status"] = "cleared"
    constraint["resolved_date"] = _today_iso()
    sidecar.save_lps(project.source_path, payload)
    return {"cleared": True, "constraint": constraint}


def list_constraints(
    project: mspdi.Project,
    task_uid: int | None = None,
    status: str | None = None,
    constraint_type: str | None = None,
) -> dict[str, Any]:
    """List constraints, optionally filtered by task, status, or type."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    items = payload["constraints"]
    if task_uid is not None:
        items = [c for c in items if c.get("task_uid") == task_uid]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    if constraint_type is not None:
        items = [c for c in items if c.get("type") == constraint_type]
    return {"count": len(items), "constraints": items}


# ======================================================================
# Lookahead
# ======================================================================


def lookahead(
    project: mspdi.Project,
    weeks: int = 6,
    from_date: str | None = None,
) -> dict[str, Any]:
    """Return tasks starting within the next N weeks + their open constraints.

    Tasks are gathered from the project schedule (not from WWPs), giving the
    classic LPS lookahead: "what's coming, and what's blocking it?"
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    origin = _parse_iso_date(from_date) or datetime.now(UTC).date()
    horizon = origin + timedelta(weeks=weeks)
    payload = sidecar.load_lps(project.source_path)
    open_constraints: dict[int, list[dict[str, Any]]] = {}
    for c in payload["constraints"]:
        if c.get("status") != "open":
            continue
        open_constraints.setdefault(int(c["task_uid"]), []).append(c)

    upcoming: list[dict[str, Any]] = []
    for task in project.tasks:
        if task.is_summary or task.is_null:
            continue
        start = _parse_iso_date(task.start)
        if start is None or start < origin or start > horizon:
            continue
        cs = open_constraints.get(task.uid, [])
        # Make-ready alert: constraint promised for *after* the task starts
        late = [
            c["id"] for c in cs
            if (due := _parse_iso_date(c.get("due_date"))) is not None and due > start
        ]
        upcoming.append({
            "task_uid": task.uid, "name": task.name,
            "start": task.start, "finish": task.finish,
            "duration_hours": task.duration_hours,
            "is_critical": task.is_critical,
            "constraint_count": len(cs),
            "constraints": cs,
            "ready": len(cs) == 0,
            "late_constraint_ids": late,
        })
    upcoming.sort(key=lambda t: (t["start"] or "9999", t["task_uid"]))
    ready_count = sum(1 for t in upcoming if t["ready"])
    late_count = sum(1 for t in upcoming if t["late_constraint_ids"])
    return {
        "origin": origin.isoformat(),
        "horizon": horizon.isoformat(),
        "weeks": weeks,
        "task_count": len(upcoming),
        "ready_count": ready_count,
        "blocked_count": len(upcoming) - ready_count,
        "late_constraint_task_count": late_count,
        "tasks": upcoming,
    }


def snapshot_lookahead(
    project: mspdi.Project,
    weeks: int = 6,
    from_date: str | None = None,
) -> dict[str, Any]:
    """Persist a lookahead snapshot — the basis for TA/TMR reliability metrics.

    Call this when the lookahead is reviewed (typically weekly). Each snapshot
    records which tasks were anticipated and which were already ready, so
    `reliability` can later measure how well the make-ready process performed.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    view = lookahead(project, weeks, from_date)
    if "error" in view:
        return view
    payload = sidecar.load_lps(project.source_path)
    snapshot = {
        "id": f"SNAP-{uuid4().hex[:8].upper()}",
        "taken_on": view["origin"],
        "week": _iso_week(_parse_iso_date(view["origin"]) or date.today()),
        "horizon": view["horizon"],
        "anticipated": [
            {"task_uid": t["task_uid"], "start": t["start"], "ready": t["ready"]}
            for t in view["tasks"]
        ],
    }
    payload["lookahead_snapshots"].append(snapshot)
    sidecar.save_lps(project.source_path, payload)
    return {
        "snapshot_id": snapshot["id"],
        "taken_on": snapshot["taken_on"],
        "anticipated_count": len(snapshot["anticipated"]),
        "ready_count": sum(1 for a in snapshot["anticipated"] if a["ready"]),
    }


# ======================================================================
# Weekly Work Plan + PPC
# ======================================================================


def add_commitment(
    project: mspdi.Project,
    week: str,
    task_uid: int,
    committed_by: str | None = None,
    promised_hours: float | None = None,
    allow_constrained: bool = False,
) -> dict[str, Any]:
    """Add a task commitment to a weekly work plan.

    `week` uses ISO format 'YYYY-Www' (e.g. '2025-W03'). Creates the WWP
    if it does not exist yet.

    Shielding production (Ballard 1998): only sound, constraint-free tasks
    may enter the WWP. Tasks with open constraints are rejected unless
    `allow_constrained=True` is passed as an explicit, deliberate override —
    the open constraints are then recorded on the commitment as a warning.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    if _week_start(week) is None:
        return {"error": f"Invalid week '{week}'. Use ISO format 'YYYY-Www' (e.g. '2025-W03')."}
    task = project.task_by_uid(task_uid)
    if task is None:
        return {"error": f"Task UID {task_uid} not found in project."}
    payload = sidecar.load_lps(project.source_path)
    open_cs = _open_constraints_for_task(payload, task_uid)
    if open_cs and not allow_constrained:
        return {
            "error": f"Task UID {task_uid} has {len(open_cs)} open constraint(s). "
                     "Only constraint-free tasks enter the WWP (shielding production). "
                     "Clear them with lps_clear_constraint, or pass "
                     "allow_constrained=true to override deliberately.",
            "open_constraints": open_cs,
        }
    wwp = _find_wwp(payload, week)
    if wwp is None:
        wwp = {"week": week, "commitments": []}
        payload["weekly_work_plans"].append(wwp)
    existing = next((c for c in wwp["commitments"] if c["task_uid"] == task_uid), None)
    commitment = {
        "task_uid": task_uid,
        "task_name": task.name,
        "committed_by": committed_by,
        "promised_hours": promised_hours,
        "actual_hours": None,
        "complete": False,
        "variance_reason": None,
        "corrective_action": None,
        "constrained_override": bool(open_cs),
    }
    if existing is None:
        wwp["commitments"].append(commitment)
        action = "added"
    else:
        existing.update({
            "committed_by": committed_by,
            "promised_hours": promised_hours,
            "constrained_override": bool(open_cs),
        })
        commitment = existing
        action = "updated"
    sidecar.save_lps(project.source_path, payload)
    result: dict[str, Any] = {"action": action, "week": week, "commitment": commitment}
    if open_cs:
        result["warning"] = (
            f"Committed with {len(open_cs)} open constraint(s) — deliberate override. "
            "This commitment is at risk."
        )
        result["open_constraints"] = open_cs
    return result


def mark_complete(
    project: mspdi.Project,
    week: str,
    task_uid: int,
    complete: bool,
    actual_hours: float | None = None,
    variance_reason: str | None = None,
    corrective_action: str | None = None,
) -> dict[str, Any]:
    """Close a commitment at week end. If not complete, a variance reason is required.

    `corrective_action` closes the PDCA loop: record what will be done so the
    same variance does not repeat (root cause / 5 Whys outcome).
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    if not complete and not variance_reason:
        return {"error": "Incomplete commitments require variance_reason."}
    if variance_reason and variance_reason not in VALID_VARIANCE_REASONS:
        return {
            "error": f"Invalid variance_reason '{variance_reason}'",
            "valid_reasons": sorted(VALID_VARIANCE_REASONS),
        }
    payload = sidecar.load_lps(project.source_path)
    wwp = _find_wwp(payload, week)
    if wwp is None:
        return {"error": f"No weekly work plan for '{week}'."}
    commitment = next((c for c in wwp["commitments"] if c["task_uid"] == task_uid), None)
    if commitment is None:
        return {"error": f"Task UID {task_uid} is not committed in {week}."}
    commitment["complete"] = complete
    commitment["actual_hours"] = actual_hours
    commitment["variance_reason"] = None if complete else variance_reason
    commitment["corrective_action"] = corrective_action
    sidecar.save_lps(project.source_path, payload)
    return {"updated": True, "week": week, "commitment": commitment}


def get_wwp(project: mspdi.Project, week: str) -> dict[str, Any]:
    """Get the weekly work plan for a given ISO week."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    wwp = _find_wwp(payload, week)
    if wwp is None:
        return {"error": f"No weekly work plan for '{week}'.", "week": week}
    return {
        "week": week,
        "commitment_count": len(wwp["commitments"]),
        "commitments": wwp["commitments"],
    }


def calculate_ppc(
    project: mspdi.Project,
    week: str | None = None,
    weeks_back: int = 4,
) -> dict[str, Any]:
    """Compute Percent Plan Complete.

    If `week` is given, returns PPC for that single week. Otherwise returns
    a series of the last `weeks_back` weeks that have WWPs recorded.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    wwps = payload["weekly_work_plans"]
    if not wwps:
        return {"series": [], "note": "No weekly work plans recorded."}

    def _compute_one(w: dict[str, Any]) -> dict[str, Any]:
        commitments = w["commitments"]
        total = len(commitments)
        complete = sum(1 for c in commitments if c.get("complete"))
        failed = [c for c in commitments if not c.get("complete")]
        reasons: dict[str, int] = {}
        for f in failed:
            r = f.get("variance_reason") or "unspecified"
            reasons[r] = reasons.get(r, 0) + 1
        ppc = round(complete / total * 100, 1) if total else 0.0
        return {
            "week": w["week"], "committed": total, "complete": complete,
            "failed": total - complete, "ppc": ppc,
            "variance_reasons": reasons,
        }

    if week is not None:
        target = _find_wwp(payload, week)
        if target is None:
            return {"error": f"No weekly work plan for '{week}'."}
        return _compute_one(target)

    sorted_wwps = sorted(wwps, key=lambda w: w["week"])
    recent = sorted_wwps[-weeks_back:]
    series = [_compute_one(w) for w in recent]
    avg = round(sum(s["ppc"] for s in series) / len(series), 1) if series else 0.0
    return {"series": series, "average_ppc": avg, "weeks_included": len(series)}


# ======================================================================
# Workable backlog
# ======================================================================


def workable_backlog(
    project: mspdi.Project,
    week: str | None = None,
    weeks: int = 6,
) -> dict[str, Any]:
    """Return ready tasks in the lookahead not yet committed — the fallback buffer.

    A healthy WWP keeps a workable backlog: sound tasks the crews can pull if
    a committed task stalls. Ready tasks from the lookahead, minus whatever is
    already committed in the given week's WWP (default: current week).
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    target_week = week or _iso_week(date.today())
    if _week_start(target_week) is None:
        return {"error": f"Invalid week '{target_week}'. Use ISO format 'YYYY-Www'."}
    view = lookahead(project, weeks)
    if "error" in view:
        return view
    payload = sidecar.load_lps(project.source_path)
    wwp = _find_wwp(payload, target_week)
    committed_uids = {c["task_uid"] for c in wwp["commitments"]} if wwp else set()
    backlog = [
        t for t in view["tasks"]
        if t["ready"] and t["task_uid"] not in committed_uids
    ]
    return {
        "week": target_week,
        "backlog_count": len(backlog),
        "committed_count": len(committed_uids),
        "backlog": backlog,
    }


# ======================================================================
# Daily huddle
# ======================================================================


def log_daily(
    project: mspdi.Project,
    week: str,
    task_uid: int,
    note: str,
    day: str | None = None,
    blocked: bool = False,
) -> dict[str, Any]:
    """Log a daily-huddle entry against a committed task.

    The daily huddle is LPS level 5: each day the crew checks progress on the
    week's commitments and surfaces new blockers early. `day` defaults to
    today (ISO 'YYYY-MM-DD').
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    wwp = _find_wwp(payload, week)
    if wwp is None:
        return {"error": f"No weekly work plan for '{week}'."}
    commitment = next((c for c in wwp["commitments"] if c["task_uid"] == task_uid), None)
    if commitment is None:
        return {"error": f"Task UID {task_uid} is not committed in {week}."}
    entry = {
        "day": day or _today_iso(),
        "task_uid": task_uid,
        "task_name": commitment.get("task_name"),
        "note": note,
        "blocked": blocked,
    }
    wwp.setdefault("daily_log", []).append(entry)
    sidecar.save_lps(project.source_path, payload)
    return {"logged": True, "week": week, "entry": entry}


def get_daily_log(
    project: mspdi.Project, week: str, day: str | None = None
) -> dict[str, Any]:
    """Return daily-huddle entries for a week, optionally filtered by day."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    wwp = _find_wwp(payload, week)
    if wwp is None:
        return {"error": f"No weekly work plan for '{week}'."}
    entries = wwp.get("daily_log", [])
    if day:
        entries = [e for e in entries if e.get("day") == day]
    blocked = [e for e in entries if e.get("blocked")]
    return {
        "week": week,
        "entry_count": len(entries),
        "blocked_count": len(blocked),
        "entries": entries,
    }


# ======================================================================
# Reliability metrics — TA / TMR
# ======================================================================


def reliability(project: mspdi.Project, weeks_back: int = 4) -> dict[str, Any]:
    """Compute TA and TMR — the health of the make-ready process.

    For each recorded WWP week (newest `weeks_back`):

      TA  (Tasks Anticipated): % of committed tasks that appeared in a
          lookahead snapshot taken *before* that week started. Low TA means
          work is entering the weekly plan that planning never saw coming.

      TMR (Tasks Made Ready): of the tasks a prior snapshot anticipated to
          start in that week, % that actually got committed. Low TMR means
          the make-ready process is not clearing constraints in time.

    PPC alone measures last week's promise-keeping; TA/TMR measure whether
    the planning system upstream is doing its job. Requires snapshots taken
    via `snapshot_lookahead` (do it at every weekly lookahead review).
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_lps(project.source_path)
    snapshots = payload["lookahead_snapshots"]
    if not snapshots:
        return {
            "series": [],
            "note": "No lookahead snapshots recorded. Call lps_snapshot_lookahead "
                    "at each weekly review to enable TA/TMR.",
        }
    wwps = sorted(payload["weekly_work_plans"], key=lambda w: w["week"])[-weeks_back:]
    series: list[dict[str, Any]] = []
    for wwp in wwps:
        week = wwp["week"]
        start = _week_start(week)
        if start is None:
            continue
        prior = [
            s for s in snapshots
            if (taken := _parse_iso_date(s.get("taken_on"))) is not None and taken < start
        ]
        committed_uids = {c["task_uid"] for c in wwp["commitments"]}
        anticipated_uids: set[int] = set()
        anticipated_for_week: set[int] = set()
        for snap in prior:
            for item in snap.get("anticipated", []):
                uid = int(item["task_uid"])
                anticipated_uids.add(uid)
                item_start = _parse_iso_date(item.get("start"))
                if item_start is not None and _iso_week(item_start) == week:
                    anticipated_for_week.add(uid)
        ta = (
            round(len(committed_uids & anticipated_uids) / len(committed_uids) * 100, 1)
            if committed_uids else None
        )
        tmr = (
            round(len(anticipated_for_week & committed_uids) / len(anticipated_for_week) * 100, 1)
            if anticipated_for_week else None
        )
        series.append({
            "week": week,
            "committed": len(committed_uids),
            "anticipated_for_week": len(anticipated_for_week),
            "ta_percent": ta,
            "tmr_percent": tmr,
            "snapshots_considered": len(prior),
        })
    return {"series": series, "weeks_included": len(series)}
