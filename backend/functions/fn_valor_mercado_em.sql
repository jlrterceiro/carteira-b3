-- Valor de mercado de uma empresa em uma data: acoes em circulacao (ultimo trimestre <= data de tb_acoes_emissor, total - tesouraria; antes do
-- primeiro trimestre, o primeiro) corrigidas pelos eventos corporativos (desdobramento/grupamento/bonificacao) entre o fim do trimestre e a data,
-- x preco REAL do dia por classe: ON pelo preco do ticker ON e PN pelo do PN, na proporcao de acoes preferenciais do capital (UNIT nunca entra:
-- o preco da unit x todas as acoes contaria ON+PN em dobro). Sem ticker PN ou sem preco dele, usa o preco da ON pra tudo.
CREATE OR REPLACE FUNCTION public.fn_valor_mercado_em(p_id_emissor INTEGER, p_dt DATE)
RETURNS TABLE (acoes NUMERIC, mercado NUMERIC)
LANGUAGE sql STABLE AS $$
    WITH tri AS (
        SELECT e.dt_referencia, (e.qt_total - e.qt_tesouraria) AS base, COALESCE(e.qt_preferencial / NULLIF(e.qt_total, 0), 0) AS f_pn
        FROM public.tb_acoes_emissor e WHERE e.id_emissor = p_id_emissor
        ORDER BY (e.dt_referencia > p_dt), abs(e.dt_referencia - p_dt) LIMIT 1),
    a_on AS (
        SELECT a.id_ativo FROM public.tb_ativo a WHERE a.id_emissor = p_id_emissor
        ORDER BY (a.sg_classe = 'UNIT'), (a.sg_classe <> 'ON'), a.id_ativo LIMIT 1),
    a_pn AS (
        SELECT a.id_ativo FROM public.tb_ativo a WHERE a.id_emissor = p_id_emissor AND a.sg_classe = 'PN' ORDER BY a.id_ativo LIMIT 1),
    ev AS (
        SELECT exp(COALESCE(sum(ln(v.vl_fator)) FILTER (WHERE v.dt_evento > tri.dt_referencia AND v.dt_evento <= p_dt), 0)
                   - COALESCE(sum(ln(v.vl_fator)) FILTER (WHERE v.dt_evento > p_dt AND v.dt_evento <= tri.dt_referencia), 0)) AS f
        FROM tri, a_on LEFT JOIN public.tb_evento_corporativo v ON v.id_ativo = a_on.id_ativo AND v.vl_fator > 0),
    p_on AS (
        SELECT c.vl_fechamento AS preco FROM public.tb_cotacao_bruta c, a_on
        WHERE c.id_ativo = a_on.id_ativo AND c.dt_cotacao <= p_dt ORDER BY c.dt_cotacao DESC LIMIT 1),
    p_pn AS (
        SELECT c.vl_fechamento AS preco FROM public.tb_cotacao_bruta c, a_pn
        WHERE c.id_ativo = a_pn.id_ativo AND c.dt_cotacao <= p_dt ORDER BY c.dt_cotacao DESC LIMIT 1)
    SELECT tri.base * ev.f,
           tri.base * ev.f * ((1 - tri.f_pn) * p_on.preco + tri.f_pn * COALESCE((SELECT preco FROM p_pn), p_on.preco))
    FROM tri, ev, p_on WHERE tri.base > 0;
$$;
