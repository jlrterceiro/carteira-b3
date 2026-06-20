-- Recalcula do zero a tb_posicao_diaria a partir de tb_operacao (compra/venda/transferencia)
-- e tb_evento_corporativo (split/agrupamento/bonificacao), gerando uma linha por dia
-- (carteira, corretora, ativo) entre a primeira movimentacao e hoje.
--
-- Fracoes resultantes de eventos corporativos sao truncadas (sem mercado fracionario
-- separado). Preco medio nao se altera em venda; em compra, faz media ponderada;
-- em evento corporativo, e dividido pelo fator pra manter o custo total coerente.
--
-- Tie-break do mesmo dia: evento corporativo antes de operacao; dentro de operacao,
-- COMPRA antes de VENDA (extrato da B3 nao tem horario, e conta de pessoa fisica no
-- fracionario nao vende a descoberto -- se VENDA e COMPRA do mesmo ativo caem no
-- mesmo dia, a compra teve que vir primeiro na vida real).

CREATE OR REPLACE FUNCTION public.fn_popula_posicao_diaria()
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    rec_grupo RECORD;
    rec_evento RECORD;
    v_qt NUMERIC;
    v_preco_medio NUMERIC;
    v_dt_inicio DATE;
BEGIN
    TRUNCATE TABLE public.tb_posicao_diaria;

    CREATE TEMP TABLE tmp_posicao_evento (
        seq SERIAL,
        id_carteira INTEGER,
        id_corretora INTEGER,
        id_ativo INTEGER,
        dt_evento DATE,
        qt_ativo NUMERIC,
        vl_preco_medio NUMERIC
    ) ON COMMIT DROP;

    FOR rec_grupo IN
        SELECT DISTINCT id_carteira, id_corretora, id_ativo
        FROM (
            SELECT id_carteira, id_corretora, id_ativo
            FROM public.tb_operacao
            WHERE id_carteira IS NOT NULL AND id_corretora IS NOT NULL

            UNION

            SELECT id_carteira_destino, id_corretora_destino, id_ativo
            FROM public.tb_operacao
            WHERE id_carteira_destino IS NOT NULL AND id_corretora_destino IS NOT NULL
        ) grupos
    LOOP
        v_qt := 0;
        v_preco_medio := 0;
        v_dt_inicio := NULL;

        FOR rec_evento IN
            SELECT dt, tipo, qt_delta, preco, fator
            FROM (
                SELECT
                    o.dt_operacao AS dt,
                    top.sg_tipo_operacao AS tipo,
                    CASE
                        WHEN top.sg_tipo_operacao = 'COMPRA' THEN o.qt_ativo
                        WHEN top.sg_tipo_operacao = 'VENDA' THEN -o.qt_ativo
                        ELSE 0
                    END AS qt_delta,
                    o.vl_preco_unitario AS preco,
                    NULL::numeric AS fator
                FROM public.tb_operacao o
                JOIN public.tb_tipo_operacao top ON top.id_tipo_operacao = o.id_tipo_operacao
                WHERE o.id_carteira = rec_grupo.id_carteira
                  AND o.id_corretora = rec_grupo.id_corretora
                  AND o.id_ativo = rec_grupo.id_ativo
                  AND top.sg_tipo_operacao IN ('COMPRA', 'VENDA')

                UNION ALL

                SELECT o.dt_operacao, 'TRANSF_SAIDA', -o.qt_ativo, NULL, NULL
                FROM public.tb_operacao o
                JOIN public.tb_tipo_operacao top ON top.id_tipo_operacao = o.id_tipo_operacao
                WHERE o.id_carteira = rec_grupo.id_carteira
                  AND o.id_corretora = rec_grupo.id_corretora
                  AND o.id_ativo = rec_grupo.id_ativo
                  AND top.sg_tipo_operacao = 'TRANSF'

                UNION ALL

                SELECT o.dt_operacao, 'TRANSF_ENTRADA', COALESCE(o.qt_ativo_destino, o.qt_ativo), NULL, NULL
                FROM public.tb_operacao o
                JOIN public.tb_tipo_operacao top ON top.id_tipo_operacao = o.id_tipo_operacao
                WHERE o.id_carteira_destino = rec_grupo.id_carteira
                  AND o.id_corretora_destino = rec_grupo.id_corretora
                  AND o.id_ativo = rec_grupo.id_ativo
                  AND top.sg_tipo_operacao = 'TRANSF'

                UNION ALL

                SELECT e.dt_evento, top.sg_tipo_operacao, 0, NULL, e.vl_fator
                FROM public.tb_evento_corporativo e
                JOIN public.tb_tipo_operacao top ON top.id_tipo_operacao = e.id_tipo_operacao
                WHERE e.id_ativo = rec_grupo.id_ativo
            ) eventos
            ORDER BY dt, (fator IS NULL), (tipo = 'VENDA')
        LOOP
            IF rec_evento.fator IS NOT NULL THEN
                v_qt := TRUNC(v_qt * rec_evento.fator);
                IF rec_evento.fator <> 0 THEN
                    v_preco_medio := v_preco_medio / rec_evento.fator;
                END IF;
            ELSIF rec_evento.tipo = 'COMPRA' THEN
                v_preco_medio := CASE
                    WHEN (v_qt + rec_evento.qt_delta) = 0 THEN 0
                    ELSE ((v_qt * v_preco_medio) + (rec_evento.qt_delta * rec_evento.preco)) / (v_qt + rec_evento.qt_delta)
                END;
                v_qt := v_qt + rec_evento.qt_delta;
            ELSE
                v_qt := v_qt + rec_evento.qt_delta;
            END IF;

            IF v_dt_inicio IS NULL THEN
                v_dt_inicio := rec_evento.dt;
            END IF;

            INSERT INTO tmp_posicao_evento (id_carteira, id_corretora, id_ativo, dt_evento, qt_ativo, vl_preco_medio)
            VALUES (rec_grupo.id_carteira, rec_grupo.id_corretora, rec_grupo.id_ativo, rec_evento.dt, v_qt, v_preco_medio);
        END LOOP;
    END LOOP;

    INSERT INTO public.tb_posicao_diaria (dt_posicao, id_carteira, id_corretora, id_ativo, qt_ativo, vl_preco_medio)
    SELECT d.dia, g.id_carteira, g.id_corretora, g.id_ativo, s.qt_ativo, s.vl_preco_medio
    FROM (SELECT DISTINCT id_carteira, id_corretora, id_ativo, MIN(dt_evento) OVER (PARTITION BY id_carteira, id_corretora, id_ativo) AS dt_inicio
          FROM tmp_posicao_evento) g
    CROSS JOIN LATERAL generate_series(g.dt_inicio, CURRENT_DATE, INTERVAL '1 day') AS d(dia)
    JOIN LATERAL (
        SELECT qt_ativo, vl_preco_medio
        FROM tmp_posicao_evento e
        WHERE e.id_carteira = g.id_carteira
          AND e.id_corretora = g.id_corretora
          AND e.id_ativo = g.id_ativo
          AND e.dt_evento <= d.dia
        ORDER BY e.dt_evento DESC, e.seq DESC
        LIMIT 1
    ) s ON true;
END;
$$;
