-- Eventos que uma fonte (API de eventos da B3, yfinance...) informou mas que as fontes EXATAS contradizem
-- (oscilacao oficial da B3 / ajuste de strike das opcoes). Os scrapers consultam esta tabela pra nao
-- reinserir o evento errado na proxima execucao.
CREATE TABLE IF NOT EXISTS public.tb_evento_rejeitado (
    id_evento_rejeitado SERIAL PRIMARY KEY,
    id_ativo            INTEGER NOT NULL REFERENCES public.tb_ativo (id_ativo),
    dt_evento           DATE NOT NULL,
    vl_fator            NUMERIC(24,12) NOT NULL,
    ds_origem           TEXT,
    ds_motivo           TEXT,
    dh_criacao          TIMESTAMP DEFAULT now(),
    CONSTRAINT uk_tb_evento_rejeitado_01 UNIQUE (id_ativo, dt_evento, vl_fator)
);
