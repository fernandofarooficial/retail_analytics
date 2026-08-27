#!/usr/bin/env python3
"""
Resolução + expiração dos vínculos manuais de nota fiscal (tela Clientes).
Complementa a resolução preguiçosa que roda a cada carregamento da tela
Clientes (só cobre as lojas em vista) — este job varre TODA loja com vínculo
'pending', pra cobrir quem não abriu a tela recentemente, e expira (marca
'not_found') os pendentes há mais de 3 dias.
Agendado via cron do VPS: 50 23 * * * ... (logo depois do recálculo de ranking)
"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / '.env')

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(project_root / 'logs' / 'notas_manuais_job.log'),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def main():
    import people

    log.info('Resolvendo vínculos manuais de nota fiscal pendentes...')
    try:
        people.manual_purchase_links_resolver_todas()
        log.info('Concluído.')
    except Exception:
        log.exception('Erro ao resolver vínculos manuais de nota fiscal')
        sys.exit(1)


if __name__ == '__main__':
    main()
