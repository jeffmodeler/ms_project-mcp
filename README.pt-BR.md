# lean-planning-mcp

[![CI](https://github.com/jeffersonbim/lean-planning-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jeffersonbim/lean-planning-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

> 🇧🇷 Versão em português · 🇺🇸 [English version](README.md)

Servidor MCP (Model Context Protocol) que expõe cronogramas — **Microsoft
Project, Primavera P6 e Synchro Scheduler** — para clientes LLM como Claude
Desktop e Claude Code. Lê cronogramas, recursos, dependências, caminho crítico
e variação de baseline — e adiciona camadas de **AWP** (Advanced Work
Packaging, CII) e **LPS** (Last Planner System, Lean) para gerenciar pacotes
de trabalho, restrições, compromissos semanais e PPC. Tudo local, sem chamadas
à nuvem e sem necessidade de licença de ferramenta de planejamento.

## Por que existe

Fluxos de trabalho de construção, engenharia e BIM vivem dentro de cronogramas
do Microsoft Project. Este servidor permite que seu LLM:

- Inspecione um cronograma e responda perguntas sobre ele (prazos, caminho
  crítico, sobrealocação de recursos).
- Cruze dados de tarefas com quantitativos de modelos BIM ou com dados de
  custo de dashboards Power BI.
- Gere exportações JSON para automações downstream (dashboards, relatórios,
  pipelines ETL).

É **read-only por design**. Edições no cronograma permanecem onde devem estar:
no próprio Microsoft Project.

## Requisitos

- Python 3.11+
- Um cliente MCP compatível (Claude Desktop, Claude Code, etc.)
- Para `.xml` (MSPDI): nenhuma dependência extra
- Para todos os outros formatos: a dependência opcional `[mpp]` (requer JVM
  via pacote `mpxj`)

## Formatos suportados

| Formato | Extensão | Requer extra `[mpp]` |
|---|---|---|
| Microsoft Project MSPDI XML | `.xml` | Não |
| Microsoft Project nativo | `.mpp`, `.mpx` | Sim |
| Primavera P6 export | `.xer` | Sim |
| Primavera P6 XML (PMXML) | `.pmxml`, `.xml`* | Sim |
| Synchro Scheduler | `.sp` | Sim |
| Asta Powerproject | `.pp` | Sim |

\* Um `.xml` que não é MSPDI é automaticamente reprocessado pelo leitor
universal (mpxj), então exports P6 XML salvos como `.xml` também carregam.

Nota Synchro: o mpxj lê arquivos `.sp` do Synchro Scheduler até as versões
que suporta; para projetos recentes do Synchro 4D Pro, exportar XER ou MS
Project XML de dentro do Synchro é o caminho mais confiável. Depois de
carregado, **todas as 49 tools — incluindo as camadas AWP e LPS — funcionam
igual independente do formato de origem**, pois operam sobre task UIDs.

## Instalação

### Opção A — `uv` (recomendada)

```bash
git clone https://github.com/jeffersonbim/lean-planning-mcp.git
cd lean-planning-mcp
uv sync
```

### Opção B — `pip`

```bash
pip install git+https://github.com/jeffersonbim/lean-planning-mcp.git
```

Para suporte a `.mpp`:

```bash
uv sync --extra mpp
# ou
pip install "lean-planning-mcp[mpp] @ git+https://github.com/jeffersonbim/lean-planning-mcp.git"
```

## Integração com Claude Desktop

Adicione ao seu `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "lean-planning-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\caminho\\para\\lean-planning-mcp",
        "run",
        "lean-planning-mcp"
      ]
    }
  }
}
```

Reinicie o Claude Desktop. As 49 tools ficam disponíveis em qualquer conversa
(14 do núcleo MS Project + 17 AWP + 18 LPS).

## Tools disponíveis

| Tool | Finalidade |
|---|---|
| `load_project` | Carrega cronograma na memória — MSPDI `.xml`, `.mpp`, P6 `.xer`/`.pmxml`, Synchro `.sp`, Asta `.pp` |
| `open_in_ms_project` | Abre o projeto carregado (ou um caminho informado) no Microsoft Project via associação padrão do SO |
| `project_info` | Título, autor, janela do cronograma, moeda, contagens agregadas |
| `list_tasks` | Filtra tarefas por tipo, criticidade, substring no nome, top N |
| `get_task` | Registro completo de uma tarefa por UID, ID ou nome |
| `list_resources` | Recursos, opcionalmente filtrados por tipo ou sobrealocação |
| `get_resource_assignments` | Atribuições para um ou todos os recursos |
| `find_overallocated_resources` | Recursos marcados como sobrealocados |
| `get_critical_path` | Tarefas no caminho crítico, ordenadas por data de início |
| `get_predecessors_successors` | Rede de dependências de uma tarefa |
| `get_baseline_variance` | Comparação de datas e duração atual vs. baseline |
| `get_gantt_data` | Tarefas formatadas para bibliotecas de Gantt |
| `export_to_json` | Exportação completa do projeto para JSON (arquivo ou inline) |
| `generate_pbip_dashboard` | Gera um Power BI Project (.pbip) e abre no Power BI Desktop |

## Exportando `.mpp` para MSPDI XML

Se você não quer instalar Java para a dependência opcional `mpp`, exporte
seu cronograma do Microsoft Project como XML:

1. Abra o `.mpp` no Microsoft Project.
2. **Arquivo → Salvar como → Tipo de arquivo → Formato XML (\*.xml)**.
3. Aponte `load_project` para o `.xml` resultante.

O formato XML é o esquema oficial Microsoft Project Data Interchange (MSPDI)
e contém tarefas, recursos, atribuições, predecessores, baseline e a maior
parte dos metadados do projeto.

## Exemplos de prompts

Depois de carregar um projeto, pergunte ao Claude:

```
Carregue o projeto em C:\cronogramas\obra-acme.xml
Me dê o caminho crítico com duração total em dias.
Quais recursos estão sobrealocados e em quanto?
Liste as 5 tarefas com maior variação de baseline.
Exporte o projeto completo para C:\relatorios\obra-acme.json
```

## Duas camadas, separadas por design

AWP e LPS vivem no mesmo servidor mas operam como **camadas independentes**
sobre o mesmo cronograma. Persistem em arquivos sidecar separados
(`awp.json` e `lps.json`), não compartilham estado e nenhuma depende da outra:

- **AWP** organiza o *escopo*: o que será construído, onde, e em qual pacote
  (CWA → CWP → IWP, alimentado por pacotes de engenharia e suprimentos).
- **LPS** organiza o *fluxo de compromissos*: o que as equipes prometem
  semana a semana, o que as bloqueia e quão confiável é o planejamento.

Você pode usar só uma das camadas, ou as duas lado a lado no mesmo `.mpp`.
São metodologias complementares — AWP responde "o pacote está pronto para
ser liberado?", LPS responde "a equipe vai realmente executar esta semana?" —
mas neste servidor operam de forma independente, por decisão de projeto.

## AWP — Advanced Work Packaging ✅

Metodologia do **Construction Industry Institute (CII RT-272 / RT-319)** que
estrutura a execução em pacotes de trabalho alinhados entre engenharia,
compras e campo.

```
CWA (Construction Work Area) → CWP (Construction Work Package)
                                     ↓
                               IWP (Installation Work Package)

EWP (Engineering Work Package) ─┐
                                ├→ condicionam readiness do CWP
PWP (Procurement Work Package) ─┘
```

Foco: **path of construction** como *input* de planejamento + **liberação
livre de restrições**. Um CWP só está ready quando os requisitos manuais
estão disponíveis, todos os EWPs vinculados estão `issued` e todos os PWPs
`delivered`. IWPs só são **liberados ao campo após readiness check aprovado**
— a regra de ouro do WorkFace Planning.

### Tools AWP (17)

| Tool | Finalidade |
|---|---|
| `awp_list_cwa` | Lista Construction Work Areas |
| `awp_upsert_cwa` | Cria ou atualiza uma CWA |
| `awp_list_cwp` | Lista CWPs com `task_count`, `total_hours`, `any_critical` |
| `awp_upsert_cwp` | Cria ou atualiza um CWP (status: planned/ready/in-progress/complete/on-hold) |
| `awp_assign_task_to_cwp` | Vincula tarefa a um CWP (move de outro se necessário) |
| `awp_set_cwp_requirements` | Define requisitos do CWP (materiais, documentos, acessos) |
| `awp_upsert_ewp` | Cria/atualiza Engineering Work Package (planned/in-progress/issued) |
| `awp_list_ewp` | Lista EWPs, opcionalmente por CWP |
| `awp_upsert_pwp` | Cria/atualiza Procurement Work Package (planned/ordered/delivered) |
| `awp_list_pwp` | Lista PWPs, opcionalmente por CWP |
| `awp_readiness_check` | Readiness do CWP: requisitos + EWPs issued + PWPs delivered. Condiciona liberação de IWP |
| `awp_set_path_of_construction` | Define o PoC como input de planejamento (ordem decidida pela construção) |
| `awp_path_of_construction` | Retorna o PoC — ordem manual se definida, senão derivada do cronograma |
| `awp_generate_iwps` | Quebra CWP em IWPs (default 500h — dimensionamento CII de crew-semana; grava disciplina/crew; preserva IWPs liberados) |
| `awp_release_iwp` | Libera IWP ao campo — **bloqueado se o CWP não passou no readiness check** |
| `awp_update_iwp_progress` | Avanço de campo 0-100% com horas ganhas; 100% marca complete |
| `awp_export_wpr` | Gera Work Package Release — JSON auto-contido pro canteiro |

## LPS — Last Planner System ✅

Método de **Lean Construction** com 5 níveis de planejamento — todos
implementados.

```
Master → Phase (pull plan) → Lookahead (N semanas, remove restrições)
                              → WWP (Weekly Work Plan) → Daily huddle
```

**Regra central aplicada (shielding production, Ballard 1998):** só tarefa
livre de restrições entra no Weekly Work Plan. `lps_add_commitment` rejeita
tarefas com restrições abertas, salvo override explícito — registrado no
compromisso como risco.

**Métricas**: **PPC** (Percent Plan Complete — promessas cumpridas), mais
**TA** (Tasks Anticipated) e **TMR** (Tasks Made Ready) calculadas a partir
de snapshots do lookahead — medem a saúde do processo de make-ready, não só
a confiabilidade da última semana.

### Tools LPS (18)

| Tool | Finalidade |
|---|---|
| `lps_list_phases` | Lista fases do projeto |
| `lps_upsert_phase` | Cria ou atualiza uma fase (PH-01, datas início/fim) |
| `lps_set_pull_plan` | Define sequência reversa (pull planning) com UIDs de tarefas |
| `lps_get_pull_plan` | Retorna pull plan de uma fase |
| `lps_annotate_pull_plan` | Registra handoff + condições de satisfação em entrada do pull plan |
| `lps_register_constraint` | Registra restrição (material/document/labor/equipment/access/permit/…) |
| `lps_clear_constraint` | Marca restrição como resolvida |
| `lps_list_constraints` | Lista com filtros por task, status, tipo |
| `lps_lookahead` | Janela de N semanas com ready/blocked + alerta de restrição atrasada (`due_date` após início da tarefa) |
| `lps_snapshot_lookahead` | Persiste snapshot do lookahead — alimenta TA/TMR. Rodar a cada revisão semanal |
| `lps_add_commitment` | Adiciona compromisso — **bloqueia tarefa com restrição aberta** (override: `allow_constrained`) |
| `lps_mark_complete` | Fecha compromisso com `variance_reason` + `corrective_action` opcional (PDCA) |
| `lps_log_daily` | Registro do daily huddle contra tarefa comprometida (nível 5) |
| `lps_get_daily_log` | Lê registros diários de uma semana |
| `lps_get_wwp` | Lê WWP de uma semana |
| `lps_workable_backlog` | Tarefas ready não comprometidas — buffer reserva da semana |
| `lps_reliability` | Série TA / TMR — saúde do processo de make-ready |
| `lps_ppc` | Calcula PPC de uma semana ou série das últimas N semanas |

**Tipos de restrição aceitos**: `material`, `document`, `information`, `design`,
`labor`, `equipment`, `access`, `permit`, `prerequisite`, `other`.

**Razões de variance aceitas**: `weather`, `design_change`, `material_delay`,
`labor_unavailable`, `equipment_breakdown`, `rework`, `permit`,
`prerequisite_incomplete`, `scope_change`, `other`.

## Skill companion (Claude Code, Claude Desktop, claude.ai)

O repo versiona uma **skill adaptativa** em
[skills/lean-planning/SKILL.md](skills/lean-planning/SKILL.md). Ela detecta
se as tools do MCP estão disponíveis na sessão:

- **Modo operação** (MCP presente): opera as 49 tools na ordem certa —
  sequência de setup AWP, ritual semanal do LPS (lookahead + snapshot,
  fechamento binário + PPC/variância), gates de liberação, interpretação
  de métricas.
- **Modo consultor** (MCP ausente): metodologia pura — cálculo manual de
  PPC/TA/TMR de dados colados, análise de MSPDI XML exportado, revisão de
  dimensionamento de IWP, insights entre camadas. A skill anuncia o modo
  ativo e cai graciosamente pro consultor se o servidor estiver configurado
  mas offline.

### Instalação — Claude Code

```bash
# Windows
xcopy /E /I skills\lean-planning %USERPROFILE%\.claude\skills\lean-planning
# macOS / Linux
cp -r skills/lean-planning ~/.claude/skills/lean-planning
```

### Instalação — Claude Desktop / claude.ai

Envie o arquivo [dist/lean-planning-skill.zip](dist/lean-planning-skill.zip)
em **Configurações → Capacidades → Skills**. Sem o servidor MCP a skill roda
em modo consultor; no Claude Desktop com o servidor configurado, roda em
modo operação completo.

## Arquitetura sidecar

O `.mpp`/`.xml` permanece como fonte mestre das tarefas (read-only preservado).
Ao lado do arquivo do projeto, uma pasta `<nome>.awp/` guarda metadados que o
Project não representa bem:

```
C:\cronogramas\
├── obra-acme.mpp              ← fonte mestre (nunca modificada)
└── obra-acme.awp/             ← sidecar criado automaticamente
    ├── awp.json               ← CWA / CWP / IWP / EWP / PWP + path of construction
    └── lps.json               ← phases, pull plans, constraints, WWPs, snapshots
```

Cada tool de escrita atualiza `updated_at` (ISO 8601 UTC) no JSON.

## Exemplo de diálogo com AWP + LPS

```
Você: Carregue o cronograma em D:\obra\vila-idosos.mpp
Claude: [load_project]
        "342 tarefas, 28 recursos. Início 2025-01-15."

Você: Crie a CWA "Fundações" com id CWA-01 prioridade 1
Claude: [awp_upsert_cwa] "CWA-01 criada."

Você: Crie o CWP-01.01 "Fundação Bloco A" dentro da CWA-01 e
      associe as tarefas 145, 146, 147
Claude: [awp_upsert_cwp + awp_assign_task_to_cwp x3]
        "CWP-01.01 criado com 3 tarefas (total 240h, 1 crítica)."

Você: Define que esse CWP precisa de: aço CA-50, concreto fck25, AR-01
Claude: [awp_set_cwp_requirements] "Requisitos registrados."

Você: O CWP está ready? Chegou aço CA-50 e AR-01
Claude: [awp_readiness_check]
        "Não — falta: concreto fck25."

Você: Registra essa pendência como restrição material do CWP
Claude: [lps_register_constraint]
        "CST-3F2A4B91 registrada — material, responsável compras."

Você: Qual é o lookahead de 4 semanas?
Claude: [lps_lookahead(weeks=4)]
        "47 tarefas. 12 com restrições abertas. Críticas: 3."

Você: Chegou o concreto — limpa a restrição CST-3F2A4B91
Claude: [lps_clear_constraint] "Resolvida em 2025-02-03. CWP agora READY."

Você: Compromete a task 145 para o time-arq na semana 2025-W06, 40h
Claude: [lps_add_commitment] "Compromisso adicionado."

Você: No fim da semana: task 145 concluída em 42h
Claude: [lps_mark_complete] "Fechada."

Você: Calcula o PPC da semana
Claude: [lps_ppc(week='2025-W06')]
        "PPC 100% (1/1 entregue)."
```

## Desenvolvimento

```bash
uv sync --extra dev
uv run pytest -v
uv run ruff check src tests
```

## Licença

MIT — veja [LICENSE](LICENSE).
