-- Adiciona telefone e e-mail de contato a faciais.people.
-- Tabela compartilhada com o camera300 (sincroniza o schema faciais) — ALTER
-- aditivo, não quebra nada que já está rodando. Rodar manualmente:
--   psql $PG_DSN -f migrations/add_people_contato.sql

ALTER TABLE faciais.people
    ADD COLUMN IF NOT EXISTS phone varchar(20),
    ADD COLUMN IF NOT EXISTS email varchar(255);

COMMENT ON COLUMN faciais.people.phone IS 'Telefone de contato da pessoa';
COMMENT ON COLUMN faciais.people.email IS 'E-mail de contato da pessoa';
