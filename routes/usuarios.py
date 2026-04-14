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

        except Exception as e:
            err = str(e).lower()
            if 'unique' in err and 'username' in err:
                flash('Já existe um usuário com esse username.', 'error')
            elif 'unique' in err and 'email' in err:
                flash('Já existe um usuário com esse e-mail.', 'error')
            else:
                flash(f'Erro: {e}', 'error')

        return redirect(url_for('usuarios.index'))

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
    return render_template('usuarios/index.html', usuarios=usuarios, tipos=tipos)
