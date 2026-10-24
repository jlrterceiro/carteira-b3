-- Saldo INICIAL de cada mes que os insiders declaram no VLMO da CVM (linhas "Saldo Inicial" do vlmo_cia_aberta_con_<ano>.csv): quantas acoes/units o grupo
-- (cargo) tinha no comeco do mes de competencia. Soma de todas as empresas declarantes (companhia, controladora, controlada) da ultima versao entregue.
-- Serve de denominador pra "% da posicao do grupo" que foi comprada/vendida. Carga: scrape/scraper_insiders_cvm.py (apaga o ano e regrava).
CREATE TABLE IF NOT EXISTS public.tb_insider_saldo (
    id_emissor        INTEGER       NOT NULL REFERENCES public.tb_emissor (id_emissor),
    dt_referencia     DATE          NOT NULL,          -- primeiro dia do mes de competencia
    tipo_cargo        VARCHAR(80)   NOT NULL DEFAULT '',
    tipo_ativo        VARCHAR(60)   NOT NULL,
    ds_caracteristica VARCHAR(120)  NOT NULL DEFAULT '',
    qt_saldo_inicial  NUMERIC(24,2) NOT NULL,
    CONSTRAINT pk_tb_insider_saldo PRIMARY KEY (id_emissor, dt_referencia, tipo_cargo, tipo_ativo, ds_caracteristica)
);
CREATE INDEX IF NOT EXISTS ix_tb_insider_saldo_01 ON public.tb_insider_saldo (id_emissor, dt_referencia);
