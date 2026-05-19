from datetime import date as date_type
from flask import Blueprint, render_template, request, redirect, url_for, session
from routes.utils import login_required
import db
from people import (faturamento_mensal as _faturamento_mensal,
                    vendas_mensal_por_vendedor as _vendas_mensal_por_vendedor,
                    cobertura_estoque as _cobertura_estoque)

gestao_bp = Blueprint('gestao', __name__, url_prefix='/retail_analytics/gestao')


def _store_context(endpoint):
    """Carrega empresa/loja/tema compartilhado por todas as rotas de gestão.
    Retorna (ctx_dict, redirect_ou_None).
    """
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
            "SELECT last_store_id FROM faciais.users WHERE user_id = %s",
            (user_id,)
        )
        if saved and saved['last_store_id']:
            last_sid = saved['last_store_id']
            if user_type in ('adm', 'man'):
                if user_type == 'adm':
                    row = db.query_one(
                        "SELECT company_id FROM faciais.stores WHERE store_id = %s",
                        (last_sid,)
                    )
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
                    (last_sid, user_id)
                )
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
                FROM   faciais.stores
                WHERE  company_id = %s
                ORDER  BY store_name
            """, (selected_company_id,))

    elif user_type == 'man':
        companies = db.query_all("""
            SELECT DISTINCT c.company_id, c.company_name, ct.logo_url
            FROM   faciais.user_company_groups ucg
            JOIN   faciais.companies c        ON c.company_group_id = ucg.company_group_id
            LEFT   JOIN faciais.company_themes ct ON ct.company_id  = c.company_id
            WHERE  ucg.user_id = %s
            ORDER  BY c.company_name
        """, (user_id,))
        if selected_company_id:
            match = next((c for c in companies if c['company_id'] == selected_company_id), None)
            if match:
                company_logo = match['logo_url']
                company_name = match['company_name']
            stores = db.query_all("""
                SELECT store_id, store_name, cnpj
                FROM   faciais.stores
                WHERE  company_id = %s
                ORDER  BY store_name
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
            WHERE  urg.user_id = %s AND ct.logo_url IS NOT NULL
            LIMIT  1
        """, (user_id,))
        if row:
            company_logo = row['logo_url']
            company_name = row['company_name']
        stores = db.query_all("""
            SELECT DISTINCT s.store_id, s.store_name, s.cnpj
            FROM   faciais.user_retailer_groups urg
            JOIN   faciais.stores s ON s.retailer_group_id = urg.retailer_group_id
            WHERE  urg.user_id = %s
            ORDER  BY s.store_name
        """, (user_id,))

    elif user_type == 'emp':
        row = db.query_one("""
            SELECT c.company_name, ct.logo_url
            FROM   faciais.user_stores us
            JOIN   faciais.stores s          ON s.store_id = us.store_id
            JOIN   faciais.companies c       ON c.company_id = s.company_id
            JOIN   faciais.company_themes ct ON ct.company_id = c.company_id
            WHERE  us.user_id = %s AND ct.logo_url IS NOT NULL
            LIMIT  1
        """, (user_id,))
        if row:
            company_logo = row['logo_url']
            company_name = row['company_name']
        stores = db.query_all("""
            SELECT s.store_id, s.store_name, s.cnpj
            FROM   faciais.user_stores us
            JOIN   faciais.stores s ON s.store_id = us.store_id
            WHERE  us.user_id = %s
            ORDER  BY s.store_name
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
            (active_store['store_id'],)
        )
        if row:
            theme_company_id = row['company_id']
    if theme_company_id:
        row = db.query_one(
            """SELECT primary_color, secondary_color, accent_color, text_color, background_color,
                      graph_color_1, graph_color_2, graph_color_3, graph_color_4
               FROM   faciais.company_themes WHERE company_id = %s""",
            (theme_company_id,)
        )
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


# ── Faturamento ───────────────────────────────────────────────────────────────

@gestao_bp.route('/faturamento')
@login_required
def faturamento():
    ctx, redir = _store_context('gestao.faturamento')
    if redir:
        return redir

    ano_atual = date_type.today().year
    try:
        ano = int(request.args.get('ano', ano_atual))
    except (ValueError, TypeError):
        ano = ano_atual

    fat_mensal = []
    if ctx['active_store'] and ctx['active_microvix_portal'] and ctx['active_store_cnpj']:
        fat_mensal = _faturamento_mensal(
            ctx['active_microvix_portal'], ctx['active_store_cnpj'], ano
        )

    return render_template(
        'gestao/faturamento.html',
        **ctx,
        ano=ano,
        ano_atual=ano_atual,
        fat_mensal=fat_mensal,
    )


# ── Vendas ────────────────────────────────────────────────────────────────────

@gestao_bp.route('/vendas')
@login_required
def vendas():
    ctx, redir = _store_context('gestao.vendas')
    if redir:
        return redir

    ano_atual = date_type.today().year
    try:
        ano = int(request.args.get('ano', ano_atual))
    except (ValueError, TypeError):
        ano = ano_atual

    vendas_data = {'meses_nomes': [], 'series': []}
    if ctx['active_store'] and ctx['active_microvix_portal'] and ctx['active_store_cnpj']:
        vendas_data = _vendas_mensal_por_vendedor(
            ctx['active_microvix_portal'], ctx['active_store_cnpj'], ano
        )

    return render_template(
        'gestao/vendas.html',
        **ctx,
        ano=ano,
        ano_atual=ano_atual,
        vendas_data=vendas_data,
    )


# ── Estoque ───────────────────────────────────────────────────────────────────

@gestao_bp.route('/estoque')
@login_required
def estoque():
    ctx, redir = _store_context('gestao.estoque')
    if redir:
        return redir

    cobertura = []
    if ctx['active_store'] and ctx['active_microvix_portal'] and ctx['active_store_cnpj']:
        cobertura = _cobertura_estoque(
            ctx['active_microvix_portal'], ctx['active_store_cnpj'])

    return render_template(
        'gestao/estoque.html',
        **ctx,
        cobertura=cobertura,
    )
