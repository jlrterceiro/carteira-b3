-- Serie diaria de proventos e do CAIXA de proventos por (usuario, corretora | todas), pra as rentabilidades "com caixa".
-- Fonte: tb_provento_recebido_tipo (liquido, data ex e data de pagamento) e os dias de tb_rentabilidade_diaria.
--
--   vl_prov_ex        provento liquido cujo ex cai no dia (ja esta dentro de tb_rentabilidade_diaria.vl_ganho)
--   vl_prov_pgto      provento liquido PAGO no dia. Pagamento em dia sem pregao entra no primeiro dia de serie >= data
--   vl_receber_ini    RECEBIVEL no inicio do dia: proventos com ex ANTES do dia e pagamento DEPOIS dele. Sai da conta
--                     no proprio dia do pagamento (o dinheiro foi sacado ou reinvestido; o reinvestimento reaparece
--                     como compra, entao manter o caixa contaria o mesmo dinheiro duas vezes). Sem pagamento ainda
--                     (data depois do ultimo dia da serie) segue como recebivel.
--   vl_caixa_pgto_ini soma dos proventos por data de pagamento ate o inicio do dia: usada so pelo modo "estilo Status
--                     Invest", onde o caixa nunca sai e nao rende.
-- Linhas por (usuario, corretora) e (usuario, NULL = todas as corretoras).
CREATE OR REPLACE FUNCTION public.fn_popula_rentabilidade_caixa()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM public.tb_rentabilidade_caixa_diaria;

    INSERT INTO public.tb_rentabilidade_caixa_diaria
        (dt_dia, id_usuario, id_corretora, vl_prov_ex, vl_prov_pgto, vl_receber_ini, vl_caixa_pgto_ini)
    WITH serie AS (
        SELECT id_usuario, id_corretora, dt_dia
        FROM public.tb_rentabilidade_diaria
        WHERE id_carteira IS NULL AND id_usuario IS NOT NULL
    ),
    ev AS (
        SELECT c.id_usuario, t.id_corretora, t.dt_ex, t.dt_pagamento, t.vl_total
        FROM public.tb_provento_recebido_tipo t JOIN public.tb_carteira c USING (id_carteira)
    ),
    ev_grp AS (
        SELECT id_usuario, id_corretora, dt_ex, dt_pagamento, vl_total FROM ev
        UNION ALL
        SELECT id_usuario, NULL::integer, dt_ex, dt_pagamento, vl_total FROM ev
    ),
    ev_eff AS (
        SELECT g.*,
               (SELECT MIN(s.dt_dia) FROM serie s
                 WHERE s.id_usuario = g.id_usuario AND s.id_corretora IS NOT DISTINCT FROM g.id_corretora
                   AND s.dt_dia >= g.dt_pagamento) AS dt_pgto_eff
        FROM ev_grp g
    ),
    dia AS (
        SELECT s.id_usuario, s.id_corretora, s.dt_dia,
               COALESCE((SELECT SUM(e.vl_total) FROM ev_eff e WHERE e.id_usuario = s.id_usuario
                           AND e.id_corretora IS NOT DISTINCT FROM s.id_corretora AND e.dt_ex = s.dt_dia), 0) AS prov_ex,
               COALESCE((SELECT SUM(e.vl_total) FROM ev_eff e WHERE e.id_usuario = s.id_usuario
                           AND e.id_corretora IS NOT DISTINCT FROM s.id_corretora AND e.dt_pgto_eff = s.dt_dia), 0) AS prov_pgto,
               COALESCE((SELECT SUM(e.vl_total) FROM ev_eff e WHERE e.id_usuario = s.id_usuario
                           AND e.id_corretora IS NOT DISTINCT FROM s.id_corretora AND e.dt_ex < s.dt_dia
                           AND (e.dt_pgto_eff IS NULL OR e.dt_pgto_eff > s.dt_dia)), 0) AS receber
        FROM serie s
    )
    SELECT dt_dia, id_usuario, id_corretora, prov_ex, prov_pgto, receber,
           COALESCE(SUM(prov_pgto) OVER w, 0)
    FROM dia
    WINDOW w AS (PARTITION BY id_usuario, id_corretora ORDER BY dt_dia ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING);
END;
$$;
