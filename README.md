# lean-planning-mcp

[![CI](https://github.com/jeffmodeler/lean-planning-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jeffmodeler/lean-planning-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

> 🇺🇸 English · 🇧🇷 [Versão em português](README.pt-BR.md)

Model Context Protocol (MCP) server that exposes project schedules —
**Microsoft Project, Primavera P6 and Synchro Scheduler** — to LLM clients
like Claude Desktop and Claude Code. Reads schedules, resources, dependencies,
critical-path data, and baseline variance — and adds **AWP** (Advanced Work
Packaging, CII) and **LPS** (Last Planner System, Lean) layers for
work-package planning, constraints, weekly commitments and PPC tracking.
All local, no cloud calls, no scheduling-tool license required.

## Why

Construction, engineering, and BIM workflows live in Microsoft Project
schedules. This server lets your LLM:

- Inspect a project schedule and answer questions about it (deadlines,
  critical path, resource overload).
- Cross-reference task data with quantities from BIM models or with
  cost data from Power BI dashboards.
- Generate JSON exports for downstream automation (dashboards, reports,
  ETL pipelines).

It's read-only by design. Project edits stay where they belong: in
Microsoft Project itself.

## Requirements

- Python 3.11+
- An MCP-compatible client (Claude Desktop, Claude Code, etc.)
- For `.xml` (MSPDI): no extra dependencies
- For every other format: the optional `[mpp]` extra (requires a JVM via the
  `mpxj` package)

## Supported formats

| Format | Extension | Requires `[mpp]` extra |
|---|---|---|
| Microsoft Project MSPDI XML | `.xml` | No |
| Microsoft Project native | `.mpp`, `.mpx` | Yes |
| Primavera P6 export | `.xer` | Yes |
| Primavera P6 XML (PMXML) | `.pmxml`, `.xml`* | Yes |
| Synchro Scheduler | `.sp` | Yes |
| Asta Powerproject | `.pp` | Yes |

\* A `.xml` file that is not MSPDI is automatically retried through the
universal reader (mpxj), so P6 XML exports saved as `.xml` also load.

Synchro note: mpxj reads Synchro Scheduler `.sp` files up to the versions it
supports; for recent Synchro 4D Pro projects, exporting XER or MS Project XML
from Synchro is the most reliable path. Once loaded, **all 49 tools —
including the AWP and LPS layers — work identically regardless of source
format**, since they operate on task UIDs.

## Installation

### Option A — `uv` (recommended)

```bash
git clone https://github.com/jeffmodeler/lean-planning-mcp.git
cd lean-planning-mcp
uv sync
```

### Option B — `pip`

```bash
pip install git+https://github.com/jeffmodeler/lean-planning-mcp.git
```

For `.mpp` support:

```bash
uv sync --extra mpp
# or
pip install "lean-planning-mcp[mpp] @ git+https://github.com/jeffmodeler/lean-planning-mcp.git"
```

## Claude Desktop integration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "lean-planning-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\lean-planning-mcp",
        "run",
        "lean-planning-mcp"
      ]
    }
  }
}
```

Restart Claude Desktop. The 49 tools become available in any conversation
(14 core MS Project + 17 AWP + 18 LPS).

## Tools

| Tool | Purpose |
|---|---|
| `load_project` | Load a schedule into memory — MSPDI `.xml`, `.mpp`, P6 `.xer`/`.pmxml`, Synchro `.sp`, Asta `.pp` |
| `open_in_ms_project` | Open the loaded (or a given) project file in Microsoft Project via the OS default association |
| `project_info` | Title, author, schedule window, currency, aggregate counts |
| `list_tasks` | Filter tasks by type, criticality, name substring, top N |
| `get_task` | Full record of a single task by UID, ID, or name |
| `list_resources` | Resources, optionally filtered by type or overallocation |
| `get_resource_assignments` | Assignments for one or all resources |
| `find_overallocated_resources` | Resources flagged as overallocated |
| `get_critical_path` | Tasks on the critical path, sorted by start date |
| `get_predecessors_successors` | Dependency network for a task |
| `get_baseline_variance` | Current vs baseline date and duration comparison |
| `get_gantt_data` | Tasks formatted for Gantt-chart libraries |
| `export_to_json` | Full project export to JSON file (or inline) |
| `generate_pbip_dashboard` | Generate a Power BI Project (.pbip) and open it in Power BI Desktop |

## Exporting `.mpp` to MSPDI XML

If you don't want to install Java for the optional `mpp` extra, export your
schedule from Microsoft Project as XML:

1. Open the `.mpp` file in Microsoft Project.
2. **File → Save As → Save as Type → XML Format (\*.xml)**.
3. Point `load_project` at the resulting `.xml`.

The XML format is the official Microsoft Project Data Interchange (MSPDI)
schema and contains tasks, resources, assignments, predecessors, baseline,
and most of the project metadata.

## Example prompts

After loading a project, ask Claude:

```
Load the project at C:\schedules\obra-acme.xml
Give me the critical path with total duration in days.
Which resources are overallocated and by how much?
List the 5 tasks with the largest baseline variance.
Export the full project to C:\reports\obra-acme.json
```

## Two layers, deliberately separate

AWP and LPS live in the same server but operate as **independent layers** on
top of the same schedule. They persist to separate sidecar files (`awp.json`
and `lps.json`), share no state, and neither depends on the other:

- **AWP** organizes *scope*: what gets built, where, and in which package
  (CWA → CWP → IWP, fed by engineering and procurement packages).
- **LPS** organizes *commitment flow*: what the crews promise week by week,
  what blocks them, and how reliable the planning system is.

You can use either layer alone, or both side by side on the same `.mpp`.
They are complementary methodologies — AWP answers "is the work package
ready to be released?", LPS answers "will the crew actually do it this
week?" — but in this server they are operated independently, by design.

## AWP — Advanced Work Packaging

Construction Industry Institute (CII RT-272 / RT-319) methodology. Breaks
execution into aligned packages across engineering, procurement and field:

```
CWA (Construction Work Area) → CWP (Construction Work Package)
                                     ↓
                               IWP (Installation Work Package)

EWP (Engineering Work Package) ─┐
                                ├→ gate CWP readiness
PWP (Procurement Work Package) ─┘
```

Focus: path of construction as a *planning input* + constraint-free release.
A CWP is only ready when its manual requirements are available, all linked
EWPs are `issued` and all linked PWPs are `delivered`. IWPs can only be
**released to the field after a passing readiness check** — the WorkFace
Planning golden rule.

### AWP tools

| Tool | Purpose |
|---|---|
| `awp_list_cwa` | List Construction Work Areas |
| `awp_upsert_cwa` | Create or update a CWA |
| `awp_list_cwp` | List CWPs with `task_count`, `total_hours`, `any_critical` |
| `awp_upsert_cwp` | Create or update a CWP (status: planned/ready/in-progress/complete/on-hold) |
| `awp_assign_task_to_cwp` | Link a task UID to a CWP (moves it if already elsewhere) |
| `awp_set_cwp_requirements` | Set CWP requirements (materials, documents, access) |
| `awp_upsert_ewp` | Create/update an Engineering Work Package (planned/in-progress/issued) |
| `awp_list_ewp` | List EWPs, optionally by CWP |
| `awp_upsert_pwp` | Create/update a Procurement Work Package (planned/ordered/delivered) |
| `awp_list_pwp` | List PWPs, optionally by CWP |
| `awp_readiness_check` | CWP readiness: requirements + EWPs issued + PWPs delivered. Gates IWP release |
| `awp_set_path_of_construction` | Define the PoC as a planning input (construction team's decided order) |
| `awp_path_of_construction` | Return the PoC — manual order if set, else derived from schedule |
| `awp_generate_iwps` | Split a CWP into IWPs (default 500h — CII crew-week sizing; stamps discipline/crew; preserves released IWPs) |
| `awp_release_iwp` | Release an IWP to the field — **blocked unless the CWP passed its readiness check** |
| `awp_update_iwp_progress` | Field progress 0-100% with earned hours; 100% marks complete |
| `awp_export_wpr` | Generate a Work Package Release — self-contained JSON for field teams |

## LPS — Last Planner System

Lean Construction method with five planning levels — all implemented:

```
Master → Phase (pull plan) → Lookahead (N weeks, clears constraints)
                              → WWP (Weekly Work Plan) → Daily huddle
```

**Core rule enforced (shielding production, Ballard 1998):** only
constraint-free tasks enter the Weekly Work Plan. `lps_add_commitment`
rejects tasks with open constraints unless explicitly overridden — and the
override is recorded on the commitment as a risk.

**Metrics**: **PPC** (Percent Plan Complete — promises kept), plus **TA**
(Tasks Anticipated) and **TMR** (Tasks Made Ready) computed from lookahead
snapshots — these measure whether the make-ready process upstream is healthy,
not just last week's reliability.

### LPS tools

| Tool | Purpose |
|---|---|
| `lps_list_phases` | List project phases |
| `lps_upsert_phase` | Create or update a phase (with start/end dates) |
| `lps_set_pull_plan` | Set execution sequence (pull planning) with task UIDs |
| `lps_get_pull_plan` | Retrieve a phase's pull plan |
| `lps_annotate_pull_plan` | Record handoff + conditions of satisfaction on a pull-plan entry |
| `lps_register_constraint` | Register a constraint (material/document/labor/equipment/access/permit/…) |
| `lps_clear_constraint` | Mark a constraint as resolved |
| `lps_list_constraints` | List with filters by task, status, type |
| `lps_lookahead` | N-week horizon with ready/blocked tasks + late-constraint alerts (`due_date` after task start) |
| `lps_snapshot_lookahead` | Persist a lookahead snapshot — feeds TA/TMR. Call at every weekly review |
| `lps_add_commitment` | Add a commitment — **blocks tasks with open constraints** (override: `allow_constrained`) |
| `lps_mark_complete` | Close a commitment with `variance_reason` + optional `corrective_action` (PDCA) |
| `lps_log_daily` | Daily-huddle entry against a committed task (level 5) |
| `lps_get_daily_log` | Read daily-huddle entries for a week |
| `lps_get_wwp` | Read a weekly work plan |
| `lps_workable_backlog` | Ready-but-uncommitted tasks — the fallback buffer for the week |
| `lps_reliability` | TA / TMR series — health of the make-ready process |
| `lps_ppc` | Compute PPC for a single week or a series of the last N weeks |

**Constraint types**: material, document, information, design, labor,
equipment, access, permit, prerequisite, other.

**Variance reasons**: weather, design_change, material_delay, labor_unavailable,
equipment_breakdown, rework, permit, prerequisite_incomplete, scope_change, other.

## Sidecar storage

The `.mpp`/`.xml` file remains authoritative (read-only preserved). Next to
the project file, an `<name>.awp/` folder holds metadata that Microsoft
Project does not represent well:

```
C:\schedules\
├── obra-acme.mpp              ← authoritative schedule (never modified)
└── obra-acme.awp/             ← sidecar folder, created on demand
    ├── awp.json               ← CWA / CWP / IWP / EWP / PWP + path of construction
    └── lps.json               ← phases, pull plans, constraints, WWPs, snapshots
```

Every write updates `updated_at` (ISO 8601 UTC) in the JSON.

## Development

```bash
uv sync --extra dev
uv run pytest -v
uv run ruff check src tests
```

## License

MIT — see [LICENSE](LICENSE).
