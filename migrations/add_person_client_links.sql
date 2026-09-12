-- Vínculo de identidade entre uma pessoa reconhecida (faciais.people) e um cliente
-- cadastrado no Microvix (microvix.microvix_clientes_fornecedores, PF ou PJ). Hoje esse
-- vínculo só existe implicitamente, nota a nota, via person_purchases -> microvix_movimento
-- -> codigo_cliente; esta tabela guarda a identidade confirmada manualmente pelo usuário
-- na tela Clientes, independente de nota fiscal específica.
--
-- Regra de negócio (2026-09): uma pessoa pode ter no máximo 1 cliente PF vinculado (é ela
-- mesma) e N clientes PJ vinculados (empresas em cujo nome ela compra); um cliente PJ pode
-- ter vários faciais vinculados (vários funcionários da mesma empresa); um cliente PF só
-- pode estar vinculado a uma única pessoa. tipo_cliente é denormalizado (copiado de
-- microvix_clientes_fornecedores no momento do vínculo) pra permitir essas duas restrições
-- via índice único parcial, sem trigger — a classificação PF/PJ de um cliente cadastrado
-- não muda na prática.
--
-- Sem FK real pra microvix.microvix_clientes_fornecedores (schema microvix é só
-- sincronizado, sem FK cruzando schema — mesmo padrão de person_purchases/sellers).
-- Ausência de vínculo é o estado normal e permanente pra qualquer pessoa — não é staging,
-- não expira, não tem "pending" (diferente de manual_purchase_links).
--
-- Rodar manualmente: psql $PG_DSN -f migrations/add_person_client_links.sql

CREATE TABLE IF NOT EXISTS faciais.person_client_links (
    person_client_link_id serial PRIMARY KEY,
    person_id    integer NOT NULL REFERENCES faciais.people (person_id) ON DELETE CASCADE,
    portal       integer NOT NULL,
    cod_cliente  integer NOT NULL,
    tipo_cliente char(1) NOT NULL CHECK (tipo_cliente IN ('F', 'J')),
    entered_by   integer REFERENCES faciais.users (user_id) ON DELETE SET NULL,
    entered_at   timestamp NOT NULL DEFAULT now(),
    CONSTRAINT uq_person_client_links_vinculo UNIQUE (person_id, portal, cod_cliente)
);

CREATE INDEX IF NOT EXISTS idx_person_client_links_person ON faciais.person_client_links (person_id);
CREATE INDEX IF NOT EXISTS idx_person_client_links_cliente ON faciais.person_client_links (portal, cod_cliente);

-- No máximo 1 cliente PF por pessoa:
CREATE UNIQUE INDEX IF NOT EXISTS ux_person_client_links_pf_por_pessoa
    ON faciais.person_client_links (person_id) WHERE tipo_cliente = 'F';

-- Um cliente PF só pode estar vinculado a uma única pessoa:
CREATE UNIQUE INDEX IF NOT EXISTS ux_person_client_links_pf_unico
    ON faciais.person_client_links (portal, cod_cliente) WHERE tipo_cliente = 'F';

COMMENT ON TABLE faciais.person_client_links IS
    'Vínculo de identidade (não financeiro) entre uma pessoa reconhecida e um cliente cadastrado no Microvix (PF ou PJ), confirmado manualmente na tela Clientes. Uma pessoa pode ter no máximo 1 cliente PF vinculado e N clientes PJ; um cliente PF só pode estar vinculado a uma pessoa; um cliente PJ pode estar vinculado a várias pessoas. Ver CLAUDE.md.';
COMMENT ON COLUMN faciais.person_client_links.portal IS 'Portal Microvix do cliente (junto com cod_cliente, chave de microvix_clientes_fornecedores)';
COMMENT ON COLUMN faciais.person_client_links.cod_cliente IS 'Código do cliente no Microvix (junto com portal, chave de microvix_clientes_fornecedores)';
COMMENT ON COLUMN faciais.person_client_links.tipo_cliente IS 'F (física) ou J (jurídica), copiado de microvix_clientes_fornecedores.tipo_cliente no momento do vínculo — usado pra garantir a regra de PF único via índice';
