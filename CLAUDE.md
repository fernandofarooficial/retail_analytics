# retail_analytics — CLAUDE.md

## Visão Geral

SaaS multi-tenant de analytics de varejo com reconhecimento facial. Correlaciona dados de câmeras (schema `faciais`) com dados de PDV Microvix (schema `microvix`). Banco PostgreSQL `lojas` em `72.60.58.241:5432`.

**URL produção:** http://72.60.58.241/retail_analytics/  
**Porta Flask:** 5003 (gunicorn)

## Stack

- Python 3.13 + Flask ≥3.0 + PostgreSQL + gunicorn
- Virtualenv em `.venv/`
- Conexão DB via `PG_DSN` no `.env`; `db.py` usa `ThreadedConnectionPool(min=2, max=10)` com `RealDictCursor`, expõe `query_one`, `query_all`, `execute` — todas dão `commit()` ao final (necessário para `INSERT ... RETURNING` via `query_one`) e `rollback()` em caso de exceção antes de devolver a conexão ao pool
- Cache Flask-Caching (SimpleCache, 900 s default); charts do dashboard memoizados 15 min via `@cache.memoize(timeout=900)`

## Deploy

```
ssh root@72.60.58.241
# no VPS: /home/workuser/retail_analytics
git pull origin main && sudo systemctl restart retail_analytics
```

**Cron job:** `scripts/recalcular_ranking.py` roda diariamente às 23:45 no VPS (`45 23 * * *`) para recalcular `faciais.customer_ranking`. Log em `logs/ranking_job.log`.

**Índices de performance:** `migrations/indexes_performance.sql` — rodar manualmente com `psql $PG_DSN -f migrations/indexes_performance.sql` (usa `CREATE INDEX CONCURRENTLY`, um comando por vez, fora de transaction block).

## Arquitetura

**Blueprints (`routes/`):**
- `auth.py` (~1950 linhas) — login/logout, dashboard web, `/visitacao` (+ `/visitacao/pessoa/<person_id>` POST — edição de dados do cliente, ver seção "Visitação" abaixo), `/mapa-calor`, `/ranking` (+ `/ranking/<person_id>`, `/ranking/recalcular`), `/heatmap-imagem`. Prefix: `/retail_analytics`
- `mobile.py` (~2690 linhas) — espelho do auth.py para mobile (login, dashboard, `/visitacao` + `/visitacao/pessoa/<person_id>` POST, `/ranking`, `/mapa-calor`, `/heatmap-imagem`) + `/sw.js` (PWA) + reimplementação própria (não reuso de blueprint) das telas de `gestao.py` (`/gestao/faturamento|vendas|estoque`) e `motor.py` (`/motor/faturamento|vendas|estoque`). Prefix: `/retail_analytics/m`. **Não tem equivalente de `relatorios.py`** — o quadro "Pedidos" (meta/realizado por vendedor) que existia em `/motor/vendas` foi removido do mobile (2026-08), só existe na versão web (`Relatórios > Pedidos`).
- `cadastros.py` — CRUD empresas, lojas, câmeras, temas, regras de ranking (`/ranking-regras`)
- `usuarios.py` — gestão de usuários e permissões
- `conta.py` — troca de senha
- `metas.py` — módulo de metas, calendário, exceções, feriados regionais e perfis de calendário (admin only). Prefix: `/retail_analytics/metas`
- `motor.py` — Motor Operacional (`/faturamento`, `/vendas`, `/estoque`). Prefix: `/retail_analytics/motor`. Em `/vendas`, ao selecionar um vendedor mostra Top 10 (clientes e produtos, aumentado de Top 5 em 2026-08) por faturamento do mês anterior com comparativo mês atual — `people.top10_clientes_vendedor`/`top10_produtos_vendedor`, também usado em `mobile.py`. `/vendas` também tem o quadro "Top 10 Inadimplentes" (2026-08) — ver seção "Inadimplência" abaixo
- `gestao.py` — Gestão Estratégica (`/faturamento`, `/vendas`, `/estoque`). Prefix: `/retail_analytics/gestao`
- `relatorios.py` (2026-08) — Relatórios, web only (sem equivalente mobile). Hoje só `/pedidos`
  (quadro de pedidos por vendedor — mês atual em R$ + meta/realizado semanal de Pedidos Gerados —
  movido de dentro de Motor > Vendas). Prefix: `/retail_analytics/relatorios`. Estrutura pensada
  pra crescer: menu "Relatórios" na navbar + sub-tabs (`.gest-tabs`) dentro da página pros
  relatórios futuros.
- `utils.py` — decorators `@login_required`, `@screen_required(screen_id)`, `@block_user_types(*user_types)` (2026-08, ver seção "Papéis de usuário" abaixo), helpers de KPI de tempo de permanência

**Padrão `_store_context(endpoint)`:** centraliza carregamento de empresa/loja/tema/cnpj/portal em `motor.py`, `gestao.py` e `relatorios.py` (cada um com sua própria cópia local da função — não é compartilhada via import). Retorna `(ctx_dict, redirect_ou_None)`. `motor.py`, `gestao.py` e `relatorios.py` usam `@login_required` (sem `@screen_required`) + `@block_user_types('emp')` em toda rota (2026-08); `cadastros.py`, `conta.py`, `usuarios.py` e as rotas de dashboard/ranking em `auth.py` usam `@screen_required(screen_id)`.

**Queries analíticas:** `people.py` (~910 linhas) — funções de KPI Microvix, ranking, estoque; usa `get_store_series(store_id)` para obter `(series_pf, series_pj)` de `faciais.store_serie_rules`  
**Lógica de metas:** `metas.py` (module, ~230 linhas) — resolução de meta efetiva (`_goal_value`), acumulado YTD, distribuição diária/semanal em tempo real a partir do valor mensal (`_distribuir_mensal`, `_weekly_target`)

**Scripts (`scripts/`):** `recalcular_ranking.py` — job agendado via cron no VPS (`45 23 * * *`): faz `REFRESH MATERIALIZED VIEW faciais.mv_microvix_vendas`, trunca e repopula `faciais.customer_ranking` a partir de `faciais.vw_customer_ranking`. Log em `logs/ranking_job.log`.

## Papéis de usuário (`faciais.user_types`)

| user_type_id | Acesso |
|---|---|
| `adm` | Todas as empresas/lojas |
| `man` | Grupos de empresas vinculados (`user_company_groups`) |
| `ret` | Grupos de lojistas vinculados (`user_retailer_groups`) |
| `emp` | Lojas específicas vinculadas (`user_stores`) |

**Restrição `emp` a Gestão/Motor/Relatórios (2026-08):** usuários `emp` não têm acesso aos módulos
Gestão Estratégica, Motor Operacional e Relatórios (nem web nem mobile) — só Dashboard, Visitação,
Ranking e Mapa de Calor. Implementado via decorator `@block_user_types('emp')` (`routes/utils.py`)
aplicado em toda rota de `motor.py`, `gestao.py`, `relatorios.py` e nos equivalentes mobile
(`mobile.gestao_*`/`mobile.motor_*`) — retorna 403 se `session['user_type_id'] == 'emp'`. Os links
correspondentes também somem da navbar (`base_web.html`) e da bottom nav (`base_mobile.html`) pra
esse tipo de usuário. Diferente do mecanismo de `screens`/`user_type_screens` (que não tem
`screen_id` cadastrado pra esses três módulos) — é uma checagem direta de `user_type_id`, não
baseada em `vw_user_screen_access`.

## Filtro padrão Microvix (vendas)

```sql
cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
AND (tipo_transacao IN ('P','V') OR tipo_transacao IS NULL)
AND codigo_cliente = 1
AND cod_natureza_operacao = '10030'
```

**Séries PF vs. PJ:** `faciais.store_serie_rules` mapeia, por loja, quais séries de NF (`serie`) correspondem a Pessoa Física ou Jurídica (`person_kind`). `people.get_store_series(store_id)` retorna `(series_pf, series_pj)`; a maioria das queries analíticas (faturamento, ticket médio, ranking de clientes) filtra `microvix_movimento.serie = ANY(series_pf)` para considerar só vendas a PF, enquanto concentração/venda por vendedor a PJ usa `series_pj`. Existe também a view `faciais.vw_store_series` com o mesmo dado agregado em array, mas as queries em `people.py` consultam `store_serie_rules` diretamente.

**Inadimplência — `people.top10_inadimplentes` (2026-08):** quadro "Top 10 Inadimplentes" em
Motor > Vendas (web e mobile), com toggle de ordenação por valor em aberto ou dias de atraso
(`?inadimplentes_order=valor|prazo`). Fonte: `microvix.microvix_faturas` (Web Service
`LinxFaturas`), filtrando `receber_pagar='R'`, `cancelado='N'`, `excluido='N'`,
`data_baixa IS NULL` e `data_vencimento < CURRENT_DATE`, agregado por `cod_cliente`.
**Restrito a `forma_pgto = 'Crediário'`** (2026-08, ajustado de "excluir só Cartão" pra essa
forma mais estrita): é a única forma onde o `cod_cliente` aponta de modo confiável pro cliente
real que comprou a prazo direto da loja. As demais ficam de fora — `Cartão` em especial tem
`cod_cliente` apontando pra adquirente/bandeira (ex: "REDE SA", "SICREDI CARTOES", "Banrisul",
"VISA OPERADORA CARTÃO CRÉDITO"), não pro cliente real: é repasse de maquininha em trânsito, não
dívida de cliente; `Chq.Vista`/`Convênio` têm cliente real mas volume marginal (poucas dezenas de
faturas no total). Confirmado por investigação (2026-08): o link `documento`+`serie` entre
`microvix_faturas` e `microvix_movimento` bate em 99,5% dos casos (as poucas divergências são só
itens com `excluido='S'`), então não é problema de sincronização — é conceitual, de qual
`forma_pgto` tem `cod_cliente` confiável. Causa raiz encontrada (2026-08): `data_baixa`
praticamente não era preenchida pra faturas emitidas a partir de mai/2025 (em ambas as lojas
testadas) — não era processo de cobrança real da loja nem lacuna do Microvix, e sim a
sincronização (`camera300`, fora deste repo) só consultar `LinxFaturas` pelo período de *emissão*
(`data_inicial`/`data_fim`); a API só aceita um período por chamada, então faturas antigas nunca
eram revisitadas pra pegar a baixa feita depois. Corrigido no `camera300` (`microvix_ingest.py`,
função `_ingerir_faturas_pagamento`) com uma segunda consulta a `LinxFaturas` filtrando por
`data_inicial_pag`/`data_fim_pag` (janela móvel de 90 dias, cursor de controle próprio
`LinxFaturasPag`), fazendo upsert em `microvix_faturas` por `(portal, cnpj_emp, codigo_fatura)`.

**⚠️ Pendência em aberto (2026-08):** a correção acima e um backfill único (mai/2025→hoje) foram
aplicados, mas **não resolveram o quadro pro portal `18922` (Ecoville POA, `cnpj 49104467000170`
— a loja com o maior volume de "inadimplentes" hoje)**. Reconferido após o backfill: `Crediário`
`receber_pagar='R'` desse portal segue com **0% de baixa em todo mês de mar/2025 a jun/2026**, sem
nenhuma melhora (testado dez/2025 e jan/2026 especificamente, os meses que o backfill reportou
como corrigidos na agregação geral — mas essa melhora veio de outro lugar, não daqui: os +44
registros do backfill caíram em `receber_pagar='P'`, não `R`). Evidência de que o valor do quadro
não reflete dívida real: o cliente `cod_cliente=1000040` ("LG - SERVICOS"/"Líder Gravataí", hoje
#1 do ranking com R$ 310 mil / 307 faturas) tinha taxa de baixa normal de 80–100% entre jan/2024 e
fev/2025, caiu pra 0% a partir de mar/2025 e **segue exatamente em 0% até hoje** — não é
comportamento real de inadimplência, é o mesmo apagão de sincronização, ainda não corrigido nesse
portal especificamente. Separadamente, o portal `19926` (Ecoville Itapema, `cnpj
34881719000109`) nunca teve **nenhuma** baixa de `receber_pagar='R'` em toda a história
sincronizada (não é um gap desde mai/2025, é ausência total) — pode ser processo de cobrança fora
do Microvix pra essa loja, a confirmar com o lojista. **Enquanto isso não for resolvido no
`camera300`, os valores do quadro "Top 10 Inadimplentes" não são confiáveis como dívida real —
refletem principalmente o buraco de sincronização, não inadimplência de fato.**

**Visitação — edição de `faciais.people` (2026-08):** na tela `/visitacao` (web e mobile), cada
card de cliente tem um botão de editar (&#9998;) que abre um formulário (modal `<dialog>` na web,
bottom-sheet no mobile) para corrigir os dados da pessoa reconhecida. Campos editáveis: `full_name`,
`nickname`, `document`, `phone`, `email`, `birth_date`, `age`, `gender_id`, `notes`
(`phone`/`email`, 2026-08, colunas compartilhadas com o camera300 — migration
`migrations/add_people_contato.sql`). **Não editáveis** por esta tela:
`person_type_id` (a lista só mostra `person_type_id='C'`; trocar o tipo faria o registro desaparecer
da visitação) e os campos de integração do pipeline facial (`crm_key`, `reference_track_id`). Rota:
`POST /visitacao/pessoa/<person_id>` (`auth.visitacao_editar_pessoa` / `mobile.visitacao_editar_pessoa`),
que faz `UPDATE faciais.people` e redireciona de volta pra `/visitacao` preservando
`company_id`/`store_id`/`date` (enviados como campos hidden no form). Web usa `flash()` pra
confirmar sucesso/erro; mobile não tem `flash()` (base mobile não renderiza flashed messages) —
em caso de erro no `UPDATE`, redireciona com `?pessoa_erro=1` e a página mostra um banner inline.
Cada card também exibe `person_id` (ex: `#1234`) centralizado abaixo da foto/placeholder (2026-08,
`.vis-photo-wrap`/`.vis-person-id` na web, `.m-vis-photo-wrap`/`.m-vis-person-id` no mobile) —
identificador visual rápido do cadastro em `faciais.people`, sem link/ação associada.

## Template filters registrados em `app.py`

- `br_valor(value, symbol='')` — formata BR com R$, %, ou unidade
- `br_valor_k(value)` — formata em milhares: "R$ 12,3k"
- `fmt_cep(cep)` — formata para `00000-000`

---

## Banco de Dados

> **Referência definitiva do schema:** `C:\Users\ferna\db-docs\lojas\doc_faciais.sql` e `doc_microvix.sql` — pasta **compartilhada entre todas as aplicações locais que usam o banco `lojas`** (não só o retail_analytics; ver `C:\Users\ferna\db-docs\lojas\README.md`), pra evitar cópias divergentes por projeto. Gerada por introspecção direta do banco de produção (PyCharm Database tools / MCP). Comentários de coluna de `doc_faciais.sql` vêm de `COMMENT ON` já existentes no banco; os de `doc_microvix.sql` vêm da especificação oficial do Web Service (PDF incluído na mesma pasta compartilhada) já que o schema `microvix` não tem `COMMENT ON` — é dado sincronizado do ERP. Regenerar (e sobrescrever os arquivos na pasta compartilhada) quando o schema mudar (nova migration, nova tabela sincronizada). Havia uma cópia local em `_documentacao/base_de_dados/` (gitignored) de antes desse compartilhamento — pode ficar defasada, preferir sempre a pasta compartilhada.
>
> **Schema `itumbiara` no mesmo banco `lojas`:** existe um schema `itumbiara` (tabelas `cameras`, `estabelecimentos`, `pessoas`, `eventos_faciais`, `evento_matches`, `sync_control`) na mesma instância Postgres, mas **não tem nenhuma relação com este projeto** — nenhum código do repositório o referencia. Parece um sistema de reconhecimento facial separado/legado para uma rede específica. Ignorar ao investigar o schema deste projeto.

### Schema `faciais`

#### Tabelas de referência (lookups)

| Tabela | Descrição |
|---|---|
| `camera_types` | Tipos de câmera (PK: `camera_type_id bpchar(1)`) |
| `company_groups` | Grupos de empresas clientes (PK: `company_group_id serial`) |
| `company_types` | Tipos de empresa — franquia, loja própria, etc. (PK: `company_type_id serial`) |
| `day_types` | Tipos de dia com `weight` (0.0–1.0) para cálculo de metas (PK: `day_type_id varchar(20)`) |
| `genders` | Gêneros (PK: `gender_id bpchar(1)`) |
| `goal_periods` | Períodos de apuração — daily, weekly, monthly, etc. (PK: `goal_period_id varchar(20)`) |
| `goal_units` | Unidades de medida das metas — pct, brl, qty, min (PK: `goal_unit_id varchar(20)`) |
| `person_types` | Tipos de pessoa na loja (PK: `person_type_id bpchar(1)`) |
| `ranking_rules` | Regras de pontuação para ranking de clientes por loja. Campos: `analysis_period_days`, `min_visits_required`, `points_per_visit_with_purchase` (default 100), `points_per_visit_no_purchase` (default 20), `points_per_currency_unit` (default 0.5), `is_active` |
| `retailer_groups` | Grupos de lojistas (mesmo dono) |
| `screens` | Telas disponíveis no sistema |
| `user_types` | Tipos de usuário: adm/man/ret/emp |

#### Entidades core

| Tabela | Colunas-chave |
|---|---|
| `companies` | `company_id`, `company_name`, `company_group_id`, `company_type_id`, `fiscal_year_start_date` |
| `stores` | `store_id`, `company_id`, `retailer_group_id`, `store_name`, `cnpj`, `uf`, `city`, `calendar_profile_id`, `microvix_portal`, `ranking_rule_id` |
| `cameras` | `camera_id` (manual), `camera_type_id`, `store_id`, `camera_name`, `rtsp_url`, `heat_camera_id` |
| `users` | `user_id`, `username`, `full_name`, `email`, `password_hash`, `user_type_id`, `is_active`, `last_company_group_id`, `last_retailer_group_id`, `last_store_id` |
| `people` | `person_id`, `full_name`, `nickname`, `document`, `phone`, `email`, `crm_key`, `birth_date`, `age`, `gender_id`, `person_type_id`, `reference_track_id`, `notes` |
| `company_themes` | `company_id`, cores HEX (`primary_color`, `secondary_color`, `accent_color`, `text_color`, `background_color`, `graph_color_1..4`), `logo_url` |
| `store_serie_rules` | `store_serie_rule_id`, `store_id` (FK cascade), `person_kind` (`PF`/`PJ`), `serie` (série da NF). Unique `(store_id, serie)`. Ver seção "Séries PF vs. PJ" acima |

**Paleta padrão:** primary=`#F47B20`, secondary=`#0057A8`, accent=`#FFFFFF`, text=`#000000`, bg=`#F5F5F5`, graph 1–4: `#1339F6`, `#44AC0C`, `#F08205`, `#DC0929`

#### Calendário e feriados

| Tabela | Descrição |
|---|---|
| `calendar` | Calendário base nacional. Colunas: `calendar_date` (PK date), `year`, `month`, `day`, `week_number`, `day_of_week` (0=dom,6=sab), `quarter`, `day_type_id`, `holiday_name` |
| `business_calendar_profiles` | Perfis reutilizáveis de funcionamento (Shopping, Varejo Rua, B2B). Define `saturday_day_type` e `sunday_day_type` |
| `geo_holidays` | Feriados estaduais/municipais. Campos: `holiday_date`, `holiday_name`, `day_type_id`, `scope` (state/city), `uf`, `city` |
| `store_calendar_exceptions` | Exceções pontuais por loja sobrescrevendo o calendário base. Campos: `store_id`, `calendar_date`, `day_type_id`, `exception_name` |

#### Reconhecimento facial

| Tabela | Descrição |
|---|---|
| `json_records` | Payloads JSON brutos das câmeras. Campos: `json_record_id`, `payload jsonb`, `log_id` |
| `detection_records` | Detecções faciais processadas. Campos: `detection_record_id`, `json_record_id`, `track_id`, `detection_score`, `recognition_score`, `image_path`, `camera_id`, `person_id`, `store_id`, `log_id` |
| `zions_identified_records` | Eventos do analítico ZIONS em que a pessoa já veio identificada por nome (não passam pelo pipeline Heimdall). Guardados só para consulta direta no banco — **não é lida por nenhuma rota/query do código atual**. Campos: `log_id`, `track_id`, `camera_id`, `full_name`, `score`, `payload jsonb` |

#### Ranking de clientes

| Tabela | Descrição |
|---|---|
| `customer_ranking` | **Cache diário** do ranking (populado pelo cron `scripts/recalcular_ranking.py` a partir de `vw_customer_ranking`; truncado e recalculado a cada ciclo). Campos: `store_id`, `ranking_rule_id`, `analysis_period_days`, `ranking_position`, `person_id`, `total_visits`, `visits_with_purchase`, `visits_no_purchase`, `total_spent`, `score`, `calculated_at` |

#### Metas

| Tabela | Descrição |
|---|---|
| `goals` | Catálogo de metas. Campos: `goal_id`, `goal_name`, `goal_description`, `goal_unit_id`, `direction` (H=maior melhor/L=menor melhor/B=binária), `base_period_id`, `is_active`. IDs fixos: 1=Faturamento na loja (monthly), 2=Ticket Médio (daily), 3=Faturamento Total/Motor (monthly), 4=Pedidos Gerados (weekly, `brl`, por vendedor — 2026-08; **valor R$ dos pedidos, não quantidade**) |
| `goal_targets` | Alocação de meta a entidade (store/company/company_group/**seller**, desde 2026-08). Campos: `goal_target_id`, `goal_id`, `entity_type`, `store_id`, `company_id`, `company_group_id`, `seller_id`, `is_active`, `distribution_mode` (`calendar_weight` padrão \| `full_days_only`, por alocação) |
| `goal_value_templates` | Valor recorrente com vigência. Campos: `template_id`, `goal_target_id`, `goal_period_id`, `target_value`, `date_from`, `date_to` (NULL=sem fim) |
| `goal_values` | Override pontual por data de referência. Campos: `goal_value_id`, `goal_target_id`, `goal_period_id`, `reference_date`, `target_value`, `actual_value`, `is_closed` |
| `goal_breakdowns` | Legado (não usada mais desde 2026-08) — registrava vínculo pai→filho do antigo desdobramento manual em daily/weekly. Sempre vazia daqui pra frente. |
| `sellers` | Identidade local de vendedores elegíveis a receber meta. Campos: `seller_id`, `store_id`, `cod_vendedor` (Microvix, escopado por loja/portal), `seller_name`, `is_active`. Alimentada por uma aplicação externa (`camera300`) que sincroniza o schema `microvix` — o retail_analytics só lê. Referenciada por `goal_targets.seller_id` (`entity_type='seller'`). |

**Cadastro só em nível mensal (goals 1 e 3), diário (goal 2, Ticket Médio) ou semanal (goal 4,
Pedidos Gerados) — desde 2026-08.** `goal_values`/`goal_value_templates` só aceitam `goal_period_id`
= `base_period_id` do goal (a UI em `/retail_analytics/metas/objetivos/<id>/alocacoes/<id>/valores|vigencias`
já restringe isso). Não existe desdobramento manual em diário/semanal — `metas.get_metas()` e
`metas.meta_faturamento_acum_diario()` calculam diário/semanal **sempre em tempo real** a partir do
valor mensal cadastrado, distribuído pelos dias proporcionalmente ao `day_weight` de `vw_store_calendar`
(sábado sai com peso reduzido, ex: 0.5 via perfil "Varejo Rua"). Ticket Médio (`goal_id=2`) é cadastrado
só em nível diário e seu valor efetivo também é multiplicado pelo `day_weight` do dia. Ver `metas.py:
_distribuir_mensal` / `_weekly_target`.

**Meta por vendedor (`goal_id=4`, Pedidos Gerados) — 2026-08, completo.** Cadastro semanal
(`base_period_id='weekly'`) por `seller_id`, feito em `/retail_analytics/metas/objetivos/4/alocacoes`
(tipo de entidade "Vendedor": escolhe loja → vendedor → `distribution_mode`). `distribution_mode` por
alocação controla como a semana se distribui em dias: `calendar_weight` = mesma lógica de
`_distribuir_mensal` (proporcional ao `day_weight`); `full_days_only` = só dias com peso exatamente 1.0
recebem meta (dividido igualmente entre eles), demais dias (sábado, meio período etc) ficam zero.
"Realizado" soma `valor_total` (R$) por vendedor em `microvix.microvix_pedidos_venda` (todo lançamento,
`aprovado` ou não, excluindo só `cancelado='S'`) via `people.pedidos_gerados_por_loja`. Cálculo:
`metas.pedidos_meta_semana_por_loja(store_id, semana_inicio)`. Exibido no quadro "Pedidos" de
**Relatórios > Pedidos** (`relatorios.pedidos`, web only — 2026-08, movido de dentro de Motor >
Vendas; não existe equivalente mobile, foi removido de lá) — colunas Meta/Realizado por semana,
formatadas em R$ via `br_valor_k`; clicar num vendedor mostra o dia a dia da semana.

**Precedência de metas:** `goal_values` (override pontual) > `goal_value_templates` (recorrente)

**Precedência de metas:** `goal_values` (override pontual) > `goal_value_templates` (recorrente)

#### Controle de acesso

| Tabela | Descrição |
|---|---|
| `user_company_groups` | man → company_group |
| `user_retailer_groups` | ret → retailer_group |
| `user_stores` | emp → store |
| `user_type_screens` | Permissão de tela por tipo de usuário (exceto adm que acessa tudo) |

#### Integração fiscal

| Tabela | Descrição |
|---|---|
| `person_purchases` | Vínculo NF × pessoa reconhecida. Campos: `person_purchase_id`, `person_id` (NULL=não identificado), `store_id`, `bill` (nº NF, único por loja), `is_cancelled`, `is_identified` |

#### Views e materialized views

| View | Descrição |
|---|---|
| `vw_store_calendar` | Calendário efetivo por loja. Hierarquia: exceção loja > feriado municipal > estadual > nacional > perfil > padrão. Campo `day_weight` e `is_working_day` |
| `vw_user_screen_access` | Todas as telas acessíveis por usuário (adm acessa tudo via CROSS JOIN) |
| `vw_user_store_access` | Todas as lojas acessíveis por usuário considerando tipo |
| `vw_goal_daily_target` | Valor efetivo da meta: prioriza override (goal_values) sobre template |
| `vw_goal_performance` | Apuração com `achievement_pct` e `status` (achieved/not_achieved/pending/no_target) |
| `vw_customer_ranking` | Ranking de clientes em tempo real (fonte do cache `customer_ranking`). Score = (visitas_com_compra × pts) + (visitas_sem_compra × pts) + (total_gasto × pts_por_real). Usa `mv_microvix_vendas` para performance |
| `mv_microvix_vendas` *(MATERIALIZED)* | Cache de vendas válidas do Microvix, usado como fonte de `vw_customer_ranking`. Precisa de `REFRESH` antes do cálculo do ranking — feito pelo cron. Filtro: `cod_natureza_operacao='10030'`/`cancelado<>'S'`/`excluido<>'S'`/`soma_relatorio='S'`, `tipo_transacao` em `('P','V','S')` ou NULL, `documento IS NOT NULL`, e `serie` restrito às séries PF da loja via join com `faciais.store_serie_rules` (`person_kind='PF'`, join por `stores.cnpj = microvix_movimento.cnpj_emp`) — corrigido em 2026-08-15 para não depender de lista fixa de séries |
| `vw_store_series` | Séries PF e PJ por loja agregadas em array (`series_pf`, `series_pj`) a partir de `store_serie_rules`, para uso em filtros de `microvix_movimento` |
| `vw_primeira_aparicao_clientes` *(MATERIALIZED)* | Primeira detecção de cada cliente (person_type_id='C'). Campo `first_record`. Index único em `person_id` |

**Funções:** `fn_set_updated_at()` — trigger que atualiza `updated_at` em todas as tabelas. `create_updated_at_trigger(p_table)` — helper para criar trigger em nova tabela.

---

### Schema `microvix`

Dados sincronizados do ERP Microvix via API. Chaves compostas geralmente incluem `portal` + identificador de negócio.

#### Tabelas principais

| Tabela | Chave primária | Descrição |
|---|---|---|
| `microvix_grupo_lojas` | `(portal, empresa)` | Grupos de lojas / redes |
| `microvix_lojas` | `(portal, empresa)` | Lojas com CNPJ, endereço, regime tributário |
| `microvix_movimento` | `(portal, cnpj_emp, transacao, cod_produto)` | **Tabela de vendas/transações PDV** — colunas de valor: `valor_total`, `valor_liquido`, `desconto`, `quantidade`, `preco_unitario`; operação: `operacao`, `tipo_transacao`, `cod_natureza_operacao`, `cancelado`, `excluido`, `soma_relatorio` |
| `microvix_produtos` | `(portal, cod_produto)` | Cadastro de produtos: nome, referência, setor, linha, marca, coleção, cor, tamanho |
| `microvix_produtos_detalhes` | `(portal, empresa, cod_produto)` | Estoque atual por empresa: `quantidade`, `preco_venda`, `preco_custo`, `custo_medio` |
| `microvix_clientes_fornecedores` | `(portal, cod_cliente)` | Clientes e fornecedores: nome, CPF/CNPJ, endereço, data nascimento, sexo |
| `microvix_vendedores` | `(portal, cod_vendedor)` | Vendedores: nome, CPF, cargo, ativo, datas admissão/saída |
| `microvix_faturas` | `(portal, cnpj_emp, codigo_fatura)` | Faturas e recebimentos. Ver seção "Inadimplência" acima — só `forma_pgto='Crediário'` tem `cod_cliente` confiável (Cartão aponta pra adquirente, não pro cliente) |
| `microvix_pedidos_venda` | `(portal, cnpj_emp, transacao, cod_produto)` | Pedidos de venda |
| `microvix_pedidos_compra` | `(portal, cnpj_emp, cod_pedido, cod_produto)` | Pedidos de compra |
| `microvix_produtos_inventario` | `(portal, cnpj_emp, cod_produto)` | Inventário por empresa |
| `microvix_produtos_depositos` | `(portal, cod_deposito)` | Depósitos |
| `microvix_produtos_promocoes` | `(portal, cnpj_emp, cod_produto, id_campanha)` | Promoções ativas |
| `microvix_produtos_tabelas` | `(portal, cnpj_emp, id_tabela)` | Tabelas de preço |
| `microvix_produtos_tabelas_precos` | `(portal, cnpj_emp, id_tabela, cod_produto)` | Preços por tabela |
| `microvix_metas_vendedores` | `(portal, cnpj_emp, id_meta)` | Metas de vendedores no Microvix |
| `microvix_fidelidade` | `(portal, id_fidelidade_parceiro_log)` | Programa de fidelidade |
| `microvix_sync_control` | `(metodo, cnpj_emp)` | Controle de sincronização: `last_timestamp`, `last_sync_at` |
| `microvix_carga` | `id_carga` | Log de cargas incrementais |
| `microvix_carga_full` | `id` | Log de cargas completas (contagens em JSONB) |
| `microvix_clientes_fornec_campos_adicionais` | `(portal, cod_cliente, campo)` | Campos extras de clientes |
| `microvix_clientes_fornec_classes` | `(portal, cod_cliente, cod_classe)` | Classes de clientes |

#### Índices relevantes em `microvix_movimento`

- `idx_mv_portal_cnpj_data` — `(portal, cnpj_emp, data_documento)` — filtro principal de período
- `idx_mv_portal_cnpj_doc` — `(portal, cnpj_emp, documento)` — JOIN com `person_purchases.bill`
- `idx_mov_cod_cliente`, `idx_mov_cod_produto`, `idx_mov_operacao`, `idx_mov_data_doc`

---

## APIs Externas

- **Imagens faciais:** `HEIMDALL_IMAGE_BASE = http://201.71.234.83:6500/api/facial/images`
- **Heatmap:** `HEATMAP_API_URL = http://201.71.234.84:5001/api/heatmap`

## PWA

Manifest + service worker (`/sw.js`), escopo `/retail_analytics/m/`. Logo salva em `/static/img/logos/company_{id}.{ext}`.
