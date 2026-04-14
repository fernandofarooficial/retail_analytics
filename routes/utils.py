from functools import wraps
from flask import session, redirect, url_for, abort
import db


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def screen_required(screen_id):
    """Decorator que verifica acesso à tela via vw_user_screen_access."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            row = db.query_one(
                "SELECT 1 FROM faciais.vw_user_screen_access "
                "WHERE user_id = %s AND screen_id = %s",
                (session['user_id'], screen_id)
            )
            if not row:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def check_screen(screen_id):
    """Verificação inline de acesso à tela. Usar dentro de views com slug dinâmico."""
    row = db.query_one(
        "SELECT 1 FROM faciais.vw_user_screen_access "
        "WHERE user_id = %s AND screen_id = %s",
        (session['user_id'], screen_id)
    )
    if not row:
        abort(403)
