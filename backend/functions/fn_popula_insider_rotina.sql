-- Operacao de ROTINA (Cohen, Malloy e Pomorski, "Decoding Inside Information"): quem compra/vende todo ano no mesmo mes (programa de compra,
-- diversificacao, plano de remuneracao) nao sinaliza nada; o sinal esta nas operacoes OPORTUNISTAS. O formulario consolidado da CVM nao identifica a
-- pessoa, entao o "trader" aqui e o grupo (empresa, cargo declarante, direcao). Uma operacao e rotina se o grupo tambem negociou na mesma direcao
-- no mesmo mes do calendario em cada um dos 3 anos anteriores. Antes de 2022 nao ha 3 anos de historico (a carga comeca em 2019): fica NULL.
--   fl_rotina = true (rotina) | false (oportunista) | NULL (sem historico pra decidir)
-- So compra e venda a vista de acoes/units entram. Recalculada do zero pelo scraper de insiders.
ALTER TABLE public.tb_insider_movimentacao ADD COLUMN IF NOT EXISTS fl_rotina BOOLEAN;

CREATE OR REPLACE FUNCTION public.fn_popula_insider_rotina() RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE n INTEGER;
BEGIN
    UPDATE public.tb_insider_movimentacao SET fl_rotina = NULL WHERE fl_rotina IS NOT NULL;
    WITH meses AS (
        SELECT DISTINCT id_emissor, tipo_cargo, tipo_movimentacao,
               EXTRACT(YEAR FROM dt_movimentacao)::int AS ano, EXTRACT(MONTH FROM dt_movimentacao)::int AS mes
        FROM public.tb_insider_movimentacao
        WHERE tipo_movimentacao IN ('Compra à vista', 'Venda à vista') AND tipo_ativo IN ('Ações', 'Units') AND dt_movimentacao IS NOT NULL),
    marca AS (
        SELECT m.id_emissor, m.tipo_cargo, m.tipo_movimentacao, m.ano, m.mes,
               (SELECT count(*) FROM meses p WHERE p.id_emissor = m.id_emissor AND p.tipo_cargo = m.tipo_cargo
                  AND p.tipo_movimentacao = m.tipo_movimentacao AND p.mes = m.mes AND p.ano BETWEEN m.ano - 3 AND m.ano - 1) = 3 AS rotina
        FROM meses m WHERE m.ano >= 2022)
    UPDATE public.tb_insider_movimentacao t SET fl_rotina = CASE WHEN EXTRACT(YEAR FROM t.dt_movimentacao) < 2022 THEN NULL ELSE COALESCE(k.rotina, false) END
    FROM (SELECT DISTINCT ON (id_emissor, tipo_cargo, tipo_movimentacao, ano, mes) * FROM marca) k
    WHERE t.id_emissor = k.id_emissor AND t.tipo_cargo = k.tipo_cargo AND t.tipo_movimentacao = k.tipo_movimentacao
      AND EXTRACT(YEAR FROM t.dt_movimentacao)::int = k.ano AND EXTRACT(MONTH FROM t.dt_movimentacao)::int = k.mes
      AND t.tipo_ativo IN ('Ações', 'Units');
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;
