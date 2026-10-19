-- Abre tb_provento_recebido (um valor por ativo/data ex) por TIPO de provento e anexa a data de pagamento
-- (tb_provento_pagamento: real quando a B3 informou, estimada senao). O liquido por tipo vem de tb_provento; como
-- tb_provento_recebido.vl_total e a soma dos tipos, o valor de cada tipo e vl_total rateado pelo liquido unitario do
-- tipo (so difere do liquido unitario quando a regra de IRRF de dividendo > R$50 mil de 2026 se aplica, o que nunca
-- ocorreu). Evento sem linha em tb_provento_pagamento cai na data ex (nao deveria acontecer: o scraper cobre todos).
CREATE OR REPLACE FUNCTION public.fn_popula_provento_recebido_tipo()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM public.tb_provento_recebido_tipo;

    INSERT INTO public.tb_provento_recebido_tipo
        (id_carteira, id_corretora, id_ativo, dt_ex, ds_tipo_provento, dt_pagamento, fl_estimado, vl_total)
    WITH liq AS (
        SELECT p.id_ativo, p.dt_ex, p.ds_tipo_provento,
               COALESCE(p.vl_unitario_liquido, p.vl_unitario_ajustado) AS liq_unit,
               SUM(COALESCE(p.vl_unitario_liquido, p.vl_unitario_ajustado)) OVER (PARTITION BY p.id_ativo, p.dt_ex) AS liq_soma
        FROM public.tb_provento p
    )
    SELECT pr.id_carteira, pr.id_corretora, pr.id_ativo, pr.dt_ex, l.ds_tipo_provento,
           GREATEST(COALESCE(pg.dt_pagamento, pr.dt_ex), pr.dt_ex),
           COALESCE(pg.fl_estimado, true),
           pr.vl_total * l.liq_unit / l.liq_soma
    FROM public.tb_provento_recebido pr
    JOIN liq l ON l.id_ativo = pr.id_ativo AND l.dt_ex = pr.dt_ex
    LEFT JOIN public.tb_provento_pagamento pg
           ON pg.id_ativo = pr.id_ativo AND pg.dt_ex = pr.dt_ex AND pg.ds_tipo_provento = l.ds_tipo_provento
    WHERE l.liq_soma > 0;
END;
$$;
