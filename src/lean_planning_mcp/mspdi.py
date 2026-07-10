"""MSPDI (Microsoft Project Data Interchange) XML parser.

MSPDI is the XML format Microsoft Project exports natively via
File → Save As → Save as Type → XML Format (*.xml).

This parser has no external dependencies beyond the Python standard library.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

NS = "http://schemas.microsoft.com/project"
NS_MAP = {"p": NS}

_ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)

LINK_TYPES = {"0": "FF", "1": "FS", "2": "SF", "3": "SS"}
RESOURCE_TYPES = {"0": "Work", "1": "Material", "2": "Cost"}


def _t(element: ET.Element | None, tag: str) -> str | None:
    """Get text of child element by tag (namespaced)."""
    if element is None:
        return None
    child = element.find(f"p:{tag}", NS_MAP)
    return child.text if child is not None and child.text else None


def _int(element: ET.Element | None, tag: str, default: int = 0) -> int:
    value = _t(element, tag)
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _float(element: ET.Element | None, tag: str, default: float = 0.0) -> float:
    value = _t(element, tag)
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _bool(element: ET.Element | None, tag: str) -> bool:
    return _t(element, tag) == "1"


def iso_duration_to_hours(duration: str | None) -> float:
    """Convert an ISO 8601 duration (e.g. 'PT8H30M') to hours. Returns 0 on failure."""
    if not duration:
        return 0.0
    match = _ISO_DURATION.match(duration)
    if not match:
        return 0.0
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return days * 24 + hours + minutes / 60 + seconds / 3600


@dataclass
class Task:
    uid: int
    id: int
    name: str | None
    outline_level: int = 0
    outline_number: str | None = None
    is_summary: bool = False
    is_milestone: bool = False
    is_critical: bool = False
    is_null: bool = False
    start: str | None = None
    finish: str | None = None
    duration_hours: float = 0.0
    work_hours: float = 0.0
    percent_complete: int = 0
    priority: int = 500
    notes: str | None = None
    predecessors: list[dict[str, Any]] = field(default_factory=list)
    baseline_start: str | None = None
    baseline_finish: str | None = None
    baseline_duration_hours: float = 0.0
    total_slack_hours: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "id": self.id,
            "name": self.name,
            "outline_level": self.outline_level,
            "outline_number": self.outline_number,
            "is_summary": self.is_summary,
            "is_milestone": self.is_milestone,
            "is_critical": self.is_critical,
            "start": self.start,
            "finish": self.finish,
            "duration_hours": round(self.duration_hours, 2),
            "work_hours": round(self.work_hours, 2),
            "percent_complete": self.percent_complete,
            "priority": self.priority,
            "predecessors": self.predecessors,
            "baseline_start": self.baseline_start,
            "baseline_finish": self.baseline_finish,
            "baseline_duration_hours": round(self.baseline_duration_hours, 2),
            "total_slack_hours": round(self.total_slack_hours, 2),
            "notes": self.notes,
        }


@dataclass
class Resource:
    uid: int
    id: int
    name: str | None
    type: str = "Work"
    initials: str | None = None
    max_units: float = 1.0
    standard_rate: float = 0.0
    overallocated: bool = False
    work_hours: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "initials": self.initials,
            "max_units": self.max_units,
            "standard_rate": self.standard_rate,
            "overallocated": self.overallocated,
            "work_hours": round(self.work_hours, 2),
        }


@dataclass
class Assignment:
    task_uid: int
    resource_uid: int
    units: float
    work_hours: float
    cost: float
    start: str | None
    finish: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_uid": self.task_uid,
            "resource_uid": self.resource_uid,
            "units": self.units,
            "work_hours": round(self.work_hours, 2),
            "cost": self.cost,
            "start": self.start,
            "finish": self.finish,
        }


@dataclass
class Project:
    """Parsed MSPDI project."""
    title: str | None = None
    name: str | None = None
    author: str | None = None
    company: str | None = None
    subject: str | None = None
    category: str | None = None
    start_date: str | None = None
    finish_date: str | None = None
    currency_code: str | None = None
    currency_symbol: str | None = None
    schema_version: str | None = None
    tasks: list[Task] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)
    source_path: str | None = None

    def task_by_uid(self, uid: int) -> Task | None:
        return next((t for t in self.tasks if t.uid == uid), None)

    def task_by_id(self, tid: int) -> Task | None:
        return next((t for t in self.tasks if t.id == tid), None)

    def task_by_name(self, name: str) -> Task | None:
        return next((t for t in self.tasks if t.name == name), None)

    def resource_by_uid(self, uid: int) -> Resource | None:
        return next((r for r in self.resources if r.uid == uid), None)

    def resource_by_name(self, name: str) -> Resource | None:
        return next((r for r in self.resources if r.name == name), None)


def parse_file(path: str | Path) -> Project:
    """Parse an MSPDI XML file and return a Project."""
    path = Path(path)
    tree = ET.parse(path)
    root = tree.getroot()
    project = _parse_root(root)
    project.source_path = str(path.resolve())
    return project


def _parse_root(root: ET.Element) -> Project:
    project = Project(
        title=_t(root, "Title"),
        name=_t(root, "Name"),
        author=_t(root, "Author"),
        company=_t(root, "Company"),
        subject=_t(root, "Subject"),
        category=_t(root, "Category"),
        start_date=_t(root, "StartDate"),
        finish_date=_t(root, "FinishDate"),
        currency_code=_t(root, "CurrencyCode"),
        currency_symbol=_t(root, "CurrencySymbol"),
        schema_version=_t(root, "SaveVersion"),
    )

    tasks_elem = root.find("p:Tasks", NS_MAP)
    if tasks_elem is not None:
        for t_elem in tasks_elem.findall("p:Task", NS_MAP):
            task = _parse_task(t_elem)
            if not task.is_null:
                project.tasks.append(task)

    resources_elem = root.find("p:Resources", NS_MAP)
    if resources_elem is not None:
        for r_elem in resources_elem.findall("p:Resource", NS_MAP):
            resource = _parse_resource(r_elem)
            if resource.uid >= 0:
                project.resources.append(resource)

    assignments_elem = root.find("p:Assignments", NS_MAP)
    if assignments_elem is not None:
        for a_elem in assignments_elem.findall("p:Assignment", NS_MAP):
            assignment = _parse_assignment(a_elem)
            project.assignments.append(assignment)

    return project


def _parse_task(elem: ET.Element) -> Task:
    predecessors = []
    for link in elem.findall("p:PredecessorLink", NS_MAP):
        predecessors.append({
            "predecessor_uid": _int(link, "PredecessorUID"),
            "link_type": LINK_TYPES.get(_t(link, "Type") or "1", "FS"),
            "lag_hours": iso_duration_to_hours(_t(link, "LinkLag")),
            "crossproject": _bool(link, "CrossProject"),
        })

    baseline_elem = elem.find("p:Baseline", NS_MAP)

    return Task(
        uid=_int(elem, "UID"),
        id=_int(elem, "ID"),
        name=_t(elem, "Name"),
        outline_level=_int(elem, "OutlineLevel"),
        outline_number=_t(elem, "OutlineNumber"),
        is_summary=_bool(elem, "Summary"),
        is_milestone=_bool(elem, "Milestone"),
        is_critical=_bool(elem, "Critical"),
        is_null=_bool(elem, "IsNull"),
        start=_t(elem, "Start"),
        finish=_t(elem, "Finish"),
        duration_hours=iso_duration_to_hours(_t(elem, "Duration")),
        work_hours=iso_duration_to_hours(_t(elem, "Work")),
        percent_complete=_int(elem, "PercentComplete"),
        priority=_int(elem, "Priority", 500),
        notes=_t(elem, "Notes"),
        predecessors=predecessors,
        baseline_start=_t(baseline_elem, "Start") if baseline_elem is not None else None,
        baseline_finish=_t(baseline_elem, "Finish") if baseline_elem is not None else None,
        baseline_duration_hours=iso_duration_to_hours(
            _t(baseline_elem, "Duration") if baseline_elem is not None else None
        ),
        total_slack_hours=iso_duration_to_hours(_t(elem, "TotalSlack")),
    )


def _parse_resource(elem: ET.Element) -> Resource:
    return Resource(
        uid=_int(elem, "UID", -1),
        id=_int(elem, "ID", -1),
        name=_t(elem, "Name"),
        type=RESOURCE_TYPES.get(_t(elem, "Type") or "0", "Work"),
        initials=_t(elem, "Initials"),
        max_units=_float(elem, "MaxUnits", 1.0),
        standard_rate=_float(elem, "StandardRate"),
        overallocated=_bool(elem, "OverAllocated"),
        work_hours=iso_duration_to_hours(_t(elem, "Work")),
    )


def _parse_assignment(elem: ET.Element) -> Assignment:
    return Assignment(
        task_uid=_int(elem, "TaskUID"),
        resource_uid=_int(elem, "ResourceUID"),
        units=_float(elem, "Units", 1.0),
        work_hours=iso_duration_to_hours(_t(elem, "Work")),
        cost=_float(elem, "Cost"),
        start=_t(elem, "Start"),
        finish=_t(elem, "Finish"),
    )
