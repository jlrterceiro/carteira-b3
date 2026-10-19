-- Ultimo preco de cada ativo DURANTE o pregao (coletado a cada ~5 min por scrape/scraper_cotacao_intradia.py, que le o
-- endpoint de cotacao do proprio site da B3). Uma linha por ativo, sempre a mais recente (upsert); nao guarda historico.
-- Preco REAL do dia (sem ajuste), igual ao COTAHIST. vw_cotacao_atual so usa a linha enquanto o COTAHIST do mesmo dia
-- ainda nao saiu; quando o dia completo entra em tb_cotacao_bruta, a view passa a ler dele.
CREATE TABLE IF NOT EXISTS public.tb_cotacao_intradia (
    id_ativo      INTEGER PRIMARY KEY REFERENCES public.tb_ativo (id_ativo),
    dt_pregao     DATE      NOT NULL,
    dh_cotacao    TIMESTAMP NOT NULL,           -- horario da cotacao informado pela B3 (Brasilia)
    vl_preco      NUMERIC(20,8) NOT NULL,       -- ultimo negocio (curPrc)
    vl_abertura   NUMERIC(20,8),
    vl_minimo     NUMERIC(20,8),
    vl_maximo     NUMERIC(20,8),
    pc_variacao   NUMERIC(10,4),                -- variacao do dia em %, como a B3 informa (prcFlcn)
    dh_coleta     TIMESTAMP NOT NULL DEFAULT now()
);
