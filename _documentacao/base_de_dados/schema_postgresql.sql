-- ============================================================
-- SCHEMA: faciais
-- Projeto: Retail Analytics BR
-- Banco: PostgreSQL
-- Versão: 1.1
-- ============================================================

-- ============================================================
-- CRIAÇÃO DO SCHEMA
-- ============================================================
CREATE SCHEMA IF NOT EXISTS faciais;

-- Define faciais como schema padrão da sessão
SET search_path TO faciais, public;


-- ============================================================
-- FUNÇÃO GENÉRICA: Atualização automática de updated_at
-- Reutilizada por todas as tabelas via trigger
-- ============================================================
CREATE OR REPLACE FUNCTION faciais.fn_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- MACRO: Cria trigger de updated_at para uma tabela
-- Uso: SELECT faciais.create_updated_at_trigger('nome_da_tabela');
-- ============================================================
CREATE OR REPLACE FUNCTION faciais.create_updated_at_trigger(p_table TEXT)
RETURNS VOID AS $$
BEGIN
    EXECUTE FORMAT(
        'CREATE TRIGGER trg_%s_updated_at
         BEFORE UPDATE ON faciais.%I
         FOR EACH ROW EXECUTE FUNCTION faciais.fn_set_updated_at()',
        p_table, p_table
    );
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- TABELA: Grupo de Empresas
-- ============================================================
CREATE TABLE faciais.company_groups (
    company_group_id    SERIAL PRIMARY KEY,
    company_group_name  VARCHAR(50) NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE  faciais.company_groups                    IS 'Grupos de empresas clientes';
COMMENT ON COLUMN faciais.company_groups.company_group_id   IS 'Identificador do grupo de empresas';
COMMENT ON COLUMN faciais.company_groups.company_group_name IS 'Nome do grupo de empresas';
COMMENT ON COLUMN faciais.company_groups.created_at         IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.company_groups.updated_at         IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('company_groups');


-- ============================================================
-- TABELA: Tipos de Empresa
-- ============================================================
CREATE TABLE faciais.company_types (
    company_type_id     SERIAL PRIMARY KEY,
    company_type_name   VARCHAR(50) NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE  faciais.company_types                   IS 'Tipos de empresa (ex: franquia, loja própria)';
COMMENT ON COLUMN faciais.company_types.company_type_id   IS 'Identificador do tipo de empresa';
COMMENT ON COLUMN faciais.company_types.company_type_name IS 'Descrição do tipo de empresa';
COMMENT ON COLUMN faciais.company_types.created_at        IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.company_types.updated_at        IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('company_types');


-- ============================================================
-- TABELA: Empresas
-- ============================================================
CREATE TABLE faciais.companies (
    company_id          SERIAL PRIMARY KEY,
    company_name        VARCHAR(50) NOT NULL,
    company_group_id    INT,
    company_type_id     INT,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_companies_group
        FOREIGN KEY (company_group_id)
        REFERENCES faciais.company_groups(company_group_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_companies_type
        FOREIGN KEY (company_type_id)
        REFERENCES faciais.company_types(company_type_id)
        ON DELETE SET NULL
);

COMMENT ON TABLE  faciais.companies                  IS 'Empresas clientes da plataforma';
COMMENT ON COLUMN faciais.companies.company_id       IS 'Identificador da empresa';
COMMENT ON COLUMN faciais.companies.company_name     IS 'Nome da empresa';
COMMENT ON COLUMN faciais.companies.company_group_id IS 'Identificador do grupo empresarial';
COMMENT ON COLUMN faciais.companies.company_type_id  IS 'Identificador do tipo da empresa';
COMMENT ON COLUMN faciais.companies.created_at       IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.companies.updated_at       IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('companies');


-- ============================================================
-- TABELA: Temas de Empresas
-- ============================================================
CREATE TABLE faciais.company_themes (
    company_theme_id    SERIAL PRIMARY KEY,
    company_id          INT NOT NULL,
    primary_color       CHAR(7) DEFAULT '#F47B20',
    secondary_color     CHAR(7) DEFAULT '#0057A8',
    accent_color        CHAR(7) DEFAULT '#FFFFFF',
    text_color          CHAR(7) DEFAULT '#000000',
    background_color    CHAR(7) DEFAULT '#F5F5F5',
    logo_url            VARCHAR(255),
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_themes_company
        FOREIGN KEY (company_id)
        REFERENCES faciais.companies(company_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_primary_color    CHECK (primary_color    ~ '^#[0-9A-Fa-f]{6}$'),
    CONSTRAINT chk_secondary_color  CHECK (secondary_color  ~ '^#[0-9A-Fa-f]{6}$'),
    CONSTRAINT chk_accent_color     CHECK (accent_color     ~ '^#[0-9A-Fa-f]{6}$'),
    CONSTRAINT chk_text_color       CHECK (text_color       ~ '^#[0-9A-Fa-f]{6}$'),
    CONSTRAINT chk_background_color CHECK (background_color ~ '^#[0-9A-Fa-f]{6}$')
);

COMMENT ON TABLE  faciais.company_themes                  IS 'Paleta de cores e identidade visual por empresa';
COMMENT ON COLUMN faciais.company_themes.company_theme_id IS 'Identificador do tema';
COMMENT ON COLUMN faciais.company_themes.company_id       IS 'Identificador da empresa';
COMMENT ON COLUMN faciais.company_themes.primary_color    IS 'Cor primária em HEX (#RRGGBB)';
COMMENT ON COLUMN faciais.company_themes.secondary_color  IS 'Cor secundária em HEX (#RRGGBB)';
COMMENT ON COLUMN faciais.company_themes.accent_color     IS 'Cor de destaque em HEX (#RRGGBB)';
COMMENT ON COLUMN faciais.company_themes.text_color       IS 'Cor do texto em HEX (#RRGGBB)';
COMMENT ON COLUMN faciais.company_themes.background_color IS 'Cor de fundo em HEX (#RRGGBB)';
COMMENT ON COLUMN faciais.company_themes.logo_url         IS 'URL do logotipo da empresa';
COMMENT ON COLUMN faciais.company_themes.created_at       IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.company_themes.updated_at       IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('company_themes');


-- ============================================================
-- TABELA: Grupos de Lojistas
-- ============================================================
CREATE TABLE faciais.retailer_groups (
    retailer_group_id    SERIAL PRIMARY KEY,
    retailer_group_name  VARCHAR(50) NOT NULL,
    created_at           TIMESTAMP DEFAULT NOW(),
    updated_at           TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE  faciais.retailer_groups                     IS 'Grupos de lojistas (mesmo dono ou grupo de pessoas)';
COMMENT ON COLUMN faciais.retailer_groups.retailer_group_id   IS 'Identificador do grupo de lojistas';
COMMENT ON COLUMN faciais.retailer_groups.retailer_group_name IS 'Nome do grupo de lojistas';
COMMENT ON COLUMN faciais.retailer_groups.created_at          IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.retailer_groups.updated_at          IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('retailer_groups');


-- ============================================================
-- TABELA: Lojas
-- ============================================================
CREATE TABLE faciais.stores (
    store_id            SERIAL PRIMARY KEY,
    company_id          INT,
    retailer_group_id   INT,
    store_name          VARCHAR(50) NOT NULL,
    cnpj                BIGINT,
    cep                 INT,
    address_number      VARCHAR(10),
    address_complement  VARCHAR(30),
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_stores_company
        FOREIGN KEY (company_id)
        REFERENCES faciais.companies(company_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_stores_retailer_group
        FOREIGN KEY (retailer_group_id)
        REFERENCES faciais.retailer_groups(retailer_group_id)
        ON DELETE SET NULL
);

COMMENT ON TABLE  faciais.stores                    IS 'Lojas cadastradas na plataforma';
COMMENT ON COLUMN faciais.stores.store_id           IS 'Identificador da loja';
COMMENT ON COLUMN faciais.stores.company_id         IS 'Identificador da empresa';
COMMENT ON COLUMN faciais.stores.retailer_group_id  IS 'Identificador do grupo de lojistas';
COMMENT ON COLUMN faciais.stores.store_name         IS 'Nome da loja';
COMMENT ON COLUMN faciais.stores.cnpj               IS 'CNPJ da loja';
COMMENT ON COLUMN faciais.stores.cep                IS 'CEP do endereço da loja';
COMMENT ON COLUMN faciais.stores.address_number     IS 'Número do endereço da loja';
COMMENT ON COLUMN faciais.stores.address_complement IS 'Complemento do endereço da loja';
COMMENT ON COLUMN faciais.stores.created_at         IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.stores.updated_at         IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('stores');


-- ============================================================
-- TABELA: Tipos de Câmera
-- ============================================================
CREATE TABLE faciais.camera_types (
    camera_type_id      CHAR(1) PRIMARY KEY,
    camera_type_name    VARCHAR(30) NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE  faciais.camera_types                  IS 'Tipos de câmera disponíveis';
COMMENT ON COLUMN faciais.camera_types.camera_type_id   IS 'Identificador do tipo de câmera';
COMMENT ON COLUMN faciais.camera_types.camera_type_name IS 'Descrição do tipo de câmera';
COMMENT ON COLUMN faciais.camera_types.created_at       IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.camera_types.updated_at       IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('camera_types');


-- ============================================================
-- TABELA: Câmeras
-- ============================================================
CREATE TABLE faciais.cameras (
    camera_id           SERIAL PRIMARY KEY,
    camera_type_id      CHAR(1),
    store_id            INT,
    camera_name         VARCHAR(30) NOT NULL,
    rtsp_url            VARCHAR(255),
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_cameras_type
        FOREIGN KEY (camera_type_id)
        REFERENCES faciais.camera_types(camera_type_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_cameras_store
        FOREIGN KEY (store_id)
        REFERENCES faciais.stores(store_id)
        ON DELETE SET NULL
);

COMMENT ON TABLE  faciais.cameras                IS 'Câmeras instaladas nas lojas';
COMMENT ON COLUMN faciais.cameras.camera_id      IS 'Identificador da câmera';
COMMENT ON COLUMN faciais.cameras.camera_type_id IS 'Identificador do tipo de câmera';
COMMENT ON COLUMN faciais.cameras.store_id       IS 'Identificador da loja onde a câmera está instalada';
COMMENT ON COLUMN faciais.cameras.camera_name    IS 'Nome da câmera';
COMMENT ON COLUMN faciais.cameras.rtsp_url       IS 'URL de streaming RTSP da câmera';
COMMENT ON COLUMN faciais.cameras.created_at     IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.cameras.updated_at     IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('cameras');


-- ============================================================
-- TABELA: Gêneros
-- ============================================================
CREATE TABLE faciais.genders (
    gender_id       CHAR(1) PRIMARY KEY,
    gender_name     VARCHAR(20) NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE  faciais.genders             IS 'Gêneros disponíveis para cadastro de pessoas';
COMMENT ON COLUMN faciais.genders.gender_id   IS 'Identificador do gênero';
COMMENT ON COLUMN faciais.genders.gender_name IS 'Descrição do gênero';
COMMENT ON COLUMN faciais.genders.created_at  IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.genders.updated_at  IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('genders');

INSERT INTO faciais.genders (gender_id, gender_name) VALUES
    ('M', 'Masculino'),
    ('F', 'Feminino'),
    ('O', 'Outro'),
    ('N', 'Não informado');


-- ============================================================
-- TABELA: Tipos de Pessoa
-- ============================================================
CREATE TABLE faciais.person_types (
    person_type_id      CHAR(1) PRIMARY KEY,
    person_type_name    VARCHAR(50) NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE  faciais.person_types                  IS 'Tipos de pessoa que circulam na loja';
COMMENT ON COLUMN faciais.person_types.person_type_id   IS 'Identificador do tipo de pessoa';
COMMENT ON COLUMN faciais.person_types.person_type_name IS 'Descrição do tipo de pessoa';
COMMENT ON COLUMN faciais.person_types.created_at       IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.person_types.updated_at       IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('person_types');

INSERT INTO faciais.person_types (person_type_id, person_type_name) VALUES
    ('C', 'Cliente'),
    ('A', 'Anônimo'),
    ('F', 'Franqueado'),
    ('E', 'Empregado'),
    ('K', 'Criança'),
    ('P', 'Prestador');


-- ============================================================
-- TABELA: Pessoas
-- ============================================================
CREATE TABLE faciais.people (
    person_id           SERIAL PRIMARY KEY,
    full_name           VARCHAR(255),
    nickname            VARCHAR(50),
    document            VARCHAR(14),
    crm_key             VARCHAR(50),
    birth_date          DATE,
    age                 INT,
    gender_id           CHAR(1),
    person_type_id      CHAR(1) NOT NULL DEFAULT 'A',
    reference_track_id  VARCHAR(100),
    notes               VARCHAR(255),
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_people_gender
        FOREIGN KEY (gender_id)
        REFERENCES faciais.genders(gender_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_people_person_type
        FOREIGN KEY (person_type_id)
        REFERENCES faciais.person_types(person_type_id)
        ON DELETE SET NULL
);

COMMENT ON TABLE  faciais.people                     IS 'Pessoas identificadas ou rastreadas nas lojas';
COMMENT ON COLUMN faciais.people.person_id           IS 'Identificador único da pessoa';
COMMENT ON COLUMN faciais.people.full_name           IS 'Nome completo da pessoa';
COMMENT ON COLUMN faciais.people.nickname            IS 'Apelido ou nome social';
COMMENT ON COLUMN faciais.people.document            IS 'Documento de identificação (CPF/CNPJ)';
COMMENT ON COLUMN faciais.people.crm_key             IS 'Chave de integração com CRM';
COMMENT ON COLUMN faciais.people.birth_date          IS 'Data de nascimento';
COMMENT ON COLUMN faciais.people.age                 IS 'Idade estimada da pessoa';
COMMENT ON COLUMN faciais.people.gender_id           IS 'Identificador do gênero';
COMMENT ON COLUMN faciais.people.person_type_id      IS 'Tipo de pessoa na loja';
COMMENT ON COLUMN faciais.people.reference_track_id  IS 'Identificador de rastreamento facial de referência';
COMMENT ON COLUMN faciais.people.notes               IS 'Observações gerais sobre a pessoa';
COMMENT ON COLUMN faciais.people.created_at          IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.people.updated_at          IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('people');


-- ============================================================
-- TABELA: Registros JSON (raw payload)
-- ============================================================
CREATE TABLE faciais.json_records (
    json_record_id  SERIAL PRIMARY KEY,
    payload         JSONB,
    created_at      TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE  faciais.json_records                IS 'Dados brutos recebidos pelas câmeras em formato JSON';
COMMENT ON COLUMN faciais.json_records.json_record_id IS 'Identificador do registro JSON';
COMMENT ON COLUMN faciais.json_records.payload        IS 'Payload bruto recebido';
COMMENT ON COLUMN faciais.json_records.created_at     IS 'Data de criação do registro';


-- ============================================================
-- TABELA: Registros de Detecção Facial
-- ============================================================
CREATE TABLE faciais.detection_records (
    detection_record_id SERIAL PRIMARY KEY,
    json_record_id      INT,
    track_id            VARCHAR(100),
    detection_score     FLOAT,
    recognition_score   FLOAT,
    image_path          VARCHAR(255),
    camera_id           INT,
    person_id           INT,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_detection_json
        FOREIGN KEY (json_record_id)
        REFERENCES faciais.json_records(json_record_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_detection_camera
        FOREIGN KEY (camera_id)
        REFERENCES faciais.cameras(camera_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_detection_person
        FOREIGN KEY (person_id)
        REFERENCES faciais.people(person_id)
        ON DELETE SET NULL,

    CONSTRAINT chk_detection_score   CHECK (detection_score   BETWEEN 0 AND 1),
    CONSTRAINT chk_recognition_score CHECK (recognition_score BETWEEN 0 AND 1)
);

COMMENT ON TABLE  faciais.detection_records                     IS 'Registros de detecção e reconhecimento facial';
COMMENT ON COLUMN faciais.detection_records.detection_record_id IS 'Identificador do registro de detecção';
COMMENT ON COLUMN faciais.detection_records.json_record_id      IS 'Identificador do registro JSON de origem';
COMMENT ON COLUMN faciais.detection_records.track_id            IS 'Identificador de rastreamento facial';
COMMENT ON COLUMN faciais.detection_records.detection_score     IS 'Score de detecção facial (0 a 1)';
COMMENT ON COLUMN faciais.detection_records.recognition_score   IS 'Score de reconhecimento facial (0 a 1)';
COMMENT ON COLUMN faciais.detection_records.image_path          IS 'Caminho da imagem capturada';
COMMENT ON COLUMN faciais.detection_records.camera_id           IS 'Identificador da câmera';
COMMENT ON COLUMN faciais.detection_records.person_id           IS 'Identificador da pessoa reconhecida';
COMMENT ON COLUMN faciais.detection_records.created_at          IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.detection_records.updated_at          IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('detection_records');


-- ============================================================
-- TABELA: Usuários
-- ============================================================
CREATE TABLE faciais.users (
    user_id         SERIAL PRIMARY KEY,
    full_name       VARCHAR(100) NOT NULL,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE  faciais.users               IS 'Usuários da plataforma';
COMMENT ON COLUMN faciais.users.user_id       IS 'Identificador do usuário';
COMMENT ON COLUMN faciais.users.full_name     IS 'Nome completo do usuário';
COMMENT ON COLUMN faciais.users.email         IS 'E-mail de acesso (único)';
COMMENT ON COLUMN faciais.users.password_hash IS 'Senha armazenada em hash (bcrypt)';
COMMENT ON COLUMN faciais.users.is_active     IS 'Indica se o usuário está ativo';
COMMENT ON COLUMN faciais.users.created_at    IS 'Data de criação do registro';
COMMENT ON COLUMN faciais.users.updated_at    IS 'Data da última atualização do registro';

SELECT faciais.create_updated_at_trigger('users');


-- ============================================================
-- TABELA: Acesso de Usuários por Loja (N:N)
-- ============================================================
CREATE TABLE faciais.user_stores (
    user_store_id   SERIAL PRIMARY KEY,
    user_id         INT NOT NULL,
    store_id        INT NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_user_stores_user
        FOREIGN KEY (user_id)
        REFERENCES faciais.users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_user_stores_store
        FOREIGN KEY (store_id)
        REFERENCES faciais.stores(store_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_user_store UNIQUE (user_id, store_id)
);

COMMENT ON TABLE  faciais.user_stores               IS 'Controle de acesso de usuários por loja';
COMMENT ON COLUMN faciais.user_stores.user_store_id IS 'Identificador do vínculo';
COMMENT ON COLUMN faciais.user_stores.user_id       IS 'Identificador do usuário';
COMMENT ON COLUMN faciais.user_stores.store_id      IS 'Identificador da loja';
COMMENT ON COLUMN faciais.user_stores.created_at    IS 'Data de criação do vínculo';


-- ============================================================
-- ÍNDICES
-- ============================================================

-- companies
CREATE INDEX idx_companies_group ON faciais.companies(company_group_id);
CREATE INDEX idx_companies_type  ON faciais.companies(company_type_id);

-- stores
CREATE INDEX idx_stores_company        ON faciais.stores(company_id);
CREATE INDEX idx_stores_retailer_group ON faciais.stores(retailer_group_id);
CREATE INDEX idx_stores_cnpj           ON faciais.stores(cnpj);

-- cameras
CREATE INDEX idx_cameras_store ON faciais.cameras(store_id);
CREATE INDEX idx_cameras_type  ON faciais.cameras(camera_type_id);

-- people
CREATE INDEX idx_people_gender   ON faciais.people(gender_id);
CREATE INDEX idx_people_type     ON faciais.people(person_type_id);
CREATE INDEX idx_people_document ON faciais.people(document);
CREATE INDEX idx_people_track    ON faciais.people(reference_track_id);

-- detection_records
CREATE INDEX idx_detection_camera  ON faciais.detection_records(camera_id);
CREATE INDEX idx_detection_person  ON faciais.detection_records(person_id);
CREATE INDEX idx_detection_track   ON faciais.detection_records(track_id);
CREATE INDEX idx_detection_json    ON faciais.detection_records(json_record_id);
CREATE INDEX idx_detection_created ON faciais.detection_records(created_at);

-- json_records
CREATE INDEX idx_json_records_payload ON faciais.json_records USING GIN(payload);

-- users
CREATE INDEX idx_users_email ON faciais.users(email);

-- user_stores
CREATE INDEX idx_user_stores_user  ON faciais.user_stores(user_id);
CREATE INDEX idx_user_stores_store ON faciais.user_stores(store_id);

-- ============================================================
-- FIM DO SCHEMA faciais
-- ============================================================
