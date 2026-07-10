# Changelog

All notable changes to this project follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Corrected all repo URLs (CI badge, `git clone`/`pip install` snippets,
  `Homepage`/`Issues` in `pyproject.toml`) to point to the actual repo name
  `ms_project-mcp` instead of the stale `project-mcp`.
- Corrected tool count in README (EN/PT-BR): 36 tools, not 35 — `14` core
  tools, not `13`. Added the missing `open_in_ms_project` row to the tools
  table in both README files.
- Updated the GitHub repository description to reflect the real tool count
  and drop the outdated "read-only" framing (several AWP/LPS tools write to
  the sidecar, and `generate_pbip_dashboard` writes files and can launch
  Power BI Desktop).

### Added

- Test coverage for `server.py` (0% → 92%) and `pbip_writer.py` (0% → 94%),
  raising total project coverage from 51% to 91%. Covers all core MSPDI
  tools, the full AWP and LPS tool-wrapper flows, and the PBIP folder/file
  structure written by `generate_pbip_dashboard`.
- `pytest-cov` added to the `dev` optional-dependency group; CI now reports
  coverage on every run.

## [0.2.0] - 2026-04-20

### Added

- New tool `generate_pbip_dashboard` that materializes the loaded project as a
  Power BI Project (PBIP) folder with full semantic model (3 tables, 10 DAX
  measures, 2 relationships, pt-BR culture) and a blank report page.
- Module `pbip_writer` with `PbipWriter` class for generating TMDL and PBIR
  artifacts. No external dependencies.
- Option `open_in_power_bi=True` (default) to auto-launch Power BI Desktop on
  the generated `.pbip` file.
- Companion Claude skill `powerbi-project-dashboard.md` (deployed separately
  to `~/.claude/skills/`) that teaches Claude when and how to use the tool.

### Changed

- Tool count: 12 → 13.

## [0.1.0] - 2026-04-20

### Added

- Initial release with MSPDI XML parser (no Java required).
- 12 read-only MCP tools:
  - `load_project` — load `.xml` (MSPDI) or `.mpp` (with optional `mpp` extra).
  - `project_info` — metadata and aggregate counts.
  - `list_tasks` — filter by type, criticality, name substring, top N.
  - `get_task` — single-task lookup by UID, ID, or name.
  - `list_resources` — filter by overallocation and type.
  - `get_resource_assignments` — assignments by resource.
  - `find_overallocated_resources` — overallocation report.
  - `get_critical_path` — critical-path tasks chronologically.
  - `get_predecessors_successors` — task dependency network.
  - `get_baseline_variance` — current vs baseline comparison.
  - `get_gantt_data` — Gantt-ready output with hierarchy and dependencies.
  - `export_to_json` — full project export.
- Pytest suite covering parser metadata, hierarchy, predecessors, baseline,
  overallocation, costs, and ISO 8601 duration handling.
- GitHub Actions CI running `ruff` and `pytest` on Python 3.11 and 3.12.
