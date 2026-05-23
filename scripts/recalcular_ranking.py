#!/usr/bin/env python3
"""
Recálculo do ranking de clientes.
Agendado via cron do VPS: 45 23 * * * ...
"""
import os
import sys
import logging
from pathlib import Path

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

INSERT_SQL = """
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
    FROM faciais.vw_customer_ranking
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
                log.info('Atualizando mv_microvix_vendas...')
                cur.execute("REFRESH MATERIALIZED VIEW faciais.mv_microvix_vendas")
                log.info('Zerando customer_ranking...')
                cur.execute("TRUNCATE TABLE faciais.customer_ranking RESTART IDENTITY")
                log.info('Recalculando ranking...')
                cur.execute(INSERT_SQL)
            conn.commit()
        log.info('Ranking recalculado com sucesso')
    except Exception:
        log.exception('Erro ao recalcular o ranking')
        sys.exit(1)


if __name__ == '__main__':
    main()
