-- Flag de situação do cliente na tela Clientes/Visitação: keep (manter, padrão) ou
-- duplicate (marcado como duplicata de outro cadastro — só informativo, sem apontar
-- pra qual person_id, sem merge automático). "Excluir" não é um valor persistido:
-- é tratado como DELETE direto de faciais.people (ver routes/auth.py e routes/mobile.py,
-- visitacao_editar_pessoa) — a FK de detection_records/person_purchases é ON DELETE
-- SET NULL e a de manual_purchase_links é ON DELETE CASCADE, então a exclusão é segura.
-- Rodar manualmente: psql $PG_DSN -f migrations/add_people_review_status.sql

ALTER TABLE faciais.people
    ADD COLUMN IF NOT EXISTS review_status varchar(20) NOT NULL DEFAULT 'keep',
    ADD COLUMN IF NOT EXISTS reviewed_by integer REFERENCES faciais.users (user_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS reviewed_at timestamp;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_people_review_status'
    ) THEN
        ALTER TABLE faciais.people
            ADD CONSTRAINT chk_people_review_status CHECK (review_status IN ('keep', 'duplicate'));
    END IF;
END $$;

COMMENT ON COLUMN faciais.people.review_status IS
    'Situação de revisão do cadastro: keep=manter (padrão), duplicate=marcado como duplicata de outro cadastro (só informativo, sem apontar qual). "Excluir" não fica salvo aqui — apaga a linha direto.';
COMMENT ON COLUMN faciais.people.reviewed_by IS 'Usuário que definiu a situação de revisão pela última vez';
COMMENT ON COLUMN faciais.people.reviewed_at IS 'Data/hora da última definição de situação de revisão';
