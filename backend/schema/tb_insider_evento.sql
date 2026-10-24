-- Evento de insider = o que um grupo (todos | administracao | controlador) comprou ou vendeu a vista de uma empresa em UM mes de competencia
-- (formulario VLMO), com o retorno da acao e do Ibovespa nos 1, 3, 6 e 12 meses seguintes a divulgacao. Base do estudo "insider compra e depois
-- sobe?" (GET /insiders/estudo). Derivada: recalculada do zero por fn_popula_insider_evento() (chamada pelo scraper de insiders).
CREATE TABLE IF NOT EXISTS public.tb_insider_evento (
    id_emissor       INTEGER       NOT NULL REFERENCES public.tb_emissor (id_emissor),
    dt_referencia    DATE          NOT NULL,
    sg_direcao       CHAR(1)       NOT NULL,            -- C compra | V venda
    sg_grupo         VARCHAR(20)   NOT NULL,            -- todos | administracao | controlador
    dt_sinal         DATE          NOT NULL,            -- divulgacao (1a entrega do formulario; nunca antes da ultima operacao do evento)
    qt_total         NUMERIC(24,2) NOT NULL,
    vl_total         NUMERIC(24,2) NOT NULL,
    sg_perfil        VARCHAR(12)   NOT NULL,            -- rotina | oportunista | desconhecido (antes de 2022 nao ha 3 anos de historico)
    id_ativo         INTEGER       REFERENCES public.tb_ativo (id_ativo),   -- acao mais negociada da empresa (retorno)
    dt_entrada       DATE,                              -- 1o pregao depois da divulgacao (fechamento)
    ret_1m  NUMERIC(14,6), ret_3m  NUMERIC(14,6), ret_6m  NUMERIC(14,6), ret_12m  NUMERIC(14,6),     -- retorno total da acao, %
    ibov_1m NUMERIC(14,6), ibov_3m NUMERIC(14,6), ibov_6m NUMERIC(14,6), ibov_12m NUMERIC(14,6),     -- Ibovespa no mesmo periodo, %
    CONSTRAINT pk_tb_insider_evento PRIMARY KEY (id_emissor, dt_referencia, sg_direcao, sg_grupo)
);

-- Linha de base do estudo: retorno (e excesso sobre o Ibovespa) de comprar as MESMAS empresas no 1o pregao de qualquer mes, sem olhar o que os insiders
-- fizeram. Comparar o evento com isso tira o vies de tamanho (empresas pequenas perdem do Ibovespa em geral, com ou sem insider).
CREATE TABLE IF NOT EXISTS public.tb_insider_base (
    nr_meses     INTEGER       NOT NULL PRIMARY KEY,
    qt_amostras  INTEGER       NOT NULL,
    vl_media     NUMERIC(14,6),     -- excesso medio sobre o Ibovespa, em pontos percentuais
    vl_mediana   NUMERIC(14,6),
    pct_acima    NUMERIC(8,4)       -- % das amostras que bateram o Ibovespa
);
