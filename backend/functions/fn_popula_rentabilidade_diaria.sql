-- Recalcula do zero a tb_rentabilidade_diaria: agrega tb_rentabilidade_ativo_diaria
-- (que e por ativo) somando ganho e base de capital, usando GROUPING SETS sobre
-- usuario/carteira/corretora -- uma linha por dia em cada uma das 8 combinacoes
-- possiveis (qualquer subconjunto dessas 3 colunas, dt_dia sempre presente).
-- Colunas fora da combinacao ficam NULL (significa "todos" naquela dimensao).
--
-- rentabilidade_pct = soma(vl_ganho)/soma(vl_base) do grupo naquele dia -- e a media
-- ponderada pelo capital exposto, nao uma media simples dos retornos por ativo.

CREATE OR REPLACE FUNCTION public.fn_popula_rentabilidade_diaria()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    TRUNCATE TABLE public.tb_rentabilidade_diaria;

    INSERT INTO public.tb_rentabilidade_diaria (
        dt_dia, id_usuario, id_carteira, id_corretora, vl_base, vl_ganho, rentabilidade_pct
    )
    SELECT
        r.dt_dia,
        u.id_usuario,
        c.id_carteira,
        r.id_corretora,
        SUM(r.vl_base),
        SUM(r.vl_ganho),
        round(100 * SUM(r.vl_ganho) / SUM(r.vl_base), 4)
    FROM public.tb_rentabilidade_ativo_diaria r
    JOIN public.tb_carteira c ON c.id_carteira = r.id_carteira
    JOIN public.tb_usuario u ON u.id_usuario = c.id_usuario
    GROUP BY GROUPING SETS (
        (r.dt_dia, u.id_usuario, c.id_carteira, r.id_corretora),
        (r.dt_dia, u.id_usuario, c.id_carteira),
        (r.dt_dia, u.id_usuario, r.id_corretora),
        (r.dt_dia, c.id_carteira, r.id_corretora),
        (r.dt_dia, u.id_usuario),
        (r.dt_dia, c.id_carteira),
        (r.dt_dia, r.id_corretora),
        (r.dt_dia)
    )
    HAVING SUM(r.vl_base) <> 0;
END;
$$;
