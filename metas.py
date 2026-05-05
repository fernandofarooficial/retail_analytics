# metas.py
# =============================================================================
# METAS TEMPORÁRIAS PARA TESTES
# Altere os valores neste arquivo. Quando o banco de metas for implementado
# este módulo será substituído por consultas ao banco.
# =============================================================================

from datetime import date, timedelta
import calendar as _calendar


# =============================================================================
# CONFIGURAÇÃO DAS METAS  ← edite aqui
# =============================================================================

METAS = {
    1: {                                  # company_id = 1
        'faturamento_mensal': 30_000.00,  # R$ por mês cheio
        'ticket_medio':          375.00,  # R$ por venda
        'fecha_domingo':           False, # True → loja fecha aos domingos
    },
}


# =============================================================================
# FERIADOS  ← adicione ou remova datas conforme necessário
# =============================================================================
# Inclui feriados nacionais, estaduais (RS) e o municipal de Porto Alegre
# (Nossa Senhora dos Navegantes – 02/fev). Ajuste se necessário.

FERIADOS: set[date] = {

    # ── 2024 ──────────────────────────────────────────────────────────────────
    date(2024,  1,  1),  # Confraternização Universal
    date(2024,  2,  2),  # N. Sra. dos Navegantes (municipal – POA)
    date(2024,  2, 12),  # Carnaval (ponto facultativo)
    date(2024,  2, 13),  # Carnaval (ponto facultativo)
    date(2024,  2, 14),  # Quarta-feira de Cinzas (ponto facultativo)
    date(2024,  3, 29),  # Sexta-feira Santa
    date(2024,  3, 31),  # Páscoa
    date(2024,  4, 21),  # Tiradentes
    date(2024,  5,  1),  # Dia do Trabalhador
    date(2024,  5, 30),  # Corpus Christi
    date(2024,  9,  7),  # Independência do Brasil
    date(2024,  9, 20),  # Revolução Farroupilha – Dia do Gaúcho (RS)
    date(2024, 10, 12),  # Nossa Senhora Aparecida
    date(2024, 11,  2),  # Finados
    date(2024, 11, 15),  # Proclamação da República
    date(2024, 11, 20),  # Dia da Consciência Negra
    date(2024, 12, 25),  # Natal

    # ── 2025 ──────────────────────────────────────────────────────────────────
    date(2025,  1,  1),  # Confraternização Universal
    date(2025,  2,  2),  # N. Sra. dos Navegantes (municipal – POA)
    date(2025,  3,  3),  # Carnaval (ponto facultativo)
    date(2025,  3,  4),  # Carnaval (ponto facultativo)
    date(2025,  3,  5),  # Quarta-feira de Cinzas (ponto facultativo)
    date(2025,  4, 18),  # Sexta-feira Santa
    date(2025,  4, 20),  # Páscoa
    date(2025,  4, 21),  # Tiradentes
    date(2025,  5,  1),  # Dia do Trabalhador
    date(2025,  6, 19),  # Corpus Christi
    date(2025,  9,  7),  # Independência do Brasil
    date(2025,  9, 20),  # Revolução Farroupilha – Dia do Gaúcho (RS)
    date(2025, 10, 12),  # Nossa Senhora Aparecida
    date(2025, 11,  2),  # Finados
    date(2025, 11, 15),  # Proclamação da República
    date(2025, 11, 20),  # Dia da Consciência Negra
    date(2025, 12, 25),  # Natal

    # ── 2026 (lista fornecida pelo cliente) ───────────────────────────────────
    date(2026,  1,  1),  # Confraternização Universal
    date(2026,  2,  2),  # N. Sra. dos Navegantes (municipal – POA)
    date(2026,  2, 16),  # Carnaval (ponto facultativo)
    date(2026,  2, 17),  # Carnaval (ponto facultativo)
    date(2026,  2, 18),  # Quarta-feira de Cinzas (ponto facultativo)
    date(2026,  4,  3),  # Sexta-feira Santa
    date(2026,  4,  5),  # Páscoa
    date(2026,  4, 21),  # Tiradentes
    date(2026,  5,  1),  # Dia do Trabalhador
    date(2026,  6,  4),  # Corpus Christi
    date(2026,  9,  7),  # Independência do Brasil
    date(2026,  9, 20),  # Revolução Farroupilha – Dia do Gaúcho (RS)
    date(2026, 10, 12),  # Nossa Senhora Aparecida
    date(2026, 11,  2),  # Finados
    date(2026, 11, 15),  # Proclamação da República
    date(2026, 11, 20),  # Dia da Consciência Negra
    date(2026, 12, 25),  # Natal
}


# =============================================================================
# FUNÇÕES DE CÁLCULO  (não precisa editar)
# =============================================================================

def _aberto(company_id: int, d: date) -> bool:
    """Retorna True se a loja está aberta nesse dia."""
    if d in FERIADOS:
        return False
    cfg = METAS.get(company_id, {})
    if cfg.get('fecha_domingo', False) and d.weekday() == 6:
        return False
    return True


def _dias_abertos_mes(company_id: int, ano: int, mes: int) -> int:
    """Total de dias abertos no mês (usado para rateio diário)."""
    _, ndias = _calendar.monthrange(ano, mes)
    total = sum(1 for i in range(1, ndias + 1) if _aberto(company_id, date(ano, mes, i)))
    return total or 1  # evita divisão por zero


def meta_diaria(company_id: int, d: date) -> float | None:
    """Meta de faturamento de um dia. 0.0 se loja fechada. None se sem meta."""
    cfg = METAS.get(company_id)
    if cfg is None:
        return None
    if not _aberto(company_id, d):
        return 0.0
    return round(cfg['faturamento_mensal'] / _dias_abertos_mes(company_id, d.year, d.month), 2)


def meta_periodo(company_id: int, inicio: date, fim: date) -> float | None:
    """Soma das metas diárias entre inicio e fim (inclusive)."""
    if company_id not in METAS:
        return None
    total = 0.0
    d = inicio
    while d <= fim:
        total += meta_diaria(company_id, d) or 0.0
        d += timedelta(days=1)
    return round(total, 2)


def get_metas(company_id: int,
              data_dia: date,
              semana_inicio: date, semana_fim: date,
              mes_inicio: date,   mes_fim: date,
              ytd_inicio: date,   ytd_fim: date) -> dict | None:
    """
    Retorna dict com metas para todos os períodos do dashboard.
    Retorna None se a empresa não tiver metas configuradas.
    """
    if company_id not in METAS:
        return None
    cfg = METAS[company_id]
    return {
        'faturamento_dia':    meta_periodo(company_id, data_dia,      data_dia),
        'faturamento_semana': meta_periodo(company_id, semana_inicio,  semana_fim),
        'faturamento_mes':    meta_periodo(company_id, mes_inicio,     mes_fim),
        'faturamento_ytd':    meta_periodo(company_id, ytd_inicio,     ytd_fim),
        'ticket_medio':       cfg['ticket_medio'],
    }
