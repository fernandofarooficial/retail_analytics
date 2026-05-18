-- Performance indexes — retail_analytics
-- Rodar um por vez no banco; CONCURRENTLY não trava a tabela mas não pode ser executado dentro de transaction block.
-- Comando: psql $PG_DSN -f migrations/indexes_performance.sql

-- ============================================================
-- faciais.detection_records
-- Tabela mais consultada: filtros por store_id + created_at
-- ============================================================

-- Usado em: contagem de visitantes, gênero por hora, novos vs. recorrentes, frequência de retorno
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dr_store_created
    ON faciais.detection_records (store_id, created_at);

-- Cobre subqueries que agrupam por person_id dentro do range de data
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dr_store_created_person
    ON faciais.detection_records (store_id, created_at, person_id);

-- ============================================================
-- faciais.people
-- Join frequente com detection_records filtrando person_type_id
-- ============================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_people_type
    ON faciais.people (person_type_id);

-- ============================================================
-- faciais.person_purchases
-- Usado em queries de ticket por tipo de cliente
-- ============================================================

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pp_store_person
    ON faciais.person_purchases (store_id, person_id);

-- ============================================================
-- microvix.microvix_movimento
-- Queries de faturamento, top produtos, combinação de produtos
-- ============================================================

-- Filtro base: portal + cnpj_emp + data + flags de cancelamento
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mv_portal_cnpj_data
    ON microvix.microvix_movimento (portal, cnpj_emp, data_documento);

-- Cobre também as queries que filtram por documento (self-join de combinação de produtos)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mv_portal_cnpj_doc
    ON microvix.microvix_movimento (portal, cnpj_emp, documento);
