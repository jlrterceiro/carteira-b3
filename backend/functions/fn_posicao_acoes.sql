-- Posicao atual em acoes/FIIs por ativo, usando tb_posicao_diaria (preco medio e
-- quantidade ja ajustados por splits/agrupamentos/bonificacoes via
-- tb_evento_corporativo). Substitui query_posicao_acoes.sql -- a versao antiga
-- calculava direto de tb_operacao sem nenhum ajuste de evento corporativo, o que
-- dava quantidade e preco medio errados pra qualquer ativo que ja teve split (ex:
-- BBAS3, GGBR3, ITUB3, CGRA4, BLAU3). Usuario agora e parametro em vez de fixo no
-- codigo.
--
-- Usa a MAIOR dt_posicao ja calculada (nao CURRENT_DATE literal) -- ver fn_posicao_atual.sql.

CREATE OR REPLACE FUNCTION public.fn_posicao_acoes(p_sg_usuario TEXT DEFAULT NULL)
RETURNS TABLE (
    sg_ticker TEXT,
    nm_ativo TEXT,
    quantidade NUMERIC,
    preco_medio NUMERIC,
    preco_atual NUMERIC,
    data_cotacao DATE,
    ganho_capital NUMERIC,
    ganho_capital_pct NUMERIC
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
        GROUP BY p.id_ativo
        HAVING SUM(p.qt_ativo) > 0
    ),
    cotacao_atual AS (
        SELECT DISTINCT ON (id_ativo)
            id_ativo,
            vl_fechamento AS vl_preco_atual,
            dt_cotacao
        FROM public.tb_cotacao
        ORDER BY id_ativo, dt_cotacao DESC
    )
    SELECT
        a.sg_ticker,
        a.nm_ativo,
        p.qt_atual AS quantidade,
        round(p.vl_preco_medio, 2) AS preco_medio,
        round(ca.vl_preco_atual, 2) AS preco_atual,
        ca.dt_cotacao AS data_cotacao,
        round(p.qt_atual * (ca.vl_preco_atual - p.vl_preco_medio), 2) AS ganho_capital,
        round(100 * (ca.vl_preco_atual - p.vl_preco_medio) / p.vl_preco_medio, 2) AS ganho_capital_pct
    FROM posicao p
    JOIN public.tb_ativo a ON a.id_ativo = p.id_ativo
    LEFT JOIN cotacao_atual ca ON ca.id_ativo = p.id_ativo
    ORDER BY ganho_capital DESC;
$$;
