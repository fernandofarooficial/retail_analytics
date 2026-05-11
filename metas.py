# metas.py
# Consulta metas do banco de dados.
# goal_id=1: Faturamento  |  goal_id=2: Ticket Médio
# Alocação buscada por entity_type='company' e company_id fornecido pelo dashboard.

from datetime import date
import db

_GOAL_FATURAMENTO  = 1
_GOAL_TICKET_MEDIO = 2


def _target_id(goal_id, store_id):
    row = db.query_one("""
        SELECT goal_target_id FROM faciais.goal_targets
        WHERE  goal_id = %s AND entity_type = 'store'
          AND  store_id = %s AND is_active = TRUE
        LIMIT 1
    """, (goal_id, store_id))
    return row['goal_target_id'] if row else None


def _goal_value(target_id, period_id, ref_date):
    row = db.query_one("""
        SELECT target_value FROM faciais.goal_values
        WHERE  goal_target_id = %s AND goal_period_id = %s AND reference_date = %s
    """, (target_id, period_id, ref_date))
    return float(row['target_value']) if row and row['target_value'] is not None else None


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

    # YTD: soma das metas mensais de jan/ano até o mês da data selecionada
    ytd_rows = db.query_all("""
        SELECT target_value FROM faciais.goal_values
        WHERE  goal_target_id = %s AND goal_period_id = 'monthly'
          AND  reference_date >= %s AND reference_date <= %s
    """, (fat_tid, date(data_dia.year, 1, 1), mes_inicio))
    fat_ytd = sum(
        float(r['target_value']) for r in (ytd_rows or [])
        if r['target_value'] is not None
    ) or 0.0

    # Se nenhum valor foi configurado, não exibe seção de metas
    if fat_dia == 0.0 and fat_semana == 0.0 and fat_mes == 0.0:
        return None

    # Ticket médio: meta mensal do mês selecionado
    ticket_medio = 0.0
    tkt_tid = _target_id(_GOAL_TICKET_MEDIO, store_id)
    if tkt_tid:
        ticket_medio = _goal_value(tkt_tid, 'monthly', mes_inicio) or 0.0

    return {
        'faturamento_dia':    fat_dia,
        'faturamento_semana': fat_semana,
        'faturamento_mes':    fat_mes,
        'faturamento_ytd':    fat_ytd,
        'ticket_medio':       ticket_medio,
    }
