-- Recalcula do zero a tb_rentabilidade_ativo_diaria: para cada (carteira, corretora,
-- ativo, dia de pregao), calcula o ganho em R$ do dia e a base de capital exposta,
-- separando as acoes em 3 grupos conforme o que aconteceu naquele dia:
--
--   * mantidas o dia todo (nao compradas/vendidas hoje): ganho = qtd * (fechamento_hoje - fechamento_ontem)
--   * vendidas hoje: ganho = qtd_vendida * (preco_venda_medio - fechamento_ontem)
--     (a posicao so existiu ate a venda, entao o "fim do dia" dela e o preco de venda)
--   * compradas hoje: ganho = qtd_comprada * (fechamento_hoje - preco_compra_medio)
--     (a posicao so passou a existir a partir da compra, entao o "inicio do dia" dela
--     e o preco de compra, nao o fechamento de ontem)
--
-- Usamos o fechamento de ontem como referencia (nao a abertura de hoje) pra capturar
-- o retorno overnight tambem -- senao o gap entre o fechamento de ontem e a abertura
-- de hoje fica de fora de qualquer dia. Isso importa especialmente na data ex de
-- provento: o mercado costuma abrir mais baixo, descontando o valor do provento; com
-- fechamento de ontem como base, essa queda aparece no ganho do dia e e compensada
-- pelo provento (somado abaixo), em vez de simplesmente desaparecer.
--
-- vl_base = qtd_inicio_dia * fechamento_ontem + qtd_comprada_hoje * preco_compra_medio
--           (capital exposto no dia: o que ja estava + o que foi adicionado)
--
-- Proventos (tb_provento_recebido, na data ex) somam direto no ganho do dia, sem
-- entrar na base -- e um ganho sobre o capital que ja estava exposto, nao um aporte.
--
-- So gera linha para dias em que houve cotacao do ativo (pregao) e exposicao > 0
-- (posicao no inicio do dia ou compra no dia).
--
-- UNIDADES (corrigido em 2026-10-18): tb_cotacao_ajustada traz o preco JA ajustado por todo evento corporativo
-- POSTERIOR aquela data (em "acoes de hoje"), enquanto tb_posicao_diaria e tb_operacao guardam quantidade e
-- preco NOMINAIS da epoca. Os dois lados tem que ir pra mesma unidade: o preco de compra/venda e dividido por
-- fn_fator_acumulado(ativo, data) e a QUANTIDADE e multiplicada pelo mesmo fator (posicao do inicio do dia:
-- fator de D-1, que ja inclui um evento que ocorra em D). Antes so o preco era convertido: o retorno de cada
-- ativo saia certo (ganho e base escalavam juntos), mas o PESO dele na carteira ficava errado em todo dia anterior
-- a um split/grupamento posterior (IRBR3 entrava 30x maior, CASH3 10x, SLCE3 0,4x) e distorcia o retorno
-- agregado. Conferido contra um calculo independente em valores nominais (diferenca maxima de 3e-8 p.p. por dia).
-- Os proventos ja estao em R$ reais (quantidade nominal x valor da epoca) e nao precisam de conversao.

CREATE OR REPLACE FUNCTION public.fn_popula_rentabilidade_ativo_diaria()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM public.tb_rentabilidade_ativo_diaria;

    INSERT INTO public.tb_rentabilidade_ativo_diaria (dt_dia, id_carteira, id_corretora, id_ativo, vl_base, vl_ganho)
    WITH grupos AS (
        SELECT id_carteira, id_corretora, id_ativo, MIN(dt_posicao) AS dt_inicio
        FROM public.tb_posicao_diaria
        GROUP BY id_carteira, id_corretora, id_ativo
    ),
    cotacoes AS (
        SELECT
            id_ativo,
            dt_cotacao,
            vl_abertura,
            vl_fechamento,
            LAG(vl_fechamento) OVER (PARTITION BY id_ativo ORDER BY dt_cotacao) AS vl_fechamento_anterior
        FROM public.tb_cotacao_ajustada
    ),
    compras AS (
        SELECT
            o.id_carteira, o.id_corretora, o.id_ativo, o.dt_operacao AS dt_dia,
            SUM(o.qt_ativo) * public.fn_fator_acumulado(o.id_ativo, o.dt_operacao) AS qtd,
            (SUM(o.qt_ativo * o.vl_preco_unitario) / SUM(o.qt_ativo))
                / public.fn_fator_acumulado(o.id_ativo, o.dt_operacao) AS preco_medio
        FROM public.tb_operacao o
        JOIN public.tb_tipo_operacao top ON top.id_tipo_operacao = o.id_tipo_operacao
        WHERE top.sg_tipo_operacao = 'COMPRA'
        GROUP BY o.id_carteira, o.id_corretora, o.id_ativo, o.dt_operacao
    ),
    vendas AS (
        SELECT
            o.id_carteira, o.id_corretora, o.id_ativo, o.dt_operacao AS dt_dia,
            SUM(o.qt_ativo) * public.fn_fator_acumulado(o.id_ativo, o.dt_operacao) AS qtd,
            (SUM(o.qt_ativo * o.vl_preco_unitario) / SUM(o.qt_ativo))
                / public.fn_fator_acumulado(o.id_ativo, o.dt_operacao) AS preco_medio
        FROM public.tb_operacao o
        JOIN public.tb_tipo_operacao top ON top.id_tipo_operacao = o.id_tipo_operacao
        WHERE top.sg_tipo_operacao = 'VENDA'
        GROUP BY o.id_carteira, o.id_corretora, o.id_ativo, o.dt_operacao
    )
    SELECT
        cot.dt_cotacao,
        g.id_carteira,
        g.id_corretora,
        g.id_ativo,
        (COALESCE(pos_ini.qt_ativo, 0) * public.fn_fator_acumulado(g.id_ativo, cot.dt_cotacao - 1)
            * COALESCE(cot.vl_fechamento_anterior, cot.vl_abertura))
            + (COALESCE(c.qtd, 0) * COALESCE(c.preco_medio, 0)) AS vl_base,
        (COALESCE(pos_ini.qt_ativo, 0) * public.fn_fator_acumulado(g.id_ativo, cot.dt_cotacao - 1) - COALESCE(v.qtd, 0))
            * (cot.vl_fechamento - COALESCE(cot.vl_fechamento_anterior, cot.vl_abertura))
            + COALESCE(v.qtd, 0) * (COALESCE(v.preco_medio, 0) - COALESCE(cot.vl_fechamento_anterior, cot.vl_abertura))
            + COALESCE(c.qtd, 0) * (cot.vl_fechamento - COALESCE(c.preco_medio, 0))
            + COALESCE(pr.vl_total, 0) AS vl_ganho
    FROM grupos g
    JOIN cotacoes cot
        ON cot.id_ativo = g.id_ativo
       AND cot.dt_cotacao >= g.dt_inicio
       AND cot.dt_cotacao <= CURRENT_DATE
    LEFT JOIN public.tb_posicao_diaria pos_ini
        ON pos_ini.id_carteira = g.id_carteira
       AND pos_ini.id_corretora = g.id_corretora
       AND pos_ini.id_ativo = g.id_ativo
       AND pos_ini.dt_posicao = cot.dt_cotacao - 1
    LEFT JOIN compras c
        ON c.id_carteira = g.id_carteira
       AND c.id_corretora = g.id_corretora
       AND c.id_ativo = g.id_ativo
       AND c.dt_dia = cot.dt_cotacao
    LEFT JOIN vendas v
        ON v.id_carteira = g.id_carteira
       AND v.id_corretora = g.id_corretora
       AND v.id_ativo = g.id_ativo
       AND v.dt_dia = cot.dt_cotacao
    LEFT JOIN public.tb_provento_recebido pr
        ON pr.id_carteira = g.id_carteira
       AND pr.id_corretora = g.id_corretora
       AND pr.id_ativo = g.id_ativo
       AND pr.dt_ex = cot.dt_cotacao
    WHERE COALESCE(pos_ini.qt_ativo, 0) > 0 OR COALESCE(c.qtd, 0) > 0;
END;
$$;
