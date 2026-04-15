from datetime import date as date_type
from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash
from routes.utils import login_required, screen_required
import db

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
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

    active_company_id  = None
    active_microvix_portal = None

    if user_type == 'adm':
        companies = db.query_all("""
            SELECT c.company_id, c.company_name, c.microvix_portal, ct.logo_url
            FROM   faciais.companies c
            JOIN   faciais.company_themes ct ON ct.company_id = c.company_id
            WHERE  ct.logo_url IS NOT NULL
            ORDER  BY c.company_name
        """)
        selected_company_id = request.args.get('company_id', type=int)
        if selected_company_id:
            match = next((c for c in companies if c['company_id'] == selected_company_id), None)
            if match:
                company_logo           = match['logo_url']
                company_name           = match['company_name']
                active_company_id      = match['company_id']
                active_microvix_portal = match['microvix_portal']

    elif user_type == 'man':
        row = db.query_one("""
            SELECT c.company_id, c.company_name, c.microvix_portal, ct.logo_url
            FROM   faciais.user_company_groups ucg
            JOIN   faciais.companies c        ON c.company_group_id = ucg.company_group_id
            JOIN   faciais.company_themes ct  ON ct.company_id = c.company_id
            WHERE  ucg.user_id = %s AND ct.logo_url IS NOT NULL
            LIMIT  1
        """, (user_id,))
        if row:
            company_logo           = row['logo_url']
            company_name           = row['company_name']
            active_company_id      = row['company_id']
            active_microvix_portal = row['microvix_portal']

    elif user_type == 'ret':
        row = db.query_one("""
            SELECT c.company_id, c.company_name, c.microvix_portal, ct.logo_url
            FROM   faciais.user_retailer_groups urg
            JOIN   faciais.stores s           ON s.retailer_group_id = urg.retailer_group_id
            JOIN   faciais.companies c        ON c.company_id = s.company_id
            JOIN   faciais.company_themes ct  ON ct.company_id = c.company_id
            WHERE  urg.user_id = %s AND ct.logo_url IS NOT NULL
            LIMIT  1
        """, (user_id,))
        if row:
            company_logo           = row['logo_url']
            company_name           = row['company_name']
            active_company_id      = row['company_id']
            active_microvix_portal = row['microvix_portal']

    elif user_type == 'emp':
        row = db.query_one("""
            SELECT c.company_id, c.company_name, c.microvix_portal, ct.logo_url
            FROM   faciais.user_stores us
            JOIN   faciais.stores s           ON s.store_id = us.store_id
            JOIN   faciais.companies c        ON c.company_id = s.company_id
            JOIN   faciais.company_themes ct  ON ct.company_id = c.company_id
            WHERE  us.user_id = %s AND ct.logo_url IS NOT NULL
            LIMIT  1
        """, (user_id,))
        if row:
            company_logo           = row['logo_url']
            company_name           = row['company_name']
            active_company_id      = row['company_id']
            active_microvix_portal = row['microvix_portal']

    # ── Data selecionada (padrão: hoje) ───────────────────────────────────────
    data_str = request.args.get('date', date_type.today().strftime('%Y-%m-%d'))
    try:
        date_type.fromisoformat(data_str)
    except ValueError:
        data_str = date_type.today().strftime('%Y-%m-%d')

    # ── KPIs Operacional – Dia ────────────────────────────────────────────────
    kpi = dict(visitantes=None, recorrentes=None, vendas=None, conversao=None)

    if active_company_id:
        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.cameras cam ON cam.camera_id = dr.camera_id
            JOIN   faciais.stores  s   ON s.store_id   = cam.store_id
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  s.company_id     = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) = %s
        """, (active_company_id, data_str))
        kpi['visitantes'] = r['total'] if r else 0

        r = db.query_one("""
            SELECT COUNT(DISTINCT dr.person_id) AS total
            FROM   faciais.detection_records dr
            JOIN   faciais.cameras cam ON cam.camera_id = dr.camera_id
            JOIN   faciais.stores  s   ON s.store_id   = cam.store_id
            JOIN   faciais.people  p   ON p.person_id  = dr.person_id
            WHERE  s.company_id     = %s
              AND  p.person_type_id = 'C'
              AND  dr.person_id     IS NOT NULL
              AND  DATE(dr.created_at) = %s
              AND  EXISTS (
                  SELECT 1
                  FROM   faciais.detection_records dr2
                  JOIN   faciais.cameras cam2 ON cam2.camera_id = dr2.camera_id
                  JOIN   faciais.stores  s2   ON s2.store_id   = cam2.store_id
                  WHERE  dr2.person_id  = dr.person_id
                    AND  s2.company_id  = %s
                    AND  DATE(dr2.created_at) < %s
              )
        """, (active_company_id, data_str, active_company_id, data_str))
        kpi['recorrentes'] = r['total'] if r else 0

        if active_microvix_portal:
            r = db.query_one("""
                SELECT COUNT(DISTINCT documento) AS total
                FROM   microvix.microvix_movimento
                WHERE  portal          = %s
                  AND  DATE(data_documento) = %s
                  AND  cancelado       <> 'S'
                  AND  excluido        <> 'S'
                  AND  soma_relatorio  =  'S'
            """, (active_microvix_portal, data_str))
            kpi['vendas'] = r['total'] if r else 0
        else:
            kpi['vendas'] = None   # portal não configurado

        if kpi['visitantes']:
            vendas = kpi['vendas'] or 0
            kpi['conversao'] = round(vendas / kpi['visitantes'] * 100, 1)
        else:
            kpi['conversao'] = 0.0

    return render_template(
        'dashboard.html',
        company_logo=company_logo,
        company_name=company_name,
        companies=companies,
        selected_company_id=selected_company_id,
        data_str=data_str,
        kpi=kpi,
    )
