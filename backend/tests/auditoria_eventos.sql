-- Audita cada evento corporativo contra o salto de preco na serie JA ajustada (tb_cotacao_ajustada.vl_fechamento).
--
-- Ideia: vl_fechamento = preco bruto / (produto dos eventos posteriores). Se o evento da data D esta
-- certo, a serie ajustada e CONTINUA em D (razao ~ 1). Se o evento e espurio (o preco bruto nao pulou),
-- a serie ajustada pula por F (razao ~ F). Eventos na mesma data se multiplicam (um por ativo+data).
--
--   classe                          | significado
--   CONFIRMADO                      | preco bruto pulou ~1/F no dia: evento certo
--   CONTRADITO (preco nao pulou)    | serie ajustada pula ~F: evento espurio, de perna unica ou mal datado
--   divergente (fator ou data...)   | pulou, mas por outro valor/dia
--   inconclusivo (fator pequeno)    | |ln F| < 0.2 (bonificacao ate ~22%): indistinguivel de oscilacao
--   sem preco                       | sem cotacao a 10 dias do evento (iliquido / fora da serie)
--
--   PGPASSWORD=... psql -h localhost -U terceiro -d investimentos -f backend/tests/auditoria_eventos.sql
CREATE TEMP TABLE ev AS
SELECT e.id_ativo, e.dt_evento, exp(sum(ln(e.vl_fator))) AS f,
       string_agg(DISTINCT e.ds_origem, '+') AS origem,
       string_agg(o.sg_tipo_operacao || ' ' || round(e.vl_fator, 4), ' & ' ORDER BY o.sg_tipo_operacao) AS descr
FROM public.tb_evento_corporativo e
JOIN public.tb_tipo_operacao o USING (id_tipo_operacao)
WHERE e.vl_fator > 0
GROUP BY 1, 2;

CREATE TEMP TABLE aud AS
SELECT ev.*,
  (SELECT c.vl_fechamento FROM public.tb_cotacao_ajustada c
    WHERE c.id_ativo = ev.id_ativo AND c.dt_cotacao < ev.dt_evento AND c.dt_cotacao >= ev.dt_evento - 10
    ORDER BY c.dt_cotacao DESC LIMIT 1) AS p_ant,
  (SELECT c.vl_fechamento FROM public.tb_cotacao_ajustada c
    WHERE c.id_ativo = ev.id_ativo AND c.dt_cotacao >= ev.dt_evento AND c.dt_cotacao <= ev.dt_evento + 10
    ORDER BY c.dt_cotacao LIMIT 1) AS p_dep
FROM ev;

SELECT CASE
         WHEN p_ant IS NULL OR p_dep IS NULL OR p_ant <= 0 OR p_dep <= 0 THEN 'sem preco'
         WHEN abs(ln(f)) < 0.2 THEN 'inconclusivo (fator pequeno)'
         WHEN abs(ln(p_dep / p_ant)) < 0.4 * abs(ln(f)) THEN 'CONFIRMADO'
         WHEN abs(ln(p_dep / p_ant) - ln(f)) < 0.4 * abs(ln(f)) THEN 'CONTRADITO (preco nao pulou)'
         ELSE 'divergente (fator ou data diferem)' END AS classe,
       count(*) AS eventos
FROM aud GROUP BY 1 ORDER BY 2 DESC;

-- os problematicos, com a origem e se alguem ja negociou o ativo
SELECT a.sg_ticker, aud.dt_evento, aud.descr, round(aud.f::numeric, 4) AS f_liquido,
       round((p_dep / p_ant)::numeric, 4) AS razao_preco_ajustado, aud.origem,
       EXISTS (SELECT 1 FROM public.tb_operacao o WHERE o.id_ativo = aud.id_ativo) AS tem_operacao
FROM aud JOIN public.tb_ativo a USING (id_ativo)
WHERE p_ant > 0 AND p_dep > 0 AND abs(ln(f)) >= 0.2 AND abs(ln(p_dep / p_ant)) >= 0.4 * abs(ln(f))
ORDER BY tem_operacao DESC, a.sg_ticker, aud.dt_evento;
