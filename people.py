import math
import db


def kpi_microvix(portal, cnpj, dia_i, dia_f):
    row = db.query_one("""
        SELECT COUNT(DISTINCT documento) AS vendas,
               SUM(valor_total)        AS faturamento,
               SUM(quantidade)           AS total_itens
        FROM   microvix.microvix_movimento
        WHERE  portal                = %s
          AND  cnpj_emp             = %s
          AND  data_documento >= %s::date AND data_documento < %s::date + INTERVAL '1 day'
          AND  cancelado           <> 'S'
          AND  excluido            <> 'S'
          AND  soma_relatorio       = 'S'
          AND  (tipo_transacao IN ('P','V') OR tipo_transacao IS NULL) AND codigo_cliente = 1
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
          AND dr.created_at >= %s::date AND dr.created_at < %s::date + INTERVAL '1 day'
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
          AND  data_documento >= %s::date AND data_documento < %s::date + INTERVAL '1 day'
          AND  cancelado           <> 'S'
          AND  excluido            <> 'S'
          AND  soma_relatorio       = 'S'
          AND  (tipo_transacao IN ('P','V') OR tipo_transacao IS NULL) AND codigo_cliente = 1
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
          AND dr.created_at >= %s::date AND dr.created_at < %s::date + INTERVAL '1 day'
          AND dr.created_at::date = vpc.first_record::date
    """, (loja, dia_i, dia_f))
    return row['total'] if row else 0


def qtd_novos_recorrentes(loja, dia_i, dia_f):
    row = db.query_one("""
        SELECT
            COUNT(DISTINCT CASE WHEN dr.created_at::date > vpc.first_record::date
                                THEN p.person_id END) AS recorrentes,
            COUNT(DISTINCT CASE WHEN dr.created_at::date = vpc.first_record::date
                                THEN p.person_id END) AS novos
        FROM faciais.detection_records dr
        JOIN faciais.people p ON dr.person_id = p.person_id
        JOIN faciais.vw_primeira_aparicao_clientes vpc ON p.person_id = vpc.person_id
        WHERE p.person_type_id = 'C'
          AND dr.store_id = %s
          AND dr.created_at >= %s::date AND dr.created_at < %s::date + INTERVAL '1 day'
    """, (loja, dia_i, dia_f))
    if row:
        return int(row['recorrentes'] or 0), int(row['novos'] or 0)
    return 0, 0


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
            WHERE mm.data_documento >= %s::date AND mm.data_documento < %s::date + INTERVAL '1 day'
              AND pp.is_cancelled IS NOT TRUE
              AND pp.store_id              = %s
              AND mm.portal                = %s
              AND mm.cnpj_emp              = %s
              AND mm.cod_natureza_operacao = '10030'
              AND mm.cancelado            <> 'S'
              AND mm.excluido             <> 'S'
              AND mm.soma_relatorio        = 'S'
              AND (mm.tipo_transacao IN ('P','V') OR mm.tipo_transacao IS NULL) AND mm.codigo_cliente = 1
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
            SUM(CASE WHEN (tipo_transacao IN ('P','V') OR tipo_transacao IS NULL) AND codigo_cliente = 1  THEN valor_total ELSE 0 END) AS loja,
            SUM(CASE WHEN (tipo_transacao IN ('P','V') OR tipo_transacao IS NULL) AND codigo_cliente != 1 THEN valor_total ELSE 0 END) AS pedidos,
            SUM(valor_total)                                                 AS total
        FROM microvix.microvix_movimento
        WHERE portal                = %s
          AND cnpj_emp              = %s
          AND EXTRACT(YEAR FROM data_documento) = %s
          AND cancelado            <> 'S'
          AND excluido             <> 'S'
          AND soma_relatorio        = 'S'
          AND (tipo_transacao IN ('P','V') OR tipo_transacao IS NULL)
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


def faturamento_diario_mes(portal, cnpj, ano, mes):
    """Faturamento total por dia para o mês/ano dado. Retorna dict {dia: total}."""
    rows = db.query_all("""
        SELECT EXTRACT(DAY FROM data_documento)::int AS dia,
               SUM(valor_total) AS total
        FROM   microvix.microvix_movimento
        WHERE  portal                = %s
          AND  cnpj_emp              = %s
          AND  EXTRACT(YEAR  FROM data_documento) = %s
          AND  EXTRACT(MONTH FROM data_documento) = %s
          AND  cancelado            <> 'S'
          AND  excluido             <> 'S'
          AND  soma_relatorio        = 'S'
          AND  (tipo_transacao IN ('P','V') OR tipo_transacao IS NULL)
          AND  cod_natureza_operacao = '10030'
        GROUP  BY dia
        ORDER  BY dia
    """, (portal, cnpj, ano, mes))
    return {row['dia']: round(float(row['total'] or 0), 2) for row in rows}


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
          AND  (mm.tipo_transacao IN ('P','V') OR mm.tipo_transacao IS NULL)
          AND  mm.cod_natureza_operacao = '10030'
          AND  mm.cod_vendedor IS NOT NULL
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
                         AND  dr.created_at < pp.created_at::date
                   ) AS is_rec
            FROM   faciais.person_purchases pp
            WHERE  pp.store_id = %s
              AND  pp.created_at >= %s::date AND pp.created_at < %s::date + INTERVAL '1 day'
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
              AND  mm.soma_relatorio = 'S' AND (mm.tipo_transacao IN ('P','V') OR mm.tipo_transacao IS NULL) AND mm.codigo_cliente = 1
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


def vendedores_mes(portal, cnpj, mes_ini_cur, mes_fim_cur, mes_ini_ant, mes_fim_ant):
    """Vendedores com total vendido no mês atual e anterior, ordenados por mês anterior DESC."""
    rows = db.query_all("""
        SELECT
            m.cod_vendedor::text                                                AS cod_vendedor,
            COALESCE(NULLIF(TRIM(mv.nome_vendedor), ''), m.cod_vendedor::text)  AS nome,
            ROUND(SUM(CASE WHEN m.data_documento >= %s::date
                                AND m.data_documento < %s::date + INTERVAL '1 day'
                           THEN m.valor_total ELSE 0 END)::numeric, 2)         AS total_mes,
            ROUND(SUM(CASE WHEN m.data_documento >= %s::date
                                AND m.data_documento < %s::date + INTERVAL '1 day'
                           THEN m.valor_total ELSE 0 END)::numeric, 2)         AS total_ant
        FROM   microvix.microvix_movimento m
        LEFT   JOIN microvix.microvix_vendedores mv
                    ON mv.portal = m.portal AND mv.cod_vendedor = m.cod_vendedor
        WHERE  m.portal    = %s
          AND  m.cnpj_emp  = %s
          AND  m.cancelado <> 'S' AND m.excluido <> 'S' AND m.soma_relatorio = 'S'
          AND  (m.tipo_transacao IN ('P','V') OR m.tipo_transacao IS NULL)
          AND  m.cod_natureza_operacao = '10030'
          AND  m.cod_vendedor IS NOT NULL
          AND  m.data_documento >= %s::date
          AND  m.data_documento <  %s::date + INTERVAL '1 day'
        GROUP  BY m.cod_vendedor, mv.nome_vendedor
        HAVING SUM(CASE WHEN m.data_documento >= %s::date
                             AND m.data_documento < %s::date + INTERVAL '1 day'
                        THEN m.valor_total ELSE 0 END) > 0
        ORDER  BY total_ant DESC
    """, (mes_ini_cur, mes_fim_cur, mes_ini_ant, mes_fim_ant,
          portal, cnpj,
          mes_ini_ant, mes_fim_cur,
          mes_ini_ant, mes_fim_ant))
    return [
        {
            'cod_vendedor': str(r['cod_vendedor']),
            'nome':         r['nome'],
            'total_mes':    float(r['total_mes'] or 0),
            'total_ant':    float(r['total_ant'] or 0),
        }
        for r in rows
    ]


def top5_clientes_vendedor(portal, cnpj, cod_vendedor, mes_ini_cur, mes_fim_cur, mes_ini_ant, mes_fim_ant):
    """Top 5 clientes por faturamento no mês anterior para um vendedor, com comparativo mês atual."""
    rows = db.query_all("""
        SELECT
            m.codigo_cliente,
            COALESCE(NULLIF(TRIM(cf.nome_cliente), ''), cf.razao_cliente,
                     m.codigo_cliente::text)                                    AS nome_cliente,
            ROUND(SUM(CASE WHEN m.data_documento >= %s::date
                                AND m.data_documento < %s::date + INTERVAL '1 day'
                           THEN m.valor_total ELSE 0 END)::numeric, 2)         AS total_ant,
            ROUND(SUM(CASE WHEN m.data_documento >= %s::date
                                AND m.data_documento < %s::date + INTERVAL '1 day'
                           THEN m.valor_total ELSE 0 END)::numeric, 2)         AS total_mes
        FROM   microvix.microvix_movimento m
        LEFT   JOIN microvix.microvix_clientes_fornecedores cf
                    ON cf.portal = m.portal AND cf.cod_cliente = m.codigo_cliente
        WHERE  m.portal               = %s
          AND  m.cnpj_emp             = %s
          AND  m.cod_vendedor::text   = %s
          AND  m.codigo_cliente      != 1
          AND  m.cancelado           <> 'S' AND m.excluido <> 'S' AND m.soma_relatorio = 'S'
          AND  (m.tipo_transacao IN ('P','V') OR m.tipo_transacao IS NULL)
          AND  m.cod_natureza_operacao = '10030'
          AND  m.data_documento >= %s::date
          AND  m.data_documento <  %s::date + INTERVAL '1 day'
        GROUP  BY m.codigo_cliente, cf.nome_cliente, cf.razao_cliente
        ORDER  BY total_ant DESC
        LIMIT  5
    """, (mes_ini_ant, mes_fim_ant, mes_ini_cur, mes_fim_cur,
          portal, cnpj, cod_vendedor,
          mes_ini_ant, mes_fim_cur))
    return [
        {
            'nome':      r['nome_cliente'] or f"Cliente {r['codigo_cliente']}",
            'total_ant': float(r['total_ant'] or 0),
            'total_mes': float(r['total_mes'] or 0),
        }
        for r in rows
    ]


def top5_produtos_vendedor(portal, cnpj, cod_vendedor, mes_ini_cur, mes_fim_cur, mes_ini_ant, mes_fim_ant):
    """Top 5 produtos por faturamento no mês anterior para um vendedor, com comparativo mês atual."""
    rows = db.query_all("""
        SELECT
            COALESCE(NULLIF(TRIM(mp.descricao_basica), ''), mp.nome)            AS produto,
            ROUND(SUM(CASE WHEN m.data_documento >= %s::date
                                AND m.data_documento < %s::date + INTERVAL '1 day'
                           THEN m.valor_total ELSE 0 END)::numeric, 2)         AS total_ant,
            ROUND(SUM(CASE WHEN m.data_documento >= %s::date
                                AND m.data_documento < %s::date + INTERVAL '1 day'
                           THEN m.valor_total ELSE 0 END)::numeric, 2)         AS total_mes
        FROM   microvix.microvix_movimento m
        JOIN   microvix.microvix_produtos mp
               ON mp.portal = m.portal AND mp.cod_produto = m.cod_produto
        WHERE  m.portal               = %s
          AND  m.cnpj_emp             = %s
          AND  m.cod_vendedor::text   = %s
          AND  m.codigo_cliente      != 1
          AND  m.cancelado           <> 'S' AND m.excluido <> 'S' AND m.soma_relatorio = 'S'
          AND  (m.tipo_transacao IN ('P','V') OR m.tipo_transacao IS NULL)
          AND  m.cod_natureza_operacao = '10030'
          AND  m.data_documento >= %s::date
          AND  m.data_documento <  %s::date + INTERVAL '1 day'
        GROUP  BY mp.descricao_basica, mp.nome
        ORDER  BY total_ant DESC
        LIMIT  5
    """, (mes_ini_ant, mes_fim_ant, mes_ini_cur, mes_fim_cur,
          portal, cnpj, cod_vendedor,
          mes_ini_ant, mes_fim_cur))
    return [
        {
            'nome':      r['produto'] or '(sem nome)',
            'total_ant': float(r['total_ant'] or 0),
            'total_mes': float(r['total_mes'] or 0),
        }
        for r in rows
    ]


# ── Estoque ───────────────────────────────────────────────────────────────────

_ESTOQUE_BASE_FILTER = (
    "m.cancelado <> 'S' AND m.excluido <> 'S' AND m.soma_relatorio = 'S' "
    "AND (m.tipo_transacao IN ('P','V') OR m.tipo_transacao IS NULL) "
    "AND m.cod_natureza_operacao = '10030'"
)


def estoque_maior_volume(portal, cnpj,
                         m3_ini, m3_fim, m2_ini, m2_fim,
                         m1_ini, m1_fim, m0_ini, m0_fim):
    """Top 5 produtos por volume médio (qtd) nos últimos 3 meses."""
    rows = db.query_all(f"""
        WITH sales AS (
            SELECT
                m.cod_produto,
                COALESCE(NULLIF(TRIM(p.descricao_basica), ''), p.nome) AS produto,
                SUM(CASE WHEN m.data_documento >= %s::date AND m.data_documento < %s::date + INTERVAL '1 day'
                         THEN m.quantidade ELSE 0 END)  AS qtd_m3,
                SUM(CASE WHEN m.data_documento >= %s::date AND m.data_documento < %s::date + INTERVAL '1 day'
                         THEN m.quantidade ELSE 0 END)  AS qtd_m2,
                SUM(CASE WHEN m.data_documento >= %s::date AND m.data_documento < %s::date + INTERVAL '1 day'
                         THEN m.quantidade ELSE 0 END)  AS qtd_m1,
                SUM(CASE WHEN m.data_documento >= %s::date AND m.data_documento < %s::date + INTERVAL '1 day'
                         THEN m.quantidade ELSE 0 END)  AS qtd_m0
            FROM   microvix.microvix_movimento m
            JOIN   microvix.microvix_produtos p ON p.portal = m.portal AND p.cod_produto = m.cod_produto
            WHERE  m.portal = %s AND m.cnpj_emp = %s AND {_ESTOQUE_BASE_FILTER}
              AND  m.data_documento >= %s::date
              AND  m.data_documento <  %s::date + INTERVAL '1 day'
            GROUP  BY m.cod_produto, p.descricao_basica, p.nome
        )
        SELECT *, ROUND(((qtd_m3 + qtd_m2 + qtd_m1) / 3.0)::numeric, 1) AS media
        FROM   sales
        WHERE  (qtd_m3 + qtd_m2 + qtd_m1) > 0
        ORDER  BY media DESC
        LIMIT  5
    """, (m3_ini, m3_fim, m2_ini, m2_fim, m1_ini, m1_fim, m0_ini, m0_fim,
          portal, cnpj, m3_ini, m0_fim))
    return [
        {
            'cod_produto': r['cod_produto'],
            'produto': r['produto'] or '(sem nome)',
            'qtd_m3':  float(r['qtd_m3'] or 0),
            'qtd_m2':  float(r['qtd_m2'] or 0),
            'qtd_m1':  float(r['qtd_m1'] or 0),
            'media':   float(r['media']  or 0),
            'qtd_m0':  float(r['qtd_m0'] or 0),
        }
        for r in rows
    ]


def estoque_maior_faturamento(portal, cnpj,
                               m3_ini, m3_fim, m2_ini, m2_fim,
                               m1_ini, m1_fim, m0_ini, m0_fim):
    """Top 5 produtos por faturamento médio (valor_liquido) nos últimos 3 meses."""
    rows = db.query_all(f"""
        WITH sales AS (
            SELECT
                m.cod_produto,
                COALESCE(NULLIF(TRIM(p.descricao_basica), ''), p.nome) AS produto,
                SUM(CASE WHEN m.data_documento >= %s::date AND m.data_documento < %s::date + INTERVAL '1 day'
                         THEN m.valor_liquido ELSE 0 END)  AS fat_m3,
                SUM(CASE WHEN m.data_documento >= %s::date AND m.data_documento < %s::date + INTERVAL '1 day'
                         THEN m.valor_liquido ELSE 0 END)  AS fat_m2,
                SUM(CASE WHEN m.data_documento >= %s::date AND m.data_documento < %s::date + INTERVAL '1 day'
                         THEN m.valor_liquido ELSE 0 END)  AS fat_m1,
                SUM(CASE WHEN m.data_documento >= %s::date AND m.data_documento < %s::date + INTERVAL '1 day'
                         THEN m.valor_liquido ELSE 0 END)  AS fat_m0
            FROM   microvix.microvix_movimento m
            JOIN   microvix.microvix_produtos p ON p.portal = m.portal AND p.cod_produto = m.cod_produto
            WHERE  m.portal = %s AND m.cnpj_emp = %s AND {_ESTOQUE_BASE_FILTER}
              AND  m.data_documento >= %s::date
              AND  m.data_documento <  %s::date + INTERVAL '1 day'
            GROUP  BY m.cod_produto, p.descricao_basica, p.nome
        )
        SELECT *, ROUND(((fat_m3 + fat_m2 + fat_m1) / 3.0)::numeric, 2) AS media
        FROM   sales
        WHERE  (fat_m3 + fat_m2 + fat_m1) > 0
        ORDER  BY media DESC
        LIMIT  5
    """, (m3_ini, m3_fim, m2_ini, m2_fim, m1_ini, m1_fim, m0_ini, m0_fim,
          portal, cnpj, m3_ini, m0_fim))
    return [
        {
            'cod_produto': r['cod_produto'],
            'produto': r['produto'] or '(sem nome)',
            'fat_m3':  float(r['fat_m3'] or 0),
            'fat_m2':  float(r['fat_m2'] or 0),
            'fat_m1':  float(r['fat_m1'] or 0),
            'media':   float(r['media']  or 0),
            'fat_m0':  float(r['fat_m0'] or 0),
        }
        for r in rows
    ]


def estoque_valor_parado(portal, cnpj, corte_str):
    """Top 5 produtos com maior valor parado (qtd_estoque * preco_venda),
    sem faturamento desde antes de corte_str (mês-4 ou anterior)."""
    rows = db.query_all(f"""
        WITH ultima_venda AS (
            SELECT m.cod_produto, MAX(m.data_documento) AS ultimo_fat
            FROM   microvix.microvix_movimento m
            WHERE  m.portal = %s AND m.cnpj_emp = %s AND {_ESTOQUE_BASE_FILTER}
            GROUP  BY m.cod_produto
        )
        SELECT
            uv.cod_produto,
            COALESCE(NULLIF(TRIM(p.descricao_basica), ''), p.nome)  AS produto,
            uv.ultimo_fat,
            d.quantidade                                            AS qtd_estoque,
            d.preco_venda                                           AS preco_unit,
            ROUND((d.quantidade * d.preco_venda)::numeric, 2)       AS valor_parado
        FROM   ultima_venda uv
        JOIN   microvix.microvix_produtos p
               ON p.portal = %s AND p.cod_produto = uv.cod_produto
        JOIN   microvix.microvix_produtos_detalhes d
               ON d.portal = %s AND d.cnpj_emp = %s AND d.cod_produto = uv.cod_produto
        WHERE  uv.ultimo_fat < %s::date
          AND  d.quantidade  > 0
          AND  d.preco_venda > 0
        ORDER  BY valor_parado DESC
        LIMIT  5
    """, (portal, cnpj, portal, portal, cnpj, corte_str))
    return [
        {
            'cod_produto':  r['cod_produto'],
            'produto':      r['produto'] or '(sem nome)',
            'ultimo_fat':   r['ultimo_fat'].strftime('%d/%m/%Y') if r['ultimo_fat'] else '—',
            'qtd_estoque':  float(r['qtd_estoque']  or 0),
            'preco_unit':   float(r['preco_unit']   or 0),
            'valor_parado': float(r['valor_parado'] or 0),
        }
        for r in rows
    ]


def cobertura_estoque(portal, cnpj):
    """Top 10 produtos com menor cobertura de estoque (dias),
    baseado nas vendas dos últimos 30 dias."""
    rows = db.query_all("""
        WITH vendas_30d AS (
            SELECT m.cod_produto,
                   SUM(m.quantidade) AS qtd_vendida
            FROM   microvix.microvix_movimento m
            WHERE  m.portal = %s AND m.cnpj_emp = %s
              AND  m.cancelado <> 'S' AND m.excluido <> 'S' AND m.soma_relatorio = 'S'
              AND  (m.tipo_transacao IN ('P','V') OR m.tipo_transacao IS NULL)
              AND  m.cod_natureza_operacao = '10030'
              AND  m.data_documento >= CURRENT_DATE - INTERVAL '30 days'
              AND  m.data_documento <  CURRENT_DATE + INTERVAL '1 day'
            GROUP  BY m.cod_produto
        )
        SELECT
            v.cod_produto,
            COALESCE(NULLIF(TRIM(p.descricao_basica), ''), p.nome)  AS produto,
            (v.qtd_vendida / 30.0)                                   AS media_diaria,
            COALESCE(d.quantidade, 0)                                AS qtd_estoque
        FROM   vendas_30d v
        JOIN   microvix.microvix_produtos p
               ON p.portal = %s AND p.cod_produto = v.cod_produto
        JOIN   microvix.microvix_produtos_detalhes d
               ON d.portal = %s AND d.cnpj_emp = %s AND d.cod_produto = v.cod_produto
        WHERE  v.qtd_vendida > 0
          AND  d.quantidade  > 0
        ORDER  BY d.quantidade ASC
        LIMIT  50
    """, (portal, cnpj, portal, portal, cnpj))

    result = []
    for r in rows:
        qtd = float(r['qtd_estoque'] or 0)
        med = float(r['media_diaria'] or 0)
        if qtd <= 0 or round(med, 1) < 0.5:
            continue
        if qtd <= 1:
            cob = 1
        else:
            formula = math.floor(qtd / med)
            cob = min(formula, math.floor(qtd))
        result.append({
            'cod_produto':    r['cod_produto'],
            'produto':        r['produto'] or '(sem nome)',
            'media_diaria':   round(med, 1),
            'qtd_estoque':    qtd,
            'cobertura_dias': cob,
        })

    result.sort(key=lambda x: x['cobertura_dias'])
    return result[:10]
