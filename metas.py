# metas.py
# Consulta metas do banco de dados.
# goal_id=1: Faturamento  |  goal_id=2: Ticket Médio
# Alocação buscada por entity_type='store' e store_id fornecido pelo dashboard.
#
# Precedência (mesma lógica da vw_goal_daily_target):
#   1. goal_values com reference_date exata → override pontual
#   2. goal_value_templates com vigência ativa → valor recorrente

from datetime import date
import db

_GOAL_FATURAMENTO       = 1
_GOAL_TICKET_MEDIO      = 2
_GOAL_FATURAMENTO_TOTAL = 3


def _target_id(goal_id, store_id):
    row = db.query_one("""
        SELECT goal_target_id FROM faciais.goal_targets
        WHERE  goal_id = %s AND entity_type = 'store'
          AND  store_id = %s AND is_active = TRUE
        LIMIT 1
    """, (goal_id, store_id))
    return row['goal_target_id'] if row else None


def _goal_value(target_id, period_id, ref_date):
    """
    Retorna target_value para o target/período/data.
    Prioriza override pontual (goal_values) sobre template recorrente.
    """
    # 1. Override pontual
    row = db.query_one("""
        SELECT target_value FROM faciais.goal_values
        WHERE  goal_target_id = %s AND goal_period_id = %s AND reference_date = %s
    """, (target_id, period_id, ref_date))
    if row and row['target_value'] is not None:
        return float(row['target_value'])

    # 2. Template com vigência ativa na data
    row = db.query_one("""
        SELECT target_value FROM faciais.goal_value_templates
        WHERE  goal_target_id = %s AND goal_period_id = %s
          AND  date_from <= %s
          AND  (date_to IS NULL OR date_to >= %s)
        ORDER  BY date_from DESC
        LIMIT  1
    """, (target_id, period_id, ref_date, ref_date))
    if row and row['target_value'] is not None:
        return float(row['target_value'])

    return None


def _ytd_fat(target_id, data_dia, mes_inicio):
    """
    Soma das metas mensais de jan/ano até mes_inicio,
    resolvendo override + template para cada mês em uma única query.
    """
    rows = db.query_all("""
        SELECT
            m.month_start,
            COALESCE(
                gv.target_value,
                gvt.target_value
            ) AS target_value
        FROM generate_series(
            date_trunc('year', %s::date)::date,
            %s::date,
            '1 month'::interval
        ) AS m(month_start)
        LEFT JOIN faciais.goal_values gv
            ON  gv.goal_target_id = %s
            AND gv.goal_period_id  = 'monthly'
            AND gv.reference_date  = m.month_start
        LEFT JOIN LATERAL (
            SELECT target_value FROM faciais.goal_value_templates
            WHERE  goal_target_id = %s
              AND  goal_period_id  = 'monthly'
              AND  date_from      <= m.month_start
              AND  (date_to IS NULL OR date_to >= m.month_start)
            ORDER  BY date_from DESC
            LIMIT  1
        ) gvt ON TRUE
    """, (data_dia, mes_inicio, target_id, target_id))

    return sum(float(r['target_value']) for r in (rows or []) if r['target_value'] is not None)


def meta_faturamento_mes(store_id, mes_inicio):
    """Retorna a meta mensal de faturamento para a loja, ou None se não configurada."""
    fat_tid = _target_id(_GOAL_FATURAMENTO, store_id)
    if fat_tid is None:
        return None
    return _goal_value(fat_tid, 'monthly', mes_inicio)


def meta_faturamento_acum_diario(store_id, mes_inicio, mes_fim):
    """
    Retorna (daily_dict, meta_total) para o gráfico Motor — Faturamento.
    - daily_dict : {dia_do_mes: valor_meta_diaria}  (acumula no chamador)
    - meta_total : soma de todos os dias do mês (None se sem meta configurada)

    Prioridade:
    1. Desdobramento diário em goal_values / goal_value_templates (period='daily')
    2. Meta mensal (period='monthly') distribuída pelos dias úteis com peso
       usando vw_store_calendar (hierarquia: exceção > feriado geo > perfil > base)
    """
    fat_tid = _target_id(_GOAL_FATURAMENTO_TOTAL, store_id)
    if fat_tid is None:
        return {}, None

    # ── 1. Tenta desdobramento diário ────────────────────────────────────────
    rows = db.query_all("""
        SELECT EXTRACT(DAY FROM d.day)::int AS dia,
               COALESCE(gv.target_value, gvt.target_value) AS valor
        FROM   generate_series(%s::date, %s::date, '1 day'::interval) AS d(day)
        LEFT   JOIN faciais.goal_values gv
               ON  gv.goal_target_id = %s
               AND gv.goal_period_id  = 'daily'
               AND gv.reference_date  = d.day
        LEFT   JOIN LATERAL (
            SELECT target_value FROM faciais.goal_value_templates
            WHERE  goal_target_id = %s
              AND  goal_period_id  = 'daily'
              AND  date_from      <= d.day
              AND  (date_to IS NULL OR date_to >= d.day)
            ORDER  BY date_from DESC LIMIT 1
        ) gvt ON TRUE
        WHERE  COALESCE(gv.target_value, gvt.target_value) IS NOT NULL
    """, (mes_inicio, mes_fim, fat_tid, fat_tid))

    if rows:
        daily = {r['dia']: float(r['valor']) for r in rows}
        return daily, sum(daily.values())

    # ── 2. Distribui meta mensal pelos dias úteis com peso ───────────────────
    monthly = _goal_value(fat_tid, 'monthly', mes_inicio)
    if monthly is None:
        return {}, None

    cal_rows = db.query_all("""
        SELECT EXTRACT(DAY FROM calendar_date)::int AS dia, day_weight
        FROM   faciais.vw_store_calendar
        WHERE  store_id      = %s
          AND  calendar_date BETWEEN %s AND %s
        ORDER  BY calendar_date
    """, (store_id, mes_inicio, mes_fim))

    total_peso = sum(float(r['day_weight']) for r in cal_rows)
    if total_peso == 0:
        return {}, float(monthly)

    daily = {
        r['dia']: round(float(monthly) * float(r['day_weight']) / total_peso, 2)
        for r in cal_rows if float(r['day_weight']) > 0
    }
    return daily, float(monthly)


def get_metas(store_id,
              data_dia,
              semana_inicio, semana_fim,
              mes_inicio, mes_fim,
              ytd_inicio, ytd_fim):
    """
    Retorna dict com metas para todos os períodos do dashboard,
    ou None se não houver alocação ativa de faturamento para a loja.
    """
    fat_tid = _target_id(_GOAL_FATURAMENTO, store_id)
    if fat_tid is None:
        return None

    fat_dia    = _goal_value(fat_tid, 'daily',   data_dia)      or 0.0
    fat_semana = _goal_value(fat_tid, 'weekly',  semana_inicio) or 0.0
    fat_mes    = _goal_value(fat_tid, 'monthly', mes_inicio)    or 0.0
    fat_ytd    = _ytd_fat(fat_tid, data_dia, mes_inicio)

    # Sem nenhum valor configurado, não exibe seção de metas
    if fat_dia == 0.0 and fat_semana == 0.0 and fat_mes == 0.0:
        return None

    # Ticket médio: valor por transação — busca qualquer template ativo na data,
    # sem filtrar por período (ticket médio não depende da janela de tempo)
    ticket_medio = 0.0
    tkt_tid = _target_id(_GOAL_TICKET_MEDIO, store_id)
    if tkt_tid:
        row = db.query_one("""
            SELECT COALESCE(gv.target_value, gvt.target_value) AS target_value
            FROM (SELECT 1) _base
            LEFT JOIN faciais.goal_values gv
                ON  gv.goal_target_id = %s
                AND gv.reference_date  = %s
            LEFT JOIN LATERAL (
                SELECT target_value FROM faciais.goal_value_templates
                WHERE  goal_target_id = %s
                  AND  date_from     <= %s
                  AND  (date_to IS NULL OR date_to >= %s)
                ORDER  BY date_from DESC
                LIMIT  1
            ) gvt ON TRUE
        """, (tkt_tid, data_dia, tkt_tid, data_dia, data_dia))
        if row and row['target_value'] is not None:
            ticket_medio = float(row['target_value'])

    return {
        'faturamento_dia':    fat_dia,
        'faturamento_semana': fat_semana,
        'faturamento_mes':    fat_mes,
        'faturamento_ytd':    fat_ytd,
        'ticket_medio':       ticket_medio,
    }
