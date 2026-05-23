#!/usr/bin/env python3
"""
Recálculo do ranking de clientes.
Agendado via cron do VPS: 45 23 * * * ...
"""
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# garante que o .env do projeto seja carregado
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(project_root / 'logs' / 'ranking_job.log'),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

SQL = """
BEGIN;

    TRUNCATE TABLE faciais.customer_ranking RESTART IDENTITY;

    INSERT INTO faciais.customer_ranking (
        store_id, store_name, ranking_rule_id, analysis_period_days,
        ranking_position, person_id, full_name, nickname, person_type_id,
        total_visits, visits_with_purchase, visits_no_purchase,
        total_spent, score, first_visit_at, last_visit_at, calculated_at
    )
    SELECT
        store_id, store_name, ranking_rule_id, analysis_period_days,
        ranking_position, person_id, full_name, nickname, person_type_id,
        total_visits, visits_with_purchase, visits_no_purchase,
        total_spent, score, first_visit_at, last_visit_at, NOW()
    FROM faciais.vw_customer_ranking;

COMMIT;
"""


def main():
    dsn = os.environ.get('PG_DSN')
    if not dsn:
        log.error('PG_DSN não definido no ambiente')
        sys.exit(1)

    log.info('Iniciando recálculo do ranking')
    try:
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(SQL)
            conn.commit()
        log.info('Ranking recalculado com sucesso')
    except Exception:
        log.exception('Erro ao recalcular o ranking')
        sys.exit(1)


if __name__ == '__main__':
    main()
