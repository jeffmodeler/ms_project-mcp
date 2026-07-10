"""Generate a Power BI Project (PBIP) from a parsed MSPDI Project.

The output is a complete PBIP folder structure (SemanticModel + Report) that
Power BI Desktop can open natively. The SemanticModel is populated with:
- Three tables (Tarefas, Recursos, Atribuicoes) with inline M-query partitions
- Ten standard DAX measures for a construction dashboard
- Two relationships (Atribuicoes -> Tarefas, Atribuicoes -> Recursos)
- A pt-BR culture file

The Report folder ships as a minimal blank report — the user adds visuals
afterwards inside Power BI Desktop.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from lean_planning_mcp.mspdi import Project


def _tmdl_escape(value: str | None) -> str:
    """Escape a TMDL object name. Wraps in single quotes if needed."""
    if value is None:
        return "''"
    s = str(value).replace("'", "''")
    if re.search(r"[\s\.\=:']", s):
        return f"'{s}'"
    return s


def _tmdl_string(value: str | None) -> str:
    """Escape a TMDL property value (double-quoted)."""
    if value is None:
        return '""'
    s = str(value).replace('"', '""')
    return f'"{s}"'


def _m_escape(value: str | None) -> str:
    """Escape a string literal for Power Query M."""
    if value is None:
        return '""'
    s = str(value).replace('"', '""')
    return f'"{s}"'


def _m_date(iso_datetime: str | None) -> str:
    """Convert an ISO 8601 datetime string to a Power Query #date literal."""
    if not iso_datetime:
        return "null"
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso_datetime)
    if not match:
        return "null"
    y, m, d = match.groups()
    return f"#date({int(y)},{int(m)},{int(d)})"


def _new_lineage_tag() -> str:
    return str(uuid.uuid4())


class PbipWriter:
    """Materialize a Project into a PBIP folder structure."""

    def __init__(self, project: Project, output_dir: Path, project_name: str = "ProjectDashboard"):
        self.project = project
        self.output_dir = Path(output_dir)
        self.project_name = project_name
        self.sm_dir = self.output_dir / f"{project_name}.SemanticModel"
        self.report_dir = self.output_dir / f"{project_name}.Report"

    def write(self) -> dict[str, Any]:
        """Generate the full PBIP project. Returns metadata about what was written."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.sm_dir.mkdir(parents=True, exist_ok=True)
        (self.sm_dir / "definition").mkdir(parents=True, exist_ok=True)
        (self.sm_dir / "definition" / "tables").mkdir(parents=True, exist_ok=True)
        (self.sm_dir / "definition" / "cultures").mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        (self.report_dir / "definition").mkdir(parents=True, exist_ok=True)
        (self.report_dir / "definition" / "pages").mkdir(parents=True, exist_ok=True)

        self._write_pbip_root()
        self._write_gitignore()
        self._write_semantic_model()
        self._write_report()

        return {
            "output_dir": str(self.output_dir.resolve()),
            "pbip_file": str((self.output_dir / f"{self.project_name}.pbip").resolve()),
            "semantic_model_dir": str(self.sm_dir.resolve()),
            "report_dir": str(self.report_dir.resolve()),
            "tables_written": 3,
            "measures_written": 10,
            "relationships_written": 2,
            "leaf_tasks_in_data": sum(1 for t in self.project.tasks if not t.is_summary),
            "resources_in_data": len(self.project.resources),
            "assignments_in_data": len(self.project.assignments),
        }

    def _write_pbip_root(self) -> None:
        pbip = {
            "version": "1.0",
            "artifacts": [
                {
                    "report": {
                        "path": f"{self.project_name}.Report"
                    }
                }
            ],
            "settings": {
                "enableAutoRecovery": True
            }
        }
        (self.output_dir / f"{self.project_name}.pbip").write_text(
            json.dumps(pbip, indent=2), encoding="utf-8"
        )

    def _write_gitignore(self) -> None:
        content = "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n"
        (self.output_dir / ".gitignore").write_text(content, encoding="utf-8")

    def _write_semantic_model(self) -> None:
        (self.sm_dir / "definition.pbism").write_text(
            json.dumps({"version": "4.0", "settings": {}}, indent=2),
            encoding="utf-8",
        )
        platform = {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {
                "type": "SemanticModel",
                "displayName": self.project_name,
            },
            "config": {
                "version": "2.0",
                "logicalId": str(uuid.uuid4()),
            },
        }
        (self.sm_dir / ".platform").write_text(
            json.dumps(platform, indent=2), encoding="utf-8"
        )

        self._write_database_tmdl()
        self._write_model_tmdl()
        self._write_culture_tmdl()
        self._write_relationships_tmdl()
        self._write_tarefas_tmdl()
        self._write_recursos_tmdl()
        self._write_atribuicoes_tmdl()

    def _write_database_tmdl(self) -> None:
        content = (
            f"database {_tmdl_escape(self.project_name)}\n"
            "\tcompatibilityLevel: 1567\n"
        )
        (self.sm_dir / "definition" / "database.tmdl").write_text(content, encoding="utf-8")

    def _write_model_tmdl(self) -> None:
        content = (
            "model Model\n"
            "\tculture: pt-BR\n"
            "\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
            "\tsourceQueryCulture: pt-BR\n"
            "\n"
            "\tannotation PBIDesktopVersion = 2.132.0\n"
            "\n"
            f"ref table {_tmdl_escape('Tarefas')}\n"
            f"ref table {_tmdl_escape('Recursos')}\n"
            f"ref table {_tmdl_escape('Atribuicoes')}\n"
            "\n"
            "ref culture pt-BR\n"
        )
        (self.sm_dir / "definition" / "model.tmdl").write_text(content, encoding="utf-8")

    def _write_culture_tmdl(self) -> None:
        content = "cultureInfo pt-BR\n"
        (self.sm_dir / "definition" / "cultures" / "pt-BR.tmdl").write_text(
            content, encoding="utf-8"
        )

    def _write_relationships_tmdl(self) -> None:
        rel1_id = _new_lineage_tag()
        rel2_id = _new_lineage_tag()
        content = (
            f"relationship {rel1_id}\n"
            "\tfromColumn: Atribuicoes.TarefaID\n"
            "\ttoColumn: Tarefas.ID\n"
            "\n"
            f"relationship {rel2_id}\n"
            "\tfromColumn: Atribuicoes.Recurso\n"
            "\ttoColumn: Recursos.Recurso\n"
        )
        (self.sm_dir / "definition" / "relationships.tmdl").write_text(
            content, encoding="utf-8"
        )

    def _write_tarefas_tmdl(self) -> None:
        lines = [
            "table Tarefas",
            f"\tlineageTag: {_new_lineage_tag()}",
            "",
            "\tcolumn ID",
            "\t\tdataType: int64",
            "\t\tformatString: 0",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: ID",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Tarefa",
            "\t\tdataType: string",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Tarefa",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Fase",
            "\t\tdataType: string",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Fase",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Inicio",
            "\t\tdataType: dateTime",
            "\t\tformatString: Short Date",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Inicio",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Termino",
            "\t\tdataType: dateTime",
            "\t\tformatString: Short Date",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Termino",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn DuracaoHoras",
            "\t\tdataType: int64",
            "\t\tformatString: 0",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: sum",
            "\t\tsourceColumn: DuracaoHoras",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn PercentConcluido",
            "\t\tdataType: int64",
            "\t\tformatString: 0",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: PercentConcluido",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn IsCritica",
            "\t\tdataType: boolean",
            "\t\tformatString: \"\"\"TRUE\"\";\"\"TRUE\"\";\"\"FALSE\"\"\"",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: IsCritica",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Status",
            "\t\tdataType: string",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Status",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn DuracaoDias",
            "\t\tdataType: double",
            "\t\tformatString: #,0.##",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: sum",
            "\t\tsourceColumn: DuracaoDias",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
        ]
        lines.extend(self._measures_tarefas())
        lines.extend(self._partition_tarefas())
        lines.append("")
        lines.append("\tannotation PBI_ResultType = Table")
        lines.append("")
        (self.sm_dir / "definition" / "tables" / "Tarefas.tmdl").write_text(
            "\n".join(lines), encoding="utf-8"
        )

    def _measures_tarefas(self) -> list[str]:
        measures = []

        def add(name: str, expression: str, *, format_string: str | None = None) -> None:
            measures.append(f"\tmeasure {_tmdl_escape(name)} = ```")
            for line in expression.strip().split("\n"):
                measures.append(f"\t\t\t{line}")
            measures.append("\t\t\t```")
            if format_string is not None:
                measures.append(f"\t\tformatString: {format_string}")
            measures.append(f"\t\tlineageTag: {_new_lineage_tag()}")
            measures.append("")

        add(
            "Avanco Geral",
            "DIVIDE(\n    SUMX(Tarefas, Tarefas[PercentConcluido] * Tarefas[DuracaoHoras]),\n    SUM(Tarefas[DuracaoHoras]),\n    0\n)",
            format_string='0.0"%"',
        )
        add("Total Tarefas", "COUNTROWS(Tarefas)", format_string="0")
        add(
            "Tarefas Concluidas",
            "COUNTROWS(FILTER(Tarefas, Tarefas[PercentConcluido] = 100))",
            format_string="0",
        )
        add(
            "Tarefas Em Andamento",
            "COUNTROWS(FILTER(Tarefas, Tarefas[PercentConcluido] > 0 && Tarefas[PercentConcluido] < 100))",
            format_string="0",
        )
        add(
            "Tarefas Criticas Pendentes",
            "COUNTROWS(FILTER(Tarefas, Tarefas[IsCritica] = TRUE() && Tarefas[PercentConcluido] < 100))",
            format_string="0",
        )
        add(
            "Custo Total",
            "SUM(Atribuicoes[Custo])",
            format_string='"R$ "#,##0.00',
        )
        add(
            "Custo Realizado",
            "CALCULATE(SUM(Atribuicoes[Custo]), FILTER(Tarefas, Tarefas[PercentConcluido] = 100))",
            format_string='"R$ "#,##0.00',
        )
        add("Horas Planejadas", "SUM(Tarefas[DuracaoHoras])", format_string="#,0")
        add(
            "Label Avanco",
            'FORMAT([Avanco Geral] / 100, "0.0%")',
        )
        add(
            "Custo por Fase",
            "SUMX(RELATEDTABLE(Atribuicoes), Atribuicoes[Custo])",
            format_string='"R$ "#,##0.00',
        )

        return measures

    def _partition_tarefas(self) -> list[str]:
        rows = []
        for t in self.project.tasks:
            if t.is_summary:
                continue
            status = (
                "Concluido" if t.percent_complete == 100
                else "Em Andamento" if t.percent_complete > 0
                else "Nao Iniciado"
            )
            duracao_dias = round(t.duration_hours / 8, 2) if t.duration_hours else 0
            row = (
                f"{{{t.id}, {_m_escape(t.name)}, "
                f"{_m_escape(self._phase_from_outline(t.outline_number))}, "
                f"{_m_date(t.start)}, {_m_date(t.finish)}, "
                f"{int(t.duration_hours)}, {t.percent_complete}, "
                f"{'true' if t.is_critical else 'false'}, "
                f"{_m_escape(status)}, {duracao_dias}}}"
            )
            rows.append(row)
        rows_block = ",\n                    ".join(rows)

        partition = [
            "\tpartition Tarefas = m",
            "\t\tmode: import",
            "\t\tsource = ```",
            "\t\t\tlet",
            "\t\t\t\tFonte = Table.FromRows(",
            "\t\t\t\t\t{",
            f"\t\t\t\t\t\t{rows_block}",
            "\t\t\t\t\t},",
            '\t\t\t\t\t{"ID","Tarefa","Fase","Inicio","Termino","DuracaoHoras","PercentConcluido","IsCritica","Status","DuracaoDias"}',
            "\t\t\t\t),",
            "\t\t\t\tTipos = Table.TransformColumnTypes(Fonte, {",
            '\t\t\t\t\t{"ID", Int64.Type},',
            '\t\t\t\t\t{"Tarefa", type text},',
            '\t\t\t\t\t{"Fase", type text},',
            '\t\t\t\t\t{"Inicio", type date},',
            '\t\t\t\t\t{"Termino", type date},',
            '\t\t\t\t\t{"DuracaoHoras", Int64.Type},',
            '\t\t\t\t\t{"PercentConcluido", Int64.Type},',
            '\t\t\t\t\t{"IsCritica", type logical},',
            '\t\t\t\t\t{"Status", type text},',
            '\t\t\t\t\t{"DuracaoDias", type number}',
            "\t\t\t\t})",
            "\t\t\tin",
            "\t\t\t\tTipos",
            "\t\t\t```",
        ]
        return partition

    def _phase_from_outline(self, outline_number: str | None) -> str:
        """Derive a phase name from the project hierarchy."""
        if not outline_number:
            return "Geral"
        top_level = outline_number.split(".")[0]
        for t in self.project.tasks:
            if t.outline_number == top_level and t.is_summary:
                name = t.name or "Fase"
                return re.sub(r"^\d+\.\s*", "", name)
        return "Geral"

    def _write_recursos_tmdl(self) -> None:
        lines = [
            "table Recursos",
            f"\tlineageTag: {_new_lineage_tag()}",
            "",
            "\tcolumn UID",
            "\t\tdataType: int64",
            "\t\tformatString: 0",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: UID",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Recurso",
            "\t\tdataType: string",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Recurso",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Tipo",
            "\t\tdataType: string",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Tipo",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn MaxUnidades",
            "\t\tdataType: int64",
            "\t\tformatString: 0",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: MaxUnidades",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn TaxaHora",
            "\t\tdataType: double",
            '\t\tformatString: "R$ "#,##0.00',
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: TaxaHora",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn HorasTrabalhadas",
            "\t\tdataType: int64",
            "\t\tformatString: 0",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: sum",
            "\t\tsourceColumn: HorasTrabalhadas",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Superalocado",
            "\t\tdataType: boolean",
            "\t\tformatString: \"\"\"TRUE\"\";\"\"TRUE\"\";\"\"FALSE\"\"\"",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Superalocado",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
        ]
        rows = []
        for r in self.project.resources:
            rows.append(
                f"{{{r.uid}, {_m_escape(r.name)}, {_m_escape(r.type)}, "
                f"{int(r.max_units)}, {r.standard_rate:.2f}, "
                f"{int(r.work_hours)}, "
                f"{'true' if r.overallocated else 'false'}}}"
            )
        rows_block = ",\n                    ".join(rows)

        lines.extend([
            "\tpartition Recursos = m",
            "\t\tmode: import",
            "\t\tsource = ```",
            "\t\t\tlet",
            "\t\t\t\tFonte = Table.FromRows(",
            "\t\t\t\t\t{",
            f"\t\t\t\t\t\t{rows_block}",
            "\t\t\t\t\t},",
            '\t\t\t\t\t{"UID","Recurso","Tipo","MaxUnidades","TaxaHora","HorasTrabalhadas","Superalocado"}',
            "\t\t\t\t),",
            "\t\t\t\tTipos = Table.TransformColumnTypes(Fonte, {",
            '\t\t\t\t\t{"UID", Int64.Type},',
            '\t\t\t\t\t{"Recurso", type text},',
            '\t\t\t\t\t{"Tipo", type text},',
            '\t\t\t\t\t{"MaxUnidades", Int64.Type},',
            '\t\t\t\t\t{"TaxaHora", type number},',
            '\t\t\t\t\t{"HorasTrabalhadas", Int64.Type},',
            '\t\t\t\t\t{"Superalocado", type logical}',
            "\t\t\t\t})",
            "\t\t\tin",
            "\t\t\t\tTipos",
            "\t\t\t```",
            "",
            "\tannotation PBI_ResultType = Table",
            "",
        ])
        (self.sm_dir / "definition" / "tables" / "Recursos.tmdl").write_text(
            "\n".join(lines), encoding="utf-8"
        )

    def _write_atribuicoes_tmdl(self) -> None:
        task_by_uid = {t.uid: t for t in self.project.tasks}
        resource_by_uid = {r.uid: r for r in self.project.resources}

        lines = [
            "table Atribuicoes",
            f"\tlineageTag: {_new_lineage_tag()}",
            "",
            "\tcolumn TarefaID",
            "\t\tdataType: int64",
            "\t\tformatString: 0",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: TarefaID",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Tarefa",
            "\t\tdataType: string",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Tarefa",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Recurso",
            "\t\tdataType: string",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Recurso",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Unidades",
            "\t\tdataType: double",
            "\t\tformatString: 0.##",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: none",
            "\t\tsourceColumn: Unidades",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn HorasTrabalhadas",
            "\t\tdataType: int64",
            "\t\tformatString: 0",
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: sum",
            "\t\tsourceColumn: HorasTrabalhadas",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
            "\tcolumn Custo",
            "\t\tdataType: double",
            '\t\tformatString: "R$ "#,##0.00',
            f"\t\tlineageTag: {_new_lineage_tag()}",
            "\t\tsummarizeBy: sum",
            "\t\tsourceColumn: Custo",
            "",
            "\t\tannotation SummarizationSetBy = Automatic",
            "",
        ]
        rows = []
        for a in self.project.assignments:
            task = task_by_uid.get(a.task_uid)
            resource = resource_by_uid.get(a.resource_uid)
            task_name = task.name if task else f"Task#{a.task_uid}"
            resource_name = resource.name if resource else f"Resource#{a.resource_uid}"
            task_id = task.id if task else a.task_uid
            rows.append(
                f"{{{task_id}, {_m_escape(task_name)}, {_m_escape(resource_name)}, "
                f"{a.units}, {int(a.work_hours)}, {a.cost:.2f}}}"
            )
        rows_block = ",\n                    ".join(rows)

        lines.extend([
            "\tpartition Atribuicoes = m",
            "\t\tmode: import",
            "\t\tsource = ```",
            "\t\t\tlet",
            "\t\t\t\tFonte = Table.FromRows(",
            "\t\t\t\t\t{",
            f"\t\t\t\t\t\t{rows_block}",
            "\t\t\t\t\t},",
            '\t\t\t\t\t{"TarefaID","Tarefa","Recurso","Unidades","HorasTrabalhadas","Custo"}',
            "\t\t\t\t),",
            "\t\t\t\tTipos = Table.TransformColumnTypes(Fonte, {",
            '\t\t\t\t\t{"TarefaID", Int64.Type},',
            '\t\t\t\t\t{"Tarefa", type text},',
            '\t\t\t\t\t{"Recurso", type text},',
            '\t\t\t\t\t{"Unidades", type number},',
            '\t\t\t\t\t{"HorasTrabalhadas", Int64.Type},',
            '\t\t\t\t\t{"Custo", type number}',
            "\t\t\t\t})",
            "\t\t\tin",
            "\t\t\t\tTipos",
            "\t\t\t```",
            "",
            "\tannotation PBI_ResultType = Table",
            "",
        ])
        (self.sm_dir / "definition" / "tables" / "Atribuicoes.tmdl").write_text(
            "\n".join(lines), encoding="utf-8"
        )

    def _write_report(self) -> None:
        pbir = {
            "version": "1.0",
            "datasetReference": {
                "byPath": {
                    "path": f"../{self.project_name}.SemanticModel"
                }
            }
        }
        (self.report_dir / "definition.pbir").write_text(
            json.dumps(pbir, indent=2), encoding="utf-8"
        )
        platform = {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {
                "type": "Report",
                "displayName": self.project_name,
            },
            "config": {
                "version": "2.0",
                "logicalId": str(uuid.uuid4()),
            },
        }
        (self.report_dir / ".platform").write_text(
            json.dumps(platform, indent=2), encoding="utf-8"
        )
        report_json = {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/1.0.0/schema.json",
            "themeCollection": {"baseTheme": {"name": "CY24SU10"}},
            "layoutOptimization": "None",
            "resourcePackages": [],
        }
        (self.report_dir / "definition" / "report.json").write_text(
            json.dumps(report_json, indent=2), encoding="utf-8"
        )
        pages_index = {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": ["ResumoPage"],
            "activePageName": "ResumoPage",
        }
        (self.report_dir / "definition" / "pages" / "pages.json").write_text(
            json.dumps(pages_index, indent=2), encoding="utf-8"
        )
        page_dir = self.report_dir / "definition" / "pages" / "ResumoPage"
        page_dir.mkdir(parents=True, exist_ok=True)
        page_json = {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.0.0/schema.json",
            "name": "ResumoPage",
            "displayName": "Resumo",
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
        }
        (page_dir / "page.json").write_text(
            json.dumps(page_json, indent=2), encoding="utf-8"
        )
