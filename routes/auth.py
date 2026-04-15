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

    stores              = []   # lojas disponíveis para o seletor
    selected_company_id = None
    selected_store_id   = request.args.get('store_id', type=int)

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

    # ── KPIs Operacional – Dia ────────────────────────────────────────────────
    kpi = dict(visitantes=None, recorrentes=None, vendas=None, conversao=None)

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
                WHERE  portal           = %s
                  AND  cnpj_emp         = %s
                  AND  DATE(data_documento) = %s
                  AND  cancelado        <> 'S'
                  AND  excluido         <> 'S'
                  AND  soma_relatorio   =  'S'
            """, (active_microvix_portal, active_store_cnpj, data_str))
            kpi['vendas'] = r['total'] if r else 0
        else:
            kpi['vendas'] = None

        if kpi['visitantes']:
            kpi['conversao'] = round((kpi['vendas'] or 0) / kpi['visitantes'] * 100, 1)
        else:
            kpi['conversao'] = 0.0

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
    )
