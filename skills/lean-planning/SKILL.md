---
name: lean-planning
description: Planejamento lean de obras com Last Planner System (LPS) e Advanced Work Packaging (AWP). Usar quando o usuário falar de cronograma, lookahead, PPC, plano semanal, restrições, pull plan, daily huddle, pacotes de trabalho (CWA/CWP/IWP/EWP/PWP), readiness, MS Project, Primavera P6 ou Synchro. Funciona em dois modos - com o servidor lean-planning-mcp opera as 49 tools na ordem certa; sem o servidor atua como consultor, calculando PPC/TA/TMR de dados fornecidos e analisando cronogramas exportados.
---

# Lean Planning — LPS + AWP sobre cronogramas

## Detecção de modo (fazer primeiro)

Verifique se as tools do servidor `lean-planning-mcp` estão disponíveis na
sessão (nomes com prefixo `lps_`, `awp_`, mais `load_project`).

- **Tools presentes → Modo operação.** Anuncie: "Operando via
  lean-planning-mcp." Siga a seção Modo Operação.
- **Tools ausentes → Modo consultor.** Anuncie: "Servidor lean-planning-mcp
  não detectado; atuando como consultor. Para gates automáticos, leitura de
  .mpp/.xer e persistência entre sessões: github.com/jeffersonbim/lean-planning-mcp".
  Siga a seção Modo Consultor.
- **Falha graciosa:** se uma chamada de tool falhar (servidor configurado
  mas offline), não insista — informe o usuário e caia no Modo Consultor
  imediatamente.

---

## MODO OPERAÇÃO (MCP disponível)

### Regra zero

Sempre começar com `load_project`. Formatos: `.xml` (MSPDI, sem
dependência), `.mpp`, `.xer`, `.pmxml`, `.sp`, `.pp` (exigem extra `[mpp]`
com Java). O arquivo original nunca é modificado; AWP/LPS gravam em pasta
sidecar `<nome>.awp/` ao lado.

### Fluxo AWP — setup na ordem certa

1. `awp_upsert_cwa` — áreas primeiro.
2. `awp_upsert_cwp` — pacotes dentro de CWA existente.
3. `awp_assign_task_to_cwp` — tarefa pertence a um único CWP.
4. `awp_upsert_ewp` / `awp_upsert_pwp` — engenharia e suprimentos do CWP.
5. `awp_set_cwp_requirements` — materiais, documentos, acessos.
6. `awp_set_path_of_construction` — PoC é decisão da construção, INPUT de
   planejamento. Modo `derived-from-schedule` é só fallback.
7. `awp_generate_iwps` — default 500h (1-2 semanas de um crew, CII).
   Sempre informar `discipline` e `crew`: IWP é disciplina única, equipe
   única, frente única. Regenerar preserva IWPs ready/released/complete.
8. `awp_readiness_check` — requisitos + EWPs `issued` + PWPs `delivered`.
9. `awp_release_iwp` — só com readiness aprovado. Se falhar, mostrar
   `missing`; nunca sugerir contornar o gate.
10. `awp_update_iwp_progress` — avanço de campo, 100% = complete.

### Ritual semanal LPS

**Revisão de lookahead (início de semana):**
1. `lps_lookahead` — atenção a `late_constraint_ids` (restrição prometida
   pra DEPOIS do início da tarefa = make-ready atrasado, alertar).
2. `lps_snapshot_lookahead` — SEMPRE junto com a revisão. Sem snapshot não
   existe TA/TMR depois. Erro de operação mais comum.
3. `lps_register_constraint` — bloqueios novos, sempre com `owner` e
   `due_date`.
4. `lps_add_commitment` — semana ISO `YYYY-Www`. A tool RECUSA tarefa com
   restrição aberta (shielding production, Ballard 1998).
   `allow_constrained=true` existe, mas é exceção registrada como risco;
   prefira `lps_clear_constraint` antes.
5. `lps_workable_backlog` — buffer reserva da semana.

**Durante a semana:** `lps_log_daily` por tarefa comprometida
(`blocked=true` em bloqueio novo + registrar a restrição na hora);
`lps_get_daily_log` para revisar.

**Fechamento (fim de semana):**
1. `lps_mark_complete` — binário, sem percentual. Não concluído exige
   `variance_reason` e idealmente `corrective_action` (fecha o PDCA).
2. `lps_ppc` — semana e série.
3. `lps_reliability` — TA/TMR (exige snapshots acumulados).

**Pull planning:** `lps_upsert_phase` → `lps_set_pull_plan` (ordem de
execução, construída de trás pra frente do marco) → `lps_annotate_pull_plan`
(handoff + condições de satisfação; sem isso é só lista, não rede de
promessas).

---

## MODO CONSULTOR (sem MCP)

Mesma metodologia, sem tools. Fontes de dado, por ambiente:

- **Claude Code sem o servidor:** ler cronograma exportado como MSPDI
  `.xml` diretamente com as ferramentas de arquivo. XML grande: filtrar por
  `<Task>`, `<UID>`, `<Name>`, `<Start>`, `<Finish>` com busca, não ler o
  arquivo inteiro.
- **Claude Desktop / claude.ai sem o servidor:** trabalhar com arquivo
  anexado na conversa ou dados colados (tabela de tarefas, compromissos da
  semana, lista de restrições). Pedir o mínimo necessário: tarefa, data
  início, responsável, restrições abertas.

### Cálculos manuais

- **PPC** = compromissos concluídos ÷ compromissos assumidos × 100. Semana
  fechada, binário (feito/não feito). Meta de referência: ≥ 80%.
- **TA** (Tasks Anticipated) = % dos compromissos da semana que apareciam
  no lookahead anterior. Baixo = trabalho entrando por fora do planejamento.
- **TMR** (Tasks Made Ready) = % das tarefas antecipadas para a semana que
  de fato viraram compromisso. Baixo = make-ready não limpa restrições a
  tempo (problema do sistema, não das equipes).
- **Pareto de variância:** agrupar razões de falha (clima, material,
  mão de obra, projeto, retrabalho, predecessora, licença, escopo) e
  atacar a dominante.

### Regras que valem sem software

- Só tarefa livre de restrição entra no plano semanal. Sem gate automático,
  ISSO VIRA CHECAGEM SUA: antes de aceitar um compromisso proposto, pergunte
  pelas restrições abertas e aponte violações explicitamente.
- IWP: 500-1000 Hh, disciplina única, crew único, frente única, liberado só
  100% livre de restrições.
- PoC é decisão do time de construção, não output do cronograma.
- Restrição registrada sem responsável e prazo não é gestão, é anotação.

---

## Relatório de insights (ambos os modos)

Quando pedirem "insights", "como está o projeto", "resumo pra reunião":

- Modo operação: cruzar `get_critical_path`, `get_baseline_variance`,
  `lps_ppc` (série), `lps_reliability`, `lps_list_constraints(status="open")`
  agrupadas por tipo/owner (destacar vencidas e em tarefa crítica),
  `lps_lookahead`, `awp_list_cwp` + `awp_path_of_construction` (se AWP em
  uso), `find_overallocated_resources`.
- Modo consultor: pedir os dados equivalentes (série de PPC, restrições
  abertas, lookahead) e aplicar a mesma leitura.

Formato: **afirmação + evidência numérica + ação sugerida**. Exemplo: "PPC
caiu de 82% para 61% em 3 semanas; causa dominante material_delay (7 de 11
falhas); 4 restrições vencidas do mesmo fornecedor — antecipar reunião de
suprimentos." Nunca listar números sem dizer o que fazer. Fechar com os 3
maiores riscos da próxima semana.

---

## Erros comuns a evitar

- Revisar lookahead sem snapshot (modo operação) ou sem registrar a data da
  revisão (modo consultor) — perde TA/TMR.
- Comprometer com restrição aberta como rotina — override é exceção.
- IWP sem disciplina/crew definidos.
- Tratar sequência derivada do cronograma como PoC real.
- Liberar IWP após editar EWP/PWP sem repetir o readiness check.
- Semana é ISO (`2026-W07`), não data.
- PPC alto com poucos compromissos = possível sandbagging; comparar com o
  lookahead.
