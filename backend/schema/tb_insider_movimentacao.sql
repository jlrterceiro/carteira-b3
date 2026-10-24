-- Movimentacoes de insiders (administradores, conselho, controladores e vinculados) com valores mobiliarios da companhia: dados abertos da CVM,
-- VLMO "Posicao Consolidada" (art. 11 da Instr. CVM 358, hoje Res. CVM 44), vlmo_cia_aberta_con_<ano>.csv. Uma linha por movimentacao (o saldo inicial
-- do mes NAO entra). Carga: scrape/scraper_insiders_cvm.py (por ano: apaga o ano e regrava; so a ULTIMA versao entregue de cada mes por companhia).
-- ds_link = documento entregue (rad.cvm.gov.br) do indice vlmo_cia_aberta_<ano>.csv, pela mesma chave (CNPJ, referencia, versao).
-- (A tb_insider_negociacao, mais antiga, vem do scraper_insider.py que le PDF; esta nova vem do CSV estruturado e tem o link do documento.)
CREATE TABLE IF NOT EXISTS public.tb_insider_movimentacao (
    id_insider_movimentacao BIGSERIAL PRIMARY KEY,
    id_emissor        INTEGER NOT NULL REFERENCES public.tb_emissor (id_emissor),
    dt_referencia     DATE    NOT NULL,           -- mes de competencia do formulario (dia 01)
    nr_versao         INTEGER NOT NULL,
    tipo_empresa      TEXT,                       -- Companhia | Controladora | Controlada
    ds_empresa        TEXT,
    tipo_cargo        TEXT,                       -- Conselho de Administracao, Diretor, Controlador, Conselho Fiscal, Orgao Estatutario (ou Vinculado)
    tipo_movimentacao TEXT    NOT NULL,           -- Compra a vista, Venda a vista, Bonificacao, Subscricao, Emprestimo...
    ds_movimentacao   TEXT,
    tipo_operacao     TEXT    NOT NULL,           -- Credito (entrada) | Debito (saida)
    tipo_ativo        TEXT,                       -- Acoes, Units, Opcao de Compra, Debentures...
    ds_caracteristica TEXT,                       -- ON, PN, UNT...
    ds_intermediario  TEXT,
    dt_movimentacao   DATE    NOT NULL,
    qt_ativo          NUMERIC(24,4),
    vl_preco          NUMERIC(20,6),
    vl_volume         NUMERIC(24,4),
    ds_protocolo      TEXT,
    ds_link           TEXT
);
CREATE INDEX IF NOT EXISTS ix_tb_insider_movimentacao_01 ON public.tb_insider_movimentacao (id_emissor, dt_movimentacao);
CREATE INDEX IF NOT EXISTS ix_tb_insider_movimentacao_02 ON public.tb_insider_movimentacao (id_emissor, dt_referencia);

-- valor de mercado "da epoca" (backend/functions/fn_popula_insider_mercado.sql): acoes do emissor na data x preco real do dia
ALTER TABLE public.tb_insider_movimentacao ADD COLUMN IF NOT EXISTS qt_acoes_emissor NUMERIC(24,2);
ALTER TABLE public.tb_insider_movimentacao ADD COLUMN IF NOT EXISTS vl_valor_mercado NUMERIC(28,2);
ALTER TABLE public.tb_insider_movimentacao ADD COLUMN IF NOT EXISTS vl_pct_mercado NUMERIC(20,10);   -- vl_volume / vl_valor_mercado x 100 (positivo)

-- 1a data de entrega do formulario da competencia (indice da CVM): quando a movimentacao ficou publica
ALTER TABLE public.tb_insider_movimentacao ADD COLUMN IF NOT EXISTS dt_entrega DATE;
