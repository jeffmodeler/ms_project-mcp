"""Advanced Work Packaging (AWP) — CII methodology (RT-272 / RT-319).

Domain model and tool implementations for the full E-P-C alignment:

    CWA (Construction Work Area)  →  CWP (Construction Work Package)
                                          ↓
                                     IWP (Installation Work Package)

    EWP (Engineering Work Package)  ─┐
                                     ├→ feed CWP readiness
    PWP (Procurement Work Package)  ─┘

EWPs and PWPs are linked to CWPs: a CWP is only ready when its engineering
deliverables are issued and its procurement packages are delivered on-site.
IWPs can only be *released* to the field after a passing readiness check
(constraint-free release — the WorkFace Planning golden rule).

Metadata is persisted in the project sidecar folder (see `sidecar.py`). The
`.mpp`/`.xml` schedule remains untouched — tasks are linked to CWPs via their
UID only.

All public functions in this module return plain `dict`s so they serialize
cleanly to JSON for MCP tool responses.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from project_mcp import mspdi, sidecar

logger = logging.getLogger(__name__)

VALID_CWP_STATUS = {"planned", "ready", "in-progress", "complete", "on-hold"}
VALID_IWP_STATUS = {"planned", "ready", "released", "complete"}
VALID_EWP_STATUS = {"planned", "in-progress", "issued"}
VALID_PWP_STATUS = {"planned", "ordered", "delivered"}

# CII guidance: an IWP is 1-2 weeks of work for a single crew — typically
# 500-1000 field hours. 40h would be a single-person week, far too small.
DEFAULT_IWP_HOURS = 500.0


def _find_cwa(payload: dict[str, Any], cwa_id: str) -> dict[str, Any] | None:
    return next((c for c in payload["cwa"] if c["id"] == cwa_id), None)


def _find_cwp(payload: dict[str, Any], cwp_id: str) -> dict[str, Any] | None:
    return next((c for c in payload["cwp"] if c["id"] == cwp_id), None)


def _find_iwp(payload: dict[str, Any], iwp_id: str) -> dict[str, Any] | None:
    return next((i for i in payload["iwp"] if i["id"] == iwp_id), None)


def _find_ewp(payload: dict[str, Any], ewp_id: str) -> dict[str, Any] | None:
    return next((e for e in payload["ewp"] if e["id"] == ewp_id), None)


def _find_pwp(payload: dict[str, Any], pwp_id: str) -> dict[str, Any] | None:
    return next((p for p in payload["pwp"] if p["id"] == pwp_id), None)


def _task_to_cwp_map(payload: dict[str, Any]) -> dict[int, str]:
    """Reverse index: task_uid -> cwp_id."""
    mapping: dict[int, str] = {}
    for cwp in payload["cwp"]:
        for uid in cwp.get("task_uids", []):
            mapping[int(uid)] = cwp["id"]
    return mapping


# ---------------------------------------------------------------- CWA tools


def list_cwa(project: mspdi.Project) -> dict[str, Any]:
    """Return all Construction Work Areas defined in the sidecar."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    return {
        "source": project.source_path,
        "count": len(payload["cwa"]),
        "cwa": payload["cwa"],
    }


def upsert_cwa(
    project: mspdi.Project,
    cwa_id: str,
    name: str,
    description: str | None = None,
    priority: int = 500,
) -> dict[str, Any]:
    """Create or update a CWA. `cwa_id` is the stable identifier."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    existing = _find_cwa(payload, cwa_id)
    record = {
        "id": cwa_id,
        "name": name,
        "description": description,
        "priority": priority,
    }
    if existing is None:
        payload["cwa"].append(record)
        action = "created"
    else:
        existing.update(record)
        action = "updated"
    sidecar.save_awp(project.source_path, payload)
    return {"action": action, "cwa": record}


# ---------------------------------------------------------------- CWP tools


def list_cwp(
    project: mspdi.Project, cwa_id: str | None = None
) -> dict[str, Any]:
    """List Construction Work Packages, optionally filtered by CWA."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    items = payload["cwp"]
    if cwa_id:
        items = [c for c in items if c.get("cwa_id") == cwa_id]
    enriched = [_enrich_cwp(c, project) for c in items]
    return {"count": len(enriched), "cwp": enriched}


def upsert_cwp(
    project: mspdi.Project,
    cwp_id: str,
    name: str,
    cwa_id: str,
    description: str | None = None,
    status: str = "planned",
) -> dict[str, Any]:
    """Create or update a CWP. Must reference an existing CWA."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    if status not in VALID_CWP_STATUS:
        return {"error": f"Invalid status '{status}'. Valid: {sorted(VALID_CWP_STATUS)}"}
    payload = sidecar.load_awp(project.source_path)
    if _find_cwa(payload, cwa_id) is None:
        return {"error": f"CWA '{cwa_id}' does not exist. Create it first with upsert_cwa."}
    existing = _find_cwp(payload, cwp_id)
    if existing is None:
        record = {
            "id": cwp_id,
            "name": name,
            "cwa_id": cwa_id,
            "description": description,
            "status": status,
            "task_uids": [],
            "requirements": {"materials": [], "documents": [], "access": []},
        }
        payload["cwp"].append(record)
        action = "created"
    else:
        existing.update({
            "name": name, "cwa_id": cwa_id,
            "description": description, "status": status,
        })
        record = existing
        action = "updated"
    sidecar.save_awp(project.source_path, payload)
    return {"action": action, "cwp": record}


def assign_task_to_cwp(
    project: mspdi.Project, task_uid: int, cwp_id: str
) -> dict[str, Any]:
    """Link a task (by UID) to a CWP. The task must exist in the project."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    task = project.task_by_uid(task_uid)
    if task is None:
        return {"error": f"Task UID {task_uid} not found in project."}
    payload = sidecar.load_awp(project.source_path)
    cwp = _find_cwp(payload, cwp_id)
    if cwp is None:
        return {"error": f"CWP '{cwp_id}' does not exist."}
    # Remove this task from any other CWP it might be assigned to
    reassigned_from: str | None = None
    for other in payload["cwp"]:
        if other["id"] == cwp_id:
            continue
        if task_uid in other.get("task_uids", []):
            other["task_uids"].remove(task_uid)
            reassigned_from = other["id"]
    task_uids: list[int] = cwp.setdefault("task_uids", [])
    if task_uid not in task_uids:
        task_uids.append(task_uid)
    sidecar.save_awp(project.source_path, payload)
    return {
        "assigned": True,
        "task_uid": task_uid,
        "task_name": task.name,
        "cwp_id": cwp_id,
        "reassigned_from": reassigned_from,
    }


def set_cwp_requirements(
    project: mspdi.Project,
    cwp_id: str,
    materials: list[str] | None = None,
    documents: list[str] | None = None,
    access: list[str] | None = None,
) -> dict[str, Any]:
    """Set readiness requirements for a CWP.

    Any argument left as None preserves the existing list.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    cwp = _find_cwp(payload, cwp_id)
    if cwp is None:
        return {"error": f"CWP '{cwp_id}' does not exist."}
    default_reqs: dict[str, list[str]] = {"materials": [], "documents": [], "access": []}
    reqs: dict[str, list[str]] = cwp.setdefault("requirements", default_reqs)
    if materials is not None:
        reqs["materials"] = materials
    if documents is not None:
        reqs["documents"] = documents
    if access is not None:
        reqs["access"] = access
    sidecar.save_awp(project.source_path, payload)
    return {"cwp_id": cwp_id, "requirements": reqs}


def readiness_check(
    project: mspdi.Project,
    cwp_id: str,
    available_materials: list[str] | None = None,
    available_documents: list[str] | None = None,
    available_access: list[str] | None = None,
) -> dict[str, Any]:
    """Check whether a CWP has all requirements available.

    Verifies three things:
      1. Manual requirements (materials/documents/access) against `available_*`
      2. All linked EWPs have status 'issued' (engineering complete)
      3. All linked PWPs have status 'delivered' (materials on-site)

    The result is stored on the CWP as `last_readiness` — it is the gate that
    `release_iwp` checks before allowing field release.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    cwp = _find_cwp(payload, cwp_id)
    if cwp is None:
        return {"error": f"CWP '{cwp_id}' does not exist."}
    reqs = cwp.get("requirements", {})
    avail = {
        "materials": set(available_materials or []),
        "documents": set(available_documents or []),
        "access": set(available_access or []),
    }
    missing: dict[str, list[str]] = {}
    for key in ("materials", "documents", "access"):
        needed = set(reqs.get(key, []))
        lack = sorted(needed - avail[key])
        if lack:
            missing[key] = lack

    # E-P alignment: engineering must be issued, procurement delivered
    pending_ewp = sorted(
        e["id"] for e in payload["ewp"]
        if e.get("cwp_id") == cwp_id and e.get("status") != "issued"
    )
    pending_pwp = sorted(
        p["id"] for p in payload["pwp"]
        if p.get("cwp_id") == cwp_id and p.get("status") != "delivered"
    )
    if pending_ewp:
        missing["engineering"] = pending_ewp
    if pending_pwp:
        missing["procurement"] = pending_pwp

    is_ready = not missing
    cwp["last_readiness"] = {
        "ready": is_ready,
        "missing": missing,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    sidecar.save_awp(project.source_path, payload)
    return {
        "cwp_id": cwp_id,
        "ready": is_ready,
        "missing": missing,
        "requirements": reqs,
        "linked_ewp_pending": pending_ewp,
        "linked_pwp_pending": pending_pwp,
    }


# ------------------------------------------------------------ EWP/PWP tools


def upsert_ewp(
    project: mspdi.Project,
    ewp_id: str,
    name: str,
    cwp_id: str,
    discipline: str | None = None,
    status: str = "planned",
    issue_date: str | None = None,
) -> dict[str, Any]:
    """Create or update an Engineering Work Package linked to a CWP.

    EWPs represent engineering deliverables (drawings, specs, models) that
    must be issued before the CWP can be released to the field.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    if status not in VALID_EWP_STATUS:
        return {"error": f"Invalid status '{status}'. Valid: {sorted(VALID_EWP_STATUS)}"}
    payload = sidecar.load_awp(project.source_path)
    if _find_cwp(payload, cwp_id) is None:
        return {"error": f"CWP '{cwp_id}' does not exist. Create it first with upsert_cwp."}
    existing = _find_ewp(payload, ewp_id)
    record = {
        "id": ewp_id,
        "name": name,
        "cwp_id": cwp_id,
        "discipline": discipline,
        "status": status,
        "issue_date": issue_date,
    }
    if existing is None:
        payload["ewp"].append(record)
        action = "created"
    else:
        existing.update(record)
        record = existing
        action = "updated"
    sidecar.save_awp(project.source_path, payload)
    return {"action": action, "ewp": record}


def list_ewp(project: mspdi.Project, cwp_id: str | None = None) -> dict[str, Any]:
    """List Engineering Work Packages, optionally filtered by CWP."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    items = payload["ewp"]
    if cwp_id:
        items = [e for e in items if e.get("cwp_id") == cwp_id]
    return {"count": len(items), "ewp": items}


def upsert_pwp(
    project: mspdi.Project,
    pwp_id: str,
    name: str,
    cwp_id: str,
    materials: list[str] | None = None,
    status: str = "planned",
    required_on_site: str | None = None,
) -> dict[str, Any]:
    """Create or update a Procurement Work Package linked to a CWP.

    PWPs represent purchased materials/equipment that must be delivered
    on-site before the CWP can be released to the field.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    if status not in VALID_PWP_STATUS:
        return {"error": f"Invalid status '{status}'. Valid: {sorted(VALID_PWP_STATUS)}"}
    payload = sidecar.load_awp(project.source_path)
    if _find_cwp(payload, cwp_id) is None:
        return {"error": f"CWP '{cwp_id}' does not exist. Create it first with upsert_cwp."}
    existing = _find_pwp(payload, pwp_id)
    record = {
        "id": pwp_id,
        "name": name,
        "cwp_id": cwp_id,
        "materials": materials or [],
        "status": status,
        "required_on_site": required_on_site,
    }
    if existing is None:
        payload["pwp"].append(record)
        action = "created"
    else:
        if materials is None:
            record["materials"] = existing.get("materials", [])
        existing.update(record)
        record = existing
        action = "updated"
    sidecar.save_awp(project.source_path, payload)
    return {"action": action, "pwp": record}


def list_pwp(project: mspdi.Project, cwp_id: str | None = None) -> dict[str, Any]:
    """List Procurement Work Packages, optionally filtered by CWP."""
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    items = payload["pwp"]
    if cwp_id:
        items = [p for p in items if p.get("cwp_id") == cwp_id]
    return {"count": len(items), "pwp": items}


# ---------------------------------------------------------- Path of construction


def set_path_of_construction(
    project: mspdi.Project, cwp_ids: list[str]
) -> dict[str, Any]:
    """Define the Path of Construction as a *planning input*.

    In AWP the PoC is decided by the construction team and drives engineering
    and procurement priorities — it is not derived from the schedule. Pass
    CWP ids in the order construction intends to execute. Once set,
    `path_of_construction` returns this sequence (mode 'planned') instead of
    the schedule-derived fallback.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    unknown = [cid for cid in cwp_ids if _find_cwp(payload, cid) is None]
    if unknown:
        return {"error": f"Unknown CWP ids: {unknown}. Create them first with upsert_cwp."}
    payload["poc"] = list(cwp_ids)
    sidecar.save_awp(project.source_path, payload)
    return {"poc_set": True, "sequence": cwp_ids, "count": len(cwp_ids)}


def path_of_construction(project: mspdi.Project) -> dict[str, Any]:
    """Return the Path of Construction — the CWP execution sequence.

    If a manual PoC was defined via `set_path_of_construction`, that order is
    used (mode 'planned' — the true AWP PoC, a planning input). Otherwise the
    sequence is derived from the schedule sorted by earliest task start
    (mode 'derived-from-schedule' — a fallback report, not a real PoC).

    For each CWP, aggregates earliest start, latest finish, total hours and
    critical-path exposure.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    cwps = payload["cwp"]
    if not cwps:
        return {"count": 0, "sequence": [], "note": "No CWPs defined yet."}
    result: list[dict[str, Any]] = []
    for cwp in cwps:
        tasks = [project.task_by_uid(uid) for uid in cwp.get("task_uids", [])]
        tasks = [t for t in tasks if t is not None]
        if not tasks:
            result.append({
                "cwp_id": cwp["id"], "name": cwp["name"], "status": cwp.get("status"),
                "task_count": 0,
            })
            continue
        starts = [t.start for t in tasks if t.start]
        finishes = [t.finish for t in tasks if t.finish]
        critical_count = sum(1 for t in tasks if t.is_critical)
        total_hours = sum(t.duration_hours for t in tasks)
        result.append({
            "cwp_id": cwp["id"],
            "name": cwp["name"],
            "cwa_id": cwp.get("cwa_id"),
            "status": cwp.get("status"),
            "task_count": len(tasks),
            "earliest_start": min(starts) if starts else None,
            "latest_finish": max(finishes) if finishes else None,
            "duration_hours": round(total_hours, 2),
            "critical_task_count": critical_count,
            "on_critical_path": critical_count > 0,
        })
    manual_poc: list[str] = payload.get("poc", [])
    if manual_poc:
        order = {cid: i for i, cid in enumerate(manual_poc)}
        result.sort(key=lambda r: order.get(r["cwp_id"], len(order)))
        mode = "planned"
    else:
        result.sort(key=lambda r: (r.get("earliest_start") or "9999"))
        mode = "derived-from-schedule"
    return {"count": len(result), "mode": mode, "sequence": result}


# ---------------------------------------------------------------- IWP tools


def generate_iwps(
    project: mspdi.Project,
    cwp_id: str,
    max_hours_per_iwp: float = DEFAULT_IWP_HOURS,
    discipline: str | None = None,
    crew: str | None = None,
) -> dict[str, Any]:
    """Split a CWP into IWPs (Installation Work Packages) sized by labor hours.

    Walks the CWP's tasks in schedule order and groups them into IWPs such
    that no IWP exceeds `max_hours_per_iwp` (default 500h — CII sizing: 1-2
    weeks of work for one crew). Any task already larger than the cap becomes
    a standalone IWP.

    `discipline` and `crew` are stamped on every generated IWP — an IWP
    should always be single-discipline, single-crew, single-work-front.

    Only IWPs still in 'planned' status are regenerated. IWPs already ready,
    released or complete are preserved, and their tasks are not regrouped.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    cwp = _find_cwp(payload, cwp_id)
    if cwp is None:
        return {"error": f"CWP '{cwp_id}' does not exist."}

    # Protect IWPs that already left the planning stage
    preserved = [
        i for i in payload["iwp"]
        if i.get("cwp_id") == cwp_id and i.get("status") != "planned"
    ]
    locked_uids = {int(u) for i in preserved for u in i.get("task_uids", [])}

    tasks = [project.task_by_uid(uid) for uid in cwp.get("task_uids", [])]
    tasks = [t for t in tasks if t is not None and t.uid not in locked_uids]
    if not tasks:
        if preserved:
            return {
                "cwp_id": cwp_id, "iwp_count": 0, "iwp": [],
                "preserved_count": len(preserved),
                "note": "All tasks belong to IWPs already ready/released/complete.",
            }
        return {"error": f"CWP '{cwp_id}' has no tasks assigned."}
    tasks.sort(key=lambda t: (t.start or "9999", t.id))

    existing_ids = {i["id"] for i in payload["iwp"]}
    iwps: list[dict[str, Any]] = []
    current_uids: list[int] = []
    current_hours = 0.0
    seq = 1
    for task in tasks:
        hours = task.duration_hours or 0.0
        if current_uids and current_hours + hours > max_hours_per_iwp:
            iwps.append(_make_iwp(cwp_id, seq, current_uids, current_hours,
                                  discipline, crew, existing_ids))
            seq += 1
            current_uids = []
            current_hours = 0.0
        current_uids.append(task.uid)
        current_hours += hours
    if current_uids:
        iwps.append(_make_iwp(cwp_id, seq, current_uids, current_hours,
                              discipline, crew, existing_ids))

    # Replace only the 'planned' IWPs for this CWP; keep everything else
    payload["iwp"] = [
        i for i in payload["iwp"]
        if i.get("cwp_id") != cwp_id or i.get("status") != "planned"
    ]
    payload["iwp"].extend(iwps)
    sidecar.save_awp(project.source_path, payload)
    return {
        "cwp_id": cwp_id,
        "iwp_count": len(iwps),
        "iwp": iwps,
        "preserved_count": len(preserved),
        "preserved": [i["id"] for i in preserved],
    }


def _make_iwp(
    cwp_id: str,
    seq: int,
    task_uids: list[int],
    hours: float,
    discipline: str | None,
    crew: str | None,
    existing_ids: set[str],
) -> dict[str, Any]:
    base = f"IWP-{cwp_id.replace('CWP-', '')}"
    iwp_id = f"{base}.{seq:03d}"
    while iwp_id in existing_ids:
        seq += 1
        iwp_id = f"{base}.{seq:03d}"
    existing_ids.add(iwp_id)
    return {
        "id": iwp_id,
        "cwp_id": cwp_id,
        "task_uids": task_uids,
        "labor_hours": round(hours, 2),
        "discipline": discipline,
        "crew": crew,
        "status": "planned",
        "percent_complete": 0,
        "earned_hours": 0.0,
        "released_date": None,
    }


def release_iwp(project: mspdi.Project, iwp_id: str) -> dict[str, Any]:
    """Release an IWP to the field — gated on a passing CWP readiness check.

    WorkFace Planning golden rule: an IWP only goes to the field 100%
    constraint-free. This tool refuses to release unless the parent CWP's
    last `readiness_check` passed (ready=true). Run `awp_readiness_check`
    first, clear what's missing, then release.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    iwp = _find_iwp(payload, iwp_id)
    if iwp is None:
        return {"error": f"IWP '{iwp_id}' does not exist."}
    if iwp.get("status") == "released":
        return {"already_released": True, "iwp": iwp}
    if iwp.get("status") == "complete":
        return {"error": f"IWP '{iwp_id}' is already complete."}
    cwp = _find_cwp(payload, iwp.get("cwp_id", ""))
    if cwp is None:
        return {"error": f"Parent CWP '{iwp.get('cwp_id')}' not found."}
    last = cwp.get("last_readiness")
    if last is None:
        return {
            "released": False,
            "error": "No readiness check on record for the parent CWP. "
                     "Run awp_readiness_check first — IWPs are only released constraint-free.",
        }
    if not last.get("ready"):
        return {
            "released": False,
            "error": "Parent CWP failed its last readiness check. Clear the missing "
                     "items and re-run awp_readiness_check before releasing.",
            "missing": last.get("missing", {}),
            "checked_at": last.get("checked_at"),
        }
    iwp["status"] = "released"
    iwp["released_date"] = datetime.now(UTC).date().isoformat()
    sidecar.save_awp(project.source_path, payload)
    return {"released": True, "iwp": iwp, "readiness_checked_at": last.get("checked_at")}


def update_iwp_progress(
    project: mspdi.Project,
    iwp_id: str,
    percent_complete: int,
    earned_hours: float | None = None,
) -> dict[str, Any]:
    """Update field progress on an IWP. At 100% the IWP is marked complete.

    Progress at IWP level is the AWP earned-value signal: completed IWPs ×
    their labor_hours = earned hours for the CWP.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    if not 0 <= percent_complete <= 100:
        return {"error": "percent_complete must be between 0 and 100."}
    payload = sidecar.load_awp(project.source_path)
    iwp = _find_iwp(payload, iwp_id)
    if iwp is None:
        return {"error": f"IWP '{iwp_id}' does not exist."}
    if iwp.get("status") == "planned":
        return {
            "error": f"IWP '{iwp_id}' has not been released. "
                     "Release it first with awp_release_iwp.",
        }
    iwp["percent_complete"] = percent_complete
    if earned_hours is not None:
        iwp["earned_hours"] = round(earned_hours, 2)
    else:
        iwp["earned_hours"] = round(
            iwp.get("labor_hours", 0.0) * percent_complete / 100, 2
        )
    if percent_complete == 100:
        iwp["status"] = "complete"
    sidecar.save_awp(project.source_path, payload)
    return {"updated": True, "iwp": iwp}


# ---------------------------------------------------------------- Work Package Release


def export_wpr(project: mspdi.Project, cwp_id: str) -> dict[str, Any]:
    """Generate a Work Package Release — everything needed to send the CWP to the field.

    Returns a self-contained JSON structure with CWP metadata, requirements,
    full task list (names, dates, hours), and IWP breakdown. Field teams
    receive this to start execution without further coordination.
    """
    if project.source_path is None:
        return {"error": "Project has no source_path; load_project first."}
    payload = sidecar.load_awp(project.source_path)
    cwp = _find_cwp(payload, cwp_id)
    if cwp is None:
        return {"error": f"CWP '{cwp_id}' does not exist."}
    cwa = _find_cwa(payload, cwp.get("cwa_id", ""))
    tasks_dict = [
        project.task_by_uid(uid).to_dict()
        for uid in cwp.get("task_uids", [])
        if project.task_by_uid(uid) is not None
    ]
    iwps = [i for i in payload["iwp"] if i.get("cwp_id") == cwp_id]
    return {
        "wpr_id": f"WPR-{cwp_id}",
        "project": {"title": project.title, "source": project.source_path},
        "cwa": cwa,
        "cwp": cwp,
        "tasks": tasks_dict,
        "iwp": iwps,
        "task_count": len(tasks_dict),
        "total_hours": round(sum(t["duration_hours"] for t in tasks_dict), 2),
    }


def _enrich_cwp(cwp: dict[str, Any], project: mspdi.Project) -> dict[str, Any]:
    """Add computed fields to a CWP record for listing."""
    tasks = [project.task_by_uid(uid) for uid in cwp.get("task_uids", [])]
    tasks = [t for t in tasks if t is not None]
    return {
        **cwp,
        "task_count": len(tasks),
        "total_hours": round(sum(t.duration_hours for t in tasks), 2),
        "any_critical": any(t.is_critical for t in tasks),
    }
