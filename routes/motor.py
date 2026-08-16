import calendar
from datetime import date as date_type, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session
from routes.utils import login_required
import db
from people import (faturamento_diario_mes      as _faturamento_diario_mes,
                    vendedores_mes              as _vendedores_mes,
                    pedidos_venda_por_vendedor  as _pedidos_venda_por_vendedor,
                    pedidos_gerados_por_loja    as _pedidos_gerados_por_loja,
                    top5_clientes_vendedor      as _top5_clientes_vendedor,
                    top5_produtos_vendedor      as _top5_produtos_vendedor,
                    top10_clientes_loja         as _top10_clientes_loja,
                    top10_produtos_cliente      as _top10_produtos_cliente,
                    estoque_maior_volume        as _estoque_maior_volume,
                    estoque_maior_faturamento   as _estoque_maior_faturamento,
                    estoque_valor_parado        as _estoque_valor_parado)
from metas import (meta_faturamento_acum_diario  as _meta_faturamento_acum_diario,
                   pedidos_meta_semana_por_loja  as _pedidos_meta_semana_por_loja)

motor_bp = Blueprint('motor', __name__, url_prefix='/retail_analytics/motor')

_MESES_PT = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
             'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
_DIAS_SEMANA_PT = ['Seg','Ter','Qua','Qui','Sex','Sáb','Dom']


def _store_context(endpoint):
    """Carrega empresa/loja/tema compartilhado por todas as rotas de motor."""
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


# ── Faturamento ───────────────────────────────────────────────────────────────

@motor_bp.route('/faturamento')
@login_required
def faturamento():
    ctx, redir = _store_context('motor.faturamento')
    if redir:
        return redir

    hoje        = date_type.today()
    ano         = hoje.year
    mes         = hoje.month
    mes_inicio  = date_type(ano, mes, 1)
    dias_no_mes = calendar.monthrange(ano, mes)[1]

    fat_diario = {}
    if ctx['active_store'] and ctx['active_microvix_portal'] and ctx['active_store_cnpj']:
        fat_diario = _faturamento_diario_mes(
            ctx['active_microvix_portal'], ctx['active_store_cnpj'], ano, mes)

    mes_fim = date_type(ano, mes, dias_no_mes)
    meta_daily, meta_total = {}, None
    if ctx['active_store']:
        meta_daily, meta_total = _meta_faturamento_acum_diario(
            ctx['active_store']['store_id'], mes_inicio, mes_fim)

    labels         = [f"{d:02d}/{mes:02d}" for d in range(1, dias_no_mes + 1)]
    realizado_acum = []
    meta_acum      = []
    acum           = 0.0
    acum_meta      = 0.0

    for dia in range(1, dias_no_mes + 1):
        acum      += fat_diario.get(dia, 0.0)
        acum_meta += meta_daily.get(dia, 0.0)
        realizado_acum.append(round(acum, 2) if date_type(ano, mes, dia) <= hoje else None)
        meta_acum.append(round(acum_meta, 2) if meta_total is not None else None)

    realizado_hoje = realizado_acum[hoje.day - 1]
    meta_hoje      = meta_acum[hoje.day - 1] if meta_total is not None else None
    pct_hoje       = round(realizado_hoje / meta_hoje * 100, 1) if (meta_hoje and realizado_hoje is not None) else None

    media_necessaria = None
    dias_restantes   = dias_no_mes - hoje.day
    if (meta_total is not None and realizado_hoje is not None and
            meta_hoje is not None and realizado_hoje < meta_hoje and
            dias_restantes > 0):
        media_necessaria = round((meta_total - realizado_hoje) / dias_restantes, 2)

    return render_template(
        'motor/faturamento.html',
        **ctx,
        mes_nome=_MESES_PT[mes - 1],
        ano=ano,
        mes=mes,
        labels=labels,
        realizado_acum=realizado_acum,
        meta_acum=meta_acum,
        tem_meta=(meta_total is not None),
        meta_total=meta_total,
        realizado_hoje=realizado_hoje,
        meta_hoje=meta_hoje,
        pct_hoje=pct_hoje,
        media_necessaria=media_necessaria,
    )


# ── Vendas ────────────────────────────────────────────────────────────────────

@motor_bp.route('/vendas')
@login_required
def vendas():
    ctx, redir = _store_context('motor.vendas')
    if redir:
        return redir

    hoje = date_type.today()
    ano  = hoje.year
    mes  = hoje.month

    mes_ini_cur = date_type(ano, mes, 1)
    mes_fim_cur = date_type(ano, mes, calendar.monthrange(ano, mes)[1])
    mes_ini_cur_str = mes_ini_cur.strftime('%Y-%m-%d')
    mes_fim_cur_str = mes_fim_cur.strftime('%Y-%m-%d')

    # 3 meses anteriores: meses_ant[0]=m1 (mais recente), [2]=m3 (mais antigo)
    meses_ant = []
    y, m = ano, mes
    for _ in range(3):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        ini = date_type(y, m, 1)
        fim = date_type(y, m, calendar.monthrange(y, m)[1])
        meses_ant.append({'ini': ini.strftime('%Y-%m-%d'),
                          'fim': fim.strftime('%Y-%m-%d'),
                          'nome': _MESES_PT[m - 1]})
    m1, m2, m3 = meses_ant[0], meses_ant[1], meses_ant[2]

    semana_inicio = hoje - timedelta(days=hoje.weekday())
    semana_fim    = semana_inicio + timedelta(days=6)

    selected_vendedor = request.args.get('vendedor')
    selected_cliente  = request.args.get('cliente')

    vendedores          = []
    pedidos             = []
    top_clientes        = []
    top_produtos        = []
    top10_clientes      = []
    top10_prod_cliente  = []

    if ctx['active_store'] and ctx['active_microvix_portal'] and ctx['active_store_cnpj']:
        portal   = ctx['active_microvix_portal']
        cnpj     = ctx['active_store_cnpj']
        store_id = ctx['active_store']['store_id']

        vendedores = _vendedores_mes(
            portal, cnpj,
            mes_ini_cur_str, mes_fim_cur_str,
            m1['ini'], m1['fim'])

        pedidos = _pedidos_venda_por_vendedor(
            store_id, portal, cnpj,
            mes_ini_cur_str, mes_fim_cur_str)

        # Meta de Pedidos Gerados (goal_id=4, por vendedor) — semana atual, calculada em tempo
        # real. Cruza com o realizado (microvix_pedidos_venda) por cod_vendedor.
        meta_semana_por_seller = _pedidos_meta_semana_por_loja(store_id, semana_inicio)
        realizado_semana_por_vendedor = _pedidos_gerados_por_loja(
            portal, cnpj, semana_inicio, semana_fim)
        for p in pedidos:
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
                    'realizado':  realizado_dia.get(semana_inicio + timedelta(days=i), 0),
                }
                for i in range(7)
            ]

        if selected_vendedor:
            top_clientes = _top5_clientes_vendedor(
                store_id, portal, cnpj, selected_vendedor,
                mes_ini_cur_str, mes_fim_cur_str,
                m1['ini'], m1['fim'])
            top_produtos = _top5_produtos_vendedor(
                store_id, portal, cnpj, selected_vendedor,
                mes_ini_cur_str, mes_fim_cur_str,
                m1['ini'], m1['fim'])

        top10_clientes = _top10_clientes_loja(
            store_id, portal, cnpj,
            mes_ini_cur_str, mes_fim_cur_str,
            m1['ini'], m1['fim'],
            m2['ini'], m2['fim'],
            m3['ini'], m3['fim'])

        if selected_cliente:
            top10_prod_cliente = _top10_produtos_cliente(
                store_id, portal, cnpj, selected_cliente,
                mes_ini_cur_str, mes_fim_cur_str,
                m1['ini'], m1['fim'],
                m2['ini'], m2['fim'],
                m3['ini'], m3['fim'])

    return render_template(
        'motor/vendas.html',
        **ctx,
        mes_nome=_MESES_PT[mes - 1],
        mes_nome_ant=m1['nome'],
        ano=ano,
        mes=mes,
        m1=m1, m2=m2, m3=m3,
        semana_inicio=semana_inicio,
        semana_fim=semana_fim,
        vendedores=vendedores,
        pedidos=pedidos,
        selected_vendedor=selected_vendedor,
        top_clientes=top_clientes,
        top_produtos=top_produtos,
        top10_clientes=top10_clientes,
        selected_cliente=selected_cliente,
        top10_prod_cliente=top10_prod_cliente,
    )


# ── Estoque ───────────────────────────────────────────────────────────────────

@motor_bp.route('/estoque')
@login_required
def estoque():
    ctx, redir = _store_context('motor.estoque')
    if redir:
        return redir

    hoje = date_type.today()
    ano  = hoje.year
    mes  = hoje.month

    # Computa m0 (atual), m1, m2, m3 em ordem decrescente
    meses = []
    y, m = ano, mes
    for _ in range(4):
        ini = date_type(y, m, 1)
        fim = date_type(y, m, calendar.monthrange(y, m)[1])
        meses.append({'ini': ini.strftime('%Y-%m-%d'),
                      'fim': fim.strftime('%Y-%m-%d'),
                      'nome': _MESES_PT[m - 1]})
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    m0, m1, m2, m3 = meses[0], meses[1], meses[2], meses[3]

    maior_volume     = []
    maior_fat        = []
    valor_parado     = []

    if ctx['active_store'] and ctx['active_microvix_portal'] and ctx['active_store_cnpj']:
        portal = ctx['active_microvix_portal']
        cnpj   = ctx['active_store_cnpj']
        args   = (portal, cnpj,
                  m3['ini'], m3['fim'],
                  m2['ini'], m2['fim'],
                  m1['ini'], m1['fim'],
                  m0['ini'], m0['fim'])
        maior_volume = _estoque_maior_volume(*args)
        maior_fat    = _estoque_maior_faturamento(*args)
        valor_parado = _estoque_valor_parado(portal, cnpj, m3['ini'])

    return render_template(
        'motor/estoque.html',
        **ctx,
        ano=ano,
        m0_nome=m0['nome'], m1_nome=m1['nome'],
        m2_nome=m2['nome'], m3_nome=m3['nome'],
        maior_volume=maior_volume,
        maior_fat=maior_fat,
        valor_parado=valor_parado,
    )
