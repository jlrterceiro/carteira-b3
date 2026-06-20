-- Ganho de capital realizado em vendas (compra/venda apenas, sem dividendos/JCP/rendimentos),
-- considerando preco medio ajustado por eventos corporativos (split/agrupamento/bonificacao).
--
-- Reconstroi o historico completo de cada grupo (carteira, corretora, ativo) pra calcular
-- o preco medio correto em cada venda, mas so soma no resultado as vendas dentro do
-- intervalo/filtros pedidos. Todos os parametros sao opcionais (NULL = sem filtro).
--
-- Tie-break do mesmo dia: evento corporativo antes de operacao; dentro de operacao,
-- COMPRA antes de VENDA (extrato da B3 nao tem horario, e conta de pessoa fisica no
-- fracionario nao vende a descoberto -- se VENDA e COMPRA do mesmo ativo caem no
-- mesmo dia, a compra teve que vir primeiro na vida real).

CREATE OR REPLACE FUNCTION public.fn_ganho_realizado_venda(
    p_dt_inicio DATE DEFAULT NULL,
    p_dt_fim DATE DEFAULT NULL,
    p_id_carteira INTEGER DEFAULT NULL,
    p_id_corretora INTEGER DEFAULT NULL,
    p_sg_usuario TEXT DEFAULT NULL
)
RETURNS TABLE (
    id_ativo INTEGER,
    sg_ticker TEXT,
    qt_vendida NUMERIC,
    ganho_realizado NUMERIC
)
LANGUAGE plpgsql
AS $$
DECLARE
    rec_grupo RECORD;
    rec_evento RECORD;
    v_qt NUMERIC;
    v_preco_medio NUMERIC;
    v_ganho NUMERIC;
    v_qt_vendida NUMERIC;
BEGIN
    DROP TABLE IF EXISTS tmp_ganho_ativo;
    CREATE TEMP TABLE tmp_ganho_ativo (
        tmp_id_ativo INTEGER PRIMARY KEY,
        qt_vendida NUMERIC,
        ganho_realizado NUMERIC
    ) ON COMMIT DROP;

    FOR rec_grupo IN
        SELECT DISTINCT o.id_carteira, o.id_corretora, o.id_ativo
        FROM public.tb_operacao o
        JOIN public.tb_carteira c ON c.id_carteira = o.id_carteira
        JOIN public.tb_usuario u ON u.id_usuario = c.id_usuario
        WHERE (p_id_carteira IS NULL OR o.id_carteira = p_id_carteira)
          AND (p_id_corretora IS NULL OR o.id_corretora = p_id_corretora)
          AND (p_sg_usuario IS NULL OR u.sg_usuario = p_sg_usuario)
    LOOP
        v_qt := 0;
        v_preco_medio := 0;
        v_ganho := 0;
        v_qt_vendida := 0;

        FOR rec_evento IN
            SELECT * FROM (
                SELECT
                    o.dt_operacao AS dt,
                    top.sg_tipo_operacao AS tipo,
                    o.qt_ativo AS qtd,
                    o.vl_preco_unitario AS preco,
                    NULL::numeric AS fator,
                    o.id_operacao AS seq
                FROM public.tb_operacao o
                JOIN public.tb_tipo_operacao top ON top.id_tipo_operacao = o.id_tipo_operacao
                WHERE o.id_carteira = rec_grupo.id_carteira
                  AND o.id_corretora = rec_grupo.id_corretora
                  AND o.id_ativo = rec_grupo.id_ativo
                  AND top.sg_tipo_operacao IN ('COMPRA', 'VENDA')

                UNION ALL

                SELECT e.dt_evento, top.sg_tipo_operacao, NULL, NULL, e.vl_fator, NULL
                FROM public.tb_evento_corporativo e
                JOIN public.tb_tipo_operacao top ON top.id_tipo_operacao = e.id_tipo_operacao
                WHERE e.id_ativo = rec_grupo.id_ativo
            ) eventos
            ORDER BY dt, (fator IS NULL), (tipo = 'VENDA'), seq
        LOOP
            IF rec_evento.fator IS NOT NULL THEN
                v_qt := TRUNC(v_qt * rec_evento.fator);
                IF rec_evento.fator <> 0 THEN
                    v_preco_medio := v_preco_medio / rec_evento.fator;
                END IF;
            ELSIF rec_evento.tipo = 'COMPRA' THEN
                v_preco_medio := CASE
                    WHEN (v_qt + rec_evento.qtd) = 0 THEN 0
                    ELSE ((v_qt * v_preco_medio) + (rec_evento.qtd * rec_evento.preco)) / (v_qt + rec_evento.qtd)
                END;
                v_qt := v_qt + rec_evento.qtd;
            ELSE
                IF (p_dt_inicio IS NULL OR rec_evento.dt >= p_dt_inicio)
                   AND (p_dt_fim IS NULL OR rec_evento.dt <= p_dt_fim) THEN
                    v_ganho := v_ganho + rec_evento.qtd * (rec_evento.preco - v_preco_medio);
                    v_qt_vendida := v_qt_vendida + rec_evento.qtd;
                END IF;
                v_qt := v_qt - rec_evento.qtd;
            END IF;
        END LOOP;

        IF v_qt_vendida <> 0 THEN
            INSERT INTO tmp_ganho_ativo (tmp_id_ativo, qt_vendida, ganho_realizado)
            VALUES (rec_grupo.id_ativo, v_qt_vendida, v_ganho)
            ON CONFLICT (tmp_id_ativo) DO UPDATE SET
                qt_vendida = tmp_ganho_ativo.qt_vendida + EXCLUDED.qt_vendida,
                ganho_realizado = tmp_ganho_ativo.ganho_realizado + EXCLUDED.ganho_realizado;
        END IF;
    END LOOP;

    RETURN QUERY
    SELECT t.tmp_id_ativo, a.sg_ticker, t.qt_vendida, round(t.ganho_realizado, 2)
    FROM tmp_ganho_ativo t
    JOIN public.tb_ativo a ON a.id_ativo = t.tmp_id_ativo
    ORDER BY t.ganho_realizado DESC;
END;
$$;
