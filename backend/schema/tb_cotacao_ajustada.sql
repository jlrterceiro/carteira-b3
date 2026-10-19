-- DERIVADA de tb_cotacao_bruta + tb_evento_corporativo + tb_provento, recalculada do zero por
-- fn_popula_cotacao_ajustada() (chamada por fn_rebuild_tudo). Nao gravar aqui na mao.
--   vl_abertura/maxima/minima/fechamento : preco real / fn_fator_acumulado (so eventos: split, grupamento, bonificacao)
--   vl_fechamento_ajustado               : o de cima, descontando tambem os proventos (retorno total)
--   vl_fechamento_nominal                : o preco real do dia (= tb_cotacao_bruta.vl_fechamento)
CREATE TABLE IF NOT EXISTS public.tb_cotacao_ajustada (
    id_ativo               INTEGER NOT NULL REFERENCES public.tb_ativo (id_ativo),
    dt_cotacao             DATE NOT NULL,
    vl_abertura            NUMERIC(20,8),
    vl_maxima              NUMERIC(20,8),
    vl_minima              NUMERIC(20,8),
    vl_fechamento          NUMERIC(20,8) NOT NULL,
    vl_fechamento_ajustado NUMERIC(20,8),
    vl_fechamento_nominal  NUMERIC(20,8) NOT NULL,
    qt_volume              NUMERIC(20,8),
    PRIMARY KEY (id_ativo, dt_cotacao)
);
CREATE INDEX IF NOT EXISTS ix_tb_cotacao_ajustada_dt ON public.tb_cotacao_ajustada (dt_cotacao);
