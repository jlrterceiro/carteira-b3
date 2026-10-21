-- Series de referencia pra comparar com a carteira (grafico da Rentabilidade): uma linha por (benchmark, dia).
--   IBOV: vl_nivel = pontos do fechamento (arquivo diario de indices da B3, Index Report BVBG.087.01, so dia de pregao);
--         vl_retorno_pct = variacao sobre o fechamento anterior. O Ibovespa e um indice de RETORNO TOTAL (a metodologia da B3 reinveste os proventos na carteira teorica), entao a
--         comparacao com o TWR da carteira, que tambem inclui dividendos, e justa. Bruto x liquido de IR nao verificado.
--   CDI : vl_retorno_pct = taxa do dia em % a.d. (BCB SGS 12, dia util); vl_nivel nulo. A taxa do dia t rende de t ate o
--         proximo dia util.
-- Fonte, scrape/scraper_benchmarks.py (so upsert).
CREATE TABLE IF NOT EXISTS public.tb_benchmark_diario (
    cd_benchmark   TEXT NOT NULL,                 -- 'IBOV' | 'CDI'
    dt_dia         DATE NOT NULL,
    vl_nivel       NUMERIC(20,6),
    vl_retorno_pct NUMERIC(14,8),
    dh_atualizacao TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (cd_benchmark, dt_dia)
);
