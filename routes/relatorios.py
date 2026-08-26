import calendar
from datetime import date as date_type, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session
from routes.utils import login_required, block_user_types
import db
from people import (pedidos_venda_por_vendedor as _pedidos_venda_por_vendedor,
                    pedidos_gerados_por_loja   as _pedidos_gerados_por_loja)
from metas import (pedidos_meta_semana_por_loja as _pedidos_meta_semana_por_loja,
                   pedidos_meta_mes_por_loja    as _pedidos_meta_mes_por_loja)

relatorios_bp = Blueprint('relatorios', __name__, url_prefix='/retail_analytics/relatorios')

_MESES_PT = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
             'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
_DIAS_SEMANA_PT = ['Seg','Ter','Qua','Qui','Sex','Sáb','Dom']


def _store_context(endpoint):
    """Carrega empresa/loja/tema compartilhado por todas as rotas de relatórios (mesmo padrão
    usado em motor.py e gestao.py)."""
    user_id   = session['user_id']
    user_type = session['user_type_id']
    selected_company_id = request.args.get('company_id', type=int)
    selected_store_id   = request.args.get('store_id',   type=int)
    company_logo        = None
    company_name        = None
    companies           = []
    stores              = []

    # ── Restaurar última seleção ──────────────────────────────────────────────
    if not selected_store_id and 'company_id' not in request.args:
        saved = db.query_one(
            "SELECT last_store_id FROM faciais.users WHERE user_id = %s", (user_id,))
        if saved and saved['last_store_id']:
            last_sid = saved['last_store_id']
            if user_type in ('adm', 'man'):
                if user_type == 'adm':
                    row = db.query_one(
                        "SELECT company_id FROM faciais.stores WHERE store_id = %s",
                        (last_sid,))
                else:
                    row = db.query_one("""
                        SELECT s.company_id
                        FROM   faciais.stores s
                        JOIN   faciais.companies c ON c.company_id = s.company_id
                        JOIN   faciais.user_company_groups ucg
                               ON ucg.company_group_id = c.company_group_id
                        WHERE  s.store_id = %s AND ucg.user_id = %s
                    """, (last_sid, user_id))
                if row:
                    return None, redirect(url_for(endpoint,
                                                  company_id=row['company_id'],
                                                  store_id=last_sid))
            elif user_type == 'ret':
                row = db.query_one("""
                    SELECT s.store_id
                    FROM   faciais.stores s
                    JOIN   faciais.user_retailer_groups urg
                           ON urg.retailer_group_id = s.retailer_group_id
                    WHERE  s.store_id = %s AND urg.user_id = %s
                """, (last_sid, user_id))
                if row:
                    return None, redirect(url_for(endpoint, store_id=last_sid))
            elif user_type == 'emp':
                row = db.query_one(
                    "SELECT store_id FROM faciais.user_stores "
                    "WHERE store_id = %s AND user_id = %s",
                    (last_sid, user_id))
                if row:
                    return None, redirect(url_for(endpoint, store_id=last_sid))

    # ── Carrega empresas e lojas ──────────────────────────────────────────────
    if user_type == 'adm':
        companies = db.query_all("""
            SELECT c.company_id, c.company_name, ct.logo_url
            FROM   faciais.companies c
            JOIN   faciais.company_themes ct ON ct.company_id = c.company_id
            WHERE  ct.logo_url IS NOT NULL
            ORDER  BY c.company_name
        """)
        if selected_company_id:
            match = next((c for c in companies if c['company_id'] == selected_company_id), None)
            if match:
                company_logo = match['logo_url']
                company_name = match['company_name']
            stores = db.query_all("""
                SELECT store_id, store_name, cnpj
                FROM   faciais.stores WHERE company_id = %s ORDER BY store_name
            """, (selected_company_id,))

    elif user_type == 'man':
        companies = db.query_all("""
            SELECT DISTINCT c.company_id, c.company_name, ct.logo_url
            FROM   faciais.user_company_groups ucg
            JOIN   faciais.companies c        ON c.company_group_id = ucg.company_group_id
            LEFT   JOIN faciais.company_themes ct ON ct.company_id  = c.company_id
            WHERE  ucg.user_id = %s ORDER BY c.company_name
        """, (user_id,))
        if selected_company_id:
            match = next((c for c in companies if c['company_id'] == selected_company_id), None)
            if match:
                company_logo = match['logo_url']
                company_name = match['company_name']
            stores = db.query_all("""
                SELECT store_id, store_name, cnpj
                FROM   faciais.stores WHERE company_id = %s ORDER BY store_name
            """, (selected_company_id,))
        else:
            first = next((c for c in companies if c.get('logo_url')), None)
            if first:
                company_logo = first['logo_url']
                company_name = first['company_name']

    elif user_type == 'ret':
        row = db.query_one("""
            SELECT c.company_name, ct.logo_url
            FROM   faciais.user_retailer_groups urg
            JOIN   faciais.stores s          ON s.retailer_group_id = urg.retailer_group_id
            JOIN   faciais.companies c       ON c.company_id = s.company_id
            JOIN   faciais.company_themes ct ON ct.company_id = c.company_id
            WHERE  urg.user_id = %s AND ct.logo_url IS NOT NULL LIMIT 1
        """, (user_id,))
        if row:
            company_logo = row['logo_url']
            company_name = row['company_name']
        stores = db.query_all("""
            SELECT DISTINCT s.store_id, s.store_name, s.cnpj
            FROM   faciais.user_retailer_groups urg
            JOIN   faciais.stores s ON s.retailer_group_id = urg.retailer_group_id
            WHERE  urg.user_id = %s ORDER BY s.store_name
        """, (user_id,))

    elif user_type == 'emp':
        row = db.query_one("""
            SELECT c.company_name, ct.logo_url
            FROM   faciais.user_stores us
            JOIN   faciais.stores s          ON s.store_id = us.store_id
            JOIN   faciais.companies c       ON c.company_id = s.company_id
            JOIN   faciais.company_themes ct ON ct.company_id = c.company_id
            WHERE  us.user_id = %s AND ct.logo_url IS NOT NULL LIMIT 1
        """, (user_id,))
        if row:
            company_logo = row['logo_url']
            company_name = row['company_name']
        stores = db.query_all("""
            SELECT s.store_id, s.store_name, s.cnpj
            FROM   faciais.user_stores us
            JOIN   faciais.stores s ON s.store_id = us.store_id
            WHERE  us.user_id = %s ORDER BY s.store_name
        """, (user_id,))

    # ── Resolve loja ativa ────────────────────────────────────────────────────
    active_store = None
    if stores:
        if selected_store_id:
            active_store = next((s for s in stores if s['store_id'] == selected_store_id), None)
        if active_store is None and len(stores) == 1:
            active_store      = stores[0]
            selected_store_id = active_store['store_id']

    # ── Portal / CNPJ ────────────────────────────────────────────────────────
    active_store_cnpj      = None
    active_microvix_portal = None
    if active_store:
        if active_store['cnpj']:
            active_store_cnpj = str(active_store['cnpj']).zfill(14)
        row = db.query_one(
            "SELECT microvix_portal FROM faciais.stores WHERE store_id = %s",
            (active_store['store_id'],))
        if row:
            active_microvix_portal = row['microvix_portal']

    # ── Tema ──────────────────────────────────────────────────────────────────
    theme = dict(primary_color='#F47B20', secondary_color='#0057A8', accent_color='#FFFFFF',
                 text_color='#111827', background_color='#F5F5F5',
                 graph_color_1='#0057A8', graph_color_2='#F47B20',
                 graph_color_3='#E65100', graph_color_4='#388E3C')
    theme_company_id = selected_company_id
    if not theme_company_id and active_store:
        row = db.query_one(
            "SELECT company_id FROM faciais.stores WHERE store_id = %s",
            (active_store['store_id'],))
        if row:
            theme_company_id = row['company_id']
    if theme_company_id:
        row = db.query_one(
            """SELECT primary_color, secondary_color, accent_color, text_color, background_color,
                      graph_color_1, graph_color_2, graph_color_3, graph_color_4
               FROM   faciais.company_themes WHERE company_id = %s""",
            (theme_company_id,))
        if row:
            theme['primary_color']   = row['primary_color']
            theme['secondary_color'] = row['secondary_color']
            theme['accent_color']    = row['accent_color']
            if row['text_color']:
                theme['text_color'] = row['text_color']
            if row['background_color']:
                theme['background_color'] = row['background_color']
            for k in ('graph_color_1', 'graph_color_2', 'graph_color_3', 'graph_color_4'):
                if row[k]:
                    theme[k] = row[k]

    return dict(
        companies=companies,
        stores=stores,
        company_logo=company_logo,
        company_name=company_name,
        selected_company_id=selected_company_id,
        selected_store_id=selected_store_id,
        active_store=active_store,
        active_store_cnpj=active_store_cnpj,
        active_microvix_portal=active_microvix_portal,
        theme=theme,
    ), None


# ── Pedidos ──────────────────────────────────────────────────────────────────

@relatorios_bp.route('/pedidos')
@login_required
@block_user_types('emp')
def pedidos():
    ctx, redir = _store_context('relatorios.pedidos')
    if redir:
        return redir

    semana_str = request.args.get('semana', date_type.today().strftime('%Y-%m-%d'))
    try:
        selected_date = date_type.fromisoformat(semana_str)
    except ValueError:
        selected_date = date_type.today()

    semana_inicio = selected_date - timedelta(days=selected_date.weekday())
    semana_fim    = semana_inicio + timedelta(days=6)
    semana_inicio_str = semana_inicio.strftime('%Y-%m-%d')
    semana_fim_str    = semana_fim.strftime('%Y-%m-%d')

    semana_anterior_str = (semana_inicio - timedelta(days=1)).strftime('%Y-%m-%d')
    semana_proxima_str  = (semana_fim    + timedelta(days=1)).strftime('%Y-%m-%d')
    semana_label = f"{semana_inicio.strftime('%d/%m')} – {semana_fim.strftime('%d/%m/%Y')}"

    # Mês de referência da semana escolhida (mês em que cai a segunda-feira da semana)
    mes_inicio = semana_inicio.replace(day=1)
    mes_fim    = semana_inicio.replace(day=calendar.monthrange(semana_inicio.year, semana_inicio.month)[1])
    mes_inicio_str = mes_inicio.strftime('%Y-%m-%d')
    mes_fim_str    = mes_fim.strftime('%Y-%m-%d')
    mes_nome = _MESES_PT[semana_inicio.month - 1]

    selected_vendedor = request.args.get('vendedor')

    pedidos_lista     = []
    pedidos_mes_lista = []

    if ctx['active_store'] and ctx['active_microvix_portal'] and ctx['active_store_cnpj']:
        portal   = ctx['active_microvix_portal']
        cnpj     = ctx['active_store_cnpj']
        store_id = ctx['active_store']['store_id']

        pedidos_lista = _pedidos_venda_por_vendedor(
            store_id, portal, cnpj,
            semana_inicio_str, semana_fim_str)

        meta_semana_por_seller = _pedidos_meta_semana_por_loja(store_id, semana_inicio)
        realizado_semana_por_vendedor = _pedidos_gerados_por_loja(
            portal, cnpj, semana_inicio, semana_fim)
        for p in pedidos_lista:
            realizado_dia = realizado_semana_por_vendedor.get(p['cod_vendedor'], {})
            p['pedidos_realizado_semana'] = sum(realizado_dia.values())
            meta_dia, meta_semana = ({}, None)
            if p['seller_id'] is not None:
                meta_dia, meta_semana = meta_semana_por_seller.get(p['seller_id'], ({}, None))
            p['pedidos_meta_semana'] = meta_semana
            p['pedidos_dias_semana'] = [
                {
                    'data':       semana_inicio + timedelta(days=i),
                    'dia_semana': _DIAS_SEMANA_PT[i],
                    'meta':       meta_dia.get(semana_inicio + timedelta(days=i), 0.0),
                    'realizado':  realizado_dia.get(semana_inicio + timedelta(days=i), 0.0),
                }
                for i in range(7)
            ]

        pedidos_mes_lista = _pedidos_venda_por_vendedor(
            store_id, portal, cnpj,
            mes_inicio_str, mes_fim_str)

        meta_mes_por_seller = _pedidos_meta_mes_por_loja(store_id, mes_inicio, mes_fim)
        realizado_mes_por_vendedor = _pedidos_gerados_por_loja(
            portal, cnpj, mes_inicio_str, mes_fim_str)
        for p in pedidos_mes_lista:
            realizado_dia_mes = realizado_mes_por_vendedor.get(p['cod_vendedor'], {})
            p['pedidos_realizado_mes'] = sum(realizado_dia_mes.values())
            p['pedidos_meta_mes'] = (
                meta_mes_por_seller.get(p['seller_id']) if p['seller_id'] is not None else None)

    return render_template(
        'relatorios/pedidos.html',
        **ctx,
        semana=semana_str,
        semana_inicio=semana_inicio,
        semana_fim=semana_fim,
        semana_anterior_str=semana_anterior_str,
        semana_proxima_str=semana_proxima_str,
        semana_label=semana_label,
        mes_inicio=mes_inicio,
        mes_fim=mes_fim,
        mes_nome=mes_nome,
        pedidos=pedidos_lista,
        pedidos_mes=pedidos_mes_lista,
        selected_vendedor=selected_vendedor,
    )
