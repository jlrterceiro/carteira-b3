-- Preco de cada ativo "como estava" em uma data (visao de snapshot das telas). Mesmo formato da vw_cotacao_atual.
--   p_dt NULL -> o preco de agora (vw_cotacao_atual: intradia enquanto o COTAHIST do dia nao saiu).
--   p_dt data -> ultimo pregao <= p_dt do COTAHIST: vl_preco_atual = fechamento REAL daquele dia (mesma base nominal da quantidade e
--                do preco medio da posicao naquela data); vl_preco_anterior = o pregao anterior reexpresso nas unidades do dia
--                (real do dia x ajustado anterior / ajustado do dia), pra a variacao do dia nao ser distorcida por split/grupamento.
CREATE OR REPLACE FUNCTION public.fn_cotacao_em(p_dt DATE DEFAULT NULL)
RETURNS TABLE (
    id_ativo INTEGER,
    vl_preco_atual NUMERIC,
    vl_preco_anterior NUMERIC,
    dt_cotacao DATE,
    dh_cotacao TIMESTAMP,
    ds_fonte TEXT
)
LANGUAGE sql STABLE
AS $$
    SELECT v.id_ativo, v.vl_preco_atual, v.vl_preco_anterior, v.dt_cotacao, v.dh_cotacao, v.ds_fonte
    FROM public.vw_cotacao_atual v
    WHERE p_dt IS NULL
    UNION ALL
    SELECT a.id_ativo,
           u.nominal,
           u.nominal * u.aj_ant / NULLIF(u.aj, 0),
           u.dt,
           NULL::timestamp,
           'COTAHIST'::text
    FROM public.tb_ativo a
    CROSS JOIN LATERAL (
        SELECT (array_agg(x.vl_fechamento_nominal ORDER BY x.dt_cotacao DESC))[1] AS nominal,
               (array_agg(x.vl_fechamento ORDER BY x.dt_cotacao DESC))[1] AS aj,
               (array_agg(x.vl_fechamento ORDER BY x.dt_cotacao DESC))[2] AS aj_ant,
               max(x.dt_cotacao) AS dt
        FROM (SELECT dt_cotacao, vl_fechamento_nominal, vl_fechamento FROM public.tb_cotacao_ajustada
              WHERE id_ativo = a.id_ativo AND dt_cotacao <= p_dt ORDER BY dt_cotacao DESC LIMIT 2) x
    ) u
    WHERE p_dt IS NOT NULL AND u.nominal IS NOT NULL;
$$;
