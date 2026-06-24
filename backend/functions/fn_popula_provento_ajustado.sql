-- Atualiza tb_provento.vl_unitario_ajustado.
--
-- Pra proventos de origem B3 (ds_origem='B3', fonte atual): a B3 reporta o valor real
-- declarado na epoca, sem nenhum ajuste retroativo de split/grupamento -- ou seja,
-- vl_unitario JA E o valor "ajustado" (vl_unitario_ajustado = vl_unitario direto, fator
-- implicito = 1).
--
-- Pra proventos de origem yfinance (ds_origem='yfinance', historico/descontinuado):
-- vl_unitario era o valor JA reescrito retroativamente pra baixo pelo yfinance refletindo
-- splits/grupamentos ocorridos DEPOIS da data ex -- multiplicar pelo fator acumulado (ver
-- fn_fator_acumulado) desfaz esse ajuste, recuperando o valor real pago na epoca
-- (confirmado contra divulgacao oficial: BBAS3, JCP de 12/06/2023, yfinance mostrava
-- metade do valor anunciado por causa do split 2:1 que a BBAS3 fez em 16/04/2024).
--
-- vl_unitario (raw) nunca e sobrescrito -- e o dado bruto do scraper. Precisa rodar
-- de novo sempre que tb_evento_corporativo ou tb_provento forem atualizados.

CREATE OR REPLACE FUNCTION public.fn_popula_provento_ajustado()
RETURNS void
LANGUAGE sql
AS $$
    UPDATE public.tb_provento
    SET vl_unitario_ajustado = CASE
        WHEN ds_origem = 'B3' THEN vl_unitario
        ELSE vl_unitario * public.fn_fator_acumulado(id_ativo, dt_ex)
    END;
$$;
