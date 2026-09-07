-- Usa as colunas novas faciais.person_purchases.serie/data (adicionadas pelo camera300,
-- 2026-09, com backfill de 98,1%) pra eliminar a ambiguidade de "documento sozinho nao
-- identifica a NF" tambem no ranking de clientes (vw_customer_ranking/mv_microvix_vendas).
-- As demais queries que fazem esse join (people.py: ticket_por_tipo, top5_por_tipo,
-- produtos_por_pessoa, ticket_medio_pessoas, compras_recentes_pessoa[_detalhe]) ja foram
-- ajustadas no codigo Python, sem precisar de migration.
--
-- mv_microvix_vendas passa a agregar tambem por serie (nao so cnpj_emp+documento+data),
-- e vw_customer_ranking passa a casar por (mv.serie = pp.serie) quando pp.serie for
-- conhecido, caindo pro comportamento antigo (so cnpj_emp+documento+data>=cutoff, sem
-- distinguir serie) nas linhas antigas de person_purchases sem serie/data (residual do
-- backfill, mesmo cuidado documentado no CLAUDE.md).
--
-- Rodar manualmente: psql $PG_DSN -f migrations/person_purchases_serie_data.sql
--
-- Depois de rodar, recalcular o ranking de clientes com o dado novo:
--   python scripts/recalcular_ranking.py
-- (ou esperar o cron diario 45 23 * * *).

DROP MATERIALIZED VIEW faciais.mv_microvix_vendas CASCADE;

CREATE MATERIALIZED VIEW faciais.mv_microvix_vendas AS
 SELECT mm.cnpj_emp, mm.documento, mm.serie, mm.data_documento::date AS data_documento, sum(mm.valor_total) AS total_nf
   FROM microvix.microvix_movimento mm
     JOIN faciais.stores s ON s.cnpj::character varying::text = mm.cnpj_emp
     LEFT JOIN microvix.microvix_clientes_fornecedores cf
       ON cf.portal = mm.portal AND cf.cod_cliente = mm.codigo_cliente
  WHERE mm.cod_natureza_operacao = '10030' AND mm.cancelado <> 'S' AND mm.excluido <> 'S' AND mm.soma_relatorio = 'S'
    AND (mm.tipo_transacao <> 'J' OR mm.tipo_transacao IS NULL)
    AND mm.documento IS NOT NULL
    AND (cf.tipo_cliente IS NULL OR cf.tipo_cliente = 'F')
  GROUP BY mm.cnpj_emp, mm.documento, mm.serie, (mm.data_documento::date);

CREATE INDEX idx_mv_vendas_cnpj_doc ON faciais.mv_microvix_vendas (cnpj_emp, documento);
CREATE INDEX idx_mv_vendas_data ON faciais.mv_microvix_vendas (data_documento);

-- Recria vw_customer_ranking (derrubada pelo CASCADE acima) com o join refinado por serie/data.
CREATE VIEW faciais.vw_customer_ranking AS
 WITH store_rule AS (
         SELECT s.store_id, s.store_name, s.cnpj::varchar AS cnpj,
            rr.ranking_rule_id, rr.analysis_period_days, rr.min_visits_required,
            rr.points_per_visit_with_purchase, rr.points_per_visit_no_purchase, rr.points_per_currency_unit,
            now() - ((rr.analysis_period_days || ' days')::interval) AS cutoff_date
           FROM faciais.stores s
             JOIN faciais.ranking_rules rr ON rr.ranking_rule_id = s.ranking_rule_id AND rr.is_active = true
          WHERE s.cnpj IS NOT NULL
        ), visits AS (
         SELECT dr.store_id, dr.person_id,
            count(DISTINCT date(dr.created_at)) AS total_visits,
            min(dr.created_at) AS first_visit_at, max(dr.created_at) AS last_visit_at
           FROM faciais.detection_records dr
             JOIN store_rule sr_1 ON sr_1.store_id = dr.store_id
             JOIN faciais.people p_1 ON p_1.person_id = dr.person_id
          WHERE dr.person_id IS NOT NULL AND dr.created_at >= sr_1.cutoff_date AND p_1.person_type_id = 'C'
          GROUP BY dr.store_id, dr.person_id
        ), purchases_value AS (
         SELECT pp.store_id, pp.person_id,
            count(DISTINCT mv.data_documento) AS total_purchases,
            COALESCE(sum(mv.total_nf), 0) AS total_spent
           FROM faciais.person_purchases pp
             JOIN faciais.stores s ON s.store_id = pp.store_id
             JOIN store_rule sr_1 ON sr_1.store_id = pp.store_id
             JOIN faciais.mv_microvix_vendas mv
               ON mv.cnpj_emp = s.cnpj::varchar AND mv.documento = pp.bill AND mv.data_documento >= sr_1.cutoff_date
              AND (pp.serie IS NULL OR mv.serie = pp.serie)
              AND (pp.data  IS NULL OR mv.data_documento = pp.data)
          WHERE pp.person_id IS NOT NULL AND pp.is_cancelled = false
          GROUP BY pp.store_id, pp.person_id
        ), scoring AS (
         SELECT v.store_id, v.person_id, sr_1.ranking_rule_id, sr_1.analysis_period_days, sr_1.min_visits_required,
            v.total_visits,
            COALESCE(pv.total_purchases, 0) AS visits_with_purchase,
            v.total_visits - COALESCE(pv.total_purchases, 0) AS visits_no_purchase,
            COALESCE(pv.total_spent, 0) AS total_spent,
            v.first_visit_at, v.last_visit_at,
            round(COALESCE(pv.total_purchases, 0) * sr_1.points_per_visit_with_purchase
                + (v.total_visits - COALESCE(pv.total_purchases, 0)) * sr_1.points_per_visit_no_purchase
                + COALESCE(pv.total_spent, 0) * sr_1.points_per_currency_unit, 2) AS score
           FROM visits v
             JOIN store_rule sr_1 ON sr_1.store_id = v.store_id
             LEFT JOIN purchases_value pv ON pv.store_id = v.store_id AND pv.person_id = v.person_id
          WHERE v.total_visits >= sr_1.min_visits_required
        )
 SELECT sc.store_id, sr.store_name, sc.ranking_rule_id, sc.analysis_period_days,
    rank() OVER (PARTITION BY sc.store_id ORDER BY sc.score DESC) AS ranking_position,
    sc.person_id, p.full_name, p.nickname, p.person_type_id,
    sc.total_visits, sc.visits_with_purchase, sc.visits_no_purchase,
    round(sc.total_spent, 2) AS total_spent, sc.score, sc.first_visit_at, sc.last_visit_at
   FROM scoring sc
     JOIN store_rule sr ON sr.store_id = sc.store_id
     JOIN faciais.people p ON p.person_id = sc.person_id;

REFRESH MATERIALIZED VIEW faciais.mv_microvix_vendas;
