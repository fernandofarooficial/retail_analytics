-- Vínculo manual de nota fiscal (número + série) a cliente, digitado na tela
-- Clientes logo após a emissão da nota. Cobre o intervalo entre a emissão e a
-- sincronização do camera300 com o Microvix, quando a nota ainda não existe em
-- microvix_movimento e por isso não dá pra validar na hora.
-- Rodar manualmente: psql $PG_DSN -f migrations/add_manual_purchase_links.sql

CREATE TABLE IF NOT EXISTS faciais.manual_purchase_links (
    link_id      serial PRIMARY KEY,
    person_id    integer NOT NULL REFERENCES faciais.people (person_id) ON DELETE CASCADE,
    store_id     integer NOT NULL REFERENCES faciais.stores (store_id) ON DELETE CASCADE,
    numero_nota  integer NOT NULL,
    serie        varchar(20) NOT NULL,
    status       varchar(20) NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'confirmed', 'not_found')),
    entered_by   integer REFERENCES faciais.users (user_id) ON DELETE SET NULL,
    entered_at   timestamp NOT NULL DEFAULT now(),
    updated_at   timestamp NOT NULL DEFAULT now(),
    resolved_at  timestamp,
    CONSTRAINT uq_manual_purchase_links_nota UNIQUE (store_id, serie, numero_nota)
);

CREATE INDEX IF NOT EXISTS idx_manual_purchase_links_person ON faciais.manual_purchase_links (person_id);
CREATE INDEX IF NOT EXISTS idx_manual_purchase_links_status ON faciais.manual_purchase_links (status, entered_at);
CREATE INDEX IF NOT EXISTS idx_manual_purchase_links_store   ON faciais.manual_purchase_links (store_id, entered_at DESC);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_manual_purchase_links_updated_at'
    ) THEN
        PERFORM faciais.create_updated_at_trigger('manual_purchase_links');
    END IF;
END $$;

COMMENT ON TABLE faciais.manual_purchase_links IS
    'Vínculo manual de nota fiscal (numero_nota+serie) a pessoa, digitado na tela Clientes. Staging até a nota aparecer em microvix_movimento: quando confirma, grava/corrige faciais.person_purchases diretamente (o vínculo manual sempre prevalece sobre o que o camera300 já tiver gravado). Ver CLAUDE.md.';
COMMENT ON COLUMN faciais.manual_purchase_links.status IS
    'pending: aguardando a nota sincronizar; confirmed: localizada, person_purchases já atualizado (correção permanente, sem undo); not_found: expirou (3 dias) sem localizar — provável erro de digitação.';
