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
              AND pp.is_cancelled IS NOT TRUE
              AND pp.store_id              = %s
              AND mm.portal                = %s
              AND mm.cnpj_emp              = %s
              AND mm.cod_natureza_operacao = '10030'
              AND mm.cancelado            <> 'S'
              AND mm.excluido             <> 'S'
              AND mm.soma_relatorio        = 'S'
              AND mm.tipo_transacao        = 'V'
              AND mm.soma_relatorio        = 'S'
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


def faturamento_mensal(portal, cnpj, ano):
    """Faturamento mensal por tipo de transação (V=Loja, P=Pedidos) para um dado ano."""
    rows = db.query_all("""
        SELECT
            EXTRACT(MONTH FROM data_documento)::int AS mes,
            SUM(CASE WHEN tipo_transacao = 'V' THEN valor_total ELSE 0 END) AS loja,
            SUM(CASE WHEN tipo_transacao = 'P' THEN valor_total ELSE 0 END) AS pedidos,
            SUM(valor_total)                                                 AS total
        FROM microvix.microvix_movimento
        WHERE portal                = %s
          AND cnpj_emp              = %s
          AND EXTRACT(YEAR FROM data_documento) = %s
          AND cancelado            <> 'S'
          AND excluido             <> 'S'
          AND soma_relatorio        = 'S'
          AND tipo_transacao       IN ('V', 'P')
          AND cod_natureza_operacao = '10030'
        GROUP BY mes
        ORDER BY mes
    """, (portal, cnpj, ano))
    base = {m: {'loja': 0.0, 'pedidos': 0.0, 'total': 0.0} for m in range(1, 13)}
    for row in rows:
        m = row['mes']
        base[m] = {
            'loja':    round(float(row['loja']    or 0), 2),
            'pedidos': round(float(row['pedidos'] or 0), 2),
            'total':   round(float(row['total']   or 0), 2),
        }
    return [{'mes': m, **base[m]} for m in range(1, 13)]


def vendas_mensal_por_vendedor(portal, cnpj, ano):
    """Faturamento mensal por vendedor (tipo_transacao='V') para um dado ano.
    Retorna dict com meses_nomes e series=[{nome, dados}]."""
    rows = db.query_all("""
        SELECT EXTRACT(MONTH FROM mm.data_documento)::int AS mes,
               COALESCE(NULLIF(TRIM(mv.nome_vendedor), ''), mm.cod_vendedor::text) AS vendedor,
               SUM(mm.valor_total) AS total
        FROM   microvix.microvix_movimento mm
        LEFT JOIN microvix.microvix_vendedores mv
               ON mv.portal = mm.portal AND mv.cod_vendedor = mm.cod_vendedor
        WHERE  mm.portal                = %s
          AND  mm.cnpj_emp              = %s
          AND  EXTRACT(YEAR FROM mm.data_documento) = %s
          AND  mm.cancelado            <> 'S'
          AND  mm.excluido             <> 'S'
          AND  mm.soma_relatorio        = 'S'
          AND  mm.tipo_transacao        = 'V'
          AND  mm.cod_natureza_operacao = '10030'
          AND  mm.cod_vendedor IS NOT NULL AND mm.cod_vendedor <> ''
        GROUP  BY mes, vendedor
        ORDER  BY mes, vendedor
    """, (portal, cnpj, ano))

    meses_set     = set()
    vendedores_set = set()
    grid          = {}
    for row in rows:
        m = row['mes']
        v = row['vendedor']
        t = round(float(row['total'] or 0), 2)
        meses_set.add(m)
        vendedores_set.add(v)
        grid[(m, v)] = t

    _nomes = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
              'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
    meses_sorted     = sorted(meses_set)
    meses_nomes      = [_nomes[m - 1] for m in meses_sorted]
    vendedores_sorted = sorted(vendedores_set)
    series = [
        {'nome': v, 'dados': [grid.get((m, v), 0.0) for m in meses_sorted]}
        for v in vendedores_sorted
    ]
    return {'meses_nomes': meses_nomes, 'series': series}


def top5_por_tipo(sid, portal, cnpj, data_inicio, data_fim):
    """Top 5 produtos por faturamento, separado em novo/recorrente, via faciais.person_purchases."""
    rows = db.query_all("""
        WITH bills AS (
            SELECT pp.bill,
                   EXISTS (
                       SELECT 1 FROM faciais.detection_records dr
                       WHERE  dr.person_id = pp.person_id AND dr.store_id = %s
                         AND  DATE(dr.created_at) < DATE(pp.created_at)
                   ) AS is_rec
            FROM   faciais.person_purchases pp
            WHERE  pp.store_id = %s
              AND  DATE(pp.created_at) BETWEEN %s AND %s
              AND  (pp.is_cancelled IS NOT TRUE)
        ),
        linhas AS (
            SELECT b.is_rec,
                   COALESCE(NULLIF(TRIM(mp.descricao_basica), ''), mp.nome) AS produto,
                   mm.valor_liquido
            FROM   bills b
            JOIN   microvix.microvix_movimento mm ON mm.documento = b.bill
            JOIN   microvix.microvix_produtos mp
                   ON mp.portal = mm.portal AND mp.cod_produto = mm.cod_produto
            WHERE  mm.portal = %s AND mm.cnpj_emp = %s
              AND  mm.cancelado <> 'S' AND mm.excluido <> 'S'
              AND  mm.soma_relatorio = 'S' AND mm.tipo_transacao = 'V'
              AND  mm.cod_natureza_operacao = '10030'
        ),
        totais AS (
            SELECT is_rec, produto, SUM(valor_liquido) AS total_fat
            FROM   linhas GROUP BY is_rec, produto
        ),
        fat_total AS (
            SELECT is_rec, SUM(total_fat) AS grand_total FROM totais GROUP BY is_rec
        ),
        ranked AS (
            SELECT t.is_rec, t.produto, t.total_fat, ft.grand_total,
                   ROW_NUMBER() OVER (PARTITION BY t.is_rec ORDER BY t.total_fat DESC) AS rn
            FROM   totais t JOIN fat_total ft ON ft.is_rec = t.is_rec
            WHERE  t.total_fat > 0
        )
        SELECT is_rec, produto, total_fat,
               ROUND(total_fat * 100.0 / NULLIF(grand_total, 0), 1) AS pct
        FROM   ranked WHERE rn <= 5
        ORDER  BY is_rec, rn
    """, (sid, sid, data_inicio, data_fim, portal, cnpj))
    result = {'novos': [], 'recorrentes': []}
    for row in rows:
        item = {'nome': row['produto'], 'total': round(float(row['total_fat'] or 0), 2), 'pct': float(row['pct'] or 0)}
        if row['is_rec']:
            result['recorrentes'].append(item)
        else:
            result['novos'].append(item)
    return result
