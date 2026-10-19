-- Negocios consolidados do pregao (B3, arquivo TradeInformationConsolidatedFile), so segmento CASH dos
-- tickers cadastrados. pc_oscilacao e a variacao do dia calculada pela B3 contra o fechamento anterior
-- JA AJUSTADO por eventos e proventos: dela sai o fator exato de desdobramento/grupamento/bonificacao
-- (fator = (1 + osc) x fechamento_anterior / fechamento_do_dia). Disponivel a partir de 2025-06-11.
CREATE TABLE IF NOT EXISTS public.tb_negocio_diario (
    id_negocio_diario  BIGSERIAL PRIMARY KEY,
    dt_pregao          DATE          NOT NULL,
    sg_ticker          TEXT          NOT NULL,
    cd_isin            TEXT,
    vl_minimo          NUMERIC(20,8),
    vl_maximo          NUMERIC(20,8),
    vl_medio           NUMERIC(20,8),
    vl_ultimo          NUMERIC(20,8),
    pc_oscilacao       NUMERIC(12,4),
    qt_negocios        BIGINT,
    qt_titulos         NUMERIC(24,4),
    vl_financeiro      NUMERIC(24,4),
    dh_criacao         TIMESTAMP DEFAULT now(),
    CONSTRAINT uk_tb_negocio_diario_01 UNIQUE (dt_pregao, sg_ticker)
);
CREATE INDEX IF NOT EXISTS ix_tb_negocio_diario_ticker ON public.tb_negocio_diario (sg_ticker, dt_pregao);
