-- Cotacao REAL do dia, exatamente como o COTAHIST da B3 informou (ja dividida por FATCOT, so R$). Nunca e
-- ajustada: fonte da verdade. Evento corporativo novo/corrigido nao exige regerar nada aqui.
-- Os precos ajustados (por evento e por provento) saem de tb_cotacao_ajustada (fn_popula_cotacao_ajustada).
CREATE TABLE IF NOT EXISTS public.tb_cotacao_bruta (
    id_cotacao   SERIAL PRIMARY KEY,
    id_ativo     INTEGER NOT NULL REFERENCES public.tb_ativo (id_ativo),
    dt_cotacao   DATE NOT NULL,
    vl_abertura  NUMERIC(20,8),
    vl_maxima    NUMERIC(20,8),
    vl_minima    NUMERIC(20,8),
    vl_fechamento NUMERIC(20,8) NOT NULL,
    qt_volume    NUMERIC(20,8),
    dh_criacao   TIMESTAMP DEFAULT now(),
    CONSTRAINT uk_tb_cotacao_bruta_01 UNIQUE (id_ativo, dt_cotacao)
);
