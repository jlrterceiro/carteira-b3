-- Quantidade de acoes de cada emissor, por trimestre (composicao do capital que a empresa entrega a CVM no ITR/DFP), em ACOES (escala corrigida).
-- Serve pra valor de mercado "da epoca" (quantidade da data x preco real do dia): scrape/scraper_acoes_emitidas.py.
-- A CVM nao diz a unidade: algumas empresas informam em milhares (VALE, ITUB, ITSA...). nr_escala (1 ou 1000) e inferido comparando
-- (acoes x preco) com o patrimonio liquido do mesmo trimestre (P/VP entre 0,02 e 100); sem evidencia, herda a escala do trimestre vizinho.
CREATE TABLE IF NOT EXISTS public.tb_acoes_emissor (
    id_emissor       INTEGER NOT NULL REFERENCES public.tb_emissor (id_emissor),
    dt_referencia    DATE    NOT NULL,
    qt_total         NUMERIC(24,0) NOT NULL,      -- capital integralizado (ON + PN)
    qt_ordinaria     NUMERIC(24,0),
    qt_preferencial  NUMERIC(24,0),
    qt_tesouraria    NUMERIC(24,0),               -- em tesouraria (nao conta no valor de mercado)
    nr_escala        INTEGER NOT NULL,            -- fator aplicado ao numero informado (1 ou 1000)
    fl_confiavel     BOOLEAN NOT NULL,            -- escala decidida com evidencia (patrimonio) neste trimestre
    PRIMARY KEY (id_emissor, dt_referencia)
);
