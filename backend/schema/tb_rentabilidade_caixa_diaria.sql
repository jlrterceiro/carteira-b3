-- DERIVADA (fn_popula_rentabilidade_caixa): por (usuario, corretora ou NULL = todas, dia de pregao), os proventos
-- liquidos contados na data ex e na data de PAGAMENTO, o caixa de proventos recebido acumulado e o RECEBIVEL. Junto de
-- tb_rentabilidade_diaria (base e ganho) permite as rentabilidades:
--   TWR com proventos a receber:  ganho / (base + vl_receber_ini)
--       o provento conta no numerador na data ex e fica no denominador (sem render) ate o dia do pagamento, quando sai
--       (saque ou reinvestimento; o reinvestimento reaparece como compra)
--   estilo Status Invest:         (ganho - vl_prov_ex + vl_prov_pgto) / (base + vl_caixa_pgto_ini)
--       conta no pagamento e o caixa fica no denominador para sempre, sem render
CREATE TABLE IF NOT EXISTS public.tb_rentabilidade_caixa_diaria (
    dt_dia            DATE    NOT NULL,
    id_usuario        INTEGER NOT NULL,
    id_corretora      INTEGER,
    vl_prov_ex        NUMERIC(20,4) NOT NULL,
    vl_prov_pgto      NUMERIC(20,4) NOT NULL,
    vl_receber_ini    NUMERIC(20,4) NOT NULL,
    vl_caixa_pgto_ini NUMERIC(20,4) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tb_rentabilidade_caixa_diaria_01 ON public.tb_rentabilidade_caixa_diaria (id_usuario, id_corretora, dt_dia);
