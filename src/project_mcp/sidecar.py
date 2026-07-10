"""Sidecar storage for AWP/LPS metadata.

The `.mpp` file stays read-only. All metadata that Microsoft Project does not
represent well (CWA/CWP hierarchy, constraints, PPC history) lives in a
sidecar folder next to the project file:

    C:\\schedules\\obra-acme.mpp         ← authoritative schedule
    C:\\schedules\\obra-acme.awp\\       ← sidecar folder (created on demand)
        awp.json                          ← CWA/CWP/IWP hierarchy
        lps.json                          ← LPS: phases, constraints, WWP, PPC
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SIDECAR_VERSION = "1.0"
AWP_FILENAME = "awp.json"
LPS_FILENAME = "lps.json"


def sidecar_dir(project_path: str | Path) -> Path:
    """Return the sidecar directory path for a project file.

    Uses the same parent directory as the project file, with an `.awp` suffix
    on the stem. For `obra-acme.mpp` returns `obra-acme.awp`.
    """
    path = Path(project_path).expanduser().resolve()
    return path.with_name(f"{path.stem}.awp")


def awp_file(project_path: str | Path) -> Path:
    """Path to the AWP sidecar JSON file."""
    return sidecar_dir(project_path) / AWP_FILENAME


def ensure_sidecar_dir(project_path: str | Path) -> Path:
    """Create the sidecar directory if it does not exist. Returns the path."""
    directory = sidecar_dir(project_path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def default_awp_payload(project_path: str | Path) -> dict[str, Any]:
    """Return an empty AWP payload with metadata filled in."""
    return {
        "version": SIDECAR_VERSION,
        "project_source": str(Path(project_path).name),
        "updated_at": datetime.now(UTC).isoformat(),
        "cwa": [],
        "cwp": [],
        "iwp": [],
        "ewp": [],
        "pwp": [],
        "poc": [],
    }


def load_awp(project_path: str | Path) -> dict[str, Any]:
    """Load AWP sidecar. Returns an empty payload if the file does not exist."""
    path = awp_file(project_path)
    if not path.exists():
        return default_awp_payload(project_path)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("failed to read %s: %s — returning empty payload", path, exc)
        return default_awp_payload(project_path)
    # Forward compatibility: ensure required keys exist
    for key in ("cwa", "cwp", "iwp", "ewp", "pwp", "poc"):
        data.setdefault(key, [])
    data.setdefault("version", SIDECAR_VERSION)
    data.setdefault("project_source", Path(project_path).name)
    return data


def save_awp(project_path: str | Path, payload: dict[str, Any]) -> Path:
    """Persist the AWP payload to disk. Updates `updated_at` timestamp."""
    ensure_sidecar_dir(project_path)
    payload["updated_at"] = datetime.now(UTC).isoformat()
    payload.setdefault("version", SIDECAR_VERSION)
    path = awp_file(project_path)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    logger.info("wrote %s (%d CWA, %d CWP, %d IWP)",
                path, len(payload.get("cwa", [])),
                len(payload.get("cwp", [])), len(payload.get("iwp", [])))
    return path


def lps_file(project_path: str | Path) -> Path:
    """Path to the LPS sidecar JSON file."""
    return sidecar_dir(project_path) / LPS_FILENAME


def default_lps_payload(project_path: str | Path) -> dict[str, Any]:
    """Return an empty LPS payload with metadata filled in."""
    return {
        "version": SIDECAR_VERSION,
        "project_source": str(Path(project_path).name),
        "updated_at": datetime.now(UTC).isoformat(),
        "phases": [],
        "constraints": [],
        "weekly_work_plans": [],
        "lookahead_snapshots": [],
    }


def load_lps(project_path: str | Path) -> dict[str, Any]:
    """Load LPS sidecar. Returns an empty payload if the file does not exist."""
    path = lps_file(project_path)
    if not path.exists():
        return default_lps_payload(project_path)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("failed to read %s: %s — returning empty payload", path, exc)
        return default_lps_payload(project_path)
    for key in ("phases", "constraints", "weekly_work_plans", "lookahead_snapshots"):
        data.setdefault(key, [])
    data.setdefault("version", SIDECAR_VERSION)
    data.setdefault("project_source", Path(project_path).name)
    return data


def save_lps(project_path: str | Path, payload: dict[str, Any]) -> Path:
    """Persist the LPS payload to disk. Updates `updated_at` timestamp."""
    ensure_sidecar_dir(project_path)
    payload["updated_at"] = datetime.now(UTC).isoformat()
    payload.setdefault("version", SIDECAR_VERSION)
    path = lps_file(project_path)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    logger.info("wrote %s (%d phases, %d constraints, %d WWPs)",
                path, len(payload.get("phases", [])),
                len(payload.get("constraints", [])),
                len(payload.get("weekly_work_plans", [])))
    return path
