-- Extrato de proventos recebidos (uma linha por ativo + data ex, sem preencher dias
-- sem evento), lendo de tb_provento_recebido. Todos os parametros sao opcionais
-- (NULL = sem filtro).

CREATE OR REPLACE FUNCTION public.fn_extrato_provento(
    p_dt_inicio DATE DEFAULT NULL,
    p_dt_fim DATE DEFAULT NULL,
    p_id_carteira INTEGER DEFAULT NULL,
    p_id_corretora INTEGER DEFAULT NULL,
    p_sg_usuario TEXT DEFAULT NULL
)
RETURNS TABLE (
    sg_ticker TEXT,
    dt_ex DATE,
    nm_carteira TEXT,
    nm_corretora TEXT,
    qt_ativo NUMERIC,
    vl_unitario_ajustado NUMERIC,
    vl_total NUMERIC
)
LANGUAGE sql
AS $$
    SELECT
        a.sg_ticker,
        pr.dt_ex,
        c.nm_carteira,
        cor.nm_corretora,
        pr.qt_ativo,
        pr.vl_unitario_ajustado,
        pr.vl_total
    FROM public.tb_provento_recebido pr
    JOIN public.tb_ativo a ON a.id_ativo = pr.id_ativo
    JOIN public.tb_carteira c ON c.id_carteira = pr.id_carteira
    JOIN public.tb_usuario u ON u.id_usuario = c.id_usuario
    JOIN public.tb_corretora cor ON cor.id_corretora = pr.id_corretora
    WHERE (p_dt_inicio IS NULL OR pr.dt_ex >= p_dt_inicio)
      AND (p_dt_fim IS NULL OR pr.dt_ex <= p_dt_fim)
      AND (p_id_carteira IS NULL OR pr.id_carteira = p_id_carteira)
      AND (p_id_corretora IS NULL OR pr.id_corretora = p_id_corretora)
      AND (p_sg_usuario IS NULL OR u.sg_usuario = p_sg_usuario)
    ORDER BY a.sg_ticker, pr.dt_ex;
$$;
