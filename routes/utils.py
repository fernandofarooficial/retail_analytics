import math
from functools import wraps
from flask import session, redirect, url_for, abort
import db

HEIMDALL_IMAGE_BASE = 'http://187.17.228.160:6500/api/facial/images'


def fmt_permanencia(segundos):
    if segundos is None or segundos <= 0:
        return None
    m = int(segundos) // 60
    if m < 1:
        return '< 1 min'
    if m < 60:
        return f'{m} min'
    h = m // 60
    return f'{h}h {m % 60:02d}min'


def kpi_tempo_loja(sid, data_str):
    """Permanência média em segundos para um único dia."""
    r = db.query_one("""
        SELECT ROUND(AVG(perm)::numeric) AS avg_seg
        FROM (
            SELECT EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS perm
            FROM   faciais.detection_records dr
            JOIN   faciais.people p ON p.person_id = dr.person_id
            WHERE  dr.store_id = %s AND p.person_type_id = 'C'
              AND  dr.person_id IS NOT NULL AND DATE(dr.created_at) = %s
            GROUP  BY dr.person_id
            HAVING MAX(dr.created_at) > MIN(dr.created_at)
        ) sub
    """, (sid, data_str))
    return int(r['avg_seg']) if r and r['avg_seg'] else None


def kpi_tempo_loja_range(sid, inicio_str, fim_str):
    """Permanência média em segundos para um intervalo de datas."""
    r = db.query_one("""
        SELECT ROUND(AVG(perm)::numeric) AS avg_seg
        FROM (
            SELECT EXTRACT(EPOCH FROM MAX(dr.created_at) - MIN(dr.created_at))::int AS perm
            FROM   faciais.detection_records dr
            JOIN   faciais.people p ON p.person_id = dr.person_id
            WHERE  dr.store_id = %s AND p.person_type_id = 'C'
              AND  dr.person_id IS NOT NULL
              AND  DATE(dr.created_at) BETWEEN %s AND %s
            GROUP  BY dr.person_id, DATE(dr.created_at)
            HAVING MAX(dr.created_at) > MIN(dr.created_at)
        ) sub
    """, (sid, inicio_str, fim_str))
    return int(r['avg_seg']) if r and r['avg_seg'] else None


def tempo_gauge(segundos, max_seg=1800):
    """Coordenadas SVG (x, y) da agulha do gauge de tempo na loja."""
    if not segundos:
        return None
    pct = min(segundos / max_seg, 1.0)
    angle_rad = math.radians(180 - pct * 180)
    return {
        'x': round(50 + 36 * math.cos(angle_rad), 1),
        'y': round(58 - 36 * math.sin(angle_rad), 1),
    }


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
