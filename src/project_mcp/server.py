"""project-mcp: MCP server exposing Microsoft Project data as tools."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from project_mcp import awp, lps, mspdi
from project_mcp.pbip_writer import PbipWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("project-mcp")

mcp = FastMCP("project-mcp")

_state: dict[str, mspdi.Project | None] = {"project": None}


def _project() -> mspdi.Project:
    project = _state["project"]
    if project is None:
        raise RuntimeError("No project loaded. Call load_project(path) first.")
    return project


def _serialize(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str, ensure_ascii=False)


@mcp.tool()
def load_project(path: str) -> str:
    """Load a Microsoft Project file into memory.

    Currently supports MSPDI XML format (.xml), exported from Microsoft Project
    via File → Save As → Save as Type → XML Format. Support for native .mpp is
    available when the optional `mpxj` extra is installed (requires Java).

    Args:
        path: Absolute path to the project file.

    Returns:
        JSON with project metadata: title, author, dates, task and resource counts.
    """
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return _serialize({"error": f"File not found: {path}"})
    suffix = file_path.suffix.lower()
    if suffix in (".xml",):
        project = mspdi.parse_file(file_path)
    elif suffix == ".mpp":
        try:
            from project_mcp import mpp_loader  # type: ignore
        except ImportError:
            return _serialize({
                "error": ".mpp requires the optional 'mpp' extra. "
                         "Install with: uv pip install 'project-mcp[mpp]' "
                         "or export the file as XML from Microsoft Project."
            })
        project = mpp_loader.parse_file(file_path)
    else:
        return _serialize({
            "error": f"Unsupported file extension: {suffix}. Use .xml (MSPDI) or .mpp.",
            "hint": "From Microsoft Project: File → Save As → Save as Type → XML Format (*.xml)",
        })
    _state["project"] = project
    return _serialize({
        "loaded": True,
        "source_path": project.source_path,
        "title": project.title,
        "name": project.name,
        "author": project.author,
        "company": project.company,
        "start_date": project.start_date,
        "finish_date": project.finish_date,
        "currency_code": project.currency_code,
        "tasks_count": len(project.tasks),
        "resources_count": len(project.resources),
        "assignments_count": len(project.assignments),
    })


@mcp.tool()
def open_in_ms_project(path: str | None = None) -> str:
    """Open a project file in Microsoft Project using the default OS association.

    If path is omitted, opens the file that is currently loaded in memory.
    Uses the Windows shell (cmd /c start) so the file opens with whatever
    application is registered for .xml or .mpp on the user's machine.

    Args:
        path: Absolute path to the project file. Optional — defaults to the
              source_path of the currently loaded project.

    Returns:
        JSON confirming the file was sent to the OS for opening, or an error.
    """
    target: str | None = path

    if target is None:
        project = _state.get("project")
        if project is None:
            return _serialize({
                "error": "No project loaded and no path provided. "
                         "Call load_project(path) first or pass a path explicitly."
            })
        target = str(project.source_path)

    file_path = Path(target).expanduser()
    if not file_path.exists():
        return _serialize({"error": f"File not found: {target}"})

    try:
        # Use 'start' via cmd so Windows opens with the registered app (MS Project)
        subprocess.Popen(
            ["cmd", "/c", "start", "", str(file_path)],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Sent to OS for opening: %s", file_path)
        return _serialize({
            "opened": True,
            "path": str(file_path),
            "note": "File dispatched to the OS. Microsoft Project should open shortly.",
        })
    except Exception as exc:  # noqa: BLE001
        return _serialize({"error": f"Failed to open file: {exc}"})


@mcp.tool()
def project_info() -> str:
    """Return metadata about the currently loaded project.

    Returns:
        JSON with title, author, company, schedule window, currency and counts.
    """
    p = _project()
    summary_count = sum(1 for t in p.tasks if t.is_summary)
    milestone_count = sum(1 for t in p.tasks if t.is_milestone)
    critical_count = sum(1 for t in p.tasks if t.is_critical)
    total_work = sum(t.work_hours for t in p.tasks if not t.is_summary)
    total_duration = sum(t.duration_hours for t in p.tasks if not t.is_summary)
    return _serialize({
        "title": p.title,
        "name": p.name,
        "author": p.author,
        "company": p.company,
        "subject": p.subject,
        "category": p.category,
        "start_date": p.start_date,
        "finish_date": p.finish_date,
        "currency_code": p.currency_code,
        "currency_symbol": p.currency_symbol,
        "schema_version": p.schema_version,
        "source_path": p.source_path,
        "counts": {
            "tasks_total": len(p.tasks),
            "tasks_summary": summary_count,
            "tasks_milestone": milestone_count,
            "tasks_critical": critical_count,
            "resources": len(p.resources),
            "assignments": len(p.assignments),
        },
        "totals": {
            "work_hours": round(total_work, 2),
            "duration_hours": round(total_duration, 2),
        },
    })


@mcp.tool()
def list_tasks(
    include_summaries: bool = True,
    include_milestones: bool = True,
    only_critical: bool = False,
    name_contains: str | None = None,
    top_n: int | None = None,
) -> str:
    """List tasks in the loaded project, with optional filters.

    Args:
        include_summaries: Include summary tasks (parent rollup rows).
        include_milestones: Include milestone tasks (zero-duration markers).
        only_critical: Return only tasks on the critical path.
        name_contains: Substring filter on task name (case-insensitive).
        top_n: Limit the output to the first N tasks (None returns all).

    Returns:
        JSON with array of tasks containing UID, ID, name, dates, duration,
        percent complete, priority, and critical/summary/milestone flags.
    """
    p = _project()
    tasks = p.tasks
    if not include_summaries:
        tasks = [t for t in tasks if not t.is_summary]
    if not include_milestones:
        tasks = [t for t in tasks if not t.is_milestone]
    if only_critical:
        tasks = [t for t in tasks if t.is_critical]
    if name_contains:
        needle = name_contains.lower()
        tasks = [t for t in tasks if t.name and needle in t.name.lower()]
    if top_n:
        tasks = tasks[: int(top_n)]
    return _serialize({"count": len(tasks), "tasks": [t.to_dict() for t in tasks]})


@mcp.tool()
def get_task(uid: int | None = None, id: int | None = None, name: str | None = None) -> str:
    """Get the full record of a single task by UID, ID, or exact name.

    Args:
        uid: Task UID (the unique numeric identifier in MSPDI).
        id: Task ID (the row number shown in Project; not stable across edits).
        name: Exact task name (case-sensitive).

    Returns:
        JSON with all task fields, predecessors with link types, and resource
        assignments derived from the assignments table.
    """
    p = _project()
    task = None
    if uid is not None:
        task = p.task_by_uid(int(uid))
    elif id is not None:
        task = p.task_by_id(int(id))
    elif name:
        task = p.task_by_name(name)
    else:
        return _serialize({"error": "Provide one of: uid, id, name"})
    if task is None:
        return _serialize({"error": "Task not found"})
    assignments = [
        {**a.to_dict(), "resource_name": (
            r.name if (r := p.resource_by_uid(a.resource_uid)) else None
        )}
        for a in p.assignments if a.task_uid == task.uid
    ]
    return _serialize({**task.to_dict(), "assignments": assignments})


@mcp.tool()
def list_resources(only_overallocated: bool = False, type_filter: str | None = None) -> str:
    """List resources in the project.

    Args:
        only_overallocated: Return only resources flagged as overallocated.
        type_filter: Filter by resource type: 'Work', 'Material', or 'Cost'.

    Returns:
        JSON with array of resources including units, rates, and allocation status.
    """
    p = _project()
    resources = p.resources
    if only_overallocated:
        resources = [r for r in resources if r.overallocated]
    if type_filter:
        resources = [r for r in resources if r.type == type_filter]
    return _serialize({
        "count": len(resources),
        "resources": [r.to_dict() for r in resources],
    })


@mcp.tool()
def get_resource_assignments(
    resource_uid: int | None = None,
    resource_name: str | None = None,
) -> str:
    """List task assignments for one resource (or all resources if no filter given).

    Args:
        resource_uid: Resource UID to filter by.
        resource_name: Exact resource name to filter by.

    Returns:
        JSON with assignments enriched with task and resource names.
    """
    p = _project()
    target_uid = None
    if resource_uid is not None:
        target_uid = int(resource_uid)
    elif resource_name:
        r = p.resource_by_name(resource_name)
        if r is None:
            return _serialize({"error": f"Resource not found: {resource_name}"})
        target_uid = r.uid

    assignments = p.assignments
    if target_uid is not None:
        assignments = [a for a in assignments if a.resource_uid == target_uid]

    enriched = []
    for a in assignments:
        task = p.task_by_uid(a.task_uid)
        resource = p.resource_by_uid(a.resource_uid)
        enriched.append({
            **a.to_dict(),
            "task_name": task.name if task else None,
            "resource_name": resource.name if resource else None,
        })
    return _serialize({"count": len(enriched), "assignments": enriched})


@mcp.tool()
def find_overallocated_resources() -> str:
    """List resources flagged as overallocated by Microsoft Project.

    Returns:
        JSON with overallocated resources and the number of assignments for each.
    """
    p = _project()
    over = [r for r in p.resources if r.overallocated]
    result = []
    for r in over:
        assignments = [a for a in p.assignments if a.resource_uid == r.uid]
        result.append({
            **r.to_dict(),
            "assignment_count": len(assignments),
            "total_assigned_hours": round(sum(a.work_hours for a in assignments), 2),
        })
    return _serialize({"count": len(result), "overallocated": result})


@mcp.tool()
def get_critical_path() -> str:
    """Return tasks on the critical path (Critical=1 in MSPDI).

    Critical tasks have zero or negative slack and directly determine the
    project finish date. Sorted by start date.

    Returns:
        JSON with critical tasks ordered chronologically.
    """
    p = _project()
    critical = sorted(
        [t for t in p.tasks if t.is_critical and not t.is_summary],
        key=lambda t: t.start or "",
    )
    return _serialize({
        "count": len(critical),
        "total_critical_duration_hours": round(sum(t.duration_hours for t in critical), 2),
        "tasks": [t.to_dict() for t in critical],
    })


@mcp.tool()
def get_predecessors_successors(task_uid: int) -> str:
    """Return the dependency network for a task: its predecessors and successors.

    Args:
        task_uid: UID of the task to inspect.

    Returns:
        JSON with two arrays (predecessors, successors) listing linked tasks
        with their link type (FS/SS/FF/SF) and lag in hours.
    """
    p = _project()
    target = p.task_by_uid(int(task_uid))
    if target is None:
        return _serialize({"error": f"Task not found: uid={task_uid}"})

    predecessors = []
    for link in target.predecessors:
        pred = p.task_by_uid(link["predecessor_uid"])
        if pred:
            predecessors.append({
                "uid": pred.uid,
                "id": pred.id,
                "name": pred.name,
                "link_type": link["link_type"],
                "lag_hours": link["lag_hours"],
            })

    successors = []
    for t in p.tasks:
        for link in t.predecessors:
            if link["predecessor_uid"] == target.uid:
                successors.append({
                    "uid": t.uid,
                    "id": t.id,
                    "name": t.name,
                    "link_type": link["link_type"],
                    "lag_hours": link["lag_hours"],
                })

    return _serialize({
        "task": {"uid": target.uid, "id": target.id, "name": target.name},
        "predecessors_count": len(predecessors),
        "successors_count": len(successors),
        "predecessors": predecessors,
        "successors": successors,
    })


@mcp.tool()
def get_baseline_variance(only_off_track: bool = False) -> str:
    """Compare current dates against the saved baseline.

    Variance is computed in hours: positive = task is later than baseline,
    negative = task is earlier than baseline. Tasks without a baseline are skipped.

    Args:
        only_off_track: Return only tasks where current dates differ from baseline.

    Returns:
        JSON listing each task with current vs baseline dates and variance.
    """
    p = _project()
    rows = []
    for t in p.tasks:
        if t.is_summary or not t.baseline_finish:
            continue
        variance_hours = t.duration_hours - t.baseline_duration_hours
        unchanged = (
            variance_hours == 0
            and t.start == t.baseline_start
            and t.finish == t.baseline_finish
        )
        if only_off_track and unchanged:
            continue
        rows.append({
            "uid": t.uid,
            "id": t.id,
            "name": t.name,
            "start": t.start,
            "baseline_start": t.baseline_start,
            "finish": t.finish,
            "baseline_finish": t.baseline_finish,
            "duration_hours": round(t.duration_hours, 2),
            "baseline_duration_hours": round(t.baseline_duration_hours, 2),
            "duration_variance_hours": round(variance_hours, 2),
        })
    return _serialize({
        "count": len(rows),
        "tasks": rows,
    })


@mcp.tool()
def get_gantt_data(top_n: int | None = None, exclude_summaries: bool = False) -> str:
    """Return tasks formatted for Gantt-chart consumption.

    Each entry has the minimum fields needed by frontend Gantt libraries:
    id, name, start, end, duration_hours, percent_complete, parent_id (for
    hierarchy), and dependencies (predecessor list with link types).

    Args:
        top_n: Limit to the first N tasks.
        exclude_summaries: Drop summary rows so only leaf tasks remain.

    Returns:
        JSON array of Gantt-ready task dicts.
    """
    p = _project()
    tasks = p.tasks
    if exclude_summaries:
        tasks = [t for t in tasks if not t.is_summary]
    if top_n:
        tasks = tasks[: int(top_n)]

    parent_by_outline: dict[str, int] = {}
    for t in p.tasks:
        if t.outline_number:
            parent_by_outline[t.outline_number] = t.uid

    def _parent_uid(outline_number: str | None) -> int | None:
        if not outline_number or "." not in outline_number:
            return None
        parent_outline = outline_number.rsplit(".", 1)[0]
        return parent_by_outline.get(parent_outline)

    gantt = []
    for t in tasks:
        gantt.append({
            "id": t.uid,
            "name": t.name,
            "start": t.start,
            "end": t.finish,
            "duration_hours": round(t.duration_hours, 2),
            "percent_complete": t.percent_complete,
            "is_summary": t.is_summary,
            "is_milestone": t.is_milestone,
            "is_critical": t.is_critical,
            "parent_id": _parent_uid(t.outline_number),
            "outline_level": t.outline_level,
            "dependencies": [
                {
                    "from_id": link["predecessor_uid"],
                    "type": link["link_type"],
                    "lag_hours": link["lag_hours"],
                }
                for link in t.predecessors
            ],
        })
    return _serialize({"count": len(gantt), "gantt": gantt})


@mcp.tool()
def export_to_json(output_path: str | None = None) -> str:
    """Export the entire loaded project to a JSON file (or return inline).

    Args:
        output_path: Absolute path for the JSON output. If None, returns the
            full JSON inline (may be large).

    Returns:
        JSON with the output path and summary, or the full project JSON inline.
    """
    p = _project()
    payload = {
        "metadata": {
            "title": p.title,
            "name": p.name,
            "author": p.author,
            "company": p.company,
            "start_date": p.start_date,
            "finish_date": p.finish_date,
            "currency_code": p.currency_code,
            "source_path": p.source_path,
        },
        "tasks": [t.to_dict() for t in p.tasks],
        "resources": [r.to_dict() for r in p.resources],
        "assignments": [a.to_dict() for a in p.assignments],
    }
    if output_path:
        out = Path(output_path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_serialize(payload), encoding="utf-8")
        return _serialize({
            "exported": True,
            "output_path": str(out.resolve()),
            "tasks": len(payload["tasks"]),
            "resources": len(payload["resources"]),
            "assignments": len(payload["assignments"]),
        })
    return _serialize(payload)


@mcp.tool()
def generate_pbip_dashboard(
    output_dir: str,
    project_name: str = "ProjectDashboard",
    open_in_power_bi: bool = True,
    xml_path: str | None = None,
) -> str:
    """Generate a Power BI Project (PBIP) dashboard from the loaded project.

    Creates a complete PBIP folder structure with SemanticModel (tables, measures,
    relationships) and a Report folder. The resulting folder can be opened in
    Power BI Desktop by double-clicking the .pbip file.

    The semantic model includes:
    - Three tables: Tarefas (non-summary tasks), Recursos (resources), Atribuicoes
      (assignments) with inline M-query partitions containing the project data.
    - Ten standard DAX measures (Avanco Geral, Custo Total, Tarefas Concluidas,
      Custo por Fase, etc.)
    - Two relationships (Atribuicoes -> Tarefas and Atribuicoes -> Recursos).
    - pt-BR culture.

    Args:
        output_dir: Absolute path to the folder where the PBIP project is written.
            The folder is created if missing.
        project_name: Name of the PBIP project (used as folder prefix and in the
            Power BI Desktop title bar). Defaults to "ProjectDashboard".
        open_in_power_bi: If True (default), launches Power BI Desktop on the
            generated .pbip file after writing.
        xml_path: Optional path to an MSPDI XML file to load before generating.
            If None, uses the currently-loaded project (load_project must have
            been called first).

    Returns:
        JSON with the output path, the .pbip file path, counts of what was
        written, and whether Power BI Desktop was launched.
    """
    if xml_path:
        file_path = Path(xml_path).expanduser()
        if not file_path.exists():
            return _serialize({"error": f"XML file not found: {xml_path}"})
        _state["project"] = mspdi.parse_file(file_path)

    project = _project()
    output = Path(output_dir).expanduser()

    writer = PbipWriter(project=project, output_dir=output, project_name=project_name)
    info = writer.write()

    launched = False
    launch_error: str | None = None
    if open_in_power_bi:
        pbip_file = info["pbip_file"]
        try:
            if os.name == "nt":
                os.startfile(pbip_file)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", pbip_file])
            launched = True
        except Exception as exc:
            launch_error = str(exc)

    return _serialize({
        **info,
        "opened_in_power_bi": launched,
        "launch_error": launch_error,
        "instructions": (
            "Open the .pbip file in Power BI Desktop (auto-launched if open_in_power_bi=True). "
            "After loading, add visuals to the 'Resumo' page: Card with [Avanco Geral], "
            "Card with [Custo Total], bar chart by Fase, and a table of critical tasks."
        ),
    })


# ============================================================
# AWP — Advanced Work Packaging (CII)
#
# Hierarchy: CWA (Construction Work Area) -> CWP (Construction Work Package)
#            -> IWP (Installation Work Package)
#
# Metadata persisted in sidecar folder next to the project file
# (e.g. obra-acme.mpp -> obra-acme.awp/awp.json). The .mpp/.xml is
# never modified — tasks are linked to CWPs by UID only.
# ============================================================


@mcp.tool()
def awp_list_cwa() -> str:
    """List all Construction Work Areas defined for the current project.

    Requires a project loaded via `load_project`. Returns CWAs stored in the
    sidecar folder next to the project file.
    """
    return _serialize(awp.list_cwa(_project()))


@mcp.tool()
def awp_upsert_cwa(
    cwa_id: str,
    name: str,
    description: str | None = None,
    priority: int = 500,
) -> str:
    """Create or update a Construction Work Area.

    Args:
        cwa_id: Stable identifier (e.g. "CWA-01" or "Fundacoes").
        name: Human-readable name.
        description: Optional longer description.
        priority: 1 = highest, 1000 = lowest (default 500).
    """
    return _serialize(awp.upsert_cwa(_project(), cwa_id, name, description, priority))


@mcp.tool()
def awp_list_cwp(cwa_id: str | None = None) -> str:
    """List Construction Work Packages, optionally filtered by CWA.

    Each CWP is enriched with computed fields: task_count, total_hours,
    any_critical (whether any assigned task is on the critical path).
    """
    return _serialize(awp.list_cwp(_project(), cwa_id))


@mcp.tool()
def awp_upsert_cwp(
    cwp_id: str,
    name: str,
    cwa_id: str,
    description: str | None = None,
    status: str = "planned",
) -> str:
    """Create or update a Construction Work Package.

    Args:
        cwp_id: Stable identifier (e.g. "CWP-01.01").
        name: Human-readable name.
        cwa_id: Parent CWA — must already exist.
        description: Optional longer description.
        status: One of: planned | ready | in-progress | complete | on-hold.
    """
    return _serialize(
        awp.upsert_cwp(_project(), cwp_id, name, cwa_id, description, status)
    )


@mcp.tool()
def awp_assign_task_to_cwp(task_uid: int, cwp_id: str) -> str:
    """Link a project task (by UID) to a CWP.

    If the task was previously assigned to another CWP, it is moved. Only
    one CWP per task — the sidecar maintains a single source of truth for
    this mapping.
    """
    return _serialize(awp.assign_task_to_cwp(_project(), task_uid, cwp_id))


@mcp.tool()
def awp_set_cwp_requirements(
    cwp_id: str,
    materials: list[str] | None = None,
    documents: list[str] | None = None,
    access: list[str] | None = None,
) -> str:
    """Set readiness requirements for a CWP (materials, documents, access).

    Omitting an argument (None) preserves the existing list. Pass an empty
    list [] to clear a category.
    """
    return _serialize(
        awp.set_cwp_requirements(_project(), cwp_id, materials, documents, access)
    )


@mcp.tool()
def awp_readiness_check(
    cwp_id: str,
    available_materials: list[str] | None = None,
    available_documents: list[str] | None = None,
    available_access: list[str] | None = None,
) -> str:
    """Check whether a CWP has all requirements available to start.

    Verifies manual requirements (pass what is on-site via `available_*`),
    plus E-P alignment: all linked EWPs must be 'issued' and all linked PWPs
    'delivered'. The result is stored on the CWP and gates `awp_release_iwp`.
    """
    return _serialize(
        awp.readiness_check(
            _project(), cwp_id,
            available_materials, available_documents, available_access,
        )
    )


@mcp.tool()
def awp_upsert_ewp(
    ewp_id: str,
    name: str,
    cwp_id: str,
    discipline: str | None = None,
    status: str = "planned",
    issue_date: str | None = None,
) -> str:
    """Create or update an Engineering Work Package linked to a CWP.

    EWPs are the engineering deliverables (drawings, specs, models) feeding a
    CWP. A CWP is only ready when all its EWPs are 'issued'.

    Args:
        ewp_id: Stable identifier (e.g. "EWP-01.01").
        name: Deliverable name (e.g. "Fôrmas Bloco A — IFC drawings").
        cwp_id: Parent CWP — must already exist.
        discipline: Engineering discipline (e.g. "civil", "piping").
        status: planned | in-progress | issued.
        issue_date: ISO date the package was/will be issued.
    """
    return _serialize(
        awp.upsert_ewp(_project(), ewp_id, name, cwp_id, discipline, status, issue_date)
    )


@mcp.tool()
def awp_list_ewp(cwp_id: str | None = None) -> str:
    """List Engineering Work Packages, optionally filtered by CWP."""
    return _serialize(awp.list_ewp(_project(), cwp_id))


@mcp.tool()
def awp_upsert_pwp(
    pwp_id: str,
    name: str,
    cwp_id: str,
    materials: list[str] | None = None,
    status: str = "planned",
    required_on_site: str | None = None,
) -> str:
    """Create or update a Procurement Work Package linked to a CWP.

    PWPs are purchased materials/equipment feeding a CWP. A CWP is only
    ready when all its PWPs are 'delivered'.

    Args:
        pwp_id: Stable identifier (e.g. "PWP-01.01").
        name: Package name (e.g. "Aço CA-50 Bloco A").
        cwp_id: Parent CWP — must already exist.
        materials: List of material descriptions in the package.
        status: planned | ordered | delivered.
        required_on_site: ISO date the materials must be on-site.
    """
    return _serialize(
        awp.upsert_pwp(_project(), pwp_id, name, cwp_id, materials, status, required_on_site)
    )


@mcp.tool()
def awp_list_pwp(cwp_id: str | None = None) -> str:
    """List Procurement Work Packages, optionally filtered by CWP."""
    return _serialize(awp.list_pwp(_project(), cwp_id))


@mcp.tool()
def awp_set_path_of_construction(cwp_ids: list[str]) -> str:
    """Define the Path of Construction as a planning input (true AWP PoC).

    Pass CWP ids in the order the construction team decided to execute.
    This order then drives `awp_path_of_construction` (mode 'planned') and
    should drive engineering/procurement priorities.
    """
    return _serialize(awp.set_path_of_construction(_project(), cwp_ids))


@mcp.tool()
def awp_path_of_construction() -> str:
    """Return the Path of Construction — the CWP execution sequence.

    Uses the manual sequence from `awp_set_path_of_construction` when defined
    (mode 'planned'); otherwise falls back to schedule order by earliest task
    start (mode 'derived-from-schedule'). Each CWP is enriched with earliest
    start, latest finish, total hours and critical-path exposure.
    """
    return _serialize(awp.path_of_construction(_project()))


@mcp.tool()
def awp_generate_iwps(
    cwp_id: str,
    max_hours_per_iwp: float = 500.0,
    discipline: str | None = None,
    crew: str | None = None,
) -> str:
    """Split a CWP into IWPs sized by labor hours.

    Groups the CWP's tasks in schedule order so no IWP exceeds
    `max_hours_per_iwp` (default 500h — CII sizing: 1-2 weeks for one crew).
    Stamp `discipline` and `crew` so each IWP stays single-discipline,
    single-crew. Only 'planned' IWPs are regenerated — IWPs already ready,
    released or complete are preserved untouched.
    """
    return _serialize(
        awp.generate_iwps(_project(), cwp_id, max_hours_per_iwp, discipline, crew)
    )


@mcp.tool()
def awp_release_iwp(iwp_id: str) -> str:
    """Release an IWP to the field — gated on constraint-free readiness.

    Refuses to release unless the parent CWP's last `awp_readiness_check`
    passed (WorkFace Planning golden rule: IWPs go to the field 100%
    constraint-free). Run the readiness check first.
    """
    return _serialize(awp.release_iwp(_project(), iwp_id))


@mcp.tool()
def awp_update_iwp_progress(
    iwp_id: str,
    percent_complete: int,
    earned_hours: float | None = None,
) -> str:
    """Update field progress on a released IWP (0-100%).

    At 100% the IWP is marked complete. If `earned_hours` is omitted it is
    derived from labor_hours × percent — the AWP earned-value signal.
    """
    return _serialize(
        awp.update_iwp_progress(_project(), iwp_id, percent_complete, earned_hours)
    )


@mcp.tool()
def awp_export_wpr(cwp_id: str) -> str:
    """Generate a Work Package Release — a self-contained package for field teams.

    Returns CWP metadata, requirements, full task list (names, dates, hours)
    and IWP breakdown. This is what you hand to field execution.
    """
    return _serialize(awp.export_wpr(_project(), cwp_id))


# ============================================================
# LPS — Last Planner System (Lean Construction)
#
# Five planning levels: Master -> Phase (pull plan) -> Lookahead ->
# Weekly Work Plan -> Daily. Key metric: PPC (Percent Plan Complete).
#
# State persisted in sidecar file `lps.json` (same folder as awp.json).
# ============================================================


@mcp.tool()
def lps_list_phases() -> str:
    """List all project phases defined for pull planning."""
    return _serialize(lps.list_phases(_project()))


@mcp.tool()
def lps_upsert_phase(
    phase_id: str,
    name: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Create or update a project phase.

    Args:
        phase_id: Stable identifier (e.g. "PH-01" or "fundacoes").
        name: Human-readable name (e.g. "Fundações").
        start_date: ISO 'YYYY-MM-DD' — optional.
        end_date: ISO 'YYYY-MM-DD' — optional.
    """
    return _serialize(lps.upsert_phase(_project(), phase_id, name, start_date, end_date))


@mcp.tool()
def lps_set_pull_plan(phase_id: str, task_uids: list[int]) -> str:
    """Set the pull-plan sequence for a phase.

    Pull planning works backwards from the phase milestone. Pass `task_uids`
    in execution order — first item runs first. Each UID is validated
    against the loaded project.
    """
    return _serialize(lps.set_pull_plan(_project(), phase_id, task_uids))


@mcp.tool()
def lps_get_pull_plan(phase_id: str) -> str:
    """Retrieve the pull plan for a phase."""
    return _serialize(lps.get_pull_plan(_project(), phase_id))


@mcp.tool()
def lps_annotate_pull_plan(
    phase_id: str,
    task_uid: int,
    handoff_to: str | None = None,
    conditions_of_satisfaction: str | None = None,
) -> str:
    """Annotate a pull-plan entry with handoff and conditions of satisfaction.

    Pull planning is a network of promises: record who receives the work
    (`handoff_to`) and what "done" means for the handoff
    (`conditions_of_satisfaction`), as agreed in the pull-planning session.
    """
    return _serialize(
        lps.annotate_pull_plan(
            _project(), phase_id, task_uid, handoff_to, conditions_of_satisfaction
        )
    )


@mcp.tool()
def lps_register_constraint(
    task_uid: int,
    constraint_type: str,
    description: str,
    owner: str | None = None,
    due_date: str | None = None,
) -> str:
    """Register a constraint blocking a task.

    Valid types: material | document | information | design | labor |
                 equipment | access | permit | prerequisite | other.

    Args:
        task_uid: Task UID in the loaded project.
        constraint_type: One of the valid types above.
        description: What is blocking (e.g. "aço CA-50 não chegou").
        owner: Person/team responsible for clearing (e.g. email).
        due_date: ISO date when the constraint should be cleared.
    """
    return _serialize(
        lps.register_constraint(
            _project(), task_uid, constraint_type, description, owner, due_date,
        )
    )


@mcp.tool()
def lps_clear_constraint(constraint_id: str) -> str:
    """Mark a constraint as cleared (resolved). Uses today's date."""
    return _serialize(lps.clear_constraint(_project(), constraint_id))


@mcp.tool()
def lps_list_constraints(
    task_uid: int | None = None,
    status: str | None = None,
    constraint_type: str | None = None,
) -> str:
    """List constraints, optionally filtered by task UID, status or type.

    Status values: 'open' | 'cleared'.
    """
    return _serialize(
        lps.list_constraints(_project(), task_uid, status, constraint_type)
    )


@mcp.tool()
def lps_lookahead(weeks: int = 6, from_date: str | None = None) -> str:
    """Return tasks starting within the next N weeks with their open constraints.

    Classic LPS lookahead — answers "what's coming, and what's blocking it?".
    Tasks marked as ready (no open constraints) can be committed to a WWP.
    Constraints whose due_date falls *after* the task start are flagged in
    `late_constraint_ids` — the make-ready process is running late on them.

    Args:
        weeks: Horizon in weeks (default 6).
        from_date: ISO 'YYYY-MM-DD'; defaults to today.
    """
    return _serialize(lps.lookahead(_project(), weeks, from_date))


@mcp.tool()
def lps_snapshot_lookahead(weeks: int = 6, from_date: str | None = None) -> str:
    """Persist a lookahead snapshot — enables TA/TMR reliability metrics.

    Call at every weekly lookahead review. Snapshots record which tasks were
    anticipated and which were ready, so `lps_reliability` can measure the
    health of the make-ready process over time.
    """
    return _serialize(lps.snapshot_lookahead(_project(), weeks, from_date))


@mcp.tool()
def lps_add_commitment(
    week: str,
    task_uid: int,
    committed_by: str | None = None,
    promised_hours: float | None = None,
    allow_constrained: bool = False,
) -> str:
    """Add a task commitment to a weekly work plan.

    Only constraint-free tasks may enter the WWP (shielding production).
    Tasks with open constraints are rejected unless `allow_constrained=true`
    is passed as a deliberate override — the risk is recorded on the
    commitment.

    Args:
        week: ISO week 'YYYY-Www' (e.g. '2025-W03').
        task_uid: Task UID.
        committed_by: Team or person making the commitment.
        promised_hours: Hours promised by the team for the week.
        allow_constrained: Explicit override to commit despite open constraints.
    """
    return _serialize(
        lps.add_commitment(
            _project(), week, task_uid, committed_by, promised_hours, allow_constrained
        )
    )


@mcp.tool()
def lps_mark_complete(
    week: str,
    task_uid: int,
    complete: bool,
    actual_hours: float | None = None,
    variance_reason: str | None = None,
    corrective_action: str | None = None,
) -> str:
    """Close a commitment at week end.

    If `complete=False`, a variance_reason is required. Valid reasons:
    weather | design_change | material_delay | labor_unavailable |
    equipment_breakdown | rework | permit | prerequisite_incomplete |
    scope_change | other.

    Optionally record a `corrective_action` — what will be done so the same
    variance does not repeat (closes the PDCA loop).
    """
    return _serialize(
        lps.mark_complete(
            _project(), week, task_uid, complete, actual_hours,
            variance_reason, corrective_action,
        )
    )


@mcp.tool()
def lps_log_daily(
    week: str,
    task_uid: int,
    note: str,
    day: str | None = None,
    blocked: bool = False,
) -> str:
    """Log a daily-huddle entry against a committed task (LPS level 5).

    Args:
        week: ISO week 'YYYY-Www' of the WWP.
        task_uid: Committed task the note refers to.
        note: What happened today (progress, issue, decision).
        day: ISO 'YYYY-MM-DD'; defaults to today.
        blocked: Set true if the task hit a new blocker — surfaces early.
    """
    return _serialize(lps.log_daily(_project(), week, task_uid, note, day, blocked))


@mcp.tool()
def lps_get_daily_log(week: str, day: str | None = None) -> str:
    """Get daily-huddle entries for a week, optionally filtered by day."""
    return _serialize(lps.get_daily_log(_project(), week, day))


@mcp.tool()
def lps_workable_backlog(week: str | None = None, weeks: int = 6) -> str:
    """List ready tasks not yet committed — the fallback buffer for the week.

    A healthy WWP keeps a workable backlog: sound tasks crews can pull if a
    committed task stalls. Defaults to the current ISO week.
    """
    return _serialize(lps.workable_backlog(_project(), week, weeks))


@mcp.tool()
def lps_reliability(weeks_back: int = 4) -> str:
    """Compute TA and TMR — health of the make-ready process.

    TA (Tasks Anticipated): % of committed tasks that a prior lookahead
    snapshot saw coming. TMR (Tasks Made Ready): % of tasks anticipated for
    a week that actually got committed. PPC measures promise-keeping; TA/TMR
    measure the planning system upstream. Requires `lps_snapshot_lookahead`
    at each weekly review.
    """
    return _serialize(lps.reliability(_project(), weeks_back))


@mcp.tool()
def lps_get_wwp(week: str) -> str:
    """Get the weekly work plan for a given ISO week (e.g. '2025-W03')."""
    return _serialize(lps.get_wwp(_project(), week))


@mcp.tool()
def lps_ppc(week: str | None = None, weeks_back: int = 4) -> str:
    """Compute Percent Plan Complete.

    If `week` is given, returns PPC for that week only. Otherwise returns a
    series of the last `weeks_back` weeks plus the average PPC. Variance
    reasons are aggregated so you see why commitments fail most often.
    """
    return _serialize(lps.calculate_ppc(_project(), week, weeks_back))


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
