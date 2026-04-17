import calendar
from datetime import date as date_type, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash
from routes.utils import login_required, screen_required
import db

auth_bp = Blueprint('auth', __name__)


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

    _MESES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
              'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
    semana_label = f"{semana_inicio.strftime('%d/%m')} – {semana_fim.strftime('%d/%m/%Y')}"
    mes_label    = f"{_MESES[selected_date.month - 1]} {selected_date.year}"

    # ── KPIs Operacional – Dia ────────────────────────────────────────────────
    kpi = dict(visitantes=None, recorrentes=None, vendas=None, conversao=None)

    # ── KPIs Comercial – Dia ──────────────────────────────────────────────────
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
            JOIN   faciais.cameras cam ON cam.camera_id = dr.camera_id
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  cam.store_id     = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) = %s
        """, (sid, data_str))
        kpi['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.cameras cam ON cam.camera_id = dr.camera_id
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  cam.store_id     = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) = %s
              AND  EXISTS (
                  SELECT 1
                  FROM   faciais.detection_records dr2
                  JOIN   faciais.cameras cam2 ON cam2.camera_id = dr2.camera_id
                  WHERE  dr2.person_id = dr.person_id
                    AND  cam2.store_id = %s
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
            JOIN   faciais.cameras cam ON cam.camera_id = dr.camera_id
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  cam.store_id     = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
        """, (sid, semana_inicio_str, semana_fim_str))
        kpi_sem['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.cameras cam ON cam.camera_id = dr.camera_id
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  cam.store_id     = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
              AND  EXISTS (
                  SELECT 1
                  FROM   faciais.detection_records dr2
                  JOIN   faciais.cameras cam2 ON cam2.camera_id = dr2.camera_id
                  WHERE  dr2.person_id = dr.person_id
                    AND  cam2.store_id = %s
                    AND  DATE(dr2.created_at) < %s
              )
        """, (sid, semana_inicio_str, semana_fim_str, sid, semana_inicio_str))
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
            JOIN   faciais.cameras cam ON cam.camera_id = dr.camera_id
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  cam.store_id     = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
        """, (sid, mes_inicio_str, mes_fim_str))
        kpi_mes['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.cameras cam ON cam.camera_id = dr.camera_id
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  cam.store_id     = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
              AND  EXISTS (
                  SELECT 1
                  FROM   faciais.detection_records dr2
                  JOIN   faciais.cameras cam2 ON cam2.camera_id = dr2.camera_id
                  WHERE  dr2.person_id = dr.person_id
                    AND  cam2.store_id = %s
                    AND  DATE(dr2.created_at) < %s
              )
        """, (sid, mes_inicio_str, mes_fim_str, sid, mes_inicio_str))
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

    # ── Tema da empresa ──────────────────────────────────────────────────────
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
    )
