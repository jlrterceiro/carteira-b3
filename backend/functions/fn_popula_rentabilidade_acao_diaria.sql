CREATE OR REPLACE FUNCTION public.fn_popula_rentabilidade_acao_diaria()
RETURNS void AS $$
BEGIN

DELETE FROM public.tb_rentabilidade_acao_diaria;

INSERT INTO public.tb_rentabilidade_acao_diaria
    (id_ativo, dt_dia, id_usuario, id_carteira, id_corretora,
     vl_retorno_pct, vl_retorno_acumulado, fl_tem_posicao)

WITH

-- Retorno diário bruto por (ativo, dia, usuario, carteira, corretora)
diario_base AS (
    SELECT
        rad.id_ativo,
        rad.dt_dia,
        c.id_usuario,
        rad.id_carteira,
        rad.id_corretora,
        rad.vl_base,
        rad.vl_ganho
    FROM public.tb_rentabilidade_ativo_diaria rad
    JOIN public.tb_carteira c ON c.id_carteira = rad.id_carteira
),

-- GROUPING SETS: 8 combinações de (usuario, carteira, corretora) por ativo/dia
-- NULL numa dimensão = "todos" naquela dimensão
diario_gs AS (
    SELECT
        id_ativo,
        dt_dia,
        id_usuario,
        id_carteira,
        id_corretora,
        SUM(vl_base)  AS vl_base_total,
        SUM(vl_ganho) AS vl_ganho_total,
        CASE WHEN SUM(vl_base) > 0
             THEN SUM(vl_ganho) / SUM(vl_base) * 100
             ELSE 0
        END AS pct_dia
    FROM diario_base
    GROUP BY id_ativo, dt_dia,
        GROUPING SETS(
            (id_usuario, id_carteira, id_corretora),
            (id_usuario, id_carteira),
            (id_usuario, id_corretora),
            (id_usuario),
            (id_carteira, id_corretora),
            (id_carteira),
            (id_corretora),
            ()
        )
),

-- Data de início por combinação (primeiro dia com posição)
combos AS (
    SELECT
        id_ativo,
        id_usuario,
        id_carteira,
        id_corretora,
        MIN(dt_dia) AS dt_inicio
    FROM diario_gs
    GROUP BY id_ativo, id_usuario, id_carteira, id_corretora
),

-- Calendário de pregões por ativo (tb_cotacao_ajustada como fonte de dias de negociação)
calendario AS (
    SELECT DISTINCT id_ativo, dt_cotacao AS dt_dia
    FROM public.tb_cotacao_ajustada
),

-- Expande cada combo ao longo de todos os pregões desde o primeiro dia com posição.
-- Dias sem posição ficam com pct_dia = 0 (linha flat) e fl_tem_posicao = false.
completo AS (
    SELECT
        cb.id_ativo,
        ca.dt_dia,
        cb.id_usuario,
        cb.id_carteira,
        cb.id_corretora,
        COALESCE(dg.pct_dia, 0)        AS pct_dia,
        (dg.dt_dia IS NOT NULL)        AS fl_tem_posicao
    FROM combos cb
    JOIN calendario ca
        ON ca.id_ativo = cb.id_ativo
       AND ca.dt_dia  >= cb.dt_inicio
    LEFT JOIN diario_gs dg
        ON  dg.id_ativo     = cb.id_ativo
        AND dg.dt_dia       = ca.dt_dia
        AND dg.id_usuario   IS NOT DISTINCT FROM cb.id_usuario
        AND dg.id_carteira  IS NOT DISTINCT FROM cb.id_carteira
        AND dg.id_corretora IS NOT DISTINCT FROM cb.id_corretora
),

-- Retorno acumulado via produto encadeado (EXP/LN) — dias de gap contribuem 0%,
-- mantendo o acumulado constante durante o período sem posição.
acumulado AS (
    SELECT
        id_ativo, dt_dia, id_usuario, id_carteira, id_corretora,
        pct_dia,
        fl_tem_posicao,
        (EXP(SUM(LN(1 + pct_dia / 100.0)) OVER (
            PARTITION BY id_ativo, id_usuario, id_carteira, id_corretora
            ORDER BY dt_dia
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )) - 1) * 100 AS vl_retorno_acumulado
    FROM completo
)

SELECT
    id_ativo, dt_dia, id_usuario, id_carteira, id_corretora,
    pct_dia            AS vl_retorno_pct,
    vl_retorno_acumulado,
    fl_tem_posicao
FROM acumulado;

END;
$$ LANGUAGE plpgsql;
