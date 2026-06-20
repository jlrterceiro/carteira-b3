-- Produto de todos os vl_fator de tb_evento_corporativo de um ativo, ocorridos
-- DEPOIS de p_dt_referencia. Usado pra trazer um preco nominal (pago numa data
-- passada, sem ajuste) para a mesma base de splits/grupamentos que o tb_cotacao
-- ja vem ajustado do yfinance (que reescreve o historico de preco pra refletir a
-- estrutura de acoes atual, incluindo splits/grupamentos que ainda nao tinham
-- ocorrido naquela data).
CREATE OR REPLACE FUNCTION public.fn_fator_acumulado(p_id_ativo INTEGER, p_dt_referencia DATE)
RETURNS NUMERIC
LANGUAGE sql
AS $$
    SELECT COALESCE(EXP(SUM(LN(e.vl_fator))), 1)
    FROM public.tb_evento_corporativo e
    WHERE e.id_ativo = p_id_ativo
      AND e.dt_evento > p_dt_referencia;
$$;
