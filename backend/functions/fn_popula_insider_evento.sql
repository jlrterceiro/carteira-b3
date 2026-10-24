-- Monta tb_insider_evento a partir de tb_insider_movimentacao (compra/venda a vista de acoes/units, sem bloco e sem dado suspeito) e calcula o retorno
-- depois da divulgacao: entrada no fechamento do 1o pregao depois de dt_sinal; saida no ultimo pregao <= entrada + h meses (so se o prazo ja venceu e
-- a acao ainda negociava perto dele). Retorno da acao = vl_fechamento_ajustado (retorno total, com proventos), igual ao Ibovespa (indice de retorno total).
-- sg_perfil: rotina se a maior parte do valor do evento e de operacao de rotina (fl_rotina), oportunista se nao, desconhecido se nenhuma operacao tem a marca.
CREATE OR REPLACE FUNCTION public.fn_popula_insider_evento() RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE n INTEGER;
BEGIN
    DELETE FROM public.tb_insider_evento;
    INSERT INTO public.tb_insider_evento (id_emissor, dt_referencia, sg_direcao, sg_grupo, dt_sinal, qt_total, vl_total, sg_perfil)
    SELECT m.id_emissor, m.dt_referencia, CASE m.tipo_movimentacao WHEN 'Compra à vista' THEN 'C' ELSE 'V' END, g.grupo,
           GREATEST(min(m.dt_entrega), max(m.dt_movimentacao)), sum(m.qt_ativo), sum(m.vl_volume),
           CASE WHEN bool_and(m.fl_rotina IS NULL) THEN 'desconhecido'
                WHEN sum(m.vl_volume) FILTER (WHERE m.fl_rotina) * 2 > sum(m.vl_volume) THEN 'rotina' ELSE 'oportunista' END
    FROM public.tb_insider_movimentacao m
    CROSS JOIN LATERAL (VALUES ('todos'),
        ('administracao' || CASE WHEN m.tipo_cargo IN ('Conselho de Administração ou Vinculado', 'Diretor ou Vinculado', 'Conselho Fiscal ou Vinculado', 'Órgão Estatutário ou Vinculado') THEN '' ELSE '#' END),
        ('controlador'   || CASE WHEN m.tipo_cargo = 'Controlador ou Vinculado' THEN '' ELSE '#' END)) g(grupo)
    WHERE m.tipo_movimentacao IN ('Compra à vista', 'Venda à vista') AND m.tipo_ativo IN ('Ações', 'Units')
      AND m.dt_entrega IS NOT NULL AND m.vl_volume > 0 AND m.qt_ativo > 0
      AND NOT COALESCE(m.fl_bloco, false) AND NOT COALESCE(m.fl_suspeito, false)
      AND right(g.grupo, 1) <> '#'
    GROUP BY m.id_emissor, m.dt_referencia, m.tipo_movimentacao, g.grupo;

    -- acao do retorno: a mais negociada (volume em acoes x preco) da empresa
    UPDATE public.tb_insider_evento e SET id_ativo = a.id_ativo
    FROM (SELECT DISTINCT ON (t.id_emissor) t.id_emissor, t.id_ativo
          FROM (SELECT a.id_emissor, a.id_ativo, sum(c.qt_volume * c.vl_fechamento_nominal) AS fin
                FROM public.tb_ativo a JOIN public.tb_cotacao_ajustada c USING (id_ativo) GROUP BY 1, 2) t
          ORDER BY t.id_emissor, t.fin DESC NULLS LAST) a
    WHERE a.id_emissor = e.id_emissor;

    UPDATE public.tb_insider_evento e SET dt_entrada = (SELECT min(c.dt_cotacao) FROM public.tb_cotacao_ajustada c WHERE c.id_ativo = e.id_ativo AND c.dt_cotacao > e.dt_sinal);

    -- retornos por prazo (meses)
    UPDATE public.tb_insider_evento e SET
        (ret_1m, ibov_1m)   = (SELECT r.ra, r.ri FROM public.fn_retorno_apos(e.id_ativo, e.dt_entrada, 1) r),
        (ret_3m, ibov_3m)   = (SELECT r.ra, r.ri FROM public.fn_retorno_apos(e.id_ativo, e.dt_entrada, 3) r),
        (ret_6m, ibov_6m)   = (SELECT r.ra, r.ri FROM public.fn_retorno_apos(e.id_ativo, e.dt_entrada, 6) r),
        (ret_12m, ibov_12m) = (SELECT r.ra, r.ri FROM public.fn_retorno_apos(e.id_ativo, e.dt_entrada, 12) r)
    WHERE e.dt_entrada IS NOT NULL;
    GET DIAGNOSTICS n = ROW_COUNT;

    -- linha de base: 1o pregao de cada mes (de 2019 em diante) de cada empresa que aparece no estudo
    DELETE FROM public.tb_insider_base;
    CREATE TEMP TABLE IF NOT EXISTS tmp_base (id_ativo INTEGER, dt DATE, h INTEGER, ra NUMERIC, ri NUMERIC) ON COMMIT DROP;
    TRUNCATE tmp_base;
    INSERT INTO tmp_base
    SELECT t.id_ativo, t.dt, h.h, r.ra, r.ri
    FROM (SELECT DISTINCT e.id_ativo, d.dt
          FROM (SELECT DISTINCT id_ativo FROM public.tb_insider_evento WHERE id_ativo IS NOT NULL) e
          CROSS JOIN LATERAL (SELECT min(c.dt_cotacao) AS dt FROM public.tb_cotacao_ajustada c
                              WHERE c.id_ativo = e.id_ativo AND c.dt_cotacao >= DATE '2019-01-01' GROUP BY date_trunc('month', c.dt_cotacao)) d) t
    CROSS JOIN (VALUES (1), (3), (6), (12)) h(h)
    CROSS JOIN LATERAL public.fn_retorno_apos(t.id_ativo, t.dt, h.h) r;
    INSERT INTO public.tb_insider_base
    SELECT h, count(*), avg(ra - ri), percentile_cont(0.5) WITHIN GROUP (ORDER BY ra - ri), 100 * avg((ra > ri)::int)
    FROM tmp_base WHERE ra IS NOT NULL AND ri IS NOT NULL GROUP BY h;
    RETURN n;
END $$;

-- retorno (%) da acao e do Ibovespa de `p_entrada` ate o ultimo pregao <= p_entrada + p_meses (NULL se o prazo ainda nao venceu ou a acao parou de negociar)
CREATE OR REPLACE FUNCTION public.fn_retorno_apos(p_ativo INTEGER, p_entrada DATE, p_meses INTEGER)
RETURNS TABLE (ra NUMERIC, ri NUMERIC)
LANGUAGE sql STABLE AS $$
    WITH alvo AS (SELECT (p_entrada + make_interval(months => p_meses))::date AS dt),
    saida AS (SELECT c.dt_cotacao, c.vl_fechamento_ajustado AS p FROM public.tb_cotacao_ajustada c, alvo
              WHERE c.id_ativo = p_ativo AND c.dt_cotacao <= alvo.dt ORDER BY c.dt_cotacao DESC LIMIT 1),
    entrada AS (SELECT vl_fechamento_ajustado AS p FROM public.tb_cotacao_ajustada WHERE id_ativo = p_ativo AND dt_cotacao = p_entrada),
    ib_e AS (SELECT vl_nivel AS n FROM public.tb_benchmark_diario WHERE cd_benchmark = 'IBOV' AND dt_dia <= p_entrada ORDER BY dt_dia DESC LIMIT 1),
    ib_s AS (SELECT b.vl_nivel AS n FROM public.tb_benchmark_diario b, saida WHERE b.cd_benchmark = 'IBOV' AND b.dt_dia <= saida.dt_cotacao ORDER BY b.dt_dia DESC LIMIT 1)
    SELECT (saida.p / NULLIF(entrada.p, 0) - 1) * 100, (ib_s.n / NULLIF(ib_e.n, 0) - 1) * 100
    FROM saida, entrada, ib_e, ib_s, alvo
    WHERE alvo.dt <= (SELECT max(dt_cotacao) FROM public.tb_cotacao_ajustada WHERE id_ativo = p_ativo)
      AND alvo.dt <= (SELECT max(dt_dia) FROM public.tb_benchmark_diario WHERE cd_benchmark = 'IBOV')
      AND saida.dt_cotacao >= alvo.dt - 10;
$$;
