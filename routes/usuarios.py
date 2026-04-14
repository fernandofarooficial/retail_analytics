from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from routes.utils import login_required, screen_required
import db

usuarios_bp = Blueprint('usuarios', __name__, url_prefix='/retail_analytics/usuarios')


@usuarios_bp.route('/', methods=['GET', 'POST'])
@login_required
@screen_required('gestao_usuarios')
def index():
    if request.method == 'POST':
        action = request.form.get('_action')
        try:
            if action == 'criar':
                username     = request.form['username'].strip().lower()
                full_name    = request.form['full_name'].strip()
                email        = request.form.get('email', '').strip().lower() or None
                user_type_id = request.form['user_type_id']
                password     = request.form['password']

                if len(password) < 6:
                    flash('A senha deve ter pelo menos 6 caracteres.', 'error')
                    return redirect(url_for('usuarios.index'))

                db.execute(
                    """INSERT INTO faciais.users
                       (username, full_name, email, password_hash, user_type_id)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (username, full_name, email, generate_password_hash(password), user_type_id)
                )
                flash(f'Usuário "{username}" criado com sucesso.', 'success')

            elif action == 'editar':
                username     = request.form['username'].strip().lower()
                full_name    = request.form['full_name'].strip()
                email        = request.form.get('email', '').strip().lower() or None
                user_type_id = request.form['user_type_id']
                db.execute(
                    """UPDATE faciais.users
                       SET username=%s, full_name=%s, email=%s, user_type_id=%s
                       WHERE user_id=%s""",
                    (username, full_name, email, user_type_id, request.form['_id'])
                )
                flash('Usuário atualizado com sucesso.', 'success')

            elif action == 'redefinir_senha':
                password = request.form['password']
                if len(password) < 6:
                    flash('A senha deve ter pelo menos 6 caracteres.', 'error')
                    return redirect(url_for('usuarios.index'))
                db.execute(
                    "UPDATE faciais.users SET password_hash=%s WHERE user_id=%s",
                    (generate_password_hash(password), request.form['_id'])
                )
                flash('Senha redefinida com sucesso.', 'success')

            elif action == 'alternar_status':
                db.execute(
                    "UPDATE faciais.users SET is_active = NOT is_active WHERE user_id=%s",
                    (request.form['_id'],)
                )
                flash('Status do usuário alterado.', 'success')

            elif action == 'vincular':
                user_id      = request.form['_id']
                user_type_id = request.form['user_type_id']
                escopo_id    = request.form['escopo_id']

                if user_type_id == 'man':
                    db.execute(
                        "INSERT INTO faciais.user_company_groups (user_id, company_group_id) VALUES (%s,%s)",
                        (user_id, escopo_id)
                    )
                elif user_type_id == 'ret':
                    db.execute(
                        "INSERT INTO faciais.user_retailer_groups (user_id, retailer_group_id) VALUES (%s,%s)",
                        (user_id, escopo_id)
                    )
                elif user_type_id == 'emp':
                    db.execute(
                        "INSERT INTO faciais.user_stores (user_id, store_id) VALUES (%s,%s)",
                        (user_id, escopo_id)
                    )
                flash('Vínculo adicionado com sucesso.', 'success')

            elif action == 'desvincular':
                user_type_id = request.form['user_type_id']
                link_id      = request.form['link_id']

                if user_type_id == 'man':
                    db.execute(
                        "DELETE FROM faciais.user_company_groups WHERE user_company_group_id=%s",
                        (link_id,)
                    )
                elif user_type_id == 'ret':
                    db.execute(
                        "DELETE FROM faciais.user_retailer_groups WHERE user_retailer_group_id=%s",
                        (link_id,)
                    )
                elif user_type_id == 'emp':
                    db.execute(
                        "DELETE FROM faciais.user_stores WHERE user_store_id=%s",
                        (link_id,)
                    )
                flash('Vínculo removido.', 'success')

        except Exception as e:
            err = str(e).lower()
            if 'unique' in err and 'username' in err:
                flash('Já existe um usuário com esse username.', 'error')
            elif 'unique' in err and 'email' in err:
                flash('Já existe um usuário com esse e-mail.', 'error')
            elif 'unique' in err:
                flash('Este vínculo já existe.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        return redirect(url_for('usuarios.index'))

    # ── Dados para a página ───────────────────────────────────────────────────

    usuarios = db.query_all("""
        SELECT u.user_id, u.username, u.full_name, u.email,
               u.user_type_id, ut.user_type_name, u.is_active
        FROM   faciais.users u
        JOIN   faciais.user_types ut ON ut.user_type_id = u.user_type_id
        ORDER  BY u.full_name
    """)

    tipos = db.query_all(
        "SELECT user_type_id, user_type_name FROM faciais.user_types ORDER BY user_type_name"
    )

    # Escopos vinculados por usuário
    escopos = {}

    for row in db.query_all("""
        SELECT ucg.user_id, ucg.user_company_group_id AS link_id,
               cg.company_group_id AS escopo_id, cg.company_group_name AS escopo_nome
        FROM faciais.user_company_groups ucg
        JOIN faciais.company_groups cg ON cg.company_group_id = ucg.company_group_id
    """):
        uid = str(row['user_id'])
        escopos.setdefault(uid, {'company_groups': [], 'retailer_groups': [], 'stores': []})
        escopos[uid]['company_groups'].append({
            'link_id': row['link_id'],
            'escopo_id': row['escopo_id'],
            'escopo_nome': row['escopo_nome'],
        })

    for row in db.query_all("""
        SELECT urg.user_id, urg.user_retailer_group_id AS link_id,
               rg.retailer_group_id AS escopo_id, rg.retailer_group_name AS escopo_nome
        FROM faciais.user_retailer_groups urg
        JOIN faciais.retailer_groups rg ON rg.retailer_group_id = urg.retailer_group_id
    """):
        uid = str(row['user_id'])
        escopos.setdefault(uid, {'company_groups': [], 'retailer_groups': [], 'stores': []})
        escopos[uid]['retailer_groups'].append({
            'link_id': row['link_id'],
            'escopo_id': row['escopo_id'],
            'escopo_nome': row['escopo_nome'],
        })

    for row in db.query_all("""
        SELECT us.user_id, us.user_store_id AS link_id,
               s.store_id AS escopo_id, s.store_name AS escopo_nome
        FROM faciais.user_stores us
        JOIN faciais.stores s ON s.store_id = us.store_id
    """):
        uid = str(row['user_id'])
        escopos.setdefault(uid, {'company_groups': [], 'retailer_groups': [], 'stores': []})
        escopos[uid]['stores'].append({
            'link_id': row['link_id'],
            'escopo_id': row['escopo_id'],
            'escopo_nome': row['escopo_nome'],
        })

    # Opções disponíveis para vincular
    company_groups  = [{'id': r['company_group_id'],  'nome': r['company_group_name']}
                       for r in db.query_all("SELECT company_group_id, company_group_name FROM faciais.company_groups ORDER BY company_group_name")]
    retailer_groups = [{'id': r['retailer_group_id'], 'nome': r['retailer_group_name']}
                       for r in db.query_all("SELECT retailer_group_id, retailer_group_name FROM faciais.retailer_groups ORDER BY retailer_group_name")]
    stores          = [{'id': r['store_id'],          'nome': r['store_name']}
                       for r in db.query_all("SELECT store_id, store_name FROM faciais.stores ORDER BY store_name")]

    return render_template('usuarios/index.html',
                           usuarios=usuarios,
                           tipos=tipos,
                           escopos=escopos,
                           company_groups=company_groups,
                           retailer_groups=retailer_groups,
                           stores=stores)
