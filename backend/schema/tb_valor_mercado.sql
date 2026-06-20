-- Historico de valor de mercado por ativo (so acoes), via yfinance fast_info.marketCap.
-- Diferente de tb_balanco_patrimonial (que tem periodos fiscais oficiais), aqui cada
-- linha e so um snapshot do momento em que o scraper rodou -- nao tem como reconstruir
-- valor de mercado passado (depende da qtd de acoes em circulacao no momento, que so
-- temos pra hoje). Por isso o historico se constroi rodando o scraper periodicamente:
-- cada execucao em um dia novo gera uma linha nova; rodar de novo no mesmo dia atualiza
-- a linha do dia (nao duplica).

CREATE TABLE public.tb_valor_mercado (
    id_valor_mercado SERIAL PRIMARY KEY,
    id_ativo INTEGER NOT NULL REFERENCES public.tb_ativo(id_ativo),
    dt_referencia DATE NOT NULL,
    vl_valor_mercado NUMERIC(24,2) NOT NULL,
    ds_origem TEXT NOT NULL DEFAULT 'yfinance',
    dh_criacao TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (id_ativo, dt_referencia)
);
