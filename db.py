import os
import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor

_pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=2,
    maxconn=10,
    dsn=os.environ['PG_DSN'],
)


def get_connection():
    return _pool.getconn()


def query_one(sql, params=None):
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            result = cur.fetchone()
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def query_all(sql, params=None):
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            result = cur.fetchall()
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def execute(sql, params=None):
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
