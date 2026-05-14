import db


def kpi_microvix(portal, cnpj, dia_i, dia_f):
    row = db.query_one("""
        SELECT COUNT(DISTINCT documento) AS vendas,
               SUM(valor_total)        AS faturamento,
               SUM(quantidade)           AS total_itens
        FROM   microvix.microvix_movimento
        WHERE  portal                = %s
          AND  cnpj_emp             = %s
          AND  DATE(data_documento) BETWEEN %s AND %s
          AND  cancelado           <> 'S'
          AND  excluido            <> 'S'
          AND  soma_relatorio       = 'S'
          AND  tipo_transacao       = 'V'
          AND  cod_natureza_operacao = '10030'
    """, (portal, cnpj, dia_i, dia_f))
    if row and row['vendas']:
        v = int(row['vendas'])
        f = float(row['faturamento'] or 0)
        t = float(row['total_itens'] or 0)
        return {
            'vendas':       v,
            'faturamento':  round(f, 2),
            'ticket_medio': round(f / v, 2) if v else 0.0,
            'itens_venda':  round(t / v, 1) if v else 0.0,
        }
    return {'vendas': 0, 'faturamento': 0.0, 'ticket_medio': 0.0, 'itens_venda': 0.0}


def qtd_recorrentes(loja, dia_i, dia_f):
    row = db.query_one("""
        SELECT COUNT(DISTINCT p.person_id) AS total
        FROM faciais.detection_records dr
        JOIN faciais.people p ON dr.person_id = p.person_id
        JOIN faciais.vw_primeira_aparicao_clientes vpc ON p.person_id = vpc.person_id
        WHERE p.person_type_id = 'C'
          AND dr.store_id = %s
          AND dr.created_at::date BETWEEN %s AND %s
          AND dr.created_at::date > vpc.first_record::date
    """, (loja, dia_i, dia_f))
    return row['total'] if row else 0


def faixa_horaria(portal, cnpj, dia_i, dia_f):
    return db.query_all("""
        SELECT SPLIT_PART(hora_lancamento, ':', 1)::int AS hora,
               COUNT(DISTINCT documento)  AS vendas,
               SUM(valor_total)           AS faturamento
        FROM   microvix.microvix_movimento
        WHERE  portal   = %s AND cnpj_emp = %s
          AND  DATE(data_documento) BETWEEN %s AND %s
          AND  cancelado           <> 'S'
          AND  excluido            <> 'S'
          AND  soma_relatorio       = 'S'
          AND  tipo_transacao       = 'V'
          AND  cod_natureza_operacao = '10030'
          AND  hora_lancamento IS NOT NULL AND hora_lancamento <> ''
        GROUP  BY hora ORDER BY hora
    """, (portal, cnpj, dia_i, dia_f))


def qtd_novos(loja, dia_i, dia_f):
    row = db.query_one("""
        SELECT COUNT(DISTINCT p.person_id) AS total
        FROM faciais.detection_records dr
        JOIN faciais.people p ON dr.person_id = p.person_id
        JOIN faciais.vw_primeira_aparicao_clientes vpc ON p.person_id = vpc.person_id
        WHERE p.person_type_id = 'C'
          AND dr.store_id = %s
          AND dr.created_at::date BETWEEN %s AND %s
          AND dr.created_at::date = vpc.first_record::date
    """, (loja, dia_i, dia_f))
    return row['total'] if row else 0


def ticket_por_tipo(sid, portal, cnpj, data_inicio, data_fim):
    """Ticket médio por nota, separado em novo/recorrente, via faciais.person_purchases."""
    rows = db.query_all("""
        WITH base AS (
            SELECT
                pp.person_id,
                MIN(mm.data_documento)    AS data_nota_fiscal,
                COUNT(DISTINCT pp.bill)   AS notas,
                SUM(mm.valor_total)       AS total_valor,
                MIN(vpac.first_record)::DATE AS estreia
            FROM faciais.person_purchases pp
            JOIN microvix.microvix_movimento mm
                ON pp.bill = mm.documento
            LEFT JOIN faciais.vw_primeira_aparicao_clientes vpac
                ON pp.person_id = vpac.person_id
            WHERE mm.data_documento::date BETWEEN %s AND %s
              AND pp.store_id              = %s
              AND mm.portal                = %s
              AND mm.cnpj_emp              = %s
              AND mm.cod_natureza_operacao = '10030'
              AND mm.cancelado            <> 'S'
              AND mm.excluido             <> 'S'
              AND mm.soma_relatorio        = 'S'
              AND mm.tipo_transacao        = 'V'
            GROUP BY pp.person_id
        )
        SELECT
            (estreia IS NOT NULL AND estreia < data_nota_fiscal) AS is_rec,
            SUM(notas)       AS num_bills,
            SUM(total_valor) AS faturamento
        FROM base
        GROUP BY (estreia IS NOT NULL AND estreia < data_nota_fiscal)
    """, (data_inicio, data_fim, sid, portal, cnpj))
    result = {'ticket_novo': None, 'ticket_rec': None}
    for row in rows:
        n = int(row['num_bills'] or 0)
        f = float(row['faturamento'] or 0)
        ticket = round(f / n, 2) if n > 0 else 0.0
        if row['is_rec']:
            result['ticket_rec'] = ticket
        else:
            result['ticket_novo'] = ticket
    if rows:
        result.setdefault('ticket_novo', 0.0)
        result.setdefault('ticket_rec', 0.0)
        if result['ticket_novo'] is None:
            result['ticket_novo'] = 0.0
        if result['ticket_rec'] is None:
            result['ticket_rec'] = 0.0
    return result
