PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS fazenda (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    municipio TEXT NOT NULL,
    uf TEXT NOT NULL DEFAULT 'PR',
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    area_total_ha REAL NOT NULL CHECK (area_total_ha > 0)
);

CREATE TABLE IF NOT EXISTS bloco (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fazenda_id INTEGER NOT NULL,
    nome TEXT NOT NULL,
    area_ha REAL NOT NULL CHECK (area_ha > 0),
    UNIQUE (fazenda_id, nome),
    FOREIGN KEY (fazenda_id) REFERENCES fazenda (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS talhao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bloco_id INTEGER NOT NULL,
    codigo TEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    area_ha REAL NOT NULL CHECK (area_ha > 0),
    sistema_irrigacao TEXT NOT NULL CHECK (sistema_irrigacao IN ('PIVO', 'GOTEJO')),
    codigo_sistema TEXT NOT NULL UNIQUE,
    latitude_centro REAL NOT NULL,
    longitude_centro REAL NOT NULL,
    meta_pressao_alvo REAL NOT NULL CHECK (meta_pressao_alvo > 0),
    meta_vazao_projeto REAL NOT NULL CHECK (meta_vazao_projeto > 0),
    outorga_limite_m3_dia REAL NOT NULL CHECK (outorga_limite_m3_dia > 0),
    FOREIGN KEY (bloco_id) REFERENCES bloco (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sensores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talhao_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('PH', 'TURBIDEZ', 'PRESSAO', 'VAZAO')),
    unidade TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    UNIQUE (talhao_id, tipo),
    FOREIGN KEY (talhao_id) REFERENCES talhao (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS leituras_sensores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id INTEGER NOT NULL,
    data_hora TEXT NOT NULL,
    valor REAL NOT NULL,
    FOREIGN KEY (sensor_id) REFERENCES sensores (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS atividades_irrigacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talhao_id INTEGER NOT NULL,
    data TEXT NOT NULL,
    horas_irrigadas REAL NOT NULL CHECK (horas_irrigadas >= 0),
    horas_paradas REAL NOT NULL CHECK (horas_paradas >= 0),
    lamina_mm REAL NOT NULL CHECK (lamina_mm >= 0),
    volume_captado_m3 REAL,
    volume_aplicado_m3 REAL,
    energia_kwh REAL NOT NULL CHECK (energia_kwh >= 0),
    teve_problema INTEGER NOT NULL DEFAULT 0 CHECK (teve_problema IN (0, 1)),
    tipo_problema TEXT CHECK (tipo_problema IN ('VAZAMENTO', 'PRESSAO_BAIXA', 'BOMBA', 'ELETRICO', 'OUTRO')),
    tempo_manutencao_h REAL,
    observacoes TEXT,
    UNIQUE (talhao_id, data),
    CHECK (horas_irrigadas + horas_paradas <= 24.0001),
    CHECK (teve_problema = 0 OR (tipo_problema IS NOT NULL AND tempo_manutencao_h IS NOT NULL)),
    FOREIGN KEY (talhao_id) REFERENCES talhao (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS manutencoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talhao_id INTEGER NOT NULL,
    data_inicio TEXT NOT NULL,
    data_fim TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('PREVENTIVA', 'CORRETIVA')),
    descricao TEXT NOT NULL,
    duracao_h REAL,
    custo_manutencao_rs REAL NOT NULL DEFAULT 0 CHECK (custo_manutencao_rs >= 0),
    FOREIGN KEY (talhao_id) REFERENCES talhao (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS custos_parametros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fazenda_id INTEGER,
    custo_agua_rs_m3 REAL NOT NULL CHECK (custo_agua_rs_m3 >= 0),
    custo_energia_rs_kwh REAL NOT NULL CHECK (custo_energia_rs_kwh >= 0),
    outros_fixos_rs_mes REAL NOT NULL DEFAULT 0 CHECK (outros_fixos_rs_mes >= 0),
    UNIQUE (fazenda_id),
    FOREIGN KEY (fazenda_id) REFERENCES fazenda (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS clima_diario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fazenda_id INTEGER NOT NULL,
    data TEXT NOT NULL,
    precipitacao_mm REAL NOT NULL DEFAULT 0,
    temp_min_c REAL,
    temp_max_c REAL,
    vento_max_ms REAL,
    eto_mm_dia REAL,
    etc_mm_dia REAL,
    fonte TEXT,
    UNIQUE (fazenda_id, data),
    FOREIGN KEY (fazenda_id) REFERENCES fazenda (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planejamento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talhao_id INTEGER NOT NULL,
    periodo TEXT NOT NULL CHECK (periodo IN ('DIA', 'SEMANA', 'MES')),
    data_ref TEXT NOT NULL,
    horas_planejadas REAL NOT NULL CHECK (horas_planejadas >= 0),
    lamina_planejada_mm REAL NOT NULL CHECK (lamina_planejada_mm >= 0),
    manutencao_planejada INTEGER NOT NULL DEFAULT 0 CHECK (manutencao_planejada IN (0, 1)),
    tipo_manutencao TEXT CHECK (tipo_manutencao IN ('PREVENTIVA', 'CORRETIVA')),
    prioridade INTEGER NOT NULL CHECK (prioridade BETWEEN 1 AND 5),
    status TEXT NOT NULL CHECK (status IN ('PLANEJADO', 'EM_EXECUCAO', 'CONCLUIDO', 'CANCELADO')),
    notas TEXT,
    UNIQUE (talhao_id, periodo, data_ref),
    FOREIGN KEY (talhao_id) REFERENCES talhao (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bloco_fazenda_id ON bloco (fazenda_id);
CREATE INDEX IF NOT EXISTS idx_talhao_bloco_id ON talhao (bloco_id);
CREATE INDEX IF NOT EXISTS idx_talhao_sistema ON talhao (sistema_irrigacao);
CREATE INDEX IF NOT EXISTS idx_sensores_talhao_id ON sensores (talhao_id);
CREATE INDEX IF NOT EXISTS idx_leituras_sensor_data_hora ON leituras_sensores (sensor_id, data_hora);
CREATE INDEX IF NOT EXISTS idx_atividades_talhao_data ON atividades_irrigacao (talhao_id, data);
CREATE INDEX IF NOT EXISTS idx_atividades_data ON atividades_irrigacao (data);
CREATE INDEX IF NOT EXISTS idx_manutencoes_talhao_data ON manutencoes (talhao_id, data_inicio);
CREATE INDEX IF NOT EXISTS idx_manutencoes_data ON manutencoes (data_inicio);
CREATE INDEX IF NOT EXISTS idx_clima_fazenda_data ON clima_diario (fazenda_id, data);
CREATE INDEX IF NOT EXISTS idx_clima_data ON clima_diario (data);
CREATE INDEX IF NOT EXISTS idx_planejamento_talhao_data ON planejamento (talhao_id, data_ref);
CREATE INDEX IF NOT EXISTS idx_planejamento_data ON planejamento (data_ref);
