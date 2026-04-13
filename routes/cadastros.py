from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from routes.utils import login_required
import db

cadastros_bp = Blueprint('cadastros', __name__, url_prefix='/retail_analytics/cadastros')

# ── Tabelas simples: apenas id + nome ────────────────────────────────────────

SIMPLES = {
    'grupo-empresarial': {
        'titulo':      'Grupos Empresariais',
        'tabela':      'faciais.company_groups',
        'pk':          'company_group_id',
        'pk_tipo':     'serial',
        'campo_nome':  'company_group_name',
        'label_nome':  'Nome do Grupo',
    },
    'tipo-empresa': {
        'titulo':      'Tipos de Empresa',
        'tabela':      'faciais.company_types',
        'pk':          'company_type_id',
        'pk_tipo':     'serial',
        'campo_nome':  'company_type_name',
        'label_nome':  'Tipo de Empresa',
    },
    'lojistas': {
        'titulo':      'Grupos de Lojistas',
        'tabela':      'faciais.retailer_groups',
        'pk':          'retailer_group_id',
        'pk_tipo':     'serial',
        'campo_nome':  'retailer_group_name',
        'label_nome':  'Nome do Grupo',
    },
    'generos': {
        'titulo':      'Gêneros',
        'tabela':      'faciais.genders',
        'pk':          'gender_id',
        'pk_tipo':     'char1',
        'campo_nome':  'gender_name',
        'label_nome':  'Gênero',
    },
    'tipo-pessoa': {
        'titulo':      'Tipos de Pessoa',
        'tabela':      'faciais.person_types',
        'pk':          'person_type_id',
        'pk_tipo':     'char1',
        'campo_nome':  'person_type_name',
        'label_nome':  'Tipo de Pessoa',
    },
    'tipo-camera': {
        'titulo':      'Tipos de Câmera',
        'tabela':      'faciais.camera_types',
        'pk':          'camera_type_id',
        'pk_tipo':     'char1',
        'campo_nome':  'camera_type_name',
        'label_nome':  'Tipo de Câmera',
    },
}


@cadastros_bp.route('/')
@login_required
def index():
    return render_template('cadastros/index.html')


@cadastros_bp.route('/<slug>', methods=['GET', 'POST'])
@login_required
def simples(slug):
    if slug not in SIMPLES:
        abort(404)

    config = SIMPLES[slug]

    if request.method == 'POST':
        action = request.form.get('_action')
        tabela = config['tabela']
        pk     = config['pk']
        campo  = config['campo_nome']

        try:
            if action == 'criar':
                nome = request.form.get('nome', '').strip()
                if config['pk_tipo'] == 'char1':
                    id_val = request.form.get('id_val', '').strip().upper()
                    db.execute(
                        f"INSERT INTO {tabela} ({pk}, {campo}) VALUES (%s, %s)",
                        (id_val, nome)
                    )
                else:
                    db.execute(
                        f"INSERT INTO {tabela} ({campo}) VALUES (%s)",
                        (nome,)
                    )
                flash('Registro criado com sucesso.', 'success')

            elif action == 'editar':
                nome = request.form.get('nome', '').strip()
                db.execute(
                    f"UPDATE {tabela} SET {campo} = %s WHERE {pk} = %s",
                    (nome, request.form['_id'])
                )
                flash('Registro atualizado com sucesso.', 'success')

            elif action == 'excluir':
                db.execute(f"DELETE FROM {tabela} WHERE {pk} = %s", (request.form['_id'],))
                flash('Registro excluído com sucesso.', 'success')

        except Exception as e:
            err = str(e).lower()
            if 'unique' in err or 'duplicate' in err:
                flash('Já existe um registro com esse ID ou nome.', 'error')
            elif 'foreign key' in err or 'violates' in err:
                flash('Não é possível excluir: existem registros vinculados.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        return redirect(url_for('cadastros.simples', slug=slug))

    registros = db.query_all(
        f"SELECT * FROM {config['tabela']} ORDER BY {config['pk']}"
    )
    return render_template('cadastros/simples.html', config=config, registros=registros, slug=slug)


# ── Empresas ──────────────────────────────────────────────────────────────────

@cadastros_bp.route('/empresas', methods=['GET', 'POST'])
@login_required
def empresas():
    if request.method == 'POST':
        action = request.form.get('_action')
        try:
            if action == 'criar':
                db.execute(
                    "INSERT INTO faciais.companies (company_name, company_group_id, company_type_id) "
                    "VALUES (%s, %s, %s)",
                    (
                        request.form['nome'].strip(),
                        request.form.get('grupo') or None,
                        request.form.get('tipo') or None,
                    )
                )
                flash('Empresa criada com sucesso.', 'success')

            elif action == 'editar':
                db.execute(
                    "UPDATE faciais.companies "
                    "SET company_name=%s, company_group_id=%s, company_type_id=%s "
                    "WHERE company_id=%s",
                    (
                        request.form['nome'].strip(),
                        request.form.get('grupo') or None,
                        request.form.get('tipo') or None,
                        request.form['_id'],
                    )
                )
                flash('Empresa atualizada com sucesso.', 'success')

            elif action == 'excluir':
                db.execute(
                    "DELETE FROM faciais.companies WHERE company_id=%s",
                    (request.form['_id'],)
                )
                flash('Empresa excluída com sucesso.', 'success')

        except Exception as e:
            err = str(e).lower()
            if 'foreign key' in err or 'violates' in err:
                flash('Não é possível excluir: existem lojas ou temas vinculados.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        return redirect(url_for('cadastros.empresas'))

    registros = db.query_all("""
        SELECT c.*, cg.company_group_name, ct.company_type_name
        FROM   faciais.companies c
        LEFT JOIN faciais.company_groups cg ON c.company_group_id = cg.company_group_id
        LEFT JOIN faciais.company_types  ct ON c.company_type_id  = ct.company_type_id
        ORDER BY c.company_name
    """)
    grupos = db.query_all(
        "SELECT company_group_id, company_group_name FROM faciais.company_groups ORDER BY company_group_name"
    )
    tipos = db.query_all(
        "SELECT company_type_id, company_type_name FROM faciais.company_types ORDER BY company_type_name"
    )
    return render_template('cadastros/companies.html', registros=registros, grupos=grupos, tipos=tipos)


# ── Cores por Empresa (company_themes) ────────────────────────────────────────

@cadastros_bp.route('/temas', methods=['GET', 'POST'])
@login_required
def temas():
    if request.method == 'POST':
        action = request.form.get('_action')
        try:
            if action == 'criar':
                db.execute(
                    """INSERT INTO faciais.company_themes
                       (company_id, primary_color, secondary_color, accent_color,
                        text_color, background_color, logo_url)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        request.form['company_id'],
                        request.form.get('primary_color', '#F47B20'),
                        request.form.get('secondary_color', '#0057A8'),
                        request.form.get('accent_color', '#FFFFFF'),
                        request.form.get('text_color', '#000000'),
                        request.form.get('background_color', '#F5F5F5'),
                        request.form.get('logo_url', '').strip() or None,
                    )
                )
                flash('Tema criado com sucesso.', 'success')

            elif action == 'editar':
                db.execute(
                    """UPDATE faciais.company_themes SET
                       company_id=%s, primary_color=%s, secondary_color=%s, accent_color=%s,
                       text_color=%s, background_color=%s, logo_url=%s
                       WHERE company_theme_id=%s""",
                    (
                        request.form['company_id'],
                        request.form.get('primary_color', '#F47B20'),
                        request.form.get('secondary_color', '#0057A8'),
                        request.form.get('accent_color', '#FFFFFF'),
                        request.form.get('text_color', '#000000'),
                        request.form.get('background_color', '#F5F5F5'),
                        request.form.get('logo_url', '').strip() or None,
                        request.form['_id'],
                    )
                )
                flash('Tema atualizado com sucesso.', 'success')

            elif action == 'excluir':
                db.execute(
                    "DELETE FROM faciais.company_themes WHERE company_theme_id=%s",
                    (request.form['_id'],)
                )
                flash('Tema excluído com sucesso.', 'success')

        except Exception as e:
            flash(f'Erro: {e}', 'error')

        return redirect(url_for('cadastros.temas'))

    registros = db.query_all("""
        SELECT ct.*, c.company_name
        FROM   faciais.company_themes ct
        LEFT JOIN faciais.companies c ON ct.company_id = c.company_id
        ORDER BY c.company_name
    """)
    companies = db.query_all(
        "SELECT company_id, company_name FROM faciais.companies ORDER BY company_name"
    )
    return render_template('cadastros/company_themes.html', registros=registros, companies=companies)


# ── Lojas ─────────────────────────────────────────────────────────────────────

@cadastros_bp.route('/lojas', methods=['GET', 'POST'])
@login_required
def lojas():
    if request.method == 'POST':
        action = request.form.get('_action')
        try:
            if action == 'criar':
                db.execute(
                    """INSERT INTO faciais.stores
                       (company_id, retailer_group_id, store_name,
                        cnpj, cep, address_number, address_complement)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        request.form.get('company_id') or None,
                        request.form.get('retailer_group_id') or None,
                        request.form['store_name'].strip(),
                        request.form.get('cnpj') or None,
                        request.form.get('cep') or None,
                        request.form.get('address_number', '').strip() or None,
                        request.form.get('address_complement', '').strip() or None,
                    )
                )
                flash('Loja criada com sucesso.', 'success')

            elif action == 'editar':
                db.execute(
                    """UPDATE faciais.stores SET
                       company_id=%s, retailer_group_id=%s, store_name=%s,
                       cnpj=%s, cep=%s, address_number=%s, address_complement=%s
                       WHERE store_id=%s""",
                    (
                        request.form.get('company_id') or None,
                        request.form.get('retailer_group_id') or None,
                        request.form['store_name'].strip(),
                        request.form.get('cnpj') or None,
                        request.form.get('cep') or None,
                        request.form.get('address_number', '').strip() or None,
                        request.form.get('address_complement', '').strip() or None,
                        request.form['_id'],
                    )
                )
                flash('Loja atualizada com sucesso.', 'success')

            elif action == 'excluir':
                db.execute("DELETE FROM faciais.stores WHERE store_id=%s", (request.form['_id'],))
                flash('Loja excluída com sucesso.', 'success')

        except Exception as e:
            err = str(e).lower()
            if 'foreign key' in err or 'violates' in err:
                flash('Não é possível excluir: existem câmeras vinculadas.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        return redirect(url_for('cadastros.lojas'))

    registros = db.query_all("""
        SELECT s.*, c.company_name, rg.retailer_group_name
        FROM   faciais.stores s
        LEFT JOIN faciais.companies       c  ON s.company_id        = c.company_id
        LEFT JOIN faciais.retailer_groups rg ON s.retailer_group_id = rg.retailer_group_id
        ORDER BY s.store_name
    """)
    companies = db.query_all(
        "SELECT company_id, company_name FROM faciais.companies ORDER BY company_name"
    )
    lojistas = db.query_all(
        "SELECT retailer_group_id, retailer_group_name FROM faciais.retailer_groups ORDER BY retailer_group_name"
    )
    return render_template('cadastros/stores.html', registros=registros, companies=companies, lojistas=lojistas)


# ── Câmeras ───────────────────────────────────────────────────────────────────

@cadastros_bp.route('/cameras', methods=['GET', 'POST'])
@login_required
def cameras():
    if request.method == 'POST':
        action = request.form.get('_action')
        try:
            if action == 'criar':
                db.execute(
                    """INSERT INTO faciais.cameras (camera_type_id, store_id, camera_name, rtsp_url)
                       VALUES (%s,%s,%s,%s)""",
                    (
                        request.form.get('camera_type_id') or None,
                        request.form.get('store_id') or None,
                        request.form['camera_name'].strip(),
                        request.form.get('rtsp_url', '').strip() or None,
                    )
                )
                flash('Câmera criada com sucesso.', 'success')

            elif action == 'editar':
                db.execute(
                    """UPDATE faciais.cameras SET
                       camera_type_id=%s, store_id=%s, camera_name=%s, rtsp_url=%s
                       WHERE camera_id=%s""",
                    (
                        request.form.get('camera_type_id') or None,
                        request.form.get('store_id') or None,
                        request.form['camera_name'].strip(),
                        request.form.get('rtsp_url', '').strip() or None,
                        request.form['_id'],
                    )
                )
                flash('Câmera atualizada com sucesso.', 'success')

            elif action == 'excluir':
                db.execute("DELETE FROM faciais.cameras WHERE camera_id=%s", (request.form['_id'],))
                flash('Câmera excluída com sucesso.', 'success')

        except Exception as e:
            flash(f'Erro: {e}', 'error')

        return redirect(url_for('cadastros.cameras'))

    registros = db.query_all("""
        SELECT cam.*, ct.camera_type_name, s.store_name
        FROM   faciais.cameras cam
        LEFT JOIN faciais.camera_types ct ON cam.camera_type_id = ct.camera_type_id
        LEFT JOIN faciais.stores       s  ON cam.store_id       = s.store_id
        ORDER BY s.store_name, cam.camera_name
    """)
    tipos_cam = db.query_all(
        "SELECT camera_type_id, camera_type_name FROM faciais.camera_types ORDER BY camera_type_name"
    )
    stores = db.query_all(
        "SELECT store_id, store_name FROM faciais.stores ORDER BY store_name"
    )
    return render_template('cadastros/cameras.html', registros=registros, tipos_cam=tipos_cam, stores=stores)
