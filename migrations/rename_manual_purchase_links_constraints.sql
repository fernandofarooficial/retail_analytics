-- Padroniza os nomes de constraint de faciais.manual_purchase_links, que
-- saíram com nomes default do Postgres (a migration original usava REFERENCES
-- e CHECK inline, sem nomear as constraints) em vez de seguir a convenção do
-- resto do banco (pk_<tabela>, fk_<abrev>_<alvo>, chk_<tabela>_<campo>).
-- Operação só de catálogo (RENAME CONSTRAINT), sem reescrita de tabela.
-- Rodar manualmente: psql $PG_DSN -f migrations/rename_manual_purchase_links_constraints.sql

ALTER TABLE faciais.manual_purchase_links
    RENAME CONSTRAINT manual_purchase_links_pkey TO pk_manual_purchase_links;

ALTER TABLE faciais.manual_purchase_links
    RENAME CONSTRAINT manual_purchase_links_person_id_fkey TO fk_mpl_person;

ALTER TABLE faciais.manual_purchase_links
    RENAME CONSTRAINT manual_purchase_links_store_id_fkey TO fk_mpl_store;

ALTER TABLE faciais.manual_purchase_links
    RENAME CONSTRAINT manual_purchase_links_entered_by_fkey TO fk_mpl_entered_by;

ALTER TABLE faciais.manual_purchase_links
    RENAME CONSTRAINT manual_purchase_links_status_check TO chk_manual_purchase_links_status;
