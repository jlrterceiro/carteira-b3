-- Preco "de agora" de cada ativo + fechamento anterior (base da variacao do dia). UNICO ponto de leitura do preco atual
-- (fn_posicao_atual, fn_ganho_total).
--   * Se o ultimo pregao do COTAHIST (tb_cotacao_ajustada) e anterior ao dia da coleta intradia (tb_cotacao_intradia),
--     vale o intradia: atual = ultimo negocio, anterior = fechamento do ultimo pregao do COTAHIST.
--   * Senao (o COTAHIST do dia ja saiu completo, ou nao ha coleta) vale o COTAHIST: atual = ultimo pregao, anterior = o
--     pregao antes dele.
-- Todos os precos saem na base ajustada por evento de hoje: a quantidade da posicao e a de hoje, entao split/grupamento
-- nao distorce a variacao (o preco intradia e o real de hoje, que ja e a base atual).
DROP VIEW IF EXISTS public.vw_cotacao_atual;
CREATE VIEW public.vw_cotacao_atual AS
SELECT a.id_ativo,
       CASE WHEN i.dt_pregao > u.dt_atual THEN i.vl_preco ELSE u.atual END                AS vl_preco_atual,
       CASE WHEN i.dt_pregao > u.dt_atual THEN u.atual    ELSE u.anterior END             AS vl_preco_anterior,
       CASE WHEN i.dt_pregao > u.dt_atual THEN i.dt_pregao ELSE u.dt_atual END            AS dt_cotacao,
       CASE WHEN i.dt_pregao > u.dt_atual THEN i.dh_cotacao END                           AS dh_cotacao,
       CASE WHEN i.dt_pregao > u.dt_atual THEN 'INTRADIA' ELSE 'COTAHIST' END::text       AS ds_fonte
FROM public.tb_ativo a
CROSS JOIN LATERAL (
    SELECT (array_agg(x.vl_fechamento ORDER BY x.dt_cotacao DESC))[1] AS atual,
           (array_agg(x.vl_fechamento ORDER BY x.dt_cotacao DESC))[2] AS anterior,
           max(x.dt_cotacao) AS dt_atual
    FROM (SELECT dt_cotacao, vl_fechamento FROM public.tb_cotacao_ajustada
          WHERE id_ativo = a.id_ativo ORDER BY dt_cotacao DESC LIMIT 2) x
) u
LEFT JOIN public.tb_cotacao_intradia i ON i.id_ativo = a.id_ativo
WHERE u.atual IS NOT NULL;
