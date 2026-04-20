import calendar
from datetime import date as date_type, timedelta
from functools import wraps
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, send_from_directory, make_response)
from werkzeug.security import check_password_hash, generate_password_hash
import os
import db

mobile_bp = Blueprint('mobile', __name__)

# ── Auth helpers ─────────────────────────────────────────────────────────────

def _login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('mobile.login'))
        return f(*args, **kwargs)
    return decorated


# ── Service Worker (precisa de header especial) ──────────────────────────────

@mobile_bp.route('/sw.js')
def sw():
    static_dir = os.path.join(mobile_bp.root_path, '..', 'static')
    resp = make_response(send_from_directory(static_dir, 'sw.js'))
    resp.headers['Service-Worker-Allowed'] = '/retail_analytics/m/'
    resp.headers['Content-Type'] = 'application/javascript'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


# ── Index ────────────────────────────────────────────────────────────────────

@mobile_bp.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('mobile.dashboard'))
    return redirect(url_for('mobile.login'))


# ── Login / Logout ───────────────────────────────────────────────────────────

@mobile_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('mobile.dashboard'))

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
            session['username']     = username
            session['user_type_id'] = user['user_type_id']
            return redirect(url_for('mobile.dashboard'))

        error = 'Usuário ou senha incorretos.'

    return render_template('mobile/login.html', error=error)


@mobile_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('mobile.login'))


# ── Dashboard ────────────────────────────────────────────────────────────────

@mobile_bp.route('/dashboard')
@_login_required
def dashboard():
    user_id   = session['user_id']
    user_type = session['user_type_id']
    company_logo         = None
    company_name         = None
    companies            = []
    selected_company_id  = request.args.get('company_id', type=int)
    selected_store_id    = request.args.get('store_id',   type=int)
    stores               = []

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
                    return redirect(url_for('mobile.dashboard',
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
                    return redirect(url_for('mobile.dashboard', store_id=last_sid))
            elif user_type == 'emp':
                row = db.query_one(
                    "SELECT store_id FROM faciais.user_stores "
                    "WHERE store_id = %s AND user_id = %s",
                    (last_sid, user_id)
                )
                if row:
                    return redirect(url_for('mobile.dashboard', store_id=last_sid))

    # ── Carrega empresas e lojas por tipo de usuário ─────────────────────────
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
            JOIN   faciais.companies c       ON c.company_group_id = ucg.company_group_id
            LEFT JOIN faciais.company_themes ct ON ct.company_id = c.company_id
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

    # ── Resolve loja ativa ───────────────────────────────────────────────────
    active_store = None
    if stores:
        if selected_store_id:
            active_store = next((s for s in stores if s['store_id'] == selected_store_id), None)
        if active_store is None and len(stores) == 1:
            active_store      = stores[0]
            selected_store_id = active_store['store_id']

    # ── Salvar última seleção no banco ──────────────────────────────────────
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

    # ── CNPJ e portal Microvix ───────────────────────────────────────────────
    active_store_cnpj      = None
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

    # ── Data selecionada ─────────────────────────────────────────────────────
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

    _MESES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
              'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
    semana_label = f"{semana_inicio.strftime('%d/%m')} – {semana_fim.strftime('%d/%m/%Y')}"
    mes_label    = f"{_MESES[selected_date.month - 1]} {selected_date.year}"

    # ── KPIs Operacional – Dia ───────────────────────────────────────────────
    kpi = dict(visitantes=None, recorrentes=None, vendas=None, conversao=None)

    # ── KPIs Comercial – Dia ─────────────────────────────────────────────────
    kpi_com = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)

    # ── KPIs Operacional – Semana / Mês ──────────────────────────────────────
    kpi_sem     = dict(visitantes=None, recorrentes=None, vendas=None, conversao=None)
    kpi_mes     = dict(visitantes=None, recorrentes=None, vendas=None, conversao=None)

    # ── KPIs Comercial – Semana / Mês ────────────────────────────────────────
    kpi_com_sem = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)
    kpi_com_mes = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)

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
            kpi['conversao'] = round((kpi['vendas'] or 0) / kpi['visitantes'] * 100, 1)
        else:
            kpi['conversao'] = 0.0

        # ── Comercial – Dia ──────────────────────────────────────────────────
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
                kpi_com['vendas']       = v
                kpi_com['faturamento']  = round(f, 2)
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
            kpi_sem['conversao'] = round((kpi_sem['vendas'] or 0) / kpi_sem['visitantes'] * 100, 1)
        else:
            kpi_sem['conversao'] = 0.0

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
            kpi_mes['conversao'] = round((kpi_mes['vendas'] or 0) / kpi_mes['visitantes'] * 100, 1)
        else:
            kpi_mes['conversao'] = 0.0

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

    # ── KPIs Estratégico – derivados dos KPIs já calculados ──────────────────
    kpi_est     = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None)
    kpi_est_sem = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None)
    kpi_est_mes = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None)

    if kpi['visitantes'] is not None and kpi['recorrentes'] is not None:
        kpi_est['novos']       = kpi['visitantes'] - kpi['recorrentes']
        kpi_est['recorrentes'] = kpi['recorrentes']
        if kpi_com['faturamento'] is not None:
            fat = kpi_com['faturamento'] or 0
            kpi_est['ticket_novo'] = round(fat / kpi_est['novos'], 2) if kpi_est['novos'] else 0.0
            kpi_est['ticket_rec']  = round(fat / kpi_est['recorrentes'], 2) if kpi_est['recorrentes'] else 0.0

    if kpi_sem['visitantes'] is not None and kpi_sem['recorrentes'] is not None:
        kpi_est_sem['novos']       = kpi_sem['visitantes'] - kpi_sem['recorrentes']
        kpi_est_sem['recorrentes'] = kpi_sem['recorrentes']
        if kpi_com_sem['faturamento'] is not None:
            fat = kpi_com_sem['faturamento'] or 0
            kpi_est_sem['ticket_novo'] = round(fat / kpi_est_sem['novos'], 2) if kpi_est_sem['novos'] else 0.0
            kpi_est_sem['ticket_rec']  = round(fat / kpi_est_sem['recorrentes'], 2) if kpi_est_sem['recorrentes'] else 0.0

    if kpi_mes['visitantes'] is not None and kpi_mes['recorrentes'] is not None:
        kpi_est_mes['novos']       = kpi_mes['visitantes'] - kpi_mes['recorrentes']
        kpi_est_mes['recorrentes'] = kpi_mes['recorrentes']
        if kpi_com_mes['faturamento'] is not None:
            fat = kpi_com_mes['faturamento'] or 0
            kpi_est_mes['ticket_novo'] = round(fat / kpi_est_mes['novos'], 2) if kpi_est_mes['novos'] else 0.0
            kpi_est_mes['ticket_rec']  = round(fat / kpi_est_mes['recorrentes'], 2) if kpi_est_mes['recorrentes'] else 0.0

    # ── Gráfico faixa horária – Operacional ──────────────────────────────────
    chart_faixa_dia = {'clientes': [0]*24, 'vendas': [0]*24}
    chart_faixa_sem = {'clientes': [0]*24, 'vendas': [0]*24}
    chart_faixa_mes = {'clientes': [0]*24, 'vendas': [0]*24}

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
                       COUNT(DISTINCT documento) AS vendas
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s AND DATE(data_documento) = %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
                  AND  hora_lancamento IS NOT NULL AND hora_lancamento <> ''
                GROUP  BY hora ORDER BY hora
            """, (active_microvix_portal, active_store_cnpj, data_str))
            for row in rows:
                chart_faixa_dia['vendas'][int(row['hora'])] = int(row['vendas'] or 0)

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
                       COUNT(DISTINCT documento) AS vendas
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s
                  AND  DATE(data_documento) BETWEEN %s AND %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
                  AND  hora_lancamento IS NOT NULL AND hora_lancamento <> ''
                GROUP  BY hora ORDER BY hora
            """, (active_microvix_portal, active_store_cnpj, semana_inicio_str, semana_fim_str))
            for row in rows:
                chart_faixa_sem['vendas'][int(row['hora'])] = int(row['vendas'] or 0)

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
                       COUNT(DISTINCT documento) AS vendas
                FROM   microvix.microvix_movimento
                WHERE  portal = %s AND cnpj_emp = %s
                  AND  DATE(data_documento) BETWEEN %s AND %s
                  AND  cancelado <> 'S' AND excluido <> 'S' AND soma_relatorio = 'S'
                  AND  tipo_transacao = 'V' AND cod_natureza_operacao = '10030'
                  AND  hora_lancamento IS NOT NULL AND hora_lancamento <> ''
                GROUP  BY hora ORDER BY hora
            """, (active_microvix_portal, active_store_cnpj, mes_inicio_str, mes_fim_str))
            for row in rows:
                chart_faixa_mes['vendas'][int(row['hora'])] = int(row['vendas'] or 0)

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
                    GROUP  BY produto ORDER BY total DESC LIMIT 10
                """
                return [{'nome': r['produto'], 'total': round(float(r['total'] or 0), 2)}
                        for r in db.query_all(sql, params)]

            _p = (active_microvix_portal, active_store_cnpj)
            _date_dia  = "DATE(m.data_documento) = %s"
            _date_sem  = "DATE(m.data_documento) BETWEEN %s AND %s"

            top_produtos_qtde_dia = _top_query(_date_dia,  "SUM(m.quantidade)",    _p + (data_str,))
            top_produtos_fat_dia  = _top_query(_date_dia,  "SUM(m.valor_liquido)", _p + (data_str,))
            top_produtos_qtde_sem = _top_query(_date_sem,  "SUM(m.quantidade)",    _p + (semana_inicio_str, semana_fim_str))
            top_produtos_fat_sem  = _top_query(_date_sem,  "SUM(m.valor_liquido)", _p + (semana_inicio_str, semana_fim_str))
            top_produtos_qtde_mes = _top_query(_date_sem,  "SUM(m.quantidade)",    _p + (mes_inicio_str, mes_fim_str))
            top_produtos_fat_mes  = _top_query(_date_sem,  "SUM(m.valor_liquido)", _p + (mes_inicio_str, mes_fim_str))

        # ── Frequência de retorno por horário/dia ────────────────────────────
        chart_freq_retorno_dia = [None]*24
        chart_freq_retorno_sem = []
        chart_freq_retorno_mes = []

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

    else:
        chart_genero_dia = {'F': [0]*24, 'M': [0]*24}
        chart_genero_sem = {'F': [0]*24, 'M': [0]*24}
        chart_genero_mes = {'F': [0]*24, 'M': [0]*24}
        top_produtos_qtde_dia = []
        top_produtos_fat_dia  = []
        top_produtos_qtde_sem = []
        top_produtos_fat_sem  = []
        top_produtos_qtde_mes = []
        top_produtos_fat_mes  = []
        chart_freq_retorno_dia = [None]*24
        chart_freq_retorno_sem = []
        chart_freq_retorno_mes = []

    # ── Tema da empresa ──────────────────────────────────────────────────────
    theme = dict(primary_color='#F47B20', secondary_color='#0057A8', accent_color='#FFFFFF')
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
            "SELECT primary_color, secondary_color, accent_color "
            "FROM faciais.company_themes WHERE company_id = %s",
            (theme_company_id,)
        )
        if row:
            theme['primary_color']   = row['primary_color']
            theme['secondary_color'] = row['secondary_color']
            theme['accent_color']    = row['accent_color']

    return render_template(
        'mobile/dashboard.html',
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
        chart_freq_retorno_dia=chart_freq_retorno_dia,
        chart_freq_retorno_sem=chart_freq_retorno_sem,
        chart_freq_retorno_mes=chart_freq_retorno_mes,
    )


# ── Trocar senha ─────────────────────────────────────────────────────────────

@mobile_bp.route('/conta/trocar-senha', methods=['GET', 'POST'])
@_login_required
def trocar_senha():
    msg_type = None
    msg_text = None

    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual', '')
        nova_senha  = request.form.get('nova_senha', '')
        confirmacao = request.form.get('confirmacao', '')

        user = db.query_one(
            "SELECT password_hash FROM faciais.users WHERE user_id = %s",
            (session['user_id'],)
        )

        if not check_password_hash(user['password_hash'], senha_atual):
            msg_type = 'error'
            msg_text = 'Senha atual incorreta.'
        elif nova_senha != confirmacao:
            msg_type = 'error'
            msg_text = 'As novas senhas não coincidem.'
        elif len(nova_senha) < 6:
            msg_type = 'error'
            msg_text = 'A nova senha deve ter pelo menos 6 caracteres.'
        else:
            db.execute(
                "UPDATE faciais.users SET password_hash = %s WHERE user_id = %s",
                (generate_password_hash(nova_senha), session['user_id'])
            )
            msg_type = 'success'
            msg_text = 'Senha alterada com sucesso!'

    return render_template('mobile/trocar_senha.html',
                           msg_type=msg_type, msg_text=msg_text)


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


@mobile_bp.route('/visitacao')
@_login_required
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
                    return redirect(url_for('mobile.visitacao',
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
                    return redirect(url_for('mobile.visitacao', store_id=last_sid))
            elif user_type == 'emp':
                row = db.query_one(
                    "SELECT store_id FROM faciais.user_stores "
                    "WHERE store_id = %s AND user_id = %s",
                    (last_sid, user_id)
                )
                if row:
                    return redirect(url_for('mobile.visitacao', store_id=last_sid))

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
    theme = dict(primary_color='#F47B20', secondary_color='#0057A8', accent_color='#FFFFFF')
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
            "SELECT primary_color, secondary_color, accent_color "
            "FROM faciais.company_themes WHERE company_id = %s",
            (theme_company_id,)
        )
        if row:
            theme.update(row)

    return render_template(
        'mobile/visitacao.html',
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
