-- Extrato detalhado de um ativo: compras, vendas, splits e agrupamentos, em ordem
-- cronologica (preco medio e calculado por grupo carteira+corretora+ativo, igual
-- as outras funcoes, mas o extrato final mistura todas as corretoras por data).
-- Em cada venda mostra o ganho realizado daquela venda. No final, uma linha TOTAL
-- com a soma de todos os ganhos.
--
-- Tie-break do mesmo dia: evento corporativo antes de operacao; dentro de operacao,
-- COMPRA antes de VENDA. O extrato da B3 nao tem horario, so a ordem das linhas no
-- arquivo (que vira id_operacao), e essa ordem nem sempre e a ordem real de execucao
-- -- conta de pessoa fisica no fracionario nao vende a descoberto, entao se uma VENDA
-- e uma COMPRA do mesmo ativo caem no mesmo dia, a compra teve que vir primeiro.

CREATE OR REPLACE FUNCTION public.fn_extrato_ativo(
    p_sg_ticker TEXT,
    p_sg_usuario TEXT DEFAULT NULL
)
RETURNS TABLE (
    nm_corretora TEXT,
    dt_evento DATE,
    tipo TEXT,
    quantidade NUMERIC,
    preco NUMERIC,
    fator NUMERIC,
    qt_apos NUMERIC,
    preco_medio_apos NUMERIC,
    ganho_venda NUMERIC
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_id_ativo INTEGER;
    rec_grupo RECORD;
    rec_evento RECORD;
    v_qt NUMERIC;
    v_preco_medio NUMERIC;
    v_ganho_venda NUMERIC;
    v_ganho_total NUMERIC := 0;
BEGIN
    SELECT id_ativo INTO v_id_ativo FROM public.tb_ativo WHERE sg_ticker = p_sg_ticker;
    IF v_id_ativo IS NULL THEN
        SELECT id_ativo INTO v_id_ativo FROM public.tb_ticker_historico WHERE sg_ticker_antigo = p_sg_ticker;
    END IF;
    IF v_id_ativo IS NULL THEN
        RAISE EXCEPTION 'ativo % nao encontrado', p_sg_ticker;
    END IF;

    DROP TABLE IF EXISTS tmp_extrato_ativo;
    CREATE TEMP TABLE tmp_extrato_ativo (
        seq SERIAL,
        nm_corretora TEXT,
        dt_evento DATE,
        tipo TEXT,
        quantidade NUMERIC,
        preco NUMERIC,
        fator NUMERIC,
        qt_apos NUMERIC,
        preco_medio_apos NUMERIC,
        ganho_venda NUMERIC
    ) ON COMMIT DROP;

    FOR rec_grupo IN
        SELECT DISTINCT o.id_carteira, o.id_corretora, cor.nm_corretora
        FROM public.tb_operacao o
        JOIN public.tb_carteira c ON c.id_carteira = o.id_carteira
        JOIN public.tb_usuario u ON u.id_usuario = c.id_usuario
        JOIN public.tb_corretora cor ON cor.id_corretora = o.id_corretora
        WHERE o.id_ativo = v_id_ativo
          AND (p_sg_usuario IS NULL OR u.sg_usuario = p_sg_usuario)
    LOOP
        v_qt := 0;
        v_preco_medio := 0;

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
                  AND o.id_ativo = v_id_ativo
                  AND top.sg_tipo_operacao IN ('COMPRA', 'VENDA')

                UNION ALL

                SELECT e.dt_evento, top.sg_tipo_operacao, NULL, NULL, e.vl_fator, NULL
                FROM public.tb_evento_corporativo e
                JOIN public.tb_tipo_operacao top ON top.id_tipo_operacao = e.id_tipo_operacao
                WHERE e.id_ativo = v_id_ativo
            ) eventos
            ORDER BY dt, (eventos.fator IS NULL), (eventos.tipo = 'VENDA'), seq
        LOOP
            v_ganho_venda := NULL;

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
                v_ganho_venda := round(rec_evento.qtd * (rec_evento.preco - v_preco_medio), 2);
                v_ganho_total := v_ganho_total + v_ganho_venda;
                v_qt := v_qt - rec_evento.qtd;
            END IF;

            INSERT INTO tmp_extrato_ativo (
                nm_corretora, dt_evento, tipo, quantidade, preco, fator, qt_apos, preco_medio_apos, ganho_venda
            ) VALUES (
                rec_grupo.nm_corretora, rec_evento.dt, rec_evento.tipo, rec_evento.qtd, rec_evento.preco,
                rec_evento.fator, v_qt, round(v_preco_medio, 2), v_ganho_venda
            );
        END LOOP;
    END LOOP;

    RETURN QUERY
    SELECT t.nm_corretora, t.dt_evento, t.tipo, t.quantidade, t.preco, t.fator, t.qt_apos, t.preco_medio_apos, t.ganho_venda
    FROM tmp_extrato_ativo t
    ORDER BY t.dt_evento, t.seq;

    RETURN QUERY
    SELECT NULL::text, NULL::date, 'TOTAL'::text, NULL::numeric, NULL::numeric, NULL::numeric, NULL::numeric, NULL::numeric, round(v_ganho_total, 2);
END;
$$;
