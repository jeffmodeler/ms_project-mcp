# Changelog

All notable changes to this project follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — AWP conceptual gaps closed (CII RT-272/RT-319)

- **EWP/PWP layer** (`awp_upsert_ewp`, `awp_list_ewp`, `awp_upsert_pwp`,
  `awp_list_pwp`): Engineering and Procurement Work Packages linked to CWPs,
  completing the E-P-C alignment. `awp_readiness_check` now also requires all
  linked EWPs `issued` and PWPs `delivered`, and stores the result on the CWP.
- **Constraint-free release gate** (`awp_release_iwp`): IWPs can only be
  released to the field after the parent CWP passes a readiness check —
  the WorkFace Planning golden rule.
- **IWP field progress** (`awp_update_iwp_progress`): 0-100% with earned
  hours (AWP earned-value signal); 100% marks the IWP complete. Requires the
  IWP to be released first.
- **Manual Path of Construction** (`awp_set_path_of_construction`): the PoC
  is now a planning input decided by the construction team;
  `awp_path_of_construction` reports `mode: planned` vs
  `derived-from-schedule`.

### Added — LPS conceptual gaps closed (Ballard / Lean Construction)

- **Shielding production**: `lps_add_commitment` now rejects tasks with open
  constraints (override via `allow_constrained=true`, recorded as risk on the
  commitment). ISO-week format is validated.
- **TA/TMR reliability metrics** (`lps_snapshot_lookahead`,
  `lps_reliability`): lookahead snapshots enable Tasks Anticipated and Tasks
  Made Ready series — measuring make-ready health, not just weekly PPC.
- **Late-constraint alert**: `lps_lookahead` flags constraints whose
  `due_date` falls after the task start (`late_constraint_ids`).
- **Daily huddle (level 5)** (`lps_log_daily`, `lps_get_daily_log`): daily
  entries against committed tasks with early blocker surfacing.
- **Workable backlog** (`lps_workable_backlog`): ready-but-uncommitted tasks
  as the week's fallback buffer.
- **Pull-plan handoffs** (`lps_annotate_pull_plan`): handoff recipient and
  conditions of satisfaction per pull-plan entry.
- **Corrective action**: `lps_mark_complete` accepts `corrective_action`,
  closing the PDCA loop on variances.

### Added — multi-platform loading

- `load_project` now routes Primavera P6 (`.xer`, `.pmxml`), Synchro
  Scheduler (`.sp`), Asta Powerproject (`.pp`) and `.mpx` to the mpxj
  universal reader (requires the `[mpp]` extra). Previously these extensions
  were rejected even though the loader could already read them.
- `.xml` files that are not MSPDI (e.g. P6 PMXML exports) are automatically
  retried through the universal reader instead of silently loading as an
  empty project.
- README: supported-formats table (EN/PT-BR). All 49 tools, including the
  AWP/LPS layers, work identically regardless of the source format.

### Changed

- **Renamed project `project-mcp` → `msproject-lean-mcp` → `lean-planning-mcp`.**
  The first rename reflected the Lean layers; the second landed with
  multi-platform loading (Primavera P6, Synchro, Asta) making the
  "msproject" prefix too narrow. Renames the GitHub repo (all old URLs
  redirect), the PyPI package name, the Python package
  (`project_mcp` → `lean_planning_mcp`), the console script, and the
  FastMCP server name. Update your `claude_desktop_config.json` entry
  accordingly.
- `awp_generate_iwps`: default cap raised from 40h to 500h (CII sizing — 1-2
  weeks for one crew); stamps `discipline`/`crew` on IWPs; **no longer
  destroys released/complete IWPs on regeneration** (only `planned` IWPs are
  regrouped; locked tasks are excluded).
- Tool count: 36 → 49 (14 core + 17 AWP + 18 LPS).
- README (EN/PT-BR): documented that AWP and LPS are deliberately separate
  layers over the same schedule (separate sidecars, no shared state).

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
