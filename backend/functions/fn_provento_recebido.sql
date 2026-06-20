-- Provento recebido total por ativo, somando todas as datas ex / carteiras /
-- corretoras que passarem no filtro. Le de tb_provento_recebido (populada por
-- fn_popula_provento_recebido). Valor bruto, sem desconto de IR (15% no caso de
-- JCP). Todos os parametros sao opcionais (NULL = sem filtro).

CREATE OR REPLACE FUNCTION public.fn_provento_recebido(
    p_dt_inicio DATE DEFAULT NULL,
    p_dt_fim DATE DEFAULT NULL,
    p_id_carteira INTEGER DEFAULT NULL,
    p_id_corretora INTEGER DEFAULT NULL,
    p_sg_usuario TEXT DEFAULT NULL
)
RETURNS TABLE (
    id_ativo INTEGER,
    sg_ticker TEXT,
    vl_recebido NUMERIC
)
LANGUAGE sql
AS $$
    SELECT
        a.id_ativo,
        a.sg_ticker,
        round(SUM(pr.vl_total), 2) AS vl_recebido
    FROM public.tb_provento_recebido pr
    JOIN public.tb_carteira c ON c.id_carteira = pr.id_carteira
    JOIN public.tb_usuario u ON u.id_usuario = c.id_usuario
    JOIN public.tb_ativo a ON a.id_ativo = pr.id_ativo
    WHERE (p_dt_inicio IS NULL OR pr.dt_ex >= p_dt_inicio)
      AND (p_dt_fim IS NULL OR pr.dt_ex <= p_dt_fim)
      AND (p_id_carteira IS NULL OR pr.id_carteira = p_id_carteira)
      AND (p_id_corretora IS NULL OR pr.id_corretora = p_id_corretora)
      AND (p_sg_usuario IS NULL OR u.sg_usuario = p_sg_usuario)
    GROUP BY a.id_ativo, a.sg_ticker
    ORDER BY vl_recebido DESC;
$$;
