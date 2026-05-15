import calendar
from datetime import date as date_type, timedelta
from functools import wraps
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, send_from_directory, make_response)
from werkzeug.security import check_password_hash, generate_password_hash
import os
import db
from metas import get_metas as _get_metas, meta_faturamento_acum_diario as _meta_faturamento_acum_diario
from people import (qtd_novos as _qtd_novos, qtd_recorrentes as _qtd_recorrentes,
                    kpi_microvix as _kpi_microvix, faixa_horaria as _faixa_horaria,
                    ticket_por_tipo as _ticket_por_tipo,
                    top5_por_tipo as _top5_por_tipo,
                    faturamento_mensal as _faturamento_mensal,
                    faturamento_diario_mes as _faturamento_diario_mes,
                    vendas_mensal_por_vendedor as _vendas_mensal_por_vendedor)
from routes.utils import (fmt_permanencia, kpi_tempo_loja, kpi_tempo_loja_range,
                           tempo_gauge, HEIMDALL_IMAGE_BASE)

mobile_bp = Blueprint('mobile', __name__)


def _prev_business_day(d):
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


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
                SELECT store_id, store_name, store_short_name, cnpj
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
                SELECT store_id, store_name, store_short_name, cnpj
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
            SELECT DISTINCT s.store_id, s.store_name, s.store_short_name, s.cnpj
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
            SELECT s.store_id, s.store_name, s.store_short_name, s.cnpj
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
        row = db.query_one(
            "SELECT microvix_portal FROM faciais.stores WHERE store_id = %s",
            (active_store['store_id'],))
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

    # ── KPIs Operacional – Dia ───────────────────────────────────────────────
    kpi = dict(visitantes=None, recorrentes=None, novos=None, vendas=None, conversao=None, tempo_loja=None)

    # ── KPIs Comercial – Dia ─────────────────────────────────────────────────
    kpi_com = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)

    # ── KPIs Operacional – Semana / Mês ──────────────────────────────────────
    kpi_sem     = dict(visitantes=None, recorrentes=None, novos=None, vendas=None, conversao=None, tempo_loja=None)
    kpi_mes     = dict(visitantes=None, recorrentes=None, novos=None, vendas=None, conversao=None, tempo_loja=None)

    # ── KPIs Comercial – Semana / Mês ────────────────────────────────────────
    kpi_com_sem = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)
    kpi_com_mes = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)

    # ── KPIs Operacional / Comercial – YTD ───────────────────────────────────
    kpi_ytd     = dict(visitantes=None, recorrentes=None, novos=None, vendas=None, conversao=None, tempo_loja=None)
    kpi_com_ytd = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)

    if active_store:
        sid = active_store['store_id']

        kpi['recorrentes'] = _qtd_recorrentes(sid, data_str, data_str) or 0
        kpi['novos']       = _qtd_novos(sid, data_str, data_str) or 0
        kpi['visitantes']  = kpi['recorrentes'] + kpi['novos']

        if active_microvix_portal and active_store_cnpj:
            _com = _kpi_microvix(active_microvix_portal, active_store_cnpj, data_str, data_str)
            kpi['vendas'] = _com['vendas']
            kpi_com.update(_com)
        else:
            kpi['vendas'] = None

        if kpi['visitantes']:
            kpi['conversao'] = int(round((kpi['vendas'] or 0) / kpi['visitantes'] * 100))
        else:
            kpi['conversao'] = 0

        kpi['tempo_loja'] = kpi_tempo_loja(sid, data_str)

        # ── Operacional – Semana ─────────────────────────────────────────────
        kpi_sem['recorrentes'] = _qtd_recorrentes(sid, semana_inicio_str, semana_fim_str) or 0
        kpi_sem['novos']       = _qtd_novos(sid, semana_inicio_str, semana_fim_str) or 0
        kpi_sem['visitantes']  = kpi_sem['recorrentes'] + kpi_sem['novos']

        if active_microvix_portal and active_store_cnpj:
            _com = _kpi_microvix(active_microvix_portal, active_store_cnpj, semana_inicio_str, semana_fim_str)
            kpi_sem['vendas'] = _com['vendas']
            kpi_com_sem.update(_com)
        else:
            kpi_sem['vendas'] = None

        if kpi_sem['visitantes']:
            kpi_sem['conversao'] = int(round((kpi_sem['vendas'] or 0) / kpi_sem['visitantes'] * 100))
        else:
            kpi_sem['conversao'] = 0

        kpi_sem['tempo_loja'] = kpi_tempo_loja_range(sid, semana_inicio_str, semana_fim_str)

        # ── Operacional – Mês ─────────────────────────────────────────────────
        kpi_mes['recorrentes'] = _qtd_recorrentes(sid, mes_inicio_str, mes_fim_str) or 0
        kpi_mes['novos']       = _qtd_novos(sid, mes_inicio_str, mes_fim_str) or 0
        kpi_mes['visitantes']  = kpi_mes['recorrentes'] + kpi_mes['novos']

        if active_microvix_portal and active_store_cnpj:
            _com = _kpi_microvix(active_microvix_portal, active_store_cnpj, mes_inicio_str, mes_fim_str)
            kpi_mes['vendas'] = _com['vendas']
            kpi_com_mes.update(_com)
        else:
            kpi_mes['vendas'] = None

        if kpi_mes['visitantes']:
            kpi_mes['conversao'] = int(round((kpi_mes['vendas'] or 0) / kpi_mes['visitantes'] * 100))
        else:
            kpi_mes['conversao'] = 0

        kpi_mes['tempo_loja'] = kpi_tempo_loja_range(sid, mes_inicio_str, mes_fim_str)

        # ── Operacional – YTD ─────────────────────────────────────────────────
        kpi_ytd['recorrentes'] = _qtd_recorrentes(sid, ytd_inicio_str, ytd_fim_str) or 0
        kpi_ytd['novos']       = _qtd_novos(sid, ytd_inicio_str, ytd_fim_str) or 0
        kpi_ytd['visitantes']  = kpi_ytd['recorrentes'] + kpi_ytd['novos']

        if active_microvix_portal and active_store_cnpj:
            _com = _kpi_microvix(active_microvix_portal, active_store_cnpj, ytd_inicio_str, ytd_fim_str)
            kpi_ytd['vendas'] = _com['vendas']
            kpi_com_ytd.update(_com)
        else:
            kpi_ytd['vendas'] = None

        if kpi_ytd['visitantes']:
            kpi_ytd['conversao'] = int(round((kpi_ytd['vendas'] or 0) / kpi_ytd['visitantes'] * 100))
        else:
            kpi_ytd['conversao'] = 0

        kpi_ytd['tempo_loja'] = kpi_tempo_loja_range(sid, ytd_inicio_str, ytd_fim_str)

    # ── KPIs Estratégico – derivados dos KPIs já calculados ──────────────────
    kpi_est     = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None, taxa_retorno=None, valor_medio=None)
    kpi_est_sem = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None, taxa_retorno=None, valor_medio=None)
    kpi_est_mes = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None, taxa_retorno=None, valor_medio=None)

    if kpi['visitantes'] is not None and kpi['recorrentes'] is not None:
        kpi_est['novos']       = kpi['novos']
        kpi_est['recorrentes'] = kpi['recorrentes']
        _t = (kpi_est['novos'] or 0) + (kpi_est['recorrentes'] or 0)
        kpi_est['taxa_retorno'] = round((kpi_est['recorrentes'] or 0) / _t * 100) if _t else 0
        if kpi_com['faturamento'] is not None:
            fat = kpi_com['faturamento'] or 0
            kpi_est['valor_medio'] = round(fat / _t, 2) if _t else None
        if active_microvix_portal and active_store_cnpj:
            _tk = _ticket_por_tipo(active_store['store_id'], active_microvix_portal, active_store_cnpj,
                                   data_str, data_str)
            kpi_est['ticket_novo'] = _tk['ticket_novo']
            kpi_est['ticket_rec']  = _tk['ticket_rec']

    if kpi_sem['visitantes'] is not None and kpi_sem['recorrentes'] is not None:
        kpi_est_sem['novos']       = kpi_sem['novos']
        kpi_est_sem['recorrentes'] = kpi_sem['recorrentes']
        _t = (kpi_est_sem['novos'] or 0) + (kpi_est_sem['recorrentes'] or 0)
        kpi_est_sem['taxa_retorno'] = round((kpi_est_sem['recorrentes'] or 0) / _t * 100) if _t else 0
        if kpi_com_sem['faturamento'] is not None:
            fat = kpi_com_sem['faturamento'] or 0
            kpi_est_sem['valor_medio'] = round(fat / _t, 2) if _t else None
        if active_microvix_portal and active_store_cnpj:
            _tk = _ticket_por_tipo(active_store['store_id'], active_microvix_portal, active_store_cnpj,
                                   semana_inicio_str, semana_fim_str)
            kpi_est_sem['ticket_novo'] = _tk['ticket_novo']
            kpi_est_sem['ticket_rec']  = _tk['ticket_rec']

    if kpi_mes['visitantes'] is not None and kpi_mes['recorrentes'] is not None:
        kpi_est_mes['novos']       = kpi_mes['novos']
        kpi_est_mes['recorrentes'] = kpi_mes['recorrentes']
        _t = (kpi_est_mes['novos'] or 0) + (kpi_est_mes['recorrentes'] or 0)
        kpi_est_mes['taxa_retorno'] = round((kpi_est_mes['recorrentes'] or 0) / _t * 100) if _t else 0
        if kpi_com_mes['faturamento'] is not None:
            fat = kpi_com_mes['faturamento'] or 0
            kpi_est_mes['valor_medio'] = round(fat / _t, 2) if _t else None
        if active_microvix_portal and active_store_cnpj:
            _tk = _ticket_por_tipo(active_store['store_id'], active_microvix_portal, active_store_cnpj,
                                   mes_inicio_str, mes_fim_str)
            kpi_est_mes['ticket_novo'] = _tk['ticket_novo']
            kpi_est_mes['ticket_rec']  = _tk['ticket_rec']

    kpi_est_ytd = dict(novos=None, recorrentes=None, ticket_novo=None, ticket_rec=None, taxa_retorno=None, valor_medio=None)
    if kpi_ytd['visitantes'] is not None and kpi_ytd['recorrentes'] is not None:
        kpi_est_ytd['novos']       = kpi_ytd['novos']
        kpi_est_ytd['recorrentes'] = kpi_ytd['recorrentes']
        _t = (kpi_est_ytd['novos'] or 0) + (kpi_est_ytd['recorrentes'] or 0)
        kpi_est_ytd['taxa_retorno'] = round((kpi_est_ytd['recorrentes'] or 0) / _t * 100) if _t else 0
        if kpi_com_ytd['faturamento'] is not None:
            fat = kpi_com_ytd['faturamento'] or 0
            kpi_est_ytd['valor_medio'] = round(fat / _t, 2) if _t else None
        if active_microvix_portal and active_store_cnpj:
            _tk = _ticket_por_tipo(active_store['store_id'], active_microvix_portal, active_store_cnpj,
                                   ytd_inicio_str, ytd_fim_str)
            kpi_est_ytd['ticket_novo'] = _tk['ticket_novo']
            kpi_est_ytd['ticket_rec']  = _tk['ticket_rec']

    # ── KPIs dia útil anterior (comparação) ──────────────────────────────────
    kpi_ant = dict(visitantes=None, recorrentes=None, novos=None,
                   vendas=None, conversao=None, tempo_loja=None, taxa_retorno=None, valor_medio=None)
    kpi_ant_com = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)
    if active_store:
        _prev = _prev_business_day(selected_date)
        _ps   = _prev.strftime('%Y-%m-%d')
        sid   = active_store['store_id']

        kpi_ant['recorrentes'] = _qtd_recorrentes(sid, _ps, _ps) or 0
        kpi_ant['novos']       = _qtd_novos(sid, _ps, _ps) or 0
        kpi_ant['visitantes']  = kpi_ant['recorrentes'] + kpi_ant['novos']

        if active_microvix_portal and active_store_cnpj:
            _com = _kpi_microvix(active_microvix_portal, active_store_cnpj, _ps, _ps)
            kpi_ant['vendas'] = _com['vendas']
            kpi_ant_com.update(_com)

        if kpi_ant['visitantes']:
            kpi_ant['conversao'] = int(round((kpi_ant['vendas'] or 0) / kpi_ant['visitantes'] * 100))
        else:
            kpi_ant['conversao'] = 0

        kpi_ant['tempo_loja'] = kpi_tempo_loja(sid, _ps)

    if kpi_ant['novos'] is not None and kpi_ant['recorrentes'] is not None:
        _t_ant = (kpi_ant['novos'] or 0) + (kpi_ant['recorrentes'] or 0)
        kpi_ant['taxa_retorno'] = round((kpi_ant['recorrentes'] or 0) / _t_ant * 100) if _t_ant else 0
        if kpi_ant_com['faturamento'] is not None and _t_ant:
            kpi_ant['valor_medio'] = round(kpi_ant_com['faturamento'] / _t_ant, 2)

    kpi_ant_sem = dict(visitantes=None, recorrentes=None, novos=None,
                       vendas=None, conversao=None, tempo_loja=None, taxa_retorno=None, valor_medio=None)
    kpi_ant_com_sem = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)
    if active_store:
        sid = active_store['store_id']

        kpi_ant_sem['recorrentes'] = _qtd_recorrentes(sid, semana_ant_inicio_str, semana_ant_fim_str) or 0
        kpi_ant_sem['novos']       = _qtd_novos(sid, semana_ant_inicio_str, semana_ant_fim_str) or 0
        kpi_ant_sem['visitantes']  = kpi_ant_sem['recorrentes'] + kpi_ant_sem['novos']

        if active_microvix_portal and active_store_cnpj:
            _com = _kpi_microvix(active_microvix_portal, active_store_cnpj, semana_ant_inicio_str, semana_ant_fim_str)
            kpi_ant_sem['vendas'] = _com['vendas']
            kpi_ant_com_sem.update(_com)

        if kpi_ant_sem['visitantes']:
            kpi_ant_sem['conversao'] = int(round((kpi_ant_sem['vendas'] or 0) / kpi_ant_sem['visitantes'] * 100))
        else:
            kpi_ant_sem['conversao'] = 0

        kpi_ant_sem['tempo_loja'] = kpi_tempo_loja_range(sid, semana_ant_inicio_str, semana_ant_fim_str)

    if kpi_ant_sem['novos'] is not None and kpi_ant_sem['recorrentes'] is not None:
        _t_ant = (kpi_ant_sem['novos'] or 0) + (kpi_ant_sem['recorrentes'] or 0)
        kpi_ant_sem['taxa_retorno'] = round((kpi_ant_sem['recorrentes'] or 0) / _t_ant * 100) if _t_ant else 0
        if kpi_ant_com_sem['faturamento'] is not None and _t_ant:
            kpi_ant_sem['valor_medio'] = round(kpi_ant_com_sem['faturamento'] / _t_ant, 2)

    kpi_ant_mes = dict(visitantes=None, recorrentes=None, novos=None,
                       vendas=None, conversao=None, tempo_loja=None, taxa_retorno=None, valor_medio=None)
    kpi_ant_com_mes = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)
    if active_store:
        sid = active_store['store_id']

        kpi_ant_mes['recorrentes'] = _qtd_recorrentes(sid, mes_ant_inicio_str, mes_ant_fim_str) or 0
        kpi_ant_mes['novos']       = _qtd_novos(sid, mes_ant_inicio_str, mes_ant_fim_str) or 0
        kpi_ant_mes['visitantes']  = kpi_ant_mes['recorrentes'] + kpi_ant_mes['novos']

        if active_microvix_portal and active_store_cnpj:
            _com = _kpi_microvix(active_microvix_portal, active_store_cnpj, mes_ant_inicio_str, mes_ant_fim_str)
            kpi_ant_mes['vendas'] = _com['vendas']
            kpi_ant_com_mes.update(_com)

        if kpi_ant_mes['visitantes']:
            kpi_ant_mes['conversao'] = int(round((kpi_ant_mes['vendas'] or 0) / kpi_ant_mes['visitantes'] * 100))
        else:
            kpi_ant_mes['conversao'] = 0

        kpi_ant_mes['tempo_loja'] = kpi_tempo_loja_range(sid, mes_ant_inicio_str, mes_ant_fim_str)

    if kpi_ant_mes['novos'] is not None and kpi_ant_mes['recorrentes'] is not None:
        _t_ant = (kpi_ant_mes['novos'] or 0) + (kpi_ant_mes['recorrentes'] or 0)
        kpi_ant_mes['taxa_retorno'] = round((kpi_ant_mes['recorrentes'] or 0) / _t_ant * 100) if _t_ant else 0
        if kpi_ant_com_mes['faturamento'] is not None and _t_ant:
            kpi_ant_mes['valor_medio'] = round(kpi_ant_com_mes['faturamento'] / _t_ant, 2)

    # ── KPIs YTD anterior (comparação) ───────────────────────────────────────
    kpi_ant_ytd     = dict(visitantes=None, recorrentes=None, novos=None, vendas=None, conversao=None, tempo_loja=None, taxa_retorno=None, valor_medio=None)
    kpi_ant_com_ytd = dict(faturamento=None, ticket_medio=None, vendas=None, itens_venda=None)

    if active_store:
        sid = active_store['store_id']

        kpi_ant_ytd['recorrentes'] = _qtd_recorrentes(sid, ytd_ant_inicio_str, ytd_ant_fim_str) or 0
        kpi_ant_ytd['novos']       = _qtd_novos(sid, ytd_ant_inicio_str, ytd_ant_fim_str) or 0
        kpi_ant_ytd['visitantes']  = kpi_ant_ytd['recorrentes'] + kpi_ant_ytd['novos']

        if active_microvix_portal and active_store_cnpj:
            _com = _kpi_microvix(active_microvix_portal, active_store_cnpj, ytd_ant_inicio_str, ytd_ant_fim_str)
            kpi_ant_ytd['vendas'] = _com['vendas']
            kpi_ant_com_ytd.update(_com)
        else:
            kpi_ant_ytd['vendas'] = None

        if kpi_ant_ytd['visitantes']:
            kpi_ant_ytd['conversao'] = int(round((kpi_ant_ytd['vendas'] or 0) / kpi_ant_ytd['visitantes'] * 100))
        else:
            kpi_ant_ytd['conversao'] = 0
        kpi_ant_ytd['tempo_loja'] = kpi_tempo_loja_range(sid, ytd_ant_inicio_str, ytd_ant_fim_str)

    if kpi_ant_ytd['novos'] is not None and kpi_ant_ytd['recorrentes'] is not None:
        _t_ant = (kpi_ant_ytd['novos'] or 0) + (kpi_ant_ytd['recorrentes'] or 0)
        kpi_ant_ytd['taxa_retorno'] = round((kpi_ant_ytd['recorrentes'] or 0) / _t_ant * 100) if _t_ant else 0
        if kpi_ant_com_ytd['faturamento'] is not None and _t_ant:
            kpi_ant_ytd['valor_medio'] = round(kpi_ant_com_ytd['faturamento'] / _t_ant, 2)

    # ── Gauge do Tempo na Loja (agulha SVG) ──────────────────────────────────
    kpi_tempo_gauge     = tempo_gauge(kpi['tempo_loja'])
    kpi_tempo_gauge_sem = tempo_gauge(kpi_sem['tempo_loja'])
    kpi_tempo_gauge_mes = tempo_gauge(kpi_mes['tempo_loja'])
    kpi_tempo_gauge_ytd = tempo_gauge(kpi_ytd['tempo_loja'])

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
            for row in _faixa_horaria(active_microvix_portal, active_store_cnpj, data_str, data_str):
                chart_faixa_dia['vendas'][int(row['hora'])]      = int(row['vendas'] or 0)
                chart_faixa_dia['faturamento'][int(row['hora'])] = float(row['faturamento'] or 0)

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
            for row in _faixa_horaria(active_microvix_portal, active_store_cnpj, semana_inicio_str, semana_fim_str):
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
            for row in _faixa_horaria(active_microvix_portal, active_store_cnpj, mes_inicio_str, mes_fim_str):
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
                       (vpc.first_record::date < %s) AS is_rec
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                JOIN   faciais.vw_primeira_aparicao_clientes vpc ON vpc.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL AND DATE(dr.created_at) = %s
                GROUP  BY dr.person_id, vpc.first_record
            ) sub
            GROUP BY hora ORDER BY hora
        """, (data_str, sid, data_str)):
            h = int(row['hora'])
            chart_ocorrencias_dia['recorrentes'][h] = int(row['recorrentes'] or 0)
            chart_ocorrencias_dia['novos'][h]        = int(row['novos'] or 0)

        chart_ocorrencias_sem = {'novos': [0]*24, 'recorrentes': [0]*24}
        for row in db.query_all("""
            WITH pv AS (
                SELECT dr.person_id, MIN(dr.created_at) AS primeira_visita,
                       vpc.first_record
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                JOIN   faciais.vw_primeira_aparicao_clientes vpc ON vpc.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, vpc.first_record
            )
            SELECT hora,
                   SUM(CASE WHEN is_rec THEN 1 ELSE 0 END) AS recorrentes,
                   SUM(CASE WHEN NOT is_rec THEN 1 ELSE 0 END) AS novos
            FROM (
                SELECT EXTRACT(HOUR FROM pv.primeira_visita)::int AS hora,
                       (pv.first_record::date < DATE(pv.primeira_visita)) AS is_rec
                FROM pv
            ) sub
            GROUP BY hora ORDER BY hora
        """, (sid, semana_inicio_str, semana_fim_str)):
            h = int(row['hora'])
            chart_ocorrencias_sem['recorrentes'][h] = int(row['recorrentes'] or 0)
            chart_ocorrencias_sem['novos'][h]        = int(row['novos'] or 0)

        chart_ocorrencias_mes = {'novos': [0]*24, 'recorrentes': [0]*24}
        for row in db.query_all("""
            WITH pv AS (
                SELECT dr.person_id, MIN(dr.created_at) AS primeira_visita,
                       vpc.first_record
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                JOIN   faciais.vw_primeira_aparicao_clientes vpc ON vpc.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, vpc.first_record
            )
            SELECT hora,
                   SUM(CASE WHEN is_rec THEN 1 ELSE 0 END) AS recorrentes,
                   SUM(CASE WHEN NOT is_rec THEN 1 ELSE 0 END) AS novos
            FROM (
                SELECT EXTRACT(HOUR FROM pv.primeira_visita)::int AS hora,
                       (pv.first_record::date < DATE(pv.primeira_visita)) AS is_rec
                FROM pv
            ) sub
            GROUP BY hora ORDER BY hora
        """, (sid, mes_inicio_str, mes_fim_str)):
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
        combinacoes_dia       = []
        combinacoes_sem       = []
        combinacoes_mes       = []

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

            top_produtos_qtde_dia = _top_query(_date_dia,  "SUM(m.quantidade)",    _p + (data_str,))
            top_produtos_fat_dia  = _top_query(_date_dia,  "SUM(m.valor_liquido)", _p + (data_str,))
            top_produtos_qtde_sem = _top_query(_date_sem,  "SUM(m.quantidade)",    _p + (semana_inicio_str, semana_fim_str))
            top_produtos_fat_sem  = _top_query(_date_sem,  "SUM(m.valor_liquido)", _p + (semana_inicio_str, semana_fim_str))
            top_produtos_qtde_mes = _top_query(_date_sem,  "SUM(m.quantidade)",    _p + (mes_inicio_str, mes_fim_str))
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

        # ── YTD charts ───────────────────────────────────────────────────────
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
        """, (sid, ytd_inicio_str, ytd_fim_str))
        for row in rows:
            chart_faixa_ytd['clientes'][int(row['hora'])] = int(row['clientes'] or 0)

        if active_microvix_portal and active_store_cnpj:
            for row in _faixa_horaria(active_microvix_portal, active_store_cnpj, ytd_inicio_str, ytd_fim_str):
                chart_faixa_ytd['vendas'][int(row['hora'])]      = int(row['vendas'] or 0)
                chart_faixa_ytd['faturamento'][int(row['hora'])] = float(row['faturamento'] or 0)

        chart_genero_ytd = {'F': [0]*24, 'M': [0]*24}
        for row in db.query_all(_GENERO_RANGE_QUERY, (sid, ytd_inicio_str, ytd_fim_str)):
            g = row['gender_id']
            if g in chart_genero_ytd:
                chart_genero_ytd[g][int(row['hora'])] = int(row['total'] or 0)

        chart_ocorrencias_ytd = {'novos': [0]*24, 'recorrentes': [0]*24}
        for row in db.query_all("""
            WITH pv AS (
                SELECT dr.person_id, MIN(dr.created_at) AS primeira_visita,
                       vpc.first_record
                FROM   faciais.detection_records dr
                JOIN   faciais.people p ON p.person_id = dr.person_id
                JOIN   faciais.vw_primeira_aparicao_clientes vpc ON vpc.person_id = dr.person_id
                WHERE  dr.store_id = %s AND p.person_type_id = 'C'
                  AND  dr.person_id IS NOT NULL
                  AND  DATE(dr.created_at) BETWEEN %s AND %s
                GROUP  BY dr.person_id, vpc.first_record
            )
            SELECT hora,
                   SUM(CASE WHEN is_rec THEN 1 ELSE 0 END) AS recorrentes,
                   SUM(CASE WHEN NOT is_rec THEN 1 ELSE 0 END) AS novos
            FROM (
                SELECT EXTRACT(HOUR FROM pv.primeira_visita)::int AS hora,
                       (pv.first_record::date < DATE(pv.primeira_visita)) AS is_rec
                FROM pv
            ) sub
            GROUP BY hora ORDER BY hora
        """, (sid, ytd_inicio_str, ytd_fim_str)):
            h = int(row['hora'])
            chart_ocorrencias_ytd['recorrentes'][h] = int(row['recorrentes'] or 0)
            chart_ocorrencias_ytd['novos'][h]        = int(row['novos'] or 0)

        top_produtos_qtde_ytd = []
        top_produtos_fat_ytd  = []
        combinacoes_ytd       = []
        top5_tipo_dia = {'novos': [], 'recorrentes': []}
        top5_tipo_sem = {'novos': [], 'recorrentes': []}
        top5_tipo_mes = {'novos': [], 'recorrentes': []}
        top5_tipo_ytd = {'novos': [], 'recorrentes': []}
        if active_microvix_portal and active_store_cnpj:
            top_produtos_qtde_ytd = _top_query(_date_sem, "SUM(m.quantidade)",    _p + (ytd_inicio_str, ytd_fim_str))
            top_produtos_fat_ytd  = _top_query(_date_sem, "SUM(m.valor_liquido)", _p + (ytd_inicio_str, ytd_fim_str))
            combinacoes_ytd       = _comb_query("DATE(a.data_documento) BETWEEN %s AND %s", _p + (ytd_inicio_str, ytd_fim_str))
            top5_tipo_dia = _top5_por_tipo(sid, active_microvix_portal, active_store_cnpj, data_str, data_str)
            top5_tipo_sem = _top5_por_tipo(sid, active_microvix_portal, active_store_cnpj, semana_inicio_str, semana_fim_str)
            top5_tipo_mes = _top5_por_tipo(sid, active_microvix_portal, active_store_cnpj, mes_inicio_str, mes_fim_str)
            top5_tipo_ytd = _top5_por_tipo(sid, active_microvix_portal, active_store_cnpj, ytd_inicio_str, ytd_fim_str)

        chart_freq_retorno_ytd = [
            {'label': row['visit_day'].strftime('%d/%m'), 'avg': float(row['avg_days'])}
            for row in db.query_all(_FREQ_RANGE_SQL, (sid, ytd_inicio_str, ytd_fim_str, sid))
        ]

    else:
        chart_genero_dia = {'F': [0]*24, 'M': [0]*24}
        chart_genero_sem = {'F': [0]*24, 'M': [0]*24}
        chart_genero_mes = {'F': [0]*24, 'M': [0]*24}
        chart_genero_ytd = {'F': [0]*24, 'M': [0]*24}
        chart_ocorrencias_dia = {'novos': [0]*24, 'recorrentes': [0]*24}
        chart_ocorrencias_sem = {'novos': [0]*24, 'recorrentes': [0]*24}
        chart_ocorrencias_mes = {'novos': [0]*24, 'recorrentes': [0]*24}
        chart_ocorrencias_ytd = {'novos': [0]*24, 'recorrentes': [0]*24}
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
        chart_freq_retorno_dia = [None]*24
        chart_freq_retorno_sem = []
        chart_freq_retorno_mes = []
        chart_freq_retorno_ytd = []

    # ── Tema da empresa ──────────────────────────────────────────────────────
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

    # ── Metas ────────────────────────────────────────────────────────────────
    metas = _get_metas(
        selected_store_id,
        selected_date, semana_inicio, semana_fim,
        mes_inicio, mes_fim, ytd_inicio, ytd_fim,
    ) if selected_store_id else None

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
                SELECT store_id, store_name, store_short_name, cnpj
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
                SELECT store_id, store_name, store_short_name, cnpj
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
            SELECT DISTINCT s.store_id, s.store_name, s.store_short_name, s.cnpj
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
            SELECT s.store_id, s.store_name, s.store_short_name, s.cnpj
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
                'permanencia':       fmt_permanencia(r['permanencia_seg']),
                'img_url':           (HEIMDALL_IMAGE_BASE + r['image_path']) if r['image_path'] else None,
            })

    # ── Tema da empresa ───────────────────────────────────────────────────────
    theme = dict(primary_color='#F47B20', secondary_color='#0057A8', accent_color='#FFFFFF',
                 text_color='#111827', background_color='#F5F5F5')
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
            "SELECT primary_color, secondary_color, accent_color, text_color, background_color "
            "FROM faciais.company_themes WHERE company_id = %s",
            (theme_company_id,)
        )
        if row:
            theme.update({k: v for k, v in row.items() if v})

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


# ── Mapa de Calor ─────────────────────────────────────────────────────────────

@mobile_bp.route('/mapa-calor', methods=['GET', 'POST'])
@_login_required
def mapa_calor():
    import requests as _requests
    from routes.utils import (HEATMAP_API_URL, HEATMAP_API_BASE,
                               HEATMAP_API_USER, HEATMAP_API_PASS)

    user_id   = session['user_id']
    user_type = session['user_type_id']

    company_logo        = None
    company_name        = None
    companies           = []
    selected_company_id = None
    stores              = []
    # store_id pode vir de GET (seleção) ou POST (hidden field no form)
    selected_store_id = request.values.get('store_id', type=int)

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
                SELECT store_id, store_name, store_short_name
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
        selected_company_id = request.args.get('company_id', type=int)
        if selected_company_id:
            match = next((c for c in companies if c['company_id'] == selected_company_id), None)
            if match:
                company_logo = match['logo_url']
                company_name = match['company_name']
            stores = db.query_all("""
                SELECT store_id, store_name, store_short_name
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
            SELECT DISTINCT s.store_id, s.store_name, s.store_short_name
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
            SELECT s.store_id, s.store_name, s.store_short_name
            FROM   faciais.user_stores us
            JOIN   faciais.stores s ON s.store_id = us.store_id
            WHERE  us.user_id = %s ORDER BY s.store_name
        """, (user_id,))

    active_store = None
    if stores:
        if selected_store_id:
            active_store = next((s for s in stores if s['store_id'] == selected_store_id), None)
        if active_store is None and len(stores) == 1:
            active_store      = stores[0]
            selected_store_id = active_store['store_id']

    cameras = []
    if active_store:
        cameras = db.query_all("""
            SELECT camera_id, camera_name, heat_camera_id
            FROM   faciais.cameras
            WHERE  store_id = %s AND heat_camera_id IS NOT NULL
            ORDER  BY camera_name
        """, (active_store['store_id'],))

    today    = date_type.today().strftime('%Y-%m-%d')
    date_ini = today
    date_fim = today
    hora_ini = '08:00'
    hora_fim = '18:00'
    resultado = None
    erro      = None

    if request.method == 'POST' and active_store and cameras:
        date_ini = request.form.get('date_ini', today)
        date_fim = request.form.get('date_fim', today)
        hora_ini = request.form.get('hora_ini', '08:00')
        hora_fim = request.form.get('hora_fim', '18:00')
        heat_id  = request.form.get('heat_camera_id', type=int)
        if not heat_id and len(cameras) == 1:
            heat_id = cameras[0]['heat_camera_id']
        try:
            resp = _requests.post(
                HEATMAP_API_URL,
                json={
                    'camera_id': heat_id,
                    'data_ini':  f"{date_ini} {hora_ini}:00",
                    'data_fim':  f"{date_fim} {hora_fim}:00",
                },
                auth=(HEATMAP_API_USER, HEATMAP_API_PASS),
                timeout=30,
            )
            data = resp.json()
            if data.get('ok'):
                r = data['resultado']
                for key in ('planta_heatmap', 'frame_camera_areas'):
                    if r.get('imagens', {}).get(key):
                        r['imagens'][key]['full_url'] = (
                            '/retail_analytics/m/heatmap-imagem?path='
                            + r['imagens'][key]['url']
                        )
                total = sum(a['quantidade'] for a in r.get('resumo_por_area', []))
                for a in r.get('resumo_por_area', []):
                    a['pct'] = round(a['quantidade'] / total * 100, 1) if total else 0
                resultado = r
            else:
                erro = 'A API retornou erro.'
        except Exception as e:
            erro = f'Erro ao consultar API: {e}'

    theme = dict(primary_color='#F47B20', secondary_color='#0057A8', accent_color='#FFFFFF',
                 text_color='#111827', background_color='#F5F5F5')
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
            "SELECT primary_color, secondary_color, accent_color, text_color, background_color "
            "FROM   faciais.company_themes WHERE company_id = %s",
            (theme_company_id,)
        )
        if row:
            theme.update({k: v for k, v in row.items() if v})

    return render_template(
        'mobile/heatmap.html',
        cameras=cameras,
        resultado=resultado,
        erro=erro,
        active_store=active_store,
        stores=stores,
        companies=companies,
        company_logo=company_logo,
        company_name=company_name,
        selected_company_id=selected_company_id,
        selected_store_id=selected_store_id,
        date_ini=date_ini,
        date_fim=date_fim,
        hora_ini=hora_ini,
        hora_fim=hora_fim,
        theme=theme,
    )


# ── Gestão ────────────────────────────────────────────────────────────────────

def _gestao_mobile_ctx(endpoint):
    """Context loader compartilhado por todas as rotas mobile de gestão.
    Retorna (ctx_dict, redirect_ou_None).
    """
    user_id   = session['user_id']
    user_type = session['user_type_id']
    selected_company_id = request.args.get('company_id', type=int)
    selected_store_id   = request.args.get('store_id',   type=int)
    company_logo = None
    company_name = None
    companies    = []
    stores       = []

    # ── Restaurar última seleção ──────────────────────────────────────────────
    if not selected_store_id and 'company_id' not in request.args:
        saved = db.query_one(
            "SELECT last_store_id FROM faciais.users WHERE user_id = %s", (user_id,))
        if saved and saved['last_store_id']:
            last_sid = saved['last_store_id']
            if user_type in ('adm', 'man'):
                if user_type == 'adm':
                    row = db.query_one(
                        "SELECT company_id FROM faciais.stores WHERE store_id = %s", (last_sid,))
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
            WHERE  ct.logo_url IS NOT NULL ORDER BY c.company_name
        """)
        if selected_company_id:
            match = next((c for c in companies if c['company_id'] == selected_company_id), None)
            if match:
                company_logo = match['logo_url']
                company_name = match['company_name']
            stores = db.query_all("""
                SELECT store_id, store_name, store_short_name, cnpj
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
                SELECT store_id, store_name, store_short_name, cnpj
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
            SELECT DISTINCT s.store_id, s.store_name, s.store_short_name, s.cnpj
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
            SELECT s.store_id, s.store_name, s.store_short_name, s.cnpj
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
        company_logo=company_logo,
        company_name=company_name,
        companies=companies,
        stores=stores,
        selected_company_id=selected_company_id,
        selected_store_id=selected_store_id,
        active_store=active_store,
        active_store_cnpj=active_store_cnpj,
        active_microvix_portal=active_microvix_portal,
        theme=theme,
    ), None


@mobile_bp.route('/gestao/faturamento')
@_login_required
def gestao_faturamento():
    ctx, redir = _gestao_mobile_ctx('mobile.gestao_faturamento')
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
            ctx['active_microvix_portal'], ctx['active_store_cnpj'], ano)

    return render_template(
        'mobile/gestao_faturamento.html',
        **ctx,
        ano=ano,
        ano_atual=ano_atual,
        fat_mensal=fat_mensal,
    )


@mobile_bp.route('/gestao/vendas')
@_login_required
def gestao_vendas():
    ctx, redir = _gestao_mobile_ctx('mobile.gestao_vendas')
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
            ctx['active_microvix_portal'], ctx['active_store_cnpj'], ano)

    return render_template(
        'mobile/gestao_vendas.html',
        **ctx,
        ano=ano,
        ano_atual=ano_atual,
        vendas_data=vendas_data,
    )


# ── Motor ─────────────────────────────────────────────────────────────────────

@mobile_bp.route('/motor/faturamento')
@_login_required
def motor_faturamento():
    ctx, redir = _gestao_mobile_ctx('mobile.motor_faturamento')
    if redir:
        return redir

    hoje       = date_type.today()
    ano        = hoje.year
    mes        = hoje.month
    mes_inicio = date_type(ano, mes, 1)
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

    _nomes_mes = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
                  'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']

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
        'mobile/motor_faturamento.html',
        **ctx,
        mes_nome=_nomes_mes[mes - 1],
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


@mobile_bp.route('/motor/vendas')
@_login_required
def motor_vendas():
    ctx, redir = _gestao_mobile_ctx('mobile.motor_vendas')
    if redir:
        return redir

    ano_atual = date_type.today().year
    vendas_data = {'meses_nomes': [], 'series': []}
    if ctx['active_store'] and ctx['active_microvix_portal'] and ctx['active_store_cnpj']:
        vendas_data = _vendas_mensal_por_vendedor(
            ctx['active_microvix_portal'], ctx['active_store_cnpj'], ano_atual)

    return render_template(
        'mobile/motor_vendas.html',
        **ctx,
        ano=ano_atual,
        vendas_data=vendas_data,
    )


# ── Proxy de imagens do servidor de heatmap ───────────────────────────────────

@mobile_bp.route('/heatmap-imagem')
@_login_required
def heatmap_imagem():
    import requests as _requests
    from flask import Response
    from routes.utils import HEATMAP_API_BASE, HEATMAP_API_USER, HEATMAP_API_PASS

    path = request.args.get('path', '')
    allowed = ('/static/heatmaps/', '/static/cameras/')
    if not any(path.startswith(p) for p in allowed):
        from flask import abort
        abort(400)

    try:
        resp = _requests.get(
            HEATMAP_API_BASE + path,
            auth=(HEATMAP_API_USER, HEATMAP_API_PASS),
            timeout=20,
        )
        if resp.status_code != 200:
            from flask import abort
            abort(resp.status_code)
        content_type = resp.headers.get('Content-Type', 'image/png')
        return Response(resp.content, content_type=content_type)
    except Exception:
        from flask import abort
        abort(502)
