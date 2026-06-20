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

    RAISE NOTICE 'TODOS OS TESTES PASSARAM';
END;
$$;
