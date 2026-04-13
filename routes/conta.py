from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from routes.utils import login_required
import db

conta_bp = Blueprint('conta', __name__, url_prefix='/retail_analytics/conta')


@conta_bp.route('/trocar-senha', methods=['GET', 'POST'])
@login_required
def trocar_senha():
    if request.method == 'POST':
        senha_atual = request.form.get('senha_atual', '')
        nova_senha  = request.form.get('nova_senha', '')
        confirmacao = request.form.get('confirmacao', '')

        user = db.query_one(
            "SELECT password_hash FROM faciais.users WHERE user_id = %s",
            (session['user_id'],)
        )

        if not check_password_hash(user['password_hash'], senha_atual):
            flash('Senha atual incorreta.', 'error')
        elif nova_senha != confirmacao:
            flash('As novas senhas não coincidem.', 'error')
        elif len(nova_senha) < 6:
            flash('A nova senha deve ter pelo menos 6 caracteres.', 'error')
        else:
            db.execute(
                "UPDATE faciais.users SET password_hash = %s WHERE user_id = %s",
                (generate_password_hash(nova_senha), session['user_id'])
            )
            flash('Senha alterada com sucesso!', 'success')

    return render_template('conta/trocar_senha.html')
