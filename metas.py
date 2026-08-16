# metas.py
# Consulta metas do banco de dados.
# goal_id=1: Faturamento na loja  |  goal_id=2: Ticket Médio  |  goal_id=3: Faturamento Total
# Alocação buscada por entity_type='store' e store_id fornecido pelo dashboard.
#
# Cadastro só em nível mensal para os goals de faturamento (period='monthly') e diário
# para Ticket Médio (period='daily') — não existe mais desdobramento manual em semanal/diário.
# Precedência na resolução do valor cadastrado (mesma lógica da vw_goal_daily_target):
#   1. goal_values com reference_date exata → override pontual
#   2. goal_value_templates com vigência ativa → valor recorrente
#
# Metas diárias e semanais de faturamento são SEMPRE calculadas em tempo real a partir da
# meta mensal cadastrada, distribuída pelos dias do mês proporcionalmente ao peso de cada dia
# em faciais.vw_store_calendar (hierarquia: exceção loja > feriado geo > perfil > calendário
# base — sábado já sai com peso reduzido pelo day_type do perfil da loja, ex: 0.5).
# Ticket Médio é um valor cadastrado por dia (não se distribui um total), mas seu valor
# efetivo também é escalado pelo peso do dia — assim o sábado sai proporcionalmente menor
# que um dia útil sem precisar de um segundo valor cadastrado.

import calendar
from datetime import date, timedelta
import db

_GOAL_FATURAMENTO       = 1
_GOAL_TICKET_MEDIO      = 2
_GOAL_FATURAMENTO_TOTAL = 3
_GOAL_PEDIDOS_GERADOS   = 4


def _target_id(goal_id, store_id):
    row = db.query_one("""
        SELECT goal_target_id FROM faciais.goal_targets
        WHERE  goal_id = %s AND entity_type = 'store'
          AND  store_id = %s AND is_active = TRUE
        LIMIT 1
    """, (goal_id, store_id))
    return row['goal_target_id'] if row else None


def _target_seller(goal_id, seller_id):
    """Retorna (goal_target_id, distribution_mode) da alocação ativa do goal para o vendedor,
    ou (None, None) se não houver alocação."""
    row = db.query_one("""
        SELECT goal_target_id, distribution_mode FROM faciais.goal_targets
        WHERE  goal_id = %s AND entity_type = 'seller'
          AND  seller_id = %s AND is_active = TRUE
        LIMIT 1
    """, (goal_id, seller_id))
    return (row['goal_target_id'], row['distribution_mode']) if row else (None, None)


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


def _distribuir_mensal(store_id, target_id, ref_date):
    """
    Distribui a meta mensal cadastrada (period='monthly') do mês de ref_date pelos dias
    desse mês, proporcional ao peso de cada dia em faciais.vw_store_calendar (hierarquia:
    exceção loja > feriado geo > perfil > calendário base — ex: sábado com peso 0.5).

    Retorna (dict {date: valor_do_dia}, valor_mensal_cadastrado). Se não houver meta mensal
    cadastrada para o mês, retorna ({}, None).
    """
    mes_inicio = ref_date.replace(day=1)
    mes_fim    = ref_date.replace(day=calendar.monthrange(ref_date.year, ref_date.month)[1])

    monthly = _goal_value(target_id, 'monthly', mes_inicio)
    if monthly is None:
        return {}, None

    cal_rows = db.query_all("""
        SELECT calendar_date, day_weight
        FROM   faciais.vw_store_calendar
        WHERE  store_id      = %s
          AND  calendar_date BETWEEN %s AND %s
    """, (store_id, mes_inicio, mes_fim))

    total_peso = sum(float(r['day_weight']) for r in cal_rows)
    if total_peso == 0:
        return {}, float(monthly)

    daily = {
        r['calendar_date']: round(float(monthly) * float(r['day_weight']) / total_peso, 2)
        for r in cal_rows if float(r['day_weight']) > 0
    }
    return daily, float(monthly)


def _weekly_target(store_id, target_id, semana_inicio, semana_fim):
    """Soma das metas diárias (calculadas em tempo real) de cada dia da semana. A semana pode
    cruzar a virada do mês — cada dia usa a meta mensal e o peso do seu próprio mês."""
    total = 0.0
    cache = {}
    d = semana_inicio
    while d <= semana_fim:
        key = (d.year, d.month)
        if key not in cache:
            cache[key], _ = _distribuir_mensal(store_id, target_id, d)
        total += cache[key].get(d, 0.0)
        d += timedelta(days=1)
    return round(total, 2)


def _distribuir_semanal(store_id, target_id, semana_inicio, distribution_mode='calendar_weight'):
    """
    Distribui a meta semanal cadastrada (period='weekly') pelos dias dessa semana
    (semana_inicio = segunda-feira). Duas modalidades, por alocação
    (faciais.goal_targets.distribution_mode):
    - 'calendar_weight': proporcional ao day_weight de vw_store_calendar — mesma lógica de
      _distribuir_mensal (sábado sai reduzido conforme o perfil de calendário da loja).
    - 'full_days_only': só dias com peso exatamente 1.0 (dia cheio) recebem meta, dividida
      igualmente entre eles; demais dias (sábado, meio período, feriado etc) ficam zero.

    Retorna (dict {date: valor_do_dia}, valor_semanal_cadastrado). Se não houver meta semanal
    cadastrada, retorna ({}, None).
    """
    semana_fim = semana_inicio + timedelta(days=6)

    weekly = _goal_value(target_id, 'weekly', semana_inicio)
    if weekly is None:
        return {}, None

    cal_rows = db.query_all("""
        SELECT calendar_date, day_weight
        FROM   faciais.vw_store_calendar
        WHERE  store_id      = %s
          AND  calendar_date BETWEEN %s AND %s
    """, (store_id, semana_inicio, semana_fim))

    if distribution_mode == 'full_days_only':
        full_days = [r['calendar_date'] for r in cal_rows if float(r['day_weight']) == 1.0]
        if not full_days:
            return {}, float(weekly)
        share = round(float(weekly) / len(full_days), 2)
        daily = {d: share for d in full_days}
    else:
        total_peso = sum(float(r['day_weight']) for r in cal_rows)
        if total_peso == 0:
            return {}, float(weekly)
        daily = {
            r['calendar_date']: round(float(weekly) * float(r['day_weight']) / total_peso, 2)
            for r in cal_rows if float(r['day_weight']) > 0
        }
    return daily, float(weekly)


def meta_pedidos_semana(seller_id, store_id, semana_inicio):
    """
    Retorna (daily_dict, meta_semana) da meta de Pedidos Gerados (goal_id=4) para um vendedor
    numa semana (semana_inicio = segunda-feira), respeitando o distribution_mode da alocação.
    ({}, None) se não houver alocação/meta ativa para o vendedor.
    """
    target_id, distribution_mode = _target_seller(_GOAL_PEDIDOS_GERADOS, seller_id)
    if target_id is None:
        return {}, None
    return _distribuir_semanal(store_id, target_id, semana_inicio, distribution_mode)


def meta_faturamento_acum_diario(store_id, mes_inicio, mes_fim):
    """
    Retorna (daily_dict, meta_total) para o gráfico Motor — Faturamento.
    - daily_dict : {dia_do_mes: valor_meta_diaria}, calculado em tempo real a partir da
      meta mensal cadastrada (ver _distribuir_mensal)
    - meta_total : valor mensal cadastrado (None se sem meta configurada)

    mes_fim é aceito por compatibilidade de assinatura, mas o mês considerado é sempre o de
    mes_inicio (os chamadores atuais só passam intervalos dentro de um único mês).
    """
    fat_tid = _target_id(_GOAL_FATURAMENTO_TOTAL, store_id)
    if fat_tid is None:
        return {}, None

    by_date, meta_total = _distribuir_mensal(store_id, fat_tid, mes_inicio)
    if meta_total is None:
        return {}, None

    daily = {d.day: v for d, v in by_date.items()}
    return daily, meta_total


def get_metas(store_id,
              data_dia,
              semana_inicio, semana_fim,
              mes_inicio, mes_fim,
              ytd_inicio, ytd_fim):
    """
    Retorna dict com metas para todos os períodos do dashboard,
    ou None se não houver alocação ativa de faturamento para a loja.

    Diário e semanal de faturamento são calculados em tempo real a partir da meta mensal
    cadastrada (ver _distribuir_mensal / _weekly_target) — não há mais leitura de
    desdobramento manual salvo em goal_values/goal_value_templates period='daily'/'weekly'.
    """
    fat_tid = _target_id(_GOAL_FATURAMENTO, store_id)
    if fat_tid is None:
        return None

    fat_mes = _goal_value(fat_tid, 'monthly', mes_inicio) or 0.0

    # Sem meta mensal cadastrada, não exibe seção de metas
    if fat_mes == 0.0:
        return None

    by_date, _ = _distribuir_mensal(store_id, fat_tid, data_dia)
    fat_dia    = by_date.get(data_dia, 0.0)
    fat_semana = _weekly_target(store_id, fat_tid, semana_inicio, semana_fim)
    fat_ytd    = _ytd_fat(fat_tid, data_dia, mes_inicio)

    # Ticket médio: valor diário cadastrado (period='daily') escalado pelo peso do dia
    # (faciais.vw_store_calendar) — assim o sábado sai proporcionalmente menor que um dia
    # útil sem precisar de um segundo valor cadastrado.
    ticket_medio = 0.0
    tkt_tid = _target_id(_GOAL_TICKET_MEDIO, store_id)
    if tkt_tid:
        tkt_valor = _goal_value(tkt_tid, 'daily', data_dia)
        if tkt_valor:
            peso_row = db.query_one("""
                SELECT day_weight FROM faciais.vw_store_calendar
                WHERE  store_id = %s AND calendar_date = %s
            """, (store_id, data_dia))
            peso = float(peso_row['day_weight']) if peso_row else 1.0
            ticket_medio = round(float(tkt_valor) * peso, 2)

    return {
        'faturamento_dia':    fat_dia,
        'faturamento_semana': fat_semana,
        'faturamento_mes':    fat_mes,
        'faturamento_ytd':    fat_ytd,
        'ticket_medio':       ticket_medio,
    }
