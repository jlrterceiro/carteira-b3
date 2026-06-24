-- Recalcula do zero a tb_provento_recebido a partir de tb_provento (valor por acao, por
-- ativo, na data ex) e tb_posicao_diaria (quantidade detida no ultimo dia "com", ou seja,
-- no dia anterior a data ex). Uma linha por (carteira, corretora, ativo, dt_ex) -- so nas
-- datas em que realmente houve provento, sem preencher os dias entre eventos como
-- tb_posicao_diaria faz.
--
-- Usa o valor LIQUIDO (vl_unitario_liquido, ja descontado o IRRF de 15% no caso de JCP --
-- ver scraper_proventos.py/ALIQUOTA_IMPOSTO) pra refletir o caixa real recebido na conta,
-- nao o bruto declarado pela empresa -- decisao do usuario, ja que bruto superestimava o
-- ganho em proventos de ativos com JCP. tb_provento pode ter mais de uma linha por
-- (id_ativo, dt_ex) quando ha mais de um tipo de provento na mesma data (ex: dividendo +
-- JCP no mesmo dia) -- soma tudo (SUM) antes de gravar, ja que tb_provento_recebido e por
-- evento de caixa real, nao por tipo.
--
-- vl_unitario_ajustado (nome do campo mantido por compatibilidade com fn_extrato_provento/
-- API) carrega o valor LIQUIDO somado, nao mais o "ajustado pra split" de quando a fonte
-- era yfinance -- nao precisa mais desfazer ajuste de split aqui, a B3 (fonte atual) ja
-- reporta o valor real da epoca direto, sem reescrita retroativa.
--
-- COALESCE pro fallback de FII/BDR (ainda em ds_origem='yfinance', fora do escopo da
-- migracao pra B3 -- ver scraper_proventos.py): vl_unitario_liquido fica NULL pra essas
-- linhas (yfinance nunca discriminou tipo/imposto), cai pro bruto-com-split-desfeito de
-- fn_popula_provento_ajustado, mesmo comportamento de antes da migracao.

CREATE OR REPLACE FUNCTION public.fn_popula_provento_recebido()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    TRUNCATE TABLE public.tb_provento_recebido;

    INSERT INTO public.tb_provento_recebido (
        id_carteira, id_corretora, id_ativo, dt_ex, qt_ativo, vl_unitario_ajustado, vl_total
    )
    SELECT
        pd.id_carteira,
        pd.id_corretora,
        pr.id_ativo,
        pr.dt_ex,
        pd.qt_ativo,
        SUM(COALESCE(pr.vl_unitario_liquido, pr.vl_unitario_ajustado)),
        round(pd.qt_ativo * SUM(COALESCE(pr.vl_unitario_liquido, pr.vl_unitario_ajustado)), 2)
    FROM public.tb_provento pr
    JOIN public.tb_posicao_diaria pd
        ON pd.id_ativo = pr.id_ativo
       AND pd.dt_posicao = pr.dt_ex - 1
    WHERE pd.qt_ativo > 0
    GROUP BY pd.id_carteira, pd.id_corretora, pr.id_ativo, pr.dt_ex, pd.qt_ativo;
END;
$$;
