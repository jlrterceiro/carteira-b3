-- Valor de mercado "da epoca" e marcas de qualidade de cada movimentacao de insider (tb_insider_movimentacao). Chamada por scrape/scraper_insiders_cvm.py
-- no fim da carga (e depois de scrape/scraper_acoes_emitidas.py, que fornece a quantidade de acoes).
--   vl_valor_mercado = fn_valor_mercado_em(emissor, data): acoes em circulacao na data (CVM, corrigidas por eventos) x preco real do dia por classe (ON/PN)
--   vl_pct_mercado   = vl_volume / vl_valor_mercado x 100 (positivo; o sinal vem de compra/venda)
--   fl_bloco         = operacao grande demais pra ser pregao normal: >= 25% da quantidade negociada no dia (e >= R$ 5 mi) OU >= 2% do valor de
--                      mercado numa unica operacao (oferta, venda em bloco, operacao casada) -- nao e "sentimento" do insider
--   fl_suspeito      = dado provavelmente errado no formulario: preco fora de [minima/2, maxima x 2] do dia (com volume > 0) ou > 100% do valor de mercado

-- classe do ticker a partir de "Caracteristica do valor mobiliario" (texto livre: ON, PN, PNA, UNT, "1ON 1PN", "1 ACAO ORDINARIA E 4 ACOES PREFERENCIAIS", IGTI11...)
CREATE OR REPLACE FUNCTION public.fn_classe_insider(car TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN car IS NULL OR btrim(car) = '' THEN 'ON'
                WHEN upper(car) LIKE 'PN%' THEN 'PN'
                WHEN upper(car) ~ '(UNT|UNIT|UNID)' OR upper(car) ~ '^[0-9]' OR upper(car) ~ '[0-9]{2}$' THEN 'UNIT'
                ELSE 'ON' END
$$;

ALTER TABLE public.tb_insider_movimentacao ADD COLUMN IF NOT EXISTS fl_bloco BOOLEAN;
ALTER TABLE public.tb_insider_movimentacao ADD COLUMN IF NOT EXISTS fl_suspeito BOOLEAN;

CREATE OR REPLACE FUNCTION public.fn_popula_insider_mercado() RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    n INTEGER;
BEGIN
    UPDATE public.tb_insider_movimentacao m
    SET qt_acoes_emissor = x.acoes, vl_valor_mercado = x.mercado,
        vl_pct_mercado = CASE WHEN x.mercado > 0 AND m.vl_volume IS NOT NULL THEN 100 * m.vl_volume / x.mercado END,
        fl_bloco = COALESCE(x.dia_qt > 0 AND m.qt_ativo >= 0.25 * x.dia_qt AND m.vl_volume >= 5e6, false)
                   OR COALESCE(x.mercado > 0 AND 100 * m.vl_volume / x.mercado >= 2, false),
        fl_suspeito = COALESCE(m.vl_volume > 0 AND x.lo IS NOT NULL AND m.vl_preco IS NOT NULL AND (m.vl_preco < x.lo / 2 OR m.vl_preco > x.hi * 2), false)
                      OR COALESCE(x.mercado > 0 AND 100 * m.vl_volume / x.mercado > 100, false)
    FROM (
        SELECT m2.id_insider_movimentacao AS id, vm.acoes, vm.mercado, d.qt_volume AS dia_qt, d.vl_minima AS lo, d.vl_maxima AS hi
        FROM public.tb_insider_movimentacao m2
        CROSS JOIN LATERAL public.fn_valor_mercado_em(m2.id_emissor, m2.dt_movimentacao) vm
        CROSS JOIN LATERAL (   -- ativo da classe negociada: compara o preco do formulario com o do dia
            SELECT a.id_ativo FROM public.tb_ativo a WHERE a.id_emissor = m2.id_emissor
            ORDER BY (a.sg_classe IS DISTINCT FROM public.fn_classe_insider(m2.ds_caracteristica)), (a.sg_classe <> 'ON'), a.id_ativo LIMIT 1) ativo
        LEFT JOIN public.tb_cotacao_bruta d ON d.id_ativo = ativo.id_ativo AND d.dt_cotacao = m2.dt_movimentacao
    ) x
    WHERE m.id_insider_movimentacao = x.id;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;
