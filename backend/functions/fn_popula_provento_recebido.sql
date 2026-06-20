-- Recalcula do zero a tb_provento_recebido a partir de tb_provento (valor bruto por
-- acao, por ativo, na data ex) e tb_posicao_diaria (quantidade detida no ultimo dia
-- "com", ou seja, no dia anterior a data ex). Uma linha por (carteira, corretora,
-- ativo, dt_ex) -- so nas datas em que realmente houve provento, sem preencher os
-- dias entre eventos como tb_posicao_diaria faz.
--
-- Usa tb_provento.vl_unitario_ajustado (populado por fn_popula_provento_ajustado),
-- que ja desfez o ajuste retroativo que o yfinance aplica pra splits/grupamentos
-- ocorridos depois da data ex -- precisa rodar fn_popula_provento_ajustado() antes
-- desta funcao sempre que tb_evento_corporativo ou tb_provento mudarem.

CREATE OR REPLACE FUNCTION public.fn_popula_provento_recebido()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    TRUNCATE TABLE public.tb_provento_recebido;

    INSERT INTO public.tb_provento_recebido (
        id_carteira, id_corretora, id_ativo, dt_ex, qt_ativo, vl_unitario_ajustado, vl_total
    )
    SELECT
        pd.id_carteira,
        pd.id_corretora,
        pr.id_ativo,
        pr.dt_ex,
        pd.qt_ativo,
        pr.vl_unitario_ajustado,
        round(pd.qt_ativo * pr.vl_unitario_ajustado, 2)
    FROM public.tb_provento pr
    JOIN public.tb_posicao_diaria pd
        ON pd.id_ativo = pr.id_ativo
       AND pd.dt_posicao = pr.dt_ex - 1
    WHERE pd.qt_ativo > 0;
END;
$$;
