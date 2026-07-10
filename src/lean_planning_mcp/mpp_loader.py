"""Native ``.mpp`` loader built on mpxj (requires Java + JPype1).

``server.py`` imports this module lazily for the ``.mpp`` branch of
``load_project``. It bridges Microsoft Project binary files into the *same*
``Project``/``Task``/``Resource``/``Assignment`` dataclasses produced by the
MSPDI XML parser (``mspdi.py``), so every downstream tool stays format-agnostic.

Notes
-----
* ``import mpxj`` registers the bundled mpxj jars on the JPype classpath and so
  must run **before** the JVM is started.
* JPype locates the JVM via ``JAVA_HOME``; on macOS/Homebrew we fall back to the
  ``openjdk`` formula prefix if the caller did not set it.
"""
from __future__ import annotations

import os
from pathlib import Path

import jpype

from lean_planning_mcp.mspdi import Assignment, Project, Resource, Task

# Homebrew `openjdk` formula default (used only when JAVA_HOME is unset).
_DEFAULT_MACOS_JAVA = "/opt/homebrew/opt/openjdk"

# mpxj RelationType -> MSPDI 2-letter code, to match mspdi.py output.
_RELATION_CODES = {
    "FINISH_FINISH": "FF",
    "FINISH_START": "FS",
    "START_FINISH": "SF",
    "START_START": "SS",
}

_RESOURCE_TYPES = {"WORK": "Work", "MATERIAL": "Material", "COST": "Cost"}


def _ensure_jvm() -> None:
    """Start the JVM once, with the mpxj jars on the classpath."""
    if jpype.isJVMStarted():
        return
    if not os.environ.get("JAVA_HOME") and os.path.isdir(_DEFAULT_MACOS_JAVA):
        os.environ["JAVA_HOME"] = _DEFAULT_MACOS_JAVA
    import mpxj  # noqa: F401  -- side effect: addClassPath for the bundled jars
    jpype.startJVM()


def _iso(value) -> str | None:
    """java.time.LocalDateTime (or null) -> ISO string."""
    return None if value is None else str(value)


def _str(value) -> str | None:
    """java.lang.String (or null) -> native Python str, so downstream string
    ops and JSON serialization behave. JPype does not always auto-convert."""
    return None if value is None else str(value)


def _int(value, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _bool(value) -> bool:
    return bool(value) if value is not None else False


def parse_file(path: str | Path) -> Project:
    """Read a native ``.mpp`` (or anything mpxj's UniversalProjectReader handles)
    and return a populated :class:`~lean_planning_mcp.mspdi.Project`."""
    _ensure_jvm()
    from org.mpxj import TimeUnit
    from org.mpxj.reader import UniversalProjectReader

    file_path = Path(path)
    pf = UniversalProjectReader().read(str(file_path))
    if pf is None:
        raise ValueError(f"mpxj could not parse the file (unrecognised format): {path}")

    props = pf.getProjectProperties()

    def dur_hours(duration) -> float:
        """mpxj Duration -> hours (converting units against project calendar)."""
        if duration is None:
            return 0.0
        try:
            return float(duration.convertUnits(TimeUnit.HOURS, props).getDuration())
        except Exception:
            return _float(duration.getDuration() if duration is not None else None)

    project = Project(
        title=_str(props.getProjectTitle()),
        name=_str(props.getName()),
        author=_str(props.getAuthor()),
        company=_str(props.getCompany()),
        subject=_str(props.getSubject()),
        category=_str(props.getCategory()),
        start_date=_iso(props.getStartDate()),
        finish_date=_iso(props.getFinishDate()),
        currency_code=_str(props.getCurrencyCode()),
        currency_symbol=_str(props.getCurrencySymbol()),
        schema_version=str(props.getMppFileType()) if props.getMppFileType() is not None else None,
        source_path=str(file_path.resolve()),
    )

    for t in pf.getTasks():
        try:
            if _bool(t.getNull()):
                continue
            project.tasks.append(_parse_task(t, dur_hours))
        except Exception:
            # Never let one malformed task abort the whole load.
            continue

    for r in pf.getResources():
        try:
            if r.getUniqueID() is None:
                continue
            project.resources.append(_parse_resource(r, dur_hours))
        except Exception:
            continue

    for ra in pf.getResourceAssignments():
        try:
            project.assignments.append(_parse_assignment(ra, dur_hours))
        except Exception:
            continue

    return project


def _parse_task(t, dur_hours) -> Task:
    predecessors = []
    try:
        for rel in t.getPredecessors():
            try:
                pred = rel.getPredecessorTask()
                # mpxj RelationType already prints the 2-letter MSPDI code (FS/FF/SF/SS).
                code = str(rel.getType()) if rel.getType() is not None else "FS"
                predecessors.append({
                    "predecessor_uid": _int(pred.getUniqueID()) if pred is not None else None,
                    "link_type": _RELATION_CODES.get(code, code),
                    "lag_hours": dur_hours(rel.getLag()),
                    "crossproject": False,
                })
            except Exception:
                continue
    except Exception:
        pass

    priority = t.getPriority()
    return Task(
        uid=_int(t.getUniqueID()),
        id=_int(t.getID()),
        name=_str(t.getName()),
        outline_level=_int(t.getOutlineLevel()),
        outline_number=_str(t.getOutlineNumber()),
        is_summary=_bool(t.getSummary()),
        is_milestone=_bool(t.getMilestone()),
        is_critical=_bool(t.getCritical()),
        is_null=False,
        start=_iso(t.getStart()),
        finish=_iso(t.getFinish()),
        duration_hours=dur_hours(t.getDuration()),
        work_hours=dur_hours(t.getWork()),
        percent_complete=_int(t.getPercentageComplete()),
        priority=_int(priority.getValue(), 500) if priority is not None else 500,
        notes=_str(t.getNotes()) or None,
        predecessors=predecessors,
        baseline_start=_iso(t.getBaselineStart()),
        baseline_finish=_iso(t.getBaselineFinish()),
        baseline_duration_hours=dur_hours(t.getBaselineDuration()),
        total_slack_hours=dur_hours(t.getTotalSlack()),
    )


def _parse_resource(r, dur_hours) -> Resource:
    rtype = r.getType()
    rate = r.getStandardRate()
    return Resource(
        uid=_int(r.getUniqueID(), -1),
        id=_int(r.getID(), -1),
        name=_str(r.getName()),
        type=_RESOURCE_TYPES.get(str(rtype).upper(), "Work") if rtype is not None else "Work",
        initials=_str(r.getInitials()),
        max_units=_float(r.getMaxUnits(), 1.0),
        standard_rate=_float(rate.getAmount()) if rate is not None else 0.0,
        overallocated=_bool(r.getOverAllocated()),
        work_hours=dur_hours(r.getWork()),
    )


def _parse_assignment(ra, dur_hours) -> Assignment:
    return Assignment(
        task_uid=_int(ra.getTaskUniqueID()),
        resource_uid=_int(ra.getResourceUniqueID()),
        units=_float(ra.getUnits(), 1.0),
        work_hours=dur_hours(ra.getWork()),
        cost=_float(ra.getCost()),
        start=_iso(ra.getStart()),
        finish=_iso(ra.getFinish()),
    )
