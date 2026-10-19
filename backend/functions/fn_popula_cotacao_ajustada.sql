-- Recalcula tb_cotacao_ajustada do zero a partir de tb_cotacao_bruta.
--
-- Eventos: fator_evento(dia) = produto dos vl_fator de eventos DEPOIS do dia (mesma definicao de
-- fn_fator_acumulado). OHLC e fechamento = real / fator_evento.
--
-- Retorno total: cada provento (ativo, dt_ex) vira um fator (P - v) / P, com P = fechamento do ultimo pregao
-- ANTES do ex ja dividido pelo fator de eventos, e v = valor real pago / fn_fator_acumulado(dt_ex) (traz o
-- provento pra base de "acoes de hoje"). Trava de sanidade: v >= 50% de P e descartado (a B3 informa provento
-- anterior a ~2005 por LOTE de 1.000 acoes; aplicar zeraria/inverteria o fator). O ajustado de um dia e o
-- fechamento ajustado por evento x produto dos fatores de provento com dt_ex DEPOIS do dia (estritamente).
-- Soma de logaritmos em janela (total - acumulado ate a linha) em vez de subconsulta por linha.
CREATE OR REPLACE FUNCTION public.fn_popula_cotacao_ajustada()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    -- DELETE (e nao TRUNCATE) de proposito: TRUNCATE exige lock exclusivo e entrava em deadlock com leitores
    -- (telas lendo a posicao durante o recalculo); DELETE deixa o leitor ver o dado antigo ate o commit.
    DELETE FROM public.tb_cotacao_ajustada;

    INSERT INTO public.tb_cotacao_ajustada (
        id_ativo, dt_cotacao, vl_abertura, vl_maxima, vl_minima,
        vl_fechamento, vl_fechamento_ajustado, vl_fechamento_nominal, qt_volume)
    WITH base AS (
        SELECT b.id_ativo, b.dt_cotacao, b.vl_abertura, b.vl_maxima, b.vl_minima, b.vl_fechamento, b.qt_volume,
               COALESCE(f.fator, 1) AS fe
        FROM public.tb_cotacao_bruta b
        LEFT JOIN LATERAL (
            SELECT EXP(SUM(LN(e.vl_fator))) AS fator
            FROM public.tb_evento_corporativo e
            WHERE e.id_ativo = b.id_ativo AND e.dt_evento > b.dt_cotacao AND e.vl_fator > 0
        ) f ON TRUE
    ),
    prov AS (
        SELECT p.id_ativo, p.dt_ex,
               SUM(COALESCE(p.vl_unitario_ajustado, p.vl_unitario)) / NULLIF(public.fn_fator_acumulado(p.id_ativo, p.dt_ex), 0) AS valor
        FROM public.tb_provento p
        GROUP BY p.id_ativo, p.dt_ex
    ),
    prov_f AS (
        SELECT p.id_ativo, p.dt_ex,
               LN(((prev.preco - p.valor) / prev.preco)::double precision) AS lnf
        FROM prov p
        JOIN LATERAL (
            SELECT bb.vl_fechamento / COALESCE((SELECT EXP(SUM(LN(e.vl_fator))) FROM public.tb_evento_corporativo e
                                                 WHERE e.id_ativo = bb.id_ativo AND e.dt_evento > bb.dt_cotacao AND e.vl_fator > 0), 1) AS preco
            FROM public.tb_cotacao_bruta bb
            WHERE bb.id_ativo = p.id_ativo AND bb.dt_cotacao < p.dt_ex
            ORDER BY bb.dt_cotacao DESC LIMIT 1
        ) prev ON TRUE
        WHERE p.valor IS NOT NULL AND prev.preco > 0 AND p.valor < 0.5 * prev.preco
    ),
    linha_tempo AS (
        -- provento (k=0) vem ANTES do pregao do mesmo dia: so conta pra dias estritamente anteriores ao ex
        SELECT id_ativo, dt_ex AS dt, 0 AS k, lnf, NULL::date AS d, NULL::numeric AS abe, NULL::numeric AS mx, NULL::numeric AS mn,
               NULL::numeric AS ult, NULL::numeric AS vol, NULL::numeric AS fe
        FROM prov_f
        UNION ALL
        SELECT id_ativo, dt_cotacao, 1, 0::double precision, dt_cotacao, vl_abertura, vl_maxima, vl_minima, vl_fechamento, qt_volume, fe
        FROM base
    ),
    acumulado AS (
        SELECT t.*,
               COALESCE(SUM(t.lnf) OVER (PARTITION BY t.id_ativo), 0)
               - SUM(t.lnf) OVER (PARTITION BY t.id_ativo ORDER BY t.dt, t.k ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS ln_depois
        FROM linha_tempo t
    )
    SELECT a.id_ativo, a.d,
           ROUND(a.abe / a.fe, 8), ROUND(a.mx / a.fe, 8), ROUND(a.mn / a.fe, 8),
           ROUND(a.ult / a.fe, 8),
           ROUND((a.ult / a.fe) * EXP(a.ln_depois)::numeric, 8),
           a.ult, a.vol
    FROM acumulado a
    WHERE a.k = 1
      AND a.fe > 0
      AND GREATEST(a.abe, a.mx, a.mn, a.ult) / a.fe <= 1e11     -- preco acima de R$100bi e espurio (mesma trava do scraper antigo)
      AND (a.ult / a.fe) * EXP(a.ln_depois)::numeric <= 1e11;
END;
$$;
