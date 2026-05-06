import calendar
import math
from datetime import date as date_type, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash
from routes.utils import login_required, screen_required
import db
from metas import get_metas as _get_metas

auth_bp = Blueprint('auth', __name__)


def _prev_business_day(d):
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


def _is_mobile():
    ua = request.headers.get('User-Agent', '').lower()
    return any(k in ua for k in ('iphone', 'android', 'mobile', 'ipad'))


@auth_bp.route('/')
def index():
    if _is_mobile():
        return redirect(url_for('mobile.index'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if _is_mobile():
        return redirect(url_for('mobile.login'))
    if 'user_id' in session:
        return redirect(url_for('auth.dashboard'))

    error = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')

        user = db.query_one(
            "SELECT user_id, full_name, password_hash, user_type_id "
            "FROM faciais.users "
            "WHERE lower(username) = %s AND is_active = TRUE",
            (username,)
        )

        if user and check_password_hash(user['password_hash'], password):
            session['user_id']      = user['user_id']
            session['full_name']    = user['full_name']
            session['user_type_id'] = user['user_type_id']
            return redirect(url_for('auth.dashboard'))

        error = 'Usuário ou senha incorretos.'

    return render_template('auth/login.html', error=error)


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


def _ticket_por_tipo(sid, portal, cnpj, data_inicio, data_fim, corte_recorrente):
    """Ticket médio por nota, separado em novo/recorrente, via faciais.person_purchases."""
    rows = db.query_all("""
        WITH recorrentes AS (
            SELECT DISTINCT person_id
            FROM   faciais.detection_records
            WHERE  store_id         = %s
              AND  DATE(created_at) < %s
              AND  person_id IS NOT NULL
        ),
        bills AS (
            SELECT pp.person_id,
                   pp.bill,
                   (r.person_id IS NOT NULL) AS is_rec
            FROM   faciais.person_purchases pp
            LEFT   JOIN recorrentes r ON r.person_id = pp.person_id
            WHERE  pp.store_id              = %s
              AND  DATE(pp.created_at) BETWEEN %s AND %s
              AND  (pp.is_cancelled IS NOT TRUE)
        ),
        fat_bills AS (
            SELECT mm.documento,
                   SUM(mm.valor_liquido) AS valor_nota
            FROM   microvix.microvix_movimento mm
            WHERE  mm.portal                = %s
              AND  mm.cnpj_emp              = %s
              AND  DATE(mm.data_documento)  BETWEEN %s AND %s
              AND  mm.cancelado            <> 'S'
              AND  mm.excluido             <> 'S'
              AND  mm.soma_relatorio        = 'S'
              AND  mm.tipo_transacao        = 'V'
              AND  mm.cod_natureza_operacao = '10030'
            GROUP  BY mm.documento
        )
        SELECT  b.is_rec,
                COUNT(DISTINCT b.bill)          AS num_bills,
                COALESCE(SUM(fb.valor_nota), 0) AS faturamento
        FROM    bills b
        JOIN    fat_bills fb ON fb.documento = b.bill
        GROUP   BY b.is_rec
    """, (sid, corte_recorrente, sid, data_inicio, data_fim,
          portal, cnpj, data_inicio, data_fim))
    result = {'ticket_novo': None, 'ticket_rec': None}
    for row in rows:
        n = row['num_bills'] or 0
        f = float(row['faturamento'] or 0)
        ticket = round(f / n, 2) if n > 0 else 0.0
        if row['is_rec']:
            result['ticket_rec'] = ticket
        else:
            result['ticket_novo'] = ticket
    if rows:
        result.setdefault('ticket_novo', 0.0)
        result.setdefault('ticket_rec', 0.0)
        if result['ticket_novo'] is None:
            result['ticket_novo'] = 0.0
        if result['ticket_rec'] is None:
            result['ticket_rec'] = 0.0
    return result


def _top5_por_tipo(sid, portal, cnpj, data_inicio, data_fim, corte_recorrente):
    """Top 5 produtos por faturamento, separado em novo/recorrente, via faciais.person_purchases."""
    rows = db.query_all("""
        WITH recorrentes AS (
            SELECT DISTINCT person_id
            FROM   faciais.detection_records
            WHERE  store_id = %s AND DATE(created_at) < %s AND person_id IS NOT NULL
        ),
        bills AS (
            SELECT pp.bill, (r.person_id IS NOT NULL) AS is_rec
            FROM   faciais.person_purchases pp
            LEFT   JOIN recorrentes r ON r.person_id = pp.person_id
            WHERE  pp.store_id = %s
              AND  DATE(pp.created_at) BETWEEN %s AND %s
              AND  (pp.is_cancelled IS NOT TRUE)
        ),
        linhas AS (
            SELECT b.is_rec,
                   COALESCE(NULLIF(TRIM(mp.descricao_basica), ''), mp.nome) AS produto,
                   mm.valor_liquido
            FROM   bills b
            JOIN   microvix.microvix_movimento mm ON mm.documento = b.bill
            JOIN   microvix.microvix_produtos mp
                   ON mp.portal = mm.portal AND mp.cod_produto = mm.cod_produto
            WHERE  mm.portal = %s AND mm.cnpj_emp = %s
              AND  mm.cancelado <> 'S' AND mm.excluido <> 'S'
              AND  mm.soma_relatorio = 'S' AND mm.tipo_transacao = 'V'
              AND  mm.cod_natureza_operacao = '10030'
        ),
        totais AS (
            SELECT is_rec, produto, SUM(valor_liquido) AS total_fat
            FROM   linhas GROUP BY is_rec, produto
        ),
        fat_total AS (
            SELECT is_rec, SUM(total_fat) AS grand_total FROM totais GROUP BY is_rec
        ),
        ranked AS (
            SELECT t.is_rec, t.produto, t.total_fat, ft.grand_total,
                   ROW_NUMBER() OVER (PARTITION BY t.is_rec ORDER BY t.total_fat DESC) AS rn
            FROM   totais t JOIN fat_total ft ON ft.is_rec = t.is_rec
            WHERE  t.total_fat > 0
        )
        SELECT is_rec, produto, total_fat,
               ROUND(total_fat * 100.0 / NULLIF(grand_total, 0), 1) AS pct
        FROM   ranked WHERE rn <= 5
        ORDER  BY is_rec, rn
    """, (sid, corte_recorrente, sid, data_inicio, data_fim, portal, cnpj))
    result = {'novos': [], 'recorrentes': []}
    for row in rows:
        item = {'nome': row['produto'], 'total': round(float(row['total_fat'] or 0), 2), 'pct': float(row['pct'] or 0)}
        if row['is_rec']:
            result['recorrentes'].append(item)
        else:
            result['novos'].append(item)
    return result


@auth_bp.route('/dashboard')
@login_required
@screen_required('dashboard')
def dashboard():
    user_id   = session['user_id']
    user_type = session['user_type_id']
    company_logo = None
    company_name = None
    companies    = []
    selected_company_id = None

    stores              = []   # lojas disponíveis para o seletor
    selected_company_id = None
    selected_store_id   = request.args.get('store_id', type=int)

    # ── Restaurar última seleção (quando não há parâmetros na URL) ────────────
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
                        JOIN   faciais.companies c  ON c.company_id = s.company_id
                        JOIN   faciais.user_company_groups ucg
                               ON ucg.company_group_id = c.company_group_id
                        WHERE  s.store_id = %s AND ucg.user_id = %s
                    """, (last_sid, user_id))
                if row:
                    return redirect(url_for('auth.dashboard',
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
                    return redirect(url_for('auth.dashboard', store_id=last_sid))
            elif user_type == 'emp':
                row = db.query_one(
                    "SELECT store_id FROM faciais.user_stores "
                    "WHERE store_id = %s AND user_id = %s",
                    (last_sid, user_id)
                )
                if row:
                    return redirect(url_for('auth.dashboard', store_id=last_sid))

    # ── Carrega empresas (adm) e lojas (todos os tipos) ───────────────────────
    if user_type == 'adm':
        companies = db.query_all("""
            SELECT c.company_id, c.company_name, ct.logo_url
            FROM   faciais.companies c
            JOIN   faciais.company_themes ct ON ct.company_id = c.company_id
            WHERE  ct.logo_url IS NOT NULL
            ORDER  BY c.company_name
        """)
        selected_company_id = request.args.get('company_id', type=int)
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
            SELECT DISTINCT c.company_id, c.company_name,
                   ct.logo_url
            FROM   faciais.user_company_groups ucg
            JOIN   faciais.companies c       ON c.company_group_id = ucg.company_group_id
            LEFT JOIN faciais.company_themes ct ON ct.company_id = c.company_id
            WHERE  ucg.user_id = %s
            ORDER  BY c.company_name
        """, (user_id,))
        selected_company_id = request.args.get('company_id', type=int)
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
            # Sem empresa selecionada: pega logo da primeira com tema
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

    # ── Resolve loja ativa (auto-seleciona se houver apenas uma) ──────────────
    active_store = None
    if stores:
        if selected_store_id:
            active_store = next((s for s in stores if s['store_id'] == selected_store_id), None)
        if active_store is None and len(stores) == 1:
            active_store      = stores[0]
            selected_store_id = active_store['store_id']

    # ── Salvar última seleção no banco ────────────────────────────────────────
    if active_store:
        _sid = active_store['store_id']
        if user_type in ('adm', 'man'):
            db.execute("""
                UPDATE faciais.users
                SET    last_store_id         = %s,
                       last_company_group_id = (
                           SELECT c.company_group_id
                           FROM   faciais.stores s
                           JOIN   faciais.companies c ON c.company_id = s.company_id
                           WHERE  s.store_id = %s
                       )
                WHERE  user_id = %s
            """, (_sid, _sid, user_id))
        elif user_type == 'ret':
            db.execute("""
                UPDATE faciais.users
                SET    last_store_id          = %s,
                       last_retailer_group_id = (
                           SELECT retailer_group_id
                           FROM   faciais.stores WHERE store_id = %s
                       )
                WHERE  user_id = %s
            """, (_sid, _sid, user_id))
        else:
            db.execute(
                "UPDATE faciais.users SET last_store_id = %s WHERE user_id = %s",
                (_sid, user_id)
            )

    # CNPJ da loja (14 dígitos com zeros à esquerda) para filtro no microvix
    active_store_cnpj = None
    active_microvix_portal = None
    if active_store:
        if active_store['cnpj']:
            active_store_cnpj = str(active_store['cnpj']).zfill(14)
        row = db.query_one("""
            SELECT c.microvix_portal
            FROM   faciais.stores s
            JOIN   faciais.companies c ON c.company_id = s.company_id
            WHERE  s.store_id = %s
        """, (active_store['store_id'],))
        if row:
            active_microvix_portal = row['microvix_portal']

    # ── Data selecionada (padrão: hoje) ───────────────────────────────────────
    data_str = request.args.get('date', date_type.today().strftime('%Y-%m-%d'))
    try:
        date_type.fromisoformat(data_str)
    except ValueError:
        data_str = date_type.today().strftime('%Y-%m-%d')

    # ── Períodos: semana e mês ────────────────────────────────────────────────
    selected_date     = date_type.fromisoformat(data_str)
    semana_inicio     = selected_date - timedelta(days=selected_date.weekday())
    semana_fim        = semana_inicio + timedelta(days=6)
    _, ultimo_dia     = calendar.monthrange(selected_date.year, selected_date.month)
    mes_inicio        = selected_date.replace(day=1)
    mes_fim           = selected_date.replace(day=ultimo_dia)
    semana_inicio_str = semana_inicio.strftime('%Y-%m-%d')
    semana_fim_str    = semana_fim.strftime('%Y-%m-%d')
    mes_inicio_str    = mes_inicio.strftime('%Y-%m-%d')
    mes_fim_str       = mes_fim.strftime('%Y-%m-%d')

    semana_anterior_str = (semana_inicio - timedelta(days=1)).strftime('%Y-%m-%d')
    semana_proxima_str  = (semana_fim    + timedelta(days=1)).strftime('%Y-%m-%d')
    mes_anterior_str    = (mes_inicio    - timedelta(days=1)).strftime('%Y-%m-%d')
    mes_proximo_str     = (mes_fim       + timedelta(days=1)).strftime('%Y-%m-%d')

    # ── Períodos anteriores para comparação ──────────────────────────────────
    semana_ant_inicio     = semana_inicio - timedelta(days=7)
    semana_ant_fim        = semana_fim    - timedelta(days=7)
    semana_ant_inicio_str = semana_ant_inicio.strftime('%Y-%m-%d')
    semana_ant_fim_str    = semana_ant_fim.strftime('%Y-%m-%d')
    mes_ant_fim           = mes_inicio - timedelta(days=1)
    mes_ant_inicio        = mes_ant_fim.replace(day=1)
    mes_ant_inicio_str    = mes_ant_inicio.strftime('%Y-%m-%d')
    mes_ant_fim_str       = mes_ant_fim.strftime('%Y-%m-%d')

    _MESES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
              'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
    semana_label = f"{semana_inicio.strftime('%d/%m')} – {semana_fim.strftime('%d/%m/%Y')}"
    mes_label    = f"{_MESES[selected_date.month - 1]} {selected_date.year}"

    # ── YTD: período do ano fiscal ────────────────────────────────────────────
    def _replace_year_safe(d, year):
        try:
            return d.replace(year=year)
        except ValueError:
            return date_type(year, d.month, 28)

    _fiscal_row = None
    if active_store:
        _fiscal_row = db.query_one("""
            SELECT c.fiscal_year_start_date
            FROM   faciais.stores s
            JOIN   faciais.companies c ON c.company_id = s.company_id
            WHERE  s.store_id = %s
        """, (active_store['store_id'],))
    _fys = _fiscal_row['fiscal_year_start_date'] if _fiscal_row else None
    if _fys:
        try:
            _ytd_cand = date_type(selected_date.year, _fys.month, _fys.day)
        except ValueError:
            _ytd_cand = date_type(selected_date.year, _fys.month, 28)
        ytd_inicio = _ytd_cand if _ytd_cand <= selected_date else _replace_year_safe(_ytd_cand, selected_date.year - 1)
    else:
        ytd_inicio = selected_date.replace(month=1, day=1)
    ytd_fim            = selected_date
    ytd_ant_inicio     = _replace_year_safe(ytd_inicio, ytd_inicio.year - 1)
    ytd_ant_fim        = _replace_year_safe(ytd_fim,    ytd_fim.year   - 1)
    ytd_inicio_str     = ytd_inicio.strftime('%Y-%m-%d')
    ytd_fim_str        = ytd_fim.strftime('%Y-%m-%d')
    ytd_ant_inicio_str = ytd_ant_inicio.strftime('%Y-%m-%d')
    ytd_ant_fim_str    = ytd_ant_fim.strftime('%Y-%m-%d')
    ytd_label          = f"{ytd_inicio.strftime('%d/%m/%Y')} – {ytd_fim.strftime('%d/%m/%Y')}"

    # ── KPIs Operacional – Dia ────────────────────────────────────────────────
    kpi = dict(visitantes=None, recorrentes=None, vendas=None, conversao=None, tempo_loja=None)

    # ── KPIs Comercial – Dia ──────────────────────────────────────────────────
    kpi_com = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)

    # ── KPIs Operacional – Semana / Mês ──────────────────────────────────────
    kpi_sem     = dict(visitantes=None, recorrentes=None, vendas=None, conversao=None, tempo_loja=None)
    kpi_mes     = dict(visitantes=None, recorrentes=None, vendas=None, conversao=None, tempo_loja=None)

    # ── KPIs Comercial – Semana / Mês ────────────────────────────────────────
    kpi_com_sem = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)
    kpi_com_mes = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)

    # ── KPIs Operacional / Comercial – YTD ───────────────────────────────────
    kpi_ytd     = dict(visitantes=None, recorrentes=None, vendas=None, conversao=None, tempo_loja=None)
    kpi_com_ytd = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)

    if active_store:
        sid = active_store['store_id']

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  dr.store_id      = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) = %s
        """, (sid, data_str))
        kpi['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  dr.store_id      = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) = %s
              AND  EXISTS (
                  SELECT 1
                  FROM   faciais.detection_records dr2
                  WHERE  dr2.person_id  = dr.person_id
                    AND  dr2.store_id   = %s
                    AND  DATE(dr2.created_at) < %s
              )
        """, (sid, data_str, sid, data_str))
        kpi['recorrentes'] = r['total'] if r else 0

        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento) AS total
                FROM   microvix.microvix_movimento
                WHERE  portal                  = %s
                  AND  cnpj_emp                = %s
                  AND  DATE(data_documento)    = %s
                  AND  cancelado              <> 'S'
                  AND  excluido              <> 'S'
                  AND  soma_relatorio          = 'S'
                  AND  tipo_transacao          = 'V'
                  AND  cod_natureza_operacao   = '10030'
            """, (active_microvix_portal, active_store_cnpj, data_str))
            kpi['vendas'] = r['total'] if r else 0
        else:
            kpi['vendas'] = None

        if kpi['visitantes']:
            kpi['conversao'] = int(round((kpi['vendas'] or 0) / kpi['visitantes'] * 100))
        else:
            kpi['conversao'] = 0

        r = db.query_one("""
            SELECT ROUND(AVG(perm)::numeric) AS avg_seg
            FROM (
                SELECT EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS perm
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL AND DATE(dr.created_at) = %s
                GROUP  BY dr.person_id
                HAVING MAX(dr.created_at) > MIN(dr.created_at)
            ) sub
        """, (sid, data_str))
        kpi['tempo_loja'] = int(r['avg_seg']) if r and r['avg_seg'] else None

        # ── Comercial – Dia ───────────────────────────────────────────────────
        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento)          AS vendas,
                       SUM(valor_liquido)                 AS faturamento,
                       SUM(quantidade)                    AS total_itens
                FROM   microvix.microvix_movimento
                WHERE  portal                  = %s
                  AND  cnpj_emp                = %s
                  AND  DATE(data_documento)    = %s
                  AND  cancelado              <> 'S'
                  AND  excluido              <> 'S'
                  AND  soma_relatorio          = 'S'
                  AND  tipo_transacao          = 'V'
                  AND  cod_natureza_operacao   = '10030'
            """, (active_microvix_portal, active_store_cnpj, data_str))

            if r and r['vendas']:
                v = int(r['vendas'])
                f = float(r['faturamento'] or 0)
                t = float(r['total_itens'] or 0)
                kpi_com['vendas']      = v
                kpi_com['faturamento'] = round(f, 2)
                kpi_com['ticket_medio'] = round(f / v, 2) if v else 0.0
                kpi_com['itens_venda']  = round(t / v, 1) if v else 0.0
            else:
                kpi_com['vendas']       = 0
                kpi_com['faturamento']  = 0.0
                kpi_com['ticket_medio'] = 0.0
                kpi_com['itens_venda']  = 0.0

        # ── Operacional – Semana ─────────────────────────────────────────────
        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  dr.store_id      = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
        """, (sid, semana_inicio_str, semana_fim_str))
        kpi_sem['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  dr.store_id      = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
              AND  EXISTS (
                  SELECT 1
                  FROM   faciais.detection_records dr2
                  WHERE  dr2.person_id        = dr.person_id
                    AND  dr2.store_id         = %s
                    AND  DATE(dr2.created_at) < DATE(dr.created_at)
              )
        """, (sid, semana_inicio_str, semana_fim_str, sid))
        kpi_sem['recorrentes'] = r['total'] if r else 0

        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento) AS total
                FROM   microvix.microvix_movimento
                WHERE  portal                  = %s
                  AND  cnpj_emp                = %s
                  AND  DATE(data_documento)    BETWEEN %s AND %s
                  AND  cancelado              <> 'S'
                  AND  excluido              <> 'S'
                  AND  soma_relatorio          = 'S'
                  AND  tipo_transacao          = 'V'
                  AND  cod_natureza_operacao   = '10030'
            """, (active_microvix_portal, active_store_cnpj, semana_inicio_str, semana_fim_str))
            kpi_sem['vendas'] = r['total'] if r else 0
        else:
            kpi_sem['vendas'] = None

        if kpi_sem['visitantes']:
            kpi_sem['conversao'] = int(round((kpi_sem['vendas'] or 0) / kpi_sem['visitantes'] * 100))
        else:
            kpi_sem['conversao'] = 0

        r = db.query_one("""
            SELECT ROUND(AVG(perm)::numeric) AS avg_seg
            FROM (
                SELECT EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS perm
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, DATE(dr.created_at)
                HAVING MAX(dr.created_at) > MIN(dr.created_at)
            ) sub
        """, (sid, semana_inicio_str, semana_fim_str))
        kpi_sem['tempo_loja'] = int(r['avg_seg']) if r and r['avg_seg'] else None

        # ── Comercial – Semana ────────────────────────────────────────────────
        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento)          AS vendas,
                       SUM(valor_liquido)                 AS faturamento,
                       SUM(quantidade)                    AS total_itens
                FROM   microvix.microvix_movimento
                WHERE  portal                  = %s
                  AND  cnpj_emp                = %s
                  AND  DATE(data_documento)    BETWEEN %s AND %s
                  AND  cancelado              <> 'S'
                  AND  excluido              <> 'S'
                  AND  soma_relatorio          = 'S'
                  AND  tipo_transacao          = 'V'
                  AND  cod_natureza_operacao   = '10030'
            """, (active_microvix_portal, active_store_cnpj, semana_inicio_str, semana_fim_str))
            if r and r['vendas']:
                v = int(r['vendas']); f = float(r['faturamento'] or 0); t = float(r['total_itens'] or 0)
                kpi_com_sem['vendas']       = v
                kpi_com_sem['faturamento']  = round(f, 2)
                kpi_com_sem['ticket_medio'] = round(f / v, 2) if v else 0.0
                kpi_com_sem['itens_venda']  = round(t / v, 1) if v else 0.0
            else:
                kpi_com_sem['vendas'] = 0; kpi_com_sem['faturamento'] = 0.0
                kpi_com_sem['ticket_medio'] = 0.0; kpi_com_sem['itens_venda'] = 0.0

        # ── Operacional – Mês ─────────────────────────────────────────────────
        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  dr.store_id      = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
        """, (sid, mes_inicio_str, mes_fim_str))
        kpi_mes['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  dr.store_id      = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
              AND  EXISTS (
                  SELECT 1
                  FROM   faciais.detection_records dr2
                  WHERE  dr2.person_id        = dr.person_id
                    AND  dr2.store_id         = %s
                    AND  DATE(dr2.created_at) < DATE(dr.created_at)
              )
        """, (sid, mes_inicio_str, mes_fim_str, sid))
        kpi_mes['recorrentes'] = r['total'] if r else 0

        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento) AS total
                FROM   microvix.microvix_movimento
                WHERE  portal                  = %s
                  AND  cnpj_emp                = %s
                  AND  DATE(data_documento)    BETWEEN %s AND %s
                  AND  cancelado              <> 'S'
                  AND  excluido              <> 'S'
                  AND  soma_relatorio          = 'S'
                  AND  tipo_transacao          = 'V'
                  AND  cod_natureza_operacao   = '10030'
            """, (active_microvix_portal, active_store_cnpj, mes_inicio_str, mes_fim_str))
            kpi_mes['vendas'] = r['total'] if r else 0
        else:
            kpi_mes['vendas'] = None

        if kpi_mes['visitantes']:
            kpi_mes['conversao'] = int(round((kpi_mes['vendas'] or 0) / kpi_mes['visitantes'] * 100))
        else:
            kpi_mes['conversao'] = 0

        r = db.query_one("""
            SELECT ROUND(AVG(perm)::numeric) AS avg_seg
            FROM (
                SELECT EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS perm
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, DATE(dr.created_at)
                HAVING MAX(dr.created_at) > MIN(dr.created_at)
            ) sub
        """, (sid, mes_inicio_str, mes_fim_str))
        kpi_mes['tempo_loja'] = int(r['avg_seg']) if r and r['avg_seg'] else None

        # ── Comercial – Mês ───────────────────────────────────────────────────
        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento)          AS vendas,
                       SUM(valor_liquido)                 AS faturamento,
                       SUM(quantidade)                    AS total_itens
                FROM   microvix.microvix_movimento
                WHERE  portal                  = %s
                  AND  cnpj_emp                = %s
                  AND  DATE(data_documento)    BETWEEN %s AND %s
                  AND  cancelado              <> 'S'
                  AND  excluido              <> 'S'
                  AND  soma_relatorio          = 'S'
                  AND  tipo_transacao          = 'V'
                  AND  cod_natureza_operacao   = '10030'
            """, (active_microvix_portal, active_store_cnpj, mes_inicio_str, mes_fim_str))
            if r and r['vendas']:
                v = int(r['vendas']); f = float(r['faturamento'] or 0); t = float(r['total_itens'] or 0)
                kpi_com_mes['vendas']       = v
                kpi_com_mes['faturamento']  = round(f, 2)
                kpi_com_mes['ticket_medio'] = round(f / v, 2) if v else 0.0
                kpi_com_mes['itens_venda']  = round(t / v, 1) if v else 0.0
            else:
                kpi_com_mes['vendas'] = 0; kpi_com_mes['faturamento'] = 0.0
                kpi_com_mes['ticket_medio'] = 0.0; kpi_com_mes['itens_venda'] = 0.0

        # ── Operacional – YTD ─────────────────────────────────────────────────
        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  dr.store_id      = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
        """, (sid, ytd_inicio_str, ytd_fim_str))
        kpi_ytd['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  dr.store_id      = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
              AND  EXISTS (
                  SELECT 1
                  FROM   faciais.detection_records dr2
                  WHERE  dr2.person_id        = dr.person_id
                    AND  dr2.store_id         = %s
                    AND  DATE(dr2.created_at) < DATE(dr.created_at)
              )
        """, (sid, ytd_inicio_str, ytd_fim_str, sid))
        kpi_ytd['recorrentes'] = r['total'] if r else 0

        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento) AS total
                FROM   microvix.microvix_movimento
                WHERE  portal                  = %s
                  AND  cnpj_emp                = %s
                  AND  DATE(data_documento)    BETWEEN %s AND %s
                  AND  cancelado              <> 'S'
                  AND  excluido              <> 'S'
                  AND  soma_relatorio          = 'S'
                  AND  tipo_transacao          = 'V'
                  AND  cod_natureza_operacao   = '10030'
            """, (active_microvix_portal, active_store_cnpj, ytd_inicio_str, ytd_fim_str))
            kpi_ytd['vendas'] = r['total'] if r else 0
        else:
            kpi_ytd['vendas'] = None

        if kpi_ytd['visitantes']:
            kpi_ytd['conversao'] = int(round((kpi_ytd['vendas'] or 0) / kpi_ytd['visitantes'] * 100))
        else:
            kpi_ytd['conversao'] = 0

        r = db.query_one("""
            SELECT ROUND(AVG(perm)::numeric) AS avg_seg
            FROM (
                SELECT EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS perm
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, DATE(dr.created_at)
                HAVING MAX(dr.created_at) > MIN(dr.created_at)
            ) sub
        """, (sid, ytd_inicio_str, ytd_fim_str))
        kpi_ytd['tempo_loja'] = int(r['avg_seg']) if r and r['avg_seg'] else None

        # ── Comercial – YTD ───────────────────────────────────────────────────
        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento)          AS vendas,
                       SUM(valor_liquido)                 AS faturamento,
                       SUM(quantidade)                    AS total_itens
                FROM   microvix.microvix_movimento
                WHERE  portal                  = %s
                  AND  cnpj_emp                = %s
                  AND  DATE(data_documento)    BETWEEN %s AND %s
                  AND  cancelado              <> 'S'
                  AND  excluido              <> 'S'
                  AND  soma_relatorio          = 'S'
                  AND  tipo_transacao          = 'V'
                  AND  cod_natureza_operacao   = '10030'
            """, (active_microvix_portal, active_store_cnpj, ytd_inicio_str, ytd_fim_str))
            if r and r['vendas']:
                v = int(r['vendas']); f = float(r['faturamento'] or 0); t = float(r['total_itens'] or 0)
                kpi_com_ytd['vendas']       = v
                kpi_com_ytd['faturamento']  = round(f, 2)
                kpi_com_ytd['ticket_medio'] = round(f / v, 2) if v else 0.0
                kpi_com_ytd['itens_venda']  = round(t / v, 1) if v else 0.0
            else:
                kpi_com_ytd['vendas'] = 0; kpi_com_ytd['faturamento'] = 0.0
                kpi_com_ytd['ticket_medio'] = 0.0; kpi_com_ytd['itens_venda'] = 0.0

    # ── KPIs Estratégico – derivados dos KPIs já calculados ──────────────────
    kpi_est     = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None, taxa_retorno=None, valor_medio=None)
    kpi_est_sem = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None, taxa_retorno=None, valor_medio=None)
    kpi_est_mes = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None, taxa_retorno=None, valor_medio=None)

    if kpi['visitantes'] is not None and kpi['recorrentes'] is not None:
        kpi_est['novos']       = kpi['visitantes'] - kpi['recorrentes']
        kpi_est['recorrentes'] = kpi['recorrentes']
        _t = (kpi_est['novos'] or 0) + (kpi_est['recorrentes'] or 0)
        kpi_est['taxa_retorno'] = round((kpi_est['recorrentes'] or 0) / _t * 100) if _t else 0
        if kpi_com['faturamento'] is not None:
            fat = kpi_com['faturamento'] or 0
            kpi_est['valor_medio'] = round(fat / _t, 2) if _t else None
        if active_microvix_portal and active_store_cnpj:
            _tk = _ticket_por_tipo(active_store['store_id'], active_microvix_portal, active_store_cnpj,
                                   data_str, data_str, data_str)
            kpi_est['ticket_novo'] = _tk['ticket_novo']
            kpi_est['ticket_rec']  = _tk['ticket_rec']

    if kpi_sem['visitantes'] is not None and kpi_sem['recorrentes'] is not None:
        kpi_est_sem['novos']       = kpi_sem['visitantes'] - kpi_sem['recorrentes']
        kpi_est_sem['recorrentes'] = kpi_sem['recorrentes']
        _t = (kpi_est_sem['novos'] or 0) + (kpi_est_sem['recorrentes'] or 0)
        kpi_est_sem['taxa_retorno'] = round((kpi_est_sem['recorrentes'] or 0) / _t * 100) if _t else 0
        if kpi_com_sem['faturamento'] is not None:
            fat = kpi_com_sem['faturamento'] or 0
            kpi_est_sem['valor_medio'] = round(fat / _t, 2) if _t else None
        if active_microvix_portal and active_store_cnpj:
            _tk = _ticket_por_tipo(active_store['store_id'], active_microvix_portal, active_store_cnpj,
                                   semana_inicio_str, semana_fim_str, semana_inicio_str)
            kpi_est_sem['ticket_novo'] = _tk['ticket_novo']
            kpi_est_sem['ticket_rec']  = _tk['ticket_rec']

    if kpi_mes['visitantes'] is not None and kpi_mes['recorrentes'] is not None:
        kpi_est_mes['novos']       = kpi_mes['visitantes'] - kpi_mes['recorrentes']
        kpi_est_mes['recorrentes'] = kpi_mes['recorrentes']
        _t = (kpi_est_mes['novos'] or 0) + (kpi_est_mes['recorrentes'] or 0)
        kpi_est_mes['taxa_retorno'] = round((kpi_est_mes['recorrentes'] or 0) / _t * 100) if _t else 0
        if kpi_com_mes['faturamento'] is not None:
            fat = kpi_com_mes['faturamento'] or 0
            kpi_est_mes['valor_medio'] = round(fat / _t, 2) if _t else None
        if active_microvix_portal and active_store_cnpj:
            _tk = _ticket_por_tipo(active_store['store_id'], active_microvix_portal, active_store_cnpj,
                                   mes_inicio_str, mes_fim_str, mes_inicio_str)
            kpi_est_mes['ticket_novo'] = _tk['ticket_novo']
            kpi_est_mes['ticket_rec']  = _tk['ticket_rec']

    kpi_est_ytd = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None, taxa_retorno=None, valor_medio=None)
    if kpi_ytd['visitantes'] is not None and kpi_ytd['recorrentes'] is not None:
        kpi_est_ytd['novos']       = kpi_ytd['visitantes'] - kpi_ytd['recorrentes']
        kpi_est_ytd['recorrentes'] = kpi_ytd['recorrentes']
        _t = (kpi_est_ytd['novos'] or 0) + (kpi_est_ytd['recorrentes'] or 0)
        kpi_est_ytd['taxa_retorno'] = round((kpi_est_ytd['recorrentes'] or 0) / _t * 100) if _t else 0
        if kpi_com_ytd['faturamento'] is not None:
            fat = kpi_com_ytd['faturamento'] or 0
            kpi_est_ytd['valor_medio'] = round(fat / _t, 2) if _t else None
        if active_microvix_portal and active_store_cnpj:
            _tk = _ticket_por_tipo(active_store['store_id'], active_microvix_portal, active_store_cnpj,
                                   ytd_inicio_str, ytd_fim_str, ytd_inicio_str)
            kpi_est_ytd['ticket_novo'] = _tk['ticket_novo']
            kpi_est_ytd['ticket_rec']  = _tk['ticket_rec']

    # ── KPIs dia útil anterior (comparação) ──────────────────────────────────
    kpi_ant = dict(visitantes=None, recorrentes=None, novos=None,
                   vendas=None, conversao=None, tempo_loja=None, taxa_retorno=None, valor_medio=None)
    if active_store:
        _prev = _prev_business_day(selected_date)
        _ps   = _prev.strftime('%Y-%m-%d')
        sid   = active_store['store_id']

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people p ON p.person_id = dr.person_id
            WHERE  dr.store_id = %s AND p.person_type_id = 'C'
              AND  dr.person_id IS NOT NULL AND DATE(dr.created_at) = %s
        """, (sid, _ps))
        kpi_ant['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people p ON p.person_id = dr.person_id
            WHERE  dr.store_id = %s AND p.person_type_id = 'C'
              AND  dr.person_id IS NOT NULL AND DATE(dr.created_at) = %s
              AND  EXISTS (
                  SELECT 1 FROM faciais.detection_records dr2
                  WHERE  dr2.person_id = dr.person_id AND dr2.store_id = %s
                    AND  DATE(dr2.created_at) < %s
              )
        """, (sid, _ps, sid, _ps))
        kpi_ant['recorrentes'] = r['total'] if r else 0
        kpi_ant['novos'] = kpi_ant['visitantes'] - kpi_ant['recorrentes']

        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento) AS total
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s AND DATE(data_documento) = %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
            """, (active_microvix_portal, active_store_cnpj, _ps))
            kpi_ant['vendas'] = r['total'] if r else 0

        if kpi_ant['visitantes']:
            kpi_ant['conversao'] = int(round((kpi_ant['vendas'] or 0) / kpi_ant['visitantes'] * 100))
        else:
            kpi_ant['conversao'] = 0

        r = db.query_one("""
            SELECT ROUND(AVG(perm)::numeric) AS avg_seg
            FROM (
                SELECT EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS perm
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL AND DATE(dr.created_at) = %s
                GROUP  BY dr.person_id
                HAVING MAX(dr.created_at) > MIN(dr.created_at)
            ) sub
        """, (sid, _ps))
        kpi_ant['tempo_loja'] = int(r['avg_seg']) if r and r['avg_seg'] else None

    kpi_ant_com = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)
    if active_store and active_microvix_portal and active_store_cnpj:
        _ps_com = _prev_business_day(selected_date).strftime('%Y-%m-%d')
        r = db.query_one("""
            SELECT COUNT(DISTINCT documento) AS vendas,
                   SUM(valor_liquido)        AS faturamento,
                   SUM(quantidade)           AS total_itens
            FROM   microvix.microvix_movimento
            WHERE  portal = %s AND cnpj_emp = %s AND DATE(data_documento) = %s
              AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
              AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
        """, (active_microvix_portal, active_store_cnpj, _ps_com))
        if r and r['vendas']:
            v = int(r['vendas']); f = float(r['faturamento'] or 0); t = float(r['total_itens'] or 0)
            kpi_ant_com['vendas']       = v
            kpi_ant_com['faturamento']  = round(f, 2)
            kpi_ant_com['ticket_medio'] = round(f / v, 2) if v else 0.0
            kpi_ant_com['itens_venda']  = round(t / v, 1) if v else 0.0
        else:
            kpi_ant_com['vendas'] = 0; kpi_ant_com['faturamento'] = 0.0
            kpi_ant_com['ticket_medio'] = 0.0; kpi_ant_com['itens_venda'] = 0.0
    if kpi_ant['novos'] is not None and kpi_ant['recorrentes'] is not None:
        _t_ant = (kpi_ant['novos'] or 0) + (kpi_ant['recorrentes'] or 0)
        kpi_ant['taxa_retorno'] = round((kpi_ant['recorrentes'] or 0) / _t_ant * 100) if _t_ant else 0
        if kpi_ant_com['faturamento'] is not None and _t_ant:
            kpi_ant['valor_medio'] = round(kpi_ant_com['faturamento'] / _t_ant, 2)

    # ── KPIs semana anterior (comparação) ────────────────────────────────────
    kpi_ant_sem = dict(visitantes=None, recorrentes=None, novos=None,
                       vendas=None, conversao=None, tempo_loja=None, taxa_retorno=None, valor_medio=None)
    if active_store:
        sid = active_store['store_id']
        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people p ON p.person_id = dr.person_id
            WHERE  dr.store_id = %s AND p.person_type_id = 'C'
              AND  dr.person_id IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
        """, (sid, semana_ant_inicio_str, semana_ant_fim_str))
        kpi_ant_sem['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people p ON p.person_id = dr.person_id
            WHERE  dr.store_id = %s AND p.person_type_id = 'C'
              AND  dr.person_id IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
              AND  EXISTS (
                  SELECT 1 FROM faciais.detection_records dr2
                  WHERE  dr2.person_id = dr.person_id AND dr2.store_id = %s
                    AND  DATE(dr2.created_at) < DATE(dr.created_at)
              )
        """, (sid, semana_ant_inicio_str, semana_ant_fim_str, sid))
        kpi_ant_sem['recorrentes'] = r['total'] if r else 0
        kpi_ant_sem['novos'] = kpi_ant_sem['visitantes'] - kpi_ant_sem['recorrentes']

        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento) AS total
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s
                  AND  DATE(data_documento) BETWEEN %s AND %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
            """, (active_microvix_portal, active_store_cnpj, semana_ant_inicio_str, semana_ant_fim_str))
            kpi_ant_sem['vendas'] = r['total'] if r else 0

        if kpi_ant_sem['visitantes']:
            kpi_ant_sem['conversao'] = int(round((kpi_ant_sem['vendas'] or 0) / kpi_ant_sem['visitantes'] * 100))
        else:
            kpi_ant_sem['conversao'] = 0

        r = db.query_one("""
            SELECT ROUND(AVG(perm)::numeric) AS avg_seg
            FROM (
                SELECT EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS perm
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, DATE(dr.created_at)
                HAVING MAX(dr.created_at) > MIN(dr.created_at)
            ) sub
        """, (sid, semana_ant_inicio_str, semana_ant_fim_str))
        kpi_ant_sem['tempo_loja'] = int(r['avg_seg']) if r and r['avg_seg'] else None

    kpi_ant_com_sem = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)
    if active_store and active_microvix_portal and active_store_cnpj:
        r = db.query_one("""
            SELECT COUNT(DISTINCT documento) AS vendas,
                   SUM(valor_liquido)        AS faturamento,
                   SUM(quantidade)           AS total_itens
            FROM   microvix.microvix_movimento
            WHERE  portal = %s AND cnpj_emp = %s
              AND  DATE(data_documento) BETWEEN %s AND %s
              AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
              AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
        """, (active_microvix_portal, active_store_cnpj, semana_ant_inicio_str, semana_ant_fim_str))
        if r and r['vendas']:
            v = int(r['vendas']); f = float(r['faturamento'] or 0); t = float(r['total_itens'] or 0)
            kpi_ant_com_sem['vendas']       = v
            kpi_ant_com_sem['faturamento']  = round(f, 2)
            kpi_ant_com_sem['ticket_medio'] = round(f / v, 2) if v else 0.0
            kpi_ant_com_sem['itens_venda']  = round(t / v, 1) if v else 0.0
        else:
            kpi_ant_com_sem['vendas'] = 0; kpi_ant_com_sem['faturamento'] = 0.0
            kpi_ant_com_sem['ticket_medio'] = 0.0; kpi_ant_com_sem['itens_venda'] = 0.0
    if kpi_ant_sem['novos'] is not None and kpi_ant_sem['recorrentes'] is not None:
        _t_ant = (kpi_ant_sem['novos'] or 0) + (kpi_ant_sem['recorrentes'] or 0)
        kpi_ant_sem['taxa_retorno'] = round((kpi_ant_sem['recorrentes'] or 0) / _t_ant * 100) if _t_ant else 0
        if kpi_ant_com_sem['faturamento'] is not None and _t_ant:
            kpi_ant_sem['valor_medio'] = round(kpi_ant_com_sem['faturamento'] / _t_ant, 2)

    # ── KPIs mês anterior (comparação) ───────────────────────────────────────
    kpi_ant_mes = dict(visitantes=None, recorrentes=None, novos=None,
                       vendas=None, conversao=None, tempo_loja=None, taxa_retorno=None, valor_medio=None)
    if active_store:
        sid = active_store['store_id']
        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people p ON p.person_id = dr.person_id
            WHERE  dr.store_id = %s AND p.person_type_id = 'C'
              AND  dr.person_id IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
        """, (sid, mes_ant_inicio_str, mes_ant_fim_str))
        kpi_ant_mes['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people p ON p.person_id = dr.person_id
            WHERE  dr.store_id = %s AND p.person_type_id = 'C'
              AND  dr.person_id IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
              AND  EXISTS (
                  SELECT 1 FROM faciais.detection_records dr2
                  WHERE  dr2.person_id = dr.person_id AND dr2.store_id = %s
                    AND  DATE(dr2.created_at) < DATE(dr.created_at)
              )
        """, (sid, mes_ant_inicio_str, mes_ant_fim_str, sid))
        kpi_ant_mes['recorrentes'] = r['total'] if r else 0
        kpi_ant_mes['novos'] = kpi_ant_mes['visitantes'] - kpi_ant_mes['recorrentes']

        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento) AS total
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s
                  AND  DATE(data_documento) BETWEEN %s AND %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
            """, (active_microvix_portal, active_store_cnpj, mes_ant_inicio_str, mes_ant_fim_str))
            kpi_ant_mes['vendas'] = r['total'] if r else 0

        if kpi_ant_mes['visitantes']:
            kpi_ant_mes['conversao'] = int(round((kpi_ant_mes['vendas'] or 0) / kpi_ant_mes['visitantes'] * 100))
        else:
            kpi_ant_mes['conversao'] = 0

        r = db.query_one("""
            SELECT ROUND(AVG(perm)::numeric) AS avg_seg
            FROM (
                SELECT EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS perm
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, DATE(dr.created_at)
                HAVING MAX(dr.created_at) > MIN(dr.created_at)
            ) sub
        """, (sid, mes_ant_inicio_str, mes_ant_fim_str))
        kpi_ant_mes['tempo_loja'] = int(r['avg_seg']) if r and r['avg_seg'] else None

    kpi_ant_com_mes = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)
    if active_store and active_microvix_portal and active_store_cnpj:
        r = db.query_one("""
            SELECT COUNT(DISTINCT documento) AS vendas,
                   SUM(valor_liquido)        AS faturamento,
                   SUM(quantidade)           AS total_itens
            FROM   microvix.microvix_movimento
            WHERE  portal = %s AND cnpj_emp = %s
              AND  DATE(data_documento) BETWEEN %s AND %s
              AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
              AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
        """, (active_microvix_portal, active_store_cnpj, mes_ant_inicio_str, mes_ant_fim_str))
        if r and r['vendas']:
            v = int(r['vendas']); f = float(r['faturamento'] or 0); t = float(r['total_itens'] or 0)
            kpi_ant_com_mes['vendas']       = v
            kpi_ant_com_mes['faturamento']  = round(f, 2)
            kpi_ant_com_mes['ticket_medio'] = round(f / v, 2) if v else 0.0
            kpi_ant_com_mes['itens_venda']  = round(t / v, 1) if v else 0.0
        else:
            kpi_ant_com_mes['vendas'] = 0; kpi_ant_com_mes['faturamento'] = 0.0
            kpi_ant_com_mes['ticket_medio'] = 0.0; kpi_ant_com_mes['itens_venda'] = 0.0
    if kpi_ant_mes['novos'] is not None and kpi_ant_mes['recorrentes'] is not None:
        _t_ant = (kpi_ant_mes['novos'] or 0) + (kpi_ant_mes['recorrentes'] or 0)
        kpi_ant_mes['taxa_retorno'] = round((kpi_ant_mes['recorrentes'] or 0) / _t_ant * 100) if _t_ant else 0
        if kpi_ant_com_mes['faturamento'] is not None and _t_ant:
            kpi_ant_mes['valor_medio'] = round(kpi_ant_com_mes['faturamento'] / _t_ant, 2)

    # ── KPIs YTD anterior (comparação – mesmo período, ano fiscal anterior) ───
    kpi_ant_ytd = dict(visitantes=None, recorrentes=None, novos=None,
                       vendas=None, conversao=None, tempo_loja=None, taxa_retorno=None, valor_medio=None)
    if active_store:
        sid = active_store['store_id']
        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people p ON p.person_id = dr.person_id
            WHERE  dr.store_id = %s AND p.person_type_id = 'C'
              AND  dr.person_id IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
        """, (sid, ytd_ant_inicio_str, ytd_ant_fim_str))
        kpi_ant_ytd['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.people p ON p.person_id = dr.person_id
            WHERE  dr.store_id = %s AND p.person_type_id = 'C'
              AND  dr.person_id IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
              AND  EXISTS (
                  SELECT 1 FROM faciais.detection_records dr2
                  WHERE  dr2.person_id = dr.person_id AND dr2.store_id = %s
                    AND  DATE(dr2.created_at) < DATE(dr.created_at)
              )
        """, (sid, ytd_ant_inicio_str, ytd_ant_fim_str, sid))
        kpi_ant_ytd['recorrentes'] = r['total'] if r else 0
        kpi_ant_ytd['novos'] = kpi_ant_ytd['visitantes'] - kpi_ant_ytd['recorrentes']

        if active_microvix_portal and active_store_cnpj:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento) AS total
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s
                  AND  DATE(data_documento) BETWEEN %s AND %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
            """, (active_microvix_portal, active_store_cnpj, ytd_ant_inicio_str, ytd_ant_fim_str))
            kpi_ant_ytd['vendas'] = r['total'] if r else 0

        if kpi_ant_ytd['visitantes']:
            kpi_ant_ytd['conversao'] = int(round((kpi_ant_ytd['vendas'] or 0) / kpi_ant_ytd['visitantes'] * 100))
        else:
            kpi_ant_ytd['conversao'] = 0

        r = db.query_one("""
            SELECT ROUND(AVG(perm)::numeric) AS avg_seg
            FROM (
                SELECT EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS perm
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, DATE(dr.created_at)
                HAVING MAX(dr.created_at) > MIN(dr.created_at)
            ) sub
        """, (sid, ytd_ant_inicio_str, ytd_ant_fim_str))
        kpi_ant_ytd['tempo_loja'] = int(r['avg_seg']) if r and r['avg_seg'] else None

    kpi_ant_com_ytd = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)
    if active_store and active_microvix_portal and active_store_cnpj:
        r = db.query_one("""
            SELECT COUNT(DISTINCT documento) AS vendas,
                   SUM(valor_liquido)        AS faturamento,
                   SUM(quantidade)           AS total_itens
            FROM   microvix.microvix_movimento
            WHERE  portal = %s AND cnpj_emp = %s
              AND  DATE(data_documento) BETWEEN %s AND %s
              AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
              AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
        """, (active_microvix_portal, active_store_cnpj, ytd_ant_inicio_str, ytd_ant_fim_str))
        if r and r['vendas']:
            v = int(r['vendas']); f = float(r['faturamento'] or 0); t = float(r['total_itens'] or 0)
            kpi_ant_com_ytd['vendas']       = v
            kpi_ant_com_ytd['faturamento']  = round(f, 2)
            kpi_ant_com_ytd['ticket_medio'] = round(f / v, 2) if v else 0.0
            kpi_ant_com_ytd['itens_venda']  = round(t / v, 1) if v else 0.0
        else:
            kpi_ant_com_ytd['vendas'] = 0; kpi_ant_com_ytd['faturamento'] = 0.0
            kpi_ant_com_ytd['ticket_medio'] = 0.0; kpi_ant_com_ytd['itens_venda'] = 0.0
    if kpi_ant_ytd['novos'] is not None and kpi_ant_ytd['recorrentes'] is not None:
        _t_ant = (kpi_ant_ytd['novos'] or 0) + (kpi_ant_ytd['recorrentes'] or 0)
        kpi_ant_ytd['taxa_retorno'] = round((kpi_ant_ytd['recorrentes'] or 0) / _t_ant * 100) if _t_ant else 0
        if kpi_ant_com_ytd['faturamento'] is not None and _t_ant:
            kpi_ant_ytd['valor_medio'] = round(kpi_ant_com_ytd['faturamento'] / _t_ant, 2)

    # ── Gauge do Tempo na Loja (agulha SVG) ──────────────────────────────────
    kpi_tempo_gauge = None
    if kpi['tempo_loja'] is not None and kpi['tempo_loja'] > 0:
        max_seg   = 1800  # referência: 30 minutos
        pct       = min(kpi['tempo_loja'] / max_seg, 1.0)
        angle_rad = math.radians(180 - pct * 180)
        kpi_tempo_gauge = {
            'x': round(50 + 36 * math.cos(angle_rad), 1),
            'y': round(58 - 36 * math.sin(angle_rad), 1),
        }

    kpi_tempo_gauge_sem = None
    if kpi_sem['tempo_loja'] is not None and kpi_sem['tempo_loja'] > 0:
        max_seg   = 1800
        pct       = min(kpi_sem['tempo_loja'] / max_seg, 1.0)
        angle_rad = math.radians(180 - pct * 180)
        kpi_tempo_gauge_sem = {
            'x': round(50 + 36 * math.cos(angle_rad), 1),
            'y': round(58 - 36 * math.sin(angle_rad), 1),
        }

    kpi_tempo_gauge_mes = None
    if kpi_mes['tempo_loja'] is not None and kpi_mes['tempo_loja'] > 0:
        max_seg   = 1800
        pct       = min(kpi_mes['tempo_loja'] / max_seg, 1.0)
        angle_rad = math.radians(180 - pct * 180)
        kpi_tempo_gauge_mes = {
            'x': round(50 + 36 * math.cos(angle_rad), 1),
            'y': round(58 - 36 * math.sin(angle_rad), 1),
        }

    kpi_tempo_gauge_ytd = None
    if kpi_ytd['tempo_loja'] is not None and kpi_ytd['tempo_loja'] > 0:
        max_seg   = 1800
        pct       = min(kpi_ytd['tempo_loja'] / max_seg, 1.0)
        angle_rad = math.radians(180 - pct * 180)
        kpi_tempo_gauge_ytd = {
            'x': round(50 + 36 * math.cos(angle_rad), 1),
            'y': round(58 - 36 * math.sin(angle_rad), 1),
        }

    # ── Gráfico faixa horária – Operacional ──────────────────────────────────
    chart_faixa_dia = {'clientes': [0]*24, 'vendas': [0]*24, 'faturamento': [0.0]*24}
    chart_faixa_sem = {'clientes': [0]*24, 'vendas': [0]*24, 'faturamento': [0.0]*24}
    chart_faixa_mes = {'clientes': [0]*24, 'vendas': [0]*24, 'faturamento': [0.0]*24}
    chart_faixa_ytd = {'clientes': [0]*24, 'vendas': [0]*24, 'faturamento': [0.0]*24}

    if active_store:
        sid = active_store['store_id']

        rows = db.query_all("""
            SELECT EXTRACT(HOUR FROM min_time)::int AS hora, COUNT(*) AS clientes
            FROM (
                SELECT dr.person_id, MIN(dr.created_at) AS min_time
                FROM   faciais.detection_records dr
                JOIN   faciais.people  p   ON p.person_id  = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL AND DATE(dr.created_at) = %s
                GROUP  BY dr.person_id
            ) sub GROUP BY hora ORDER BY hora
        """, (sid, data_str))
        for row in rows:
            chart_faixa_dia['clientes'][int(row['hora'])] = int(row['clientes'] or 0)

        if active_microvix_portal and active_store_cnpj:
            rows = db.query_all("""
                SELECT SPLIT_PART(hora_lancamento, ':', 1)::int AS hora,
                       COUNT(DISTINCT documento)  AS vendas,
                       SUM(valor_liquido)         AS faturamento
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s AND DATE(data_documento) = %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
                  AND  hora_lancamento IS NOT NULL AND hora_lancamento <> ''
                GROUP  BY hora ORDER BY hora
            """, (active_microvix_portal, active_store_cnpj, data_str))
            for row in rows:
                chart_faixa_dia['vendas'][int(row['hora'])]       = int(row['vendas'] or 0)
                chart_faixa_dia['faturamento'][int(row['hora'])]  = float(row['faturamento'] or 0)

        rows = db.query_all("""
            SELECT EXTRACT(HOUR FROM min_time)::int AS hora, COUNT(*) AS clientes
            FROM (
                SELECT dr.person_id, DATE(dr.created_at) AS dia, MIN(dr.created_at) AS min_time
                FROM   faciais.detection_records dr
                JOIN   faciais.people  p   ON p.person_id  = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, DATE(dr.created_at)
            ) sub GROUP BY hora ORDER BY hora
        """, (sid, semana_inicio_str, semana_fim_str))
        for row in rows:
            chart_faixa_sem['clientes'][int(row['hora'])] = int(row['clientes'] or 0)

        if active_microvix_portal and active_store_cnpj:
            rows = db.query_all("""
                SELECT SPLIT_PART(hora_lancamento, ':', 1)::int AS hora,
                       COUNT(DISTINCT documento)  AS vendas,
                       SUM(valor_liquido)         AS faturamento
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s
                  AND  DATE(data_documento) BETWEEN %s AND %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
                  AND  hora_lancamento IS NOT NULL AND hora_lancamento <> ''
                GROUP  BY hora ORDER BY hora
            """, (active_microvix_portal, active_store_cnpj, semana_inicio_str, semana_fim_str))
            for row in rows:
                chart_faixa_sem['vendas'][int(row['hora'])]      = int(row['vendas'] or 0)
                chart_faixa_sem['faturamento'][int(row['hora'])] = float(row['faturamento'] or 0)

        rows = db.query_all("""
            SELECT EXTRACT(HOUR FROM min_time)::int AS hora, COUNT(*) AS clientes
            FROM (
                SELECT dr.person_id, DATE(dr.created_at) AS dia, MIN(dr.created_at) AS min_time
                FROM   faciais.detection_records dr
                JOIN   faciais.people  p   ON p.person_id  = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, DATE(dr.created_at)
            ) sub GROUP BY hora ORDER BY hora
        """, (sid, mes_inicio_str, mes_fim_str))
        for row in rows:
            chart_faixa_mes['clientes'][int(row['hora'])] = int(row['clientes'] or 0)

        if active_microvix_portal and active_store_cnpj:
            rows = db.query_all("""
                SELECT SPLIT_PART(hora_lancamento, ':', 1)::int AS hora,
                       COUNT(DISTINCT documento)  AS vendas,
                       SUM(valor_liquido)         AS faturamento
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s
                  AND  DATE(data_documento) BETWEEN %s AND %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
                  AND  hora_lancamento IS NOT NULL AND hora_lancamento <> ''
                GROUP  BY hora ORDER BY hora
            """, (active_microvix_portal, active_store_cnpj, mes_inicio_str, mes_fim_str))
            for row in rows:
                chart_faixa_mes['vendas'][int(row['hora'])]      = int(row['vendas'] or 0)
                chart_faixa_mes['faturamento'][int(row['hora'])] = float(row['faturamento'] or 0)

        # ── Gráfico gênero por faixa horária ─────────────────────────────────
        chart_genero_dia = {'F': [0]*24, 'M': [0]*24}
        chart_genero_sem = {'F': [0]*24, 'M': [0]*24}
        chart_genero_mes = {'F': [0]*24, 'M': [0]*24}

        _GENERO_DIA_QUERY = """
            SELECT EXTRACT(HOUR FROM min_time)::int AS hora,
                   gender_id, COUNT(*) AS total
            FROM (
                SELECT dr.person_id, p.gender_id, MIN(dr.created_at) AS min_time
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL AND DATE(dr.created_at) = %s
                GROUP  BY dr.person_id, p.gender_id
            ) sub
            GROUP BY hora, gender_id ORDER BY hora
        """
        for row in db.query_all(_GENERO_DIA_QUERY, (sid, data_str)):
            g = row['gender_id']
            if g in chart_genero_dia:
                chart_genero_dia[g][int(row['hora'])] = int(row['total'] or 0)

        # ── Gráfico ocorrências por hora (Novos vs Recorrentes) – Dia ─────────
        chart_ocorrencias_dia = {'novos': [0]*24, 'recorrentes': [0]*24}
        for row in db.query_all("""
            SELECT hora,
                   SUM(CASE WHEN is_rec THEN 1 ELSE 0 END) AS recorrentes,
                   SUM(CASE WHEN NOT is_rec THEN 1 ELSE 0 END) AS novos
            FROM (
                SELECT EXTRACT(HOUR FROM MIN(dr.created_at))::int AS hora,
                       EXISTS (
                           SELECT 1 FROM faciais.detection_records dr2
                           WHERE  dr2.person_id = dr.person_id
                             AND  dr2.store_id  = %s
                             AND  DATE(dr2.created_at) < %s
                       ) AS is_rec
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL AND DATE(dr.created_at) = %s
                GROUP  BY dr.person_id
            ) sub
            GROUP BY hora ORDER BY hora
        """, (sid, data_str, sid, data_str)):
            h = int(row['hora'])
            chart_ocorrencias_dia['recorrentes'][h] = int(row['recorrentes'] or 0)
            chart_ocorrencias_dia['novos'][h]        = int(row['novos'] or 0)

        chart_ocorrencias_sem = {'novos': [0]*24, 'recorrentes': [0]*24}
        for row in db.query_all("""
            SELECT hora,
                   SUM(CASE WHEN is_rec THEN 1 ELSE 0 END) AS recorrentes,
                   SUM(CASE WHEN NOT is_rec THEN 1 ELSE 0 END) AS novos
            FROM (
                SELECT EXTRACT(HOUR FROM MIN(dr.created_at))::int AS hora,
                       EXISTS (
                           SELECT 1 FROM faciais.detection_records dr2
                           WHERE  dr2.person_id = dr.person_id
                             AND  dr2.store_id  = %s
                             AND  DATE(dr2.created_at) < %s
                       ) AS is_rec
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id
            ) sub
            GROUP BY hora ORDER BY hora
        """, (sid, semana_inicio_str, sid, semana_inicio_str, semana_fim_str)):
            h = int(row['hora'])
            chart_ocorrencias_sem['recorrentes'][h] = int(row['recorrentes'] or 0)
            chart_ocorrencias_sem['novos'][h]        = int(row['novos'] or 0)

        chart_ocorrencias_mes = {'novos': [0]*24, 'recorrentes': [0]*24}
        for row in db.query_all("""
            SELECT hora,
                   SUM(CASE WHEN is_rec THEN 1 ELSE 0 END) AS recorrentes,
                   SUM(CASE WHEN NOT is_rec THEN 1 ELSE 0 END) AS novos
            FROM (
                SELECT EXTRACT(HOUR FROM MIN(dr.created_at))::int AS hora,
                       EXISTS (
                           SELECT 1 FROM faciais.detection_records dr2
                           WHERE  dr2.person_id = dr.person_id
                             AND  dr2.store_id  = %s
                             AND  DATE(dr2.created_at) < %s
                       ) AS is_rec
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id
            ) sub
            GROUP BY hora ORDER BY hora
        """, (sid, mes_inicio_str, sid, mes_inicio_str, mes_fim_str)):
            h = int(row['hora'])
            chart_ocorrencias_mes['recorrentes'][h] = int(row['recorrentes'] or 0)
            chart_ocorrencias_mes['novos'][h]        = int(row['novos'] or 0)

        _GENERO_RANGE_QUERY = """
            SELECT EXTRACT(HOUR FROM min_time)::int AS hora,
                   gender_id, COUNT(*) AS total
            FROM (
                SELECT dr.person_id, p.gender_id,
                       DATE(dr.created_at) AS dia, MIN(dr.created_at) AS min_time
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, p.gender_id, DATE(dr.created_at)
            ) sub
            GROUP BY hora, gender_id ORDER BY hora
        """
        for row in db.query_all(_GENERO_RANGE_QUERY, (sid, semana_inicio_str, semana_fim_str)):
            g = row['gender_id']
            if g in chart_genero_sem:
                chart_genero_sem[g][int(row['hora'])] = int(row['total'] or 0)

        for row in db.query_all(_GENERO_RANGE_QUERY, (sid, mes_inicio_str, mes_fim_str)):
            g = row['gender_id']
            if g in chart_genero_mes:
                chart_genero_mes[g][int(row['hora'])] = int(row['total'] or 0)

        # ── Top produtos ─────────────────────────────────────────────────────
        top_produtos_qtde_dia = []
        top_produtos_fat_dia  = []
        top_produtos_qtde_sem = []
        top_produtos_fat_sem  = []
        top_produtos_qtde_mes = []
        top_produtos_fat_mes  = []
        top_produtos_qtde_ytd = []
        top_produtos_fat_ytd  = []
        combinacoes_dia       = []
        combinacoes_sem       = []
        combinacoes_mes       = []
        combinacoes_ytd       = []
        top5_tipo_dia = {'novos': [], 'recorrentes': []}
        top5_tipo_sem = {'novos': [], 'recorrentes': []}
        top5_tipo_mes = {'novos': [], 'recorrentes': []}
        top5_tipo_ytd = {'novos': [], 'recorrentes': []}

        _FILTRO_MV = (
            "m.portal = %s AND m.cnpj_emp = %s "
            "AND m.cancelado <> 'S' AND m.excluido <> 'S' AND m.soma_relatorio = 'S' "
            "AND m.tipo_transacao = 'V' AND m.cod_natureza_operacao = '10030'"
        )
        _JOIN_PROD = (
            "JOIN microvix.microvix_produtos p "
            "ON p.portal = m.portal AND p.cod_produto = m.cod_produto"
        )
        _NOME_PROD = "COALESCE(NULLIF(TRIM(p.descricao_basica),''), p.nome)"

        if active_microvix_portal and active_store_cnpj:
            def _top_query(date_filter, order_expr, params):
                sql = f"""
                    SELECT {_NOME_PROD} AS produto, {order_expr} AS total
                    FROM   microvix.microvix_movimento m
                    {_JOIN_PROD}
                    WHERE  {_FILTRO_MV} AND {date_filter}
                    GROUP  BY produto ORDER BY total DESC LIMIT 5
                """
                return [{'nome': r['produto'], 'total': round(float(r['total'] or 0), 2)}
                        for r in db.query_all(sql, params)]

            _p = (active_microvix_portal, active_store_cnpj)
            _date_dia  = "DATE(m.data_documento) = %s"
            _date_sem  = "DATE(m.data_documento) BETWEEN %s AND %s"

            top_produtos_qtde_dia = _top_query(_date_dia,  "SUM(m.quantidade)",   _p + (data_str,))
            top_produtos_fat_dia  = _top_query(_date_dia,  "SUM(m.valor_liquido)", _p + (data_str,))
            top_produtos_qtde_sem = _top_query(_date_sem,  "SUM(m.quantidade)",   _p + (semana_inicio_str, semana_fim_str))
            top_produtos_fat_sem  = _top_query(_date_sem,  "SUM(m.valor_liquido)", _p + (semana_inicio_str, semana_fim_str))
            top_produtos_qtde_mes = _top_query(_date_sem,  "SUM(m.quantidade)",   _p + (mes_inicio_str, mes_fim_str))
            top_produtos_fat_mes  = _top_query(_date_sem,  "SUM(m.valor_liquido)", _p + (mes_inicio_str, mes_fim_str))

            def _comb_query(date_filter, params):
                sql = f"""
                    SELECT
                        COALESCE(NULLIF(TRIM(pa.descricao_basica),''), pa.nome) AS nome_a,
                        COALESCE(NULLIF(TRIM(pb.descricao_basica),''), pb.nome) AS nome_b,
                        COUNT(*) AS qtd
                    FROM microvix.microvix_movimento a
                    JOIN microvix.microvix_movimento b
                        ON  a.portal    = b.portal
                        AND a.cnpj_emp  = b.cnpj_emp
                        AND a.documento = b.documento
                        AND a.cod_produto < b.cod_produto
                    JOIN microvix.microvix_produtos pa
                        ON pa.portal = a.portal AND pa.cod_produto = a.cod_produto
                    JOIN microvix.microvix_produtos pb
                        ON pb.portal = b.portal AND pb.cod_produto = b.cod_produto
                    WHERE a.portal = %s AND a.cnpj_emp = %s
                      AND a.cancelado <> 'S' AND a.excluido <> 'S' AND a.soma_relatorio = 'S'
                      AND a.tipo_transacao = 'V' AND a.cod_natureza_operacao = '10030'
                      AND b.cancelado <> 'S' AND b.excluido <> 'S' AND b.soma_relatorio = 'S'
                      AND b.tipo_transacao = 'V' AND b.cod_natureza_operacao = '10030'
                      AND {date_filter}
                    GROUP BY nome_a, nome_b
                    ORDER BY qtd DESC LIMIT 10
                """
                return [{'nome_a': r['nome_a'], 'nome_b': r['nome_b'], 'qtd': int(r['qtd'])}
                        for r in db.query_all(sql, params)]

            combinacoes_dia = _comb_query("DATE(a.data_documento) = %s",              _p + (data_str,))
            combinacoes_sem = _comb_query("DATE(a.data_documento) BETWEEN %s AND %s", _p + (semana_inicio_str, semana_fim_str))
            combinacoes_mes = _comb_query("DATE(a.data_documento) BETWEEN %s AND %s", _p + (mes_inicio_str, mes_fim_str))
            top_produtos_qtde_ytd = _top_query(_date_sem, "SUM(m.quantidade)",    _p + (ytd_inicio_str, ytd_fim_str))
            top_produtos_fat_ytd  = _top_query(_date_sem, "SUM(m.valor_liquido)", _p + (ytd_inicio_str, ytd_fim_str))
            combinacoes_ytd = _comb_query("DATE(a.data_documento) BETWEEN %s AND %s", _p + (ytd_inicio_str, ytd_fim_str))
            _sid = active_store['store_id']
            top5_tipo_dia = _top5_por_tipo(_sid, active_microvix_portal, active_store_cnpj, data_str, data_str, data_str)
            top5_tipo_sem = _top5_por_tipo(_sid, active_microvix_portal, active_store_cnpj, semana_inicio_str, semana_fim_str, semana_inicio_str)
            top5_tipo_mes = _top5_por_tipo(_sid, active_microvix_portal, active_store_cnpj, mes_inicio_str, mes_fim_str, mes_inicio_str)
            top5_tipo_ytd = _top5_por_tipo(_sid, active_microvix_portal, active_store_cnpj, ytd_inicio_str, ytd_fim_str, ytd_inicio_str)

        # ── Frequência de retorno por horário/dia ────────────────────────────
        chart_freq_retorno_dia = [None]*24
        chart_freq_retorno_sem = []
        chart_freq_retorno_mes = []
        chart_freq_retorno_ytd = []

        _FREQ_DIA_SQL = """
            WITH fv AS (
                SELECT dr.person_id,
                       EXTRACT(HOUR FROM MIN(dr.created_at))::int AS hora,
                       DATE(MIN(dr.created_at)) AS today
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL AND DATE(dr.created_at) = %s
                GROUP  BY dr.person_id
            ),
            pv AS (
                SELECT fv.hora,
                       (fv.today - MAX(DATE(dr2.created_at)))::int AS gap_days
                FROM   fv
                JOIN   faciais.detection_records dr2 ON dr2.person_id = fv.person_id
                WHERE  dr2.store_id = %s AND DATE(dr2.created_at) < fv.today
                GROUP  BY fv.person_id, fv.hora, fv.today
            )
            SELECT hora, ROUND(AVG(gap_days)::numeric, 1) AS avg_days
            FROM   pv GROUP BY hora ORDER BY hora
        """
        for row in db.query_all(_FREQ_DIA_SQL, (sid, data_str, sid)):
            chart_freq_retorno_dia[int(row['hora'])] = float(row['avg_days'])

        _FREQ_RANGE_SQL = """
            WITH fv AS (
                SELECT dr.person_id,
                       DATE(MIN(dr.created_at)) AS visit_day
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, DATE(dr.created_at)
            ),
            pv AS (
                SELECT fv.visit_day,
                       (fv.visit_day - MAX(DATE(dr2.created_at)))::int AS gap_days
                FROM   fv
                JOIN   faciais.detection_records dr2 ON dr2.person_id = fv.person_id
                WHERE  dr2.store_id = %s AND DATE(dr2.created_at) < fv.visit_day
                GROUP  BY fv.person_id, fv.visit_day
            )
            SELECT visit_day, ROUND(AVG(gap_days)::numeric, 1) AS avg_days
            FROM   pv GROUP BY visit_day ORDER BY visit_day
        """
        _DIAS_PT = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
        chart_freq_retorno_sem = [
            {'label': _DIAS_PT[row['visit_day'].weekday()], 'avg': float(row['avg_days'])}
            for row in db.query_all(_FREQ_RANGE_SQL, (sid, semana_inicio_str, semana_fim_str, sid))
        ]
        chart_freq_retorno_mes = [
            {'label': row['visit_day'].strftime('%d/%m'), 'avg': float(row['avg_days'])}
            for row in db.query_all(_FREQ_RANGE_SQL, (sid, mes_inicio_str, mes_fim_str, sid))
        ]
        chart_freq_retorno_ytd = [
            {'label': row['visit_day'].strftime('%d/%m'), 'avg': float(row['avg_days'])}
            for row in db.query_all(_FREQ_RANGE_SQL, (sid, ytd_inicio_str, ytd_fim_str, sid))
        ]

        # ── Charts YTD – faixa horária ────────────────────────────────────────
        rows = db.query_all("""
            SELECT EXTRACT(HOUR FROM min_time)::int AS hora, COUNT(*) AS clientes
            FROM (
                SELECT dr.person_id, MIN(dr.created_at) AS min_time
                FROM   faciais.detection_records dr
                JOIN   faciais.people  p   ON p.person_id  = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, DATE(dr.created_at)
            ) sub GROUP BY hora ORDER BY hora
        """, (sid, ytd_inicio_str, ytd_fim_str))
        for row in rows:
            chart_faixa_ytd['clientes'][int(row['hora'])] = int(row['clientes'] or 0)

        if active_microvix_portal and active_store_cnpj:
            rows = db.query_all("""
                SELECT SPLIT_PART(hora_lancamento, ':', 1)::int AS hora,
                       COUNT(DISTINCT documento)  AS vendas,
                       SUM(valor_liquido)         AS faturamento
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s
                  AND  DATE(data_documento) BETWEEN %s AND %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
                  AND  hora_lancamento IS NOT NULL AND hora_lancamento <> ''
                GROUP  BY hora ORDER BY hora
            """, (active_microvix_portal, active_store_cnpj, ytd_inicio_str, ytd_fim_str))
            for row in rows:
                chart_faixa_ytd['vendas'][int(row['hora'])]      = int(row['vendas'] or 0)
                chart_faixa_ytd['faturamento'][int(row['hora'])] = float(row['faturamento'] or 0)

        chart_genero_ytd = {'F': [0]*24, 'M': [0]*24}
        for row in db.query_all(_GENERO_RANGE_QUERY, (sid, ytd_inicio_str, ytd_fim_str)):
            g = row['gender_id']
            if g in chart_genero_ytd:
                chart_genero_ytd[g][int(row['hora'])] = int(row['total'] or 0)

        chart_ocorrencias_ytd = {'novos': [0]*24, 'recorrentes': [0]*24}
        for row in db.query_all("""
            SELECT hora,
                   SUM(CASE WHEN is_rec THEN 1 ELSE 0 END) AS recorrentes,
                   SUM(CASE WHEN NOT is_rec THEN 1 ELSE 0 END) AS novos
            FROM (
                SELECT EXTRACT(HOUR FROM MIN(dr.created_at))::int AS hora,
                       dr.person_id,
                       EXISTS (
                           SELECT 1 FROM faciais.detection_records dr2
                           WHERE  dr2.person_id = dr.person_id AND dr2.store_id = %s
                             AND  DATE(dr2.created_at) < %s
                       ) AS is_rec
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id
            ) sub
            GROUP BY hora ORDER BY hora
        """, (sid, ytd_inicio_str, sid, ytd_inicio_str, ytd_fim_str)):
            h = int(row['hora'])
            chart_ocorrencias_ytd['recorrentes'][h] = int(row['recorrentes'] or 0)
            chart_ocorrencias_ytd['novos'][h]        = int(row['novos'] or 0)

    else:
        chart_genero_dia = {'F': [0]*24, 'M': [0]*24}
        chart_genero_sem = {'F': [0]*24, 'M': [0]*24}
        chart_genero_mes = {'F': [0]*24, 'M': [0]*24}
        chart_ocorrencias_dia = {'novos': [0]*24, 'recorrentes': [0]*24}
        chart_ocorrencias_sem = {'novos': [0]*24, 'recorrentes': [0]*24}
        chart_ocorrencias_mes = {'novos': [0]*24, 'recorrentes': [0]*24}
        top_produtos_qtde_dia = []
        top_produtos_fat_dia  = []
        top_produtos_qtde_sem = []
        top_produtos_fat_sem  = []
        top_produtos_qtde_mes = []
        top_produtos_fat_mes  = []
        top_produtos_qtde_ytd = []
        top_produtos_fat_ytd  = []
        combinacoes_ytd       = []
        top5_tipo_dia = {'novos': [], 'recorrentes': []}
        top5_tipo_sem = {'novos': [], 'recorrentes': []}
        top5_tipo_mes = {'novos': [], 'recorrentes': []}
        top5_tipo_ytd = {'novos': [], 'recorrentes': []}
        chart_genero_ytd      = {'F': [0]*24, 'M': [0]*24}
        chart_ocorrencias_ytd = {'novos': [0]*24, 'recorrentes': [0]*24}
        chart_freq_retorno_dia = [None]*24
        chart_freq_retorno_sem = []
        chart_freq_retorno_mes = []
        chart_freq_retorno_ytd = []

    # ── Tema da empresa ──────────────────────────────────────────────────────
    theme = dict(primary_color='#F47B20', text_color='#111827', graph_color_1='#1339F6')
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
            "SELECT primary_color, text_color, graph_color_1 FROM faciais.company_themes WHERE company_id = %s",
            (theme_company_id,)
        )
        if row:
            theme['primary_color'] = row['primary_color']
            if row['text_color']:
                theme['text_color'] = row['text_color']
            if row['graph_color_1']:
                theme['graph_color_1'] = row['graph_color_1']

    # ── Metas ────────────────────────────────────────────────────────────────
    metas = _get_metas(
        theme_company_id,
        selected_date, semana_inicio, semana_fim,
        mes_inicio, mes_fim, ytd_inicio, ytd_fim,
    ) if theme_company_id else None

    return render_template(
        'dashboard.html',
        company_logo=company_logo,
        company_name=company_name,
        companies=companies,
        stores=stores,
        selected_company_id=selected_company_id,
        selected_store_id=selected_store_id,
        active_store=active_store,
        data_str=data_str,
        kpi=kpi,
        kpi_com=kpi_com,
        kpi_sem=kpi_sem,
        kpi_mes=kpi_mes,
        kpi_com_sem=kpi_com_sem,
        kpi_com_mes=kpi_com_mes,
        semana_label=semana_label,
        mes_label=mes_label,
        semana_anterior_str=semana_anterior_str,
        semana_proxima_str=semana_proxima_str,
        mes_anterior_str=mes_anterior_str,
        mes_proximo_str=mes_proximo_str,
        theme=theme,
        chart_faixa_dia=chart_faixa_dia,
        chart_faixa_sem=chart_faixa_sem,
        chart_faixa_mes=chart_faixa_mes,
        chart_genero_dia=chart_genero_dia,
        chart_ocorrencias_dia=chart_ocorrencias_dia,
        chart_genero_sem=chart_genero_sem,
        chart_genero_mes=chart_genero_mes,
        kpi_est=kpi_est,
        kpi_est_sem=kpi_est_sem,
        kpi_est_mes=kpi_est_mes,
        top_produtos_qtde_dia=top_produtos_qtde_dia,
        top_produtos_fat_dia=top_produtos_fat_dia,
        top_produtos_qtde_sem=top_produtos_qtde_sem,
        top_produtos_fat_sem=top_produtos_fat_sem,
        top_produtos_qtde_mes=top_produtos_qtde_mes,
        top_produtos_fat_mes=top_produtos_fat_mes,
        combinacoes_dia=combinacoes_dia,
        combinacoes_sem=combinacoes_sem,
        combinacoes_mes=combinacoes_mes,
        chart_freq_retorno_dia=chart_freq_retorno_dia,
        chart_freq_retorno_sem=chart_freq_retorno_sem,
        chart_freq_retorno_mes=chart_freq_retorno_mes,
        kpi_ant=kpi_ant,
        kpi_ant_com=kpi_ant_com,
        kpi_ant_sem=kpi_ant_sem,
        kpi_ant_mes=kpi_ant_mes,
        kpi_ant_com_sem=kpi_ant_com_sem,
        kpi_ant_com_mes=kpi_ant_com_mes,
        kpi_tempo_gauge=kpi_tempo_gauge,
        kpi_tempo_gauge_sem=kpi_tempo_gauge_sem,
        kpi_tempo_gauge_mes=kpi_tempo_gauge_mes,
        kpi_tempo_gauge_ytd=kpi_tempo_gauge_ytd,
        chart_ocorrencias_sem=chart_ocorrencias_sem,
        chart_ocorrencias_mes=chart_ocorrencias_mes,
        kpi_ytd=kpi_ytd,
        kpi_com_ytd=kpi_com_ytd,
        kpi_est_ytd=kpi_est_ytd,
        kpi_ant_ytd=kpi_ant_ytd,
        kpi_ant_com_ytd=kpi_ant_com_ytd,
        ytd_label=ytd_label,
        chart_faixa_ytd=chart_faixa_ytd,
        chart_genero_ytd=chart_genero_ytd,
        chart_ocorrencias_ytd=chart_ocorrencias_ytd,
        top_produtos_qtde_ytd=top_produtos_qtde_ytd,
        top_produtos_fat_ytd=top_produtos_fat_ytd,
        combinacoes_ytd=combinacoes_ytd,
        chart_freq_retorno_ytd=chart_freq_retorno_ytd,
        top5_tipo_dia=top5_tipo_dia,
        top5_tipo_sem=top5_tipo_sem,
        top5_tipo_mes=top5_tipo_mes,
        top5_tipo_ytd=top5_tipo_ytd,
        metas=metas,
    )


# ── Visitação ─────────────────────────────────────────────────────────────────

_HEIMDALL_IMAGE_BASE = 'http://187.17.228.160:6500/api/facial/images'


def _fmt_permanencia(segundos):
    if segundos is None or segundos <= 0:
        return None
    m = int(segundos) // 60
    if m < 1:
        return '< 1 min'
    if m < 60:
        return f'{m} min'
    h = m // 60
    return f'{h}h {m % 60:02d}min'


@auth_bp.route('/visitacao')
@login_required
@screen_required('dashboard')
def visitacao():
    user_id   = session['user_id']
    user_type = session['user_type_id']
    company_logo        = None
    company_name        = None
    companies           = []
    selected_company_id = None
    stores              = []
    selected_store_id   = request.args.get('store_id', type=int)

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
                    return redirect(url_for('auth.visitacao',
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
                    return redirect(url_for('auth.visitacao', store_id=last_sid))
            elif user_type == 'emp':
                row = db.query_one(
                    "SELECT store_id FROM faciais.user_stores "
                    "WHERE store_id = %s AND user_id = %s",
                    (last_sid, user_id)
                )
                if row:
                    return redirect(url_for('auth.visitacao', store_id=last_sid))

    # ── Carrega empresas e lojas ──────────────────────────────────────────────
    if user_type == 'adm':
        companies = db.query_all("""
            SELECT c.company_id, c.company_name, ct.logo_url
            FROM   faciais.companies c
            JOIN   faciais.company_themes ct ON ct.company_id = c.company_id
            WHERE  ct.logo_url IS NOT NULL
            ORDER  BY c.company_name
        """)
        selected_company_id = request.args.get('company_id', type=int)
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
        selected_company_id = request.args.get('company_id', type=int)
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

    # ── Data selecionada (padrão: hoje) ───────────────────────────────────────
    data_str = request.args.get('date', date_type.today().strftime('%Y-%m-%d'))
    try:
        date_type.fromisoformat(data_str)
    except ValueError:
        data_str = date_type.today().strftime('%Y-%m-%d')

    # ── Clientes do dia ───────────────────────────────────────────────────────
    clientes = []
    if active_store:
        sid  = active_store['store_id']
        rows = db.query_all("""
            WITH day_det AS (
                SELECT
                    dr.person_id,
                    MIN(dr.created_at)                                               AS primeiro_registro,
                    EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS permanencia_seg
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                WHERE  dr.store_id        = %s
                  AND  DATE(dr.created_at) = %s
                  AND  dr.person_id IS NOT NULL
                  AND  p.person_type_id   = 'C'
                GROUP  BY dr.person_id
            ),
            last_img AS (
                SELECT DISTINCT ON (dr.person_id)
                    dr.person_id,
                    dr.image_path
                FROM   faciais.detection_records dr
                WHERE  dr.store_id        = %s
                  AND  DATE(dr.created_at) = %s
                  AND  dr.person_id IS NOT NULL
                  AND  dr.image_path IS NOT NULL
                ORDER  BY dr.person_id, dr.created_at DESC
            ),
            recorrentes AS (
                SELECT DISTINCT dr.person_id
                FROM   faciais.detection_records dr
                WHERE  dr.store_id = %s
                  AND  DATE(dr.created_at) < %s
                  AND  dr.person_id IS NOT NULL
            )
            SELECT
                dd.person_id,
                dd.primeiro_registro,
                dd.permanencia_seg,
                li.image_path,
                p.full_name,
                p.nickname,
                p.age,
                g.gender_name,
                p.notes,
                (r.person_id IS NOT NULL) AS is_recorrente
            FROM   day_det  dd
            JOIN   faciais.people  p ON p.person_id  = dd.person_id
            LEFT   JOIN faciais.genders g  ON g.gender_id  = p.gender_id
            LEFT   JOIN last_img    li ON li.person_id = dd.person_id
            LEFT   JOIN recorrentes r  ON r.person_id  = dd.person_id
            ORDER  BY dd.primeiro_registro DESC
        """, (sid, data_str, sid, data_str, sid, data_str))

        for r in rows:
            clientes.append({
                'person_id':         r['person_id'],
                'full_name':         r['full_name'],
                'nickname':          r['nickname'],
                'age':               r['age'],
                'gender_name':       r['gender_name'],
                'notes':             r['notes'],
                'is_recorrente':     r['is_recorrente'],
                'primeiro_registro': r['primeiro_registro'].strftime('%H:%M') if r['primeiro_registro'] else None,
                'permanencia':       _fmt_permanencia(r['permanencia_seg']),
                'img_url':           (_HEIMDALL_IMAGE_BASE + r['image_path']) if r['image_path'] else None,
            })

    # ── Tema da empresa ───────────────────────────────────────────────────────
    theme = dict(primary_color='#F47B20')
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
            "SELECT primary_color FROM faciais.company_themes WHERE company_id = %s",
            (theme_company_id,)
        )
        if row:
            theme['primary_color'] = row['primary_color']

    return render_template(
        'visitacao.html',
        company_logo=company_logo,
        company_name=company_name,
        companies=companies,
        stores=stores,
        selected_company_id=selected_company_id,
        selected_store_id=selected_store_id,
        active_store=active_store,
        data_str=data_str,
        theme=theme,
        clientes=clientes,
    )
