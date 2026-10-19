-- Posicao atual por ativo (soma as corretoras do usuario; p_id_corretora filtra uma so), usando tb_posicao_diaria,
-- que ja considera splits/agrupamentos/bonificacoes via tb_evento_corporativo.
-- Substitui query_posicao_atual.sql -- agora com usuario como parametro em vez de
-- fixo no codigo.
--
-- Usa a MAIOR dt_posicao ja calculada (nao CURRENT_DATE literal): fn_popula_posicao_diaria
-- so gera linha pra hoje quando fn_rebuild_tudo() roda no mesmo dia -- se passar um dia sem
-- rodar (scraper nao rodou, sem operacao nova), CURRENT_DATE literal nao bate com nenhuma
-- linha e a posicao "desaparece" mesmo a carteira estando intacta. MAX(dt_posicao) sempre
-- aponta pra ultima posicao calculada, seja ela de hoje ou de alguns dias atras.

-- troca de assinatura (ganhou p_id_corretora): sem o DROP ficariam duas versoes e a chamada de 1 argumento viraria ambigua
DROP FUNCTION IF EXISTS public.fn_posicao_atual(TEXT);
DROP FUNCTION IF EXISTS public.fn_posicao_atual(TEXT, INTEGER);
CREATE OR REPLACE FUNCTION public.fn_posicao_atual(p_sg_usuario TEXT DEFAULT NULL, p_id_corretora INTEGER DEFAULT NULL)
RETURNS TABLE (
    sg_ticker TEXT,
    nm_ativo TEXT,
    quantidade NUMERIC,
    preco_medio NUMERIC,
    preco_atual NUMERIC,
    data_cotacao DATE,
    vl_posicao NUMERIC,
    ganho_capital NUMERIC,
    ganho_capital_pct NUMERIC,
    preco_anterior NUMERIC,
    var_dia_pct NUMERIC,
    ganho_dia NUMERIC,
    dh_cotacao TIMESTAMP,
    ds_fonte TEXT
)
LANGUAGE sql
AS $$
    WITH posicao AS (
        SELECT
            p.id_ativo,
            SUM(p.qt_ativo) AS qt_atual,
            SUM(p.qt_ativo * p.vl_preco_medio) / SUM(p.qt_ativo) AS vl_preco_medio
        FROM public.tb_posicao_diaria p
        JOIN public.tb_carteira c ON c.id_carteira = p.id_carteira
        JOIN public.tb_usuario u ON u.id_usuario = c.id_usuario
        WHERE p.dt_posicao = (SELECT MAX(dt_posicao) FROM public.tb_posicao_diaria)
          AND (p_sg_usuario IS NULL OR u.sg_usuario = p_sg_usuario)
          AND (p_id_corretora IS NULL OR p.id_corretora = p_id_corretora)
        GROUP BY p.id_ativo
        HAVING SUM(p.qt_ativo) > 0
    )
    SELECT
        a.sg_ticker,
        a.nm_ativo,
        p.qt_atual AS quantidade,
        round(p.vl_preco_medio, 2) AS preco_medio,
        round(ca.vl_preco_atual, 2) AS preco_atual,
        ca.dt_cotacao AS data_cotacao,
        round(p.qt_atual * ca.vl_preco_atual, 2) AS vl_posicao,
        round(p.qt_atual * (ca.vl_preco_atual - p.vl_preco_medio), 2) AS ganho_capital,
        round(100 * (ca.vl_preco_atual - p.vl_preco_medio) / p.vl_preco_medio, 2) AS ganho_capital_pct,
        round(ca.vl_preco_anterior, 2) AS preco_anterior,
        round(100 * (ca.vl_preco_atual / NULLIF(ca.vl_preco_anterior, 0) - 1), 2) AS var_dia_pct,
        round(p.qt_atual * (ca.vl_preco_atual - ca.vl_preco_anterior), 2) AS ganho_dia,
        ca.dh_cotacao,
        ca.ds_fonte
    FROM posicao p
    JOIN public.tb_ativo a ON a.id_ativo = p.id_ativo
    LEFT JOIN public.vw_cotacao_atual ca ON ca.id_ativo = p.id_ativo
    ORDER BY vl_posicao DESC;
$$;
