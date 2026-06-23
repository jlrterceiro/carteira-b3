-- Ganho total por ativo: combina ganho realizado em vendas (fn_ganho_realizado_venda),
-- proventos recebidos (fn_provento_recebido) e ganho de capital nao realizado da
-- posicao atual (qtd hoje x preco medio hoje x cotacao mais recente).
--
-- p_dt_inicio/p_dt_fim filtram vendas e proventos por periodo; o ganho nao realizado
-- e sempre da posicao mais recente ja calculada (MAX(dt_posicao), nao CURRENT_DATE
-- literal -- ver fn_posicao_atual.sql), ja que representa o que ainda esta na carteira
-- hoje -- nao faz sentido "nao realizado" num periodo passado.
--
-- ganho_total_pct e o ganho_total sobre o total comprado historicamente (todas as
-- compras, sem filtro de periodo -- e o capital que de fato foi colocado no ativo).
-- Todos os parametros sao opcionais (NULL = sem filtro).

CREATE OR REPLACE FUNCTION public.fn_ganho_total(
    p_dt_inicio DATE DEFAULT NULL,
    p_dt_fim DATE DEFAULT NULL,
    p_id_carteira INTEGER DEFAULT NULL,
    p_id_corretora INTEGER DEFAULT NULL,
    p_sg_usuario TEXT DEFAULT NULL
)
RETURNS TABLE (
    id_ativo INTEGER,
    sg_ticker TEXT,
    ganho_realizado_vendas NUMERIC,
    proventos NUMERIC,
    ganho_nao_realizado NUMERIC,
    ganho_total NUMERIC,
    valor_investido NUMERIC,
    ganho_pct_total NUMERIC
)
LANGUAGE sql
AS $$
    WITH realizado AS (
        SELECT * FROM public.fn_ganho_realizado_venda(p_dt_inicio, p_dt_fim, p_id_carteira, p_id_corretora, p_sg_usuario)
    ),
    dividendo AS (
        SELECT * FROM public.fn_provento_recebido(p_dt_inicio, p_dt_fim, p_id_carteira, p_id_corretora, p_sg_usuario)
    ),
    posicao_atual AS (
        SELECT
            p.id_ativo,
            SUM(p.qt_ativo) AS qt_atual,
            SUM(p.qt_ativo * p.vl_preco_medio) / SUM(p.qt_ativo) AS vl_preco_medio
        FROM public.tb_posicao_diaria p
        JOIN public.tb_carteira c ON c.id_carteira = p.id_carteira
        JOIN public.tb_usuario u ON u.id_usuario = c.id_usuario
        WHERE p.dt_posicao = (SELECT MAX(dt_posicao) FROM public.tb_posicao_diaria)
          AND (p_id_carteira IS NULL OR p.id_carteira = p_id_carteira)
          AND (p_id_corretora IS NULL OR p.id_corretora = p_id_corretora)
          AND (p_sg_usuario IS NULL OR u.sg_usuario = p_sg_usuario)
        GROUP BY p.id_ativo
        HAVING SUM(p.qt_ativo) > 0
    ),
    cotacao_atual AS (
        SELECT DISTINCT ON (id_ativo) id_ativo, vl_fechamento AS vl_preco_atual
        FROM public.tb_cotacao
        ORDER BY id_ativo, dt_cotacao DESC
    ),
    nao_realizado AS (
        SELECT
            pa.id_ativo,
            round(pa.qt_atual * (ca.vl_preco_atual - pa.vl_preco_medio), 2) AS ganho_nao_realizado
        FROM posicao_atual pa
        LEFT JOIN cotacao_atual ca ON ca.id_ativo = pa.id_ativo
    ),
    investido AS (
        SELECT
            o.id_ativo,
            SUM(o.qt_ativo * o.vl_preco_unitario) AS vl_investido
        FROM public.tb_operacao o
        JOIN public.tb_tipo_operacao top ON top.id_tipo_operacao = o.id_tipo_operacao
        JOIN public.tb_carteira c ON c.id_carteira = o.id_carteira
        JOIN public.tb_usuario u ON u.id_usuario = c.id_usuario
        WHERE top.sg_tipo_operacao = 'COMPRA'
          AND (p_id_carteira IS NULL OR o.id_carteira = p_id_carteira)
          AND (p_id_corretora IS NULL OR o.id_corretora = p_id_corretora)
          AND (p_sg_usuario IS NULL OR u.sg_usuario = p_sg_usuario)
        GROUP BY o.id_ativo
    ),
    ativos AS (
        SELECT id_ativo FROM realizado
        UNION
        SELECT id_ativo FROM dividendo
        UNION
        SELECT id_ativo FROM nao_realizado
    )
    SELECT
        a.id_ativo,
        at.sg_ticker,
        COALESCE(r.ganho_realizado, 0) AS ganho_realizado_vendas,
        COALESCE(d.vl_recebido, 0) AS proventos,
        COALESCE(n.ganho_nao_realizado, 0) AS ganho_nao_realizado,
        COALESCE(r.ganho_realizado, 0) + COALESCE(d.vl_recebido, 0) + COALESCE(n.ganho_nao_realizado, 0) AS ganho_total,
        round(i.vl_investido, 2) AS valor_investido,
        round(100 * (COALESCE(r.ganho_realizado, 0) + COALESCE(d.vl_recebido, 0) + COALESCE(n.ganho_nao_realizado, 0)) / i.vl_investido, 2) AS ganho_pct_total
    FROM ativos a
    JOIN public.tb_ativo at ON at.id_ativo = a.id_ativo
    LEFT JOIN realizado r ON r.id_ativo = a.id_ativo
    LEFT JOIN dividendo d ON d.id_ativo = a.id_ativo
    LEFT JOIN nao_realizado n ON n.id_ativo = a.id_ativo
    LEFT JOIN investido i ON i.id_ativo = a.id_ativo
    ORDER BY ganho_pct_total DESC;
$$;
