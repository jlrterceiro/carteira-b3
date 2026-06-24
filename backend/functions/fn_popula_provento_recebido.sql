-- Recalcula do zero a tb_provento_recebido a partir de tb_provento (valor por acao, por
-- ativo, na data ex) e tb_posicao_diaria (quantidade detida no ultimo dia "com", ou seja,
-- no dia anterior a data ex). Uma linha por (carteira, corretora, ativo, dt_ex) -- so nas
-- datas em que realmente houve provento, sem preencher os dias entre eventos como
-- tb_posicao_diaria faz.
--
-- Usa o valor LIQUIDO pra refletir o caixa real recebido na conta, nao o bruto declarado
-- pela empresa -- decisao do usuario, ja que bruto superestimava o ganho em proventos com
-- IRRF. tb_provento pode ter mais de uma linha por (id_ativo, dt_ex) quando ha mais de um
-- tipo de provento na mesma data (ex: dividendo + JCP no mesmo dia) -- soma tudo (SUM) antes
-- de gravar, ja que tb_provento_recebido e por evento de caixa real, nao por tipo.
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
--
-- DIVIDENDO a partir de 2026 (Lei 15.270/2025): IRRF de 10% só quando o total pago por uma
-- MESMA empresa a um MESMO usuario (pessoa fisica, id_usuario -- agregado entre todas as
-- carteiras/corretoras dele, o limiar e por CPF, nao por carteira) num MESMO mes passa de
-- R$50.000 -- nesse caso incide sobre o valor TOTAL do mes, nao so o excedente. Diferente do
-- JCP (aliquota fixa por data, calculada direto no scraper_proventos.py), esse calculo
-- depende da posicao de cada usuario, entao so pode ser feito aqui, nao em tb_provento
-- (generico, sem usuario). Tem regra de transicao: dividendo aprovado at 31/12/2025 fica
-- isento at 2028 mesmo pago depois -- usa tb_provento.dt_aprovacao (NULL trata como "nao
-- comprovadamente isento", ou seja, sujeito a regra nova, mais conservador). Restrito a
-- dt_ex >= 2026-01-01 -- a lei so vale a partir dai, dividendo pago antes fica de fora mesmo
-- sem dt_aprovacao (dado historico, sem essa coluna preenchida).
CREATE OR REPLACE FUNCTION public.fn_popula_provento_recebido()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    TRUNCATE TABLE public.tb_provento_recebido;

    WITH base AS (
        SELECT
            pd.id_carteira,
            pd.id_corretora,
            pr.id_ativo,
            pr.dt_ex,
            pd.qt_ativo,
            pr.ds_tipo_provento,
            pr.dt_aprovacao,
            pr.vl_unitario AS vl_bruto_unit,
            COALESCE(pr.vl_unitario_liquido, pr.vl_unitario_ajustado) AS vl_liquido_base_unit,
            c.id_usuario,
            a.id_emissor
        FROM public.tb_provento pr
        JOIN public.tb_posicao_diaria pd
            ON pd.id_ativo = pr.id_ativo AND pd.dt_posicao = pr.dt_ex - 1
        JOIN public.tb_carteira c ON c.id_carteira = pd.id_carteira
        JOIN public.tb_ativo a ON a.id_ativo = pr.id_ativo
        WHERE pd.qt_ativo > 0
    ),
    dividendo_sujeito_regra_nova AS (
        SELECT id_usuario, id_emissor, date_trunc('month', dt_ex)::date AS mes_referencia,
               qt_ativo, vl_bruto_unit
        FROM base
        WHERE ds_tipo_provento = 'DIVIDENDO'
          AND dt_ex >= '2026-01-01'
          AND (dt_aprovacao IS NULL OR dt_aprovacao > '2025-12-31')
    ),
    limiar_mes AS (
        SELECT id_usuario, id_emissor, mes_referencia, SUM(qt_ativo * vl_bruto_unit) AS total_bruto_mes
        FROM dividendo_sujeito_regra_nova
        GROUP BY id_usuario, id_emissor, mes_referencia
    ),
    com_valor_final AS (
        SELECT
            b.id_carteira, b.id_corretora, b.id_ativo, b.dt_ex, b.qt_ativo,
            CASE
                WHEN b.ds_tipo_provento = 'DIVIDENDO'
                     AND b.dt_ex >= '2026-01-01'
                     AND (b.dt_aprovacao IS NULL OR b.dt_aprovacao > '2025-12-31')
                     AND COALESCE(lm.total_bruto_mes, 0) > 50000
                THEN b.vl_bruto_unit * 0.90
                ELSE b.vl_liquido_base_unit
            END AS vl_unitario_final
        FROM base b
        LEFT JOIN limiar_mes lm
            ON lm.id_usuario = b.id_usuario AND lm.id_emissor = b.id_emissor
           AND lm.mes_referencia = date_trunc('month', b.dt_ex)::date
    )
    INSERT INTO public.tb_provento_recebido (
        id_carteira, id_corretora, id_ativo, dt_ex, qt_ativo, vl_unitario_ajustado, vl_total
    )
    SELECT
        id_carteira, id_corretora, id_ativo, dt_ex, qt_ativo,
        SUM(vl_unitario_final),
        round(qt_ativo * SUM(vl_unitario_final), 2)
    FROM com_valor_final
    GROUP BY id_carteira, id_corretora, id_ativo, dt_ex, qt_ativo;
END;
$$;
