-- Testes de regressao: valores conferidos manualmente contra fontes oficiais durante
-- o desenvolvimento. Roda como bloco PL/pgSQL anonimo; da RAISE EXCEPTION na primeira
-- falha. Nao testa tudo, so os pontos mais traicoeiros (ajuste de split em provento,
-- duplicata de evento corporativo, ordem cronologica do extrato).
--
-- Uso: PGPASSWORD=... psql -h localhost -U terceiro -d investimentos -f test_validacoes.sql

DO $$
DECLARE
    v_valor NUMERIC;
    v_qtd INTEGER;
BEGIN
    -- BBAS3 JCP de 13/06/2023: yfinance mostra 0.169316 (metade), oficial era
    -- 0.33863133949 (BB fez split 2:1 em 16/04/2024, depois da data ex).
    SELECT vl_unitario_ajustado INTO v_valor
    FROM tb_provento pr JOIN tb_ativo a ON a.id_ativo = pr.id_ativo
    WHERE a.sg_ticker = 'BBAS3' AND pr.dt_ex = '2023-06-13';

    IF v_valor IS NULL OR abs(v_valor - 0.33863133949) > 0.001 THEN
        RAISE EXCEPTION 'FALHOU: BBAS3 provento 13/06/2023 ajustado = %, esperado ~0.338631', v_valor;
    END IF;
    RAISE NOTICE 'OK: BBAS3 provento 13/06/2023 ajustado = %', v_valor;

    -- Nao deve existir par de eventos corporativos com mesmo fator a menos de 14
    -- dias de distancia (duplicata conhecida do yfinance).
    SELECT count(*) INTO v_qtd
    FROM tb_evento_corporativo e1
    JOIN tb_evento_corporativo e2 ON e2.id_ativo = e1.id_ativo
        AND e2.id_tipo_operacao = e1.id_tipo_operacao
        AND e2.vl_fator = e1.vl_fator
        AND e2.dt_evento > e1.dt_evento
        AND e2.dt_evento <= e1.dt_evento + 14;

    IF v_qtd <> 0 THEN
        RAISE EXCEPTION 'FALHOU: % par(es) de evento corporativo duplicado encontrados', v_qtd;
    END IF;
    RAISE NOTICE 'OK: nenhum evento corporativo duplicado';

    -- fn_extrato_ativo deve vir em ordem cronologica estrita (cada linha >= anterior).
    SELECT count(*) INTO v_qtd
    FROM (
        SELECT dt_evento, lag(dt_evento) OVER (ORDER BY dt_evento) AS anterior
        FROM fn_extrato_ativo('CGRA4', NULL)
        WHERE tipo <> 'TOTAL'
    ) t
    WHERE anterior IS NOT NULL AND dt_evento < anterior;

    IF v_qtd <> 0 THEN
        RAISE EXCEPTION 'FALHOU: fn_extrato_ativo(CGRA4) fora de ordem cronologica';
    END IF;
    RAISE NOTICE 'OK: fn_extrato_ativo em ordem cronologica';

    -- fn_provento_recebido e fn_extrato_provento devem bater no total (mesma fonte,
    -- agregacao diferente).
    SELECT round(sum(vl_recebido), 2) INTO v_valor FROM fn_provento_recebido(NULL,NULL,NULL,NULL,'jlrterceiro');
    IF NOT EXISTS (
        SELECT 1 FROM (
            SELECT round(sum(vl_total), 2) AS total FROM fn_extrato_provento(NULL,NULL,NULL,NULL,'jlrterceiro')
        ) t WHERE t.total = v_valor
    ) THEN
        RAISE EXCEPTION 'FALHOU: fn_provento_recebido (%) != fn_extrato_provento total', v_valor;
    END IF;
    RAISE NOTICE 'OK: fn_provento_recebido bate com fn_extrato_provento (%)', v_valor;

    -- Rentabilidade: a BASE de cada linha tem que ser o valor REAL da posicao na vespera (quantidade nominal x
    -- preco nominal), em qualquer unidade de evento. O bug antigo deixava a base multiplicada por
    -- 1/fn_fator_acumulado (IRBR3 30x, CASH3 10x). So linhas sem compra no dia (compra soma outra parcela).
    SELECT count(*) INTO v_qtd
    FROM public.tb_rentabilidade_ativo_diaria r
    JOIN public.tb_posicao_diaria p ON p.id_carteira = r.id_carteira AND p.id_corretora = r.id_corretora
         AND p.id_ativo = r.id_ativo AND p.dt_posicao = r.dt_dia - 1
    JOIN LATERAL (SELECT x.vl_fechamento FROM public.tb_cotacao_bruta x
                  WHERE x.id_ativo = r.id_ativo AND x.dt_cotacao < r.dt_dia ORDER BY x.dt_cotacao DESC LIMIT 1) prev ON TRUE
    WHERE p.qt_ativo > 0
      AND NOT EXISTS (SELECT 1 FROM public.tb_operacao o JOIN public.tb_tipo_operacao t USING (id_tipo_operacao)
                      WHERE o.id_carteira = r.id_carteira AND o.id_corretora = r.id_corretora AND o.id_ativo = r.id_ativo
                        AND o.dt_operacao = r.dt_dia AND t.sg_tipo_operacao = 'COMPRA')
      AND abs(r.vl_base / NULLIF(p.qt_ativo * prev.vl_fechamento, 0) - 1) > 0.001;
    IF v_qtd <> 0 THEN
        RAISE EXCEPTION 'FALHOU: % linhas de tb_rentabilidade_ativo_diaria com base diferente do valor real da posicao (unidade de evento)', v_qtd;
    END IF;
    RAISE NOTICE 'OK: base da rentabilidade = valor real da posicao (quantidade e preco na mesma unidade)';

    -- Proventos por tipo: tem que somar exatamente o mesmo que tb_provento_recebido (rateio por tipo sem perda) e todo
    -- evento precisa de data de pagamento >= data ex (real ou estimada).
    SELECT round(sum(vl_total), 2) INTO v_valor FROM public.tb_provento_recebido;
    IF (SELECT round(sum(vl_total), 2) FROM public.tb_provento_recebido_tipo) IS DISTINCT FROM v_valor THEN
        RAISE EXCEPTION 'FALHOU: tb_provento_recebido_tipo (%) nao soma tb_provento_recebido (%)',
            (SELECT round(sum(vl_total), 2) FROM public.tb_provento_recebido_tipo), v_valor;
    END IF;
    SELECT count(*) INTO v_qtd FROM public.tb_provento_recebido_tipo WHERE dt_pagamento < dt_ex;
    IF v_qtd <> 0 THEN
        RAISE EXCEPTION 'FALHOU: % proventos com pagamento antes da data ex', v_qtd;
    END IF;
    RAISE NOTICE 'OK: proventos por tipo somam tb_provento_recebido (%) e pagamento >= ex', v_valor;

    -- Serie de proventos (rentabilidade com proventos a receber / estilo Status Invest): conservacao por usuario no
    -- ultimo dia da serie. Soma dos proventos por data ex = total recebido com ex ate ali; soma dos pagos = total cujo
    -- pagamento ja ocorreu ate ali; e o recebivel nunca e negativo.
    SELECT count(*) INTO v_qtd
    FROM (
        SELECT m.id_usuario,
               round(sum(k.vl_prov_ex), 2)   AS ex_serie,
               round(sum(k.vl_prov_pgto), 2) AS pg_serie,
               round((SELECT COALESCE(sum(t.vl_total), 0) FROM public.tb_provento_recebido_tipo t JOIN public.tb_carteira c USING (id_carteira)
                      WHERE c.id_usuario = m.id_usuario AND t.dt_ex <= m.ult), 2) AS ex_esperado,
               round((SELECT COALESCE(sum(t.vl_total), 0) FROM public.tb_provento_recebido_tipo t JOIN public.tb_carteira c USING (id_carteira)
                      WHERE c.id_usuario = m.id_usuario AND t.dt_pagamento <= m.ult), 2) AS pg_esperado
        FROM (SELECT id_usuario, max(dt_dia) ult FROM public.tb_rentabilidade_caixa_diaria WHERE id_corretora IS NULL GROUP BY 1) m
        JOIN public.tb_rentabilidade_caixa_diaria k ON k.id_usuario = m.id_usuario AND k.id_corretora IS NULL
        GROUP BY m.id_usuario, m.ult
    ) t
    WHERE abs(ex_serie - ex_esperado) > 0.05 OR abs(pg_serie - pg_esperado) > 0.05;
    IF v_qtd <> 0 THEN
        RAISE EXCEPTION 'FALHOU: serie de proventos (ex/pagamento) nao bate com tb_provento_recebido_tipo em % usuario(s)', v_qtd;
    END IF;
    IF EXISTS (SELECT 1 FROM public.tb_rentabilidade_caixa_diaria WHERE vl_receber_ini < -0.005) THEN
        RAISE EXCEPTION 'FALHOU: recebivel negativo em tb_rentabilidade_caixa_diaria';
    END IF;
    RAISE NOTICE 'OK: serie de proventos (ex, pagamento, recebivel) bate com os proventos recebidos';

    RAISE NOTICE 'TODOS OS TESTES PASSARAM';
END;
$$;
