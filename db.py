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
            return cur.fetchone()
    finally:
        _pool.putconn(conn)


def query_all(sql, params=None):
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        _pool.putconn(conn)


def execute(sql, params=None):
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        _pool.putconn(conn)
