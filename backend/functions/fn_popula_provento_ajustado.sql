-- Atualiza tb_provento.vl_unitario_ajustado = vl_unitario (raw, yfinance) multiplicado
-- pelo fator acumulado de splits/grupamentos ocorridos depois da data ex (ver
-- fn_fator_acumulado). Isso desfaz o ajuste retroativo que o yfinance ja aplica no
-- valor por acao, recuperando o valor real pago na epoca -- confirmado contra
-- divulgacao oficial (BBAS3, JCP de 12/06/2023: yfinance mostrava metade do valor
-- anunciado, por causa do split 2:1 que a BBAS3 fez em 16/04/2024).
--
-- vl_unitario (raw) nunca e sobrescrito -- e o dado bruto do scraper. Precisa rodar
-- de novo sempre que tb_evento_corporativo ou tb_provento forem atualizados.

CREATE OR REPLACE FUNCTION public.fn_popula_provento_ajustado()
RETURNS void
LANGUAGE sql
AS $$
    UPDATE public.tb_provento
    SET vl_unitario_ajustado = vl_unitario * public.fn_fator_acumulado(id_ativo, dt_ex);
$$;
