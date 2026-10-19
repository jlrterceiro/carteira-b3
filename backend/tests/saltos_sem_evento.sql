-- Rede de seguranca pra eventos corporativos que a B3 nao lista (ela nao devolve o historico
-- completo, ver CLAUDE.md): salto diario grande na serie de cotacao JA ajustada, sem nenhum
-- evento num raio de 7 dias, em ativo com volume e preco >= R$0,50. Rodar depois de atualizar
-- cotacoes/eventos e revisar a lista a mao (papel ilíquido/em recuperacao gera ruido).
--   PGPASSWORD=... psql -h localhost -U terceiro -d investimentos -v desde="'2015-01-01'" -f backend/tests/saltos_sem_evento.sql
\if :{?desde}
\else
  \set desde '''2015-01-01'''
\endif

WITH salto AS (
    SELECT id_ativo, dt_cotacao, vl_fechamento p, qt_volume v,
           lag(vl_fechamento) OVER w p0, lag(dt_cotacao) OVER w d0
    FROM public.tb_cotacao_ajustada
    WINDOW w AS (PARTITION BY id_ativo ORDER BY dt_cotacao)
)
SELECT a.sg_ticker, s.dt_cotacao, s.p0 AS preco_anterior, s.p AS preco,
       round((s.p / s.p0)::numeric, 3) AS razao,
       EXISTS (SELECT 1 FROM public.tb_operacao o WHERE o.id_ativo = s.id_ativo) AS tem_operacao
FROM salto s JOIN public.tb_ativo a USING (id_ativo)
WHERE s.dt_cotacao >= :desde::date
  AND s.p0 >= 0.5 AND s.p >= 0.5 AND s.v > 0
  AND s.dt_cotacao - s.d0 <= 15
  AND (s.p / s.p0 > 1.4 OR s.p / s.p0 < 0.71)
  AND NOT EXISTS (
      SELECT 1 FROM public.tb_evento_corporativo e
      WHERE e.id_ativo = s.id_ativo AND e.dt_evento BETWEEN s.dt_cotacao - 7 AND s.dt_cotacao + 7)
ORDER BY tem_operacao DESC, s.dt_cotacao DESC;
