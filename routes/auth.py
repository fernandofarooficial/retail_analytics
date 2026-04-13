from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash
from routes.utils import login_required
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
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = db.query_one(
            "SELECT user_id, full_name, password_hash "
            "FROM faciais.users "
            "WHERE lower(email) = %s AND is_active = TRUE",
            (email,)
        )

        if user and check_password_hash(user['password_hash'], password):
            session['user_id']   = user['user_id']
            session['full_name'] = user['full_name']
            return redirect(url_for('auth.dashboard'))

        error = 'E-mail ou senha incorretos.'

    return render_template('auth/login.html', error=error)


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')
