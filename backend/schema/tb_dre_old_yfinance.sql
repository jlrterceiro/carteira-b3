-- HISTORICO/DESCONTINUADA -- substituida por tb_dre (fonte CVM), ver backend/schema/tb_dre.sql
-- e a secao "Demonstracao de resultado (DRE)" do CLAUDE.md. Mantida so como registro: o
-- "Net Interest Income" do yfinance usado aqui pra vl_resultado_financeiro nao corresponde
-- a linha oficial "Resultado Financeiro" da CVM (testado contra 3 trimestres da Even,
-- sinal E magnitude errados) -- por isso a troca de fonte.
--
-- DRE (Demonstracao de Resultado) por ativo (so acoes), raspada do yfinance (income_stmt e
-- quarterly_income_stmt). Subconjunto curado de 15 metricas "headline" validado contra 31
-- acoes (16 das 3 carteiras + 15 escolhidas aleatoriamente entre as negociadas no ultimo
-- pregao, cobrindo banco, petroleo, construcao, varejo, utilities, holding, agro, bebidas,
-- locacao, TI, saneamento e corretora) -- os ~70 campos granulares do yfinance variam muito
-- por setor (ex: banco nao tem o conceito de custo da receita/lucro bruto/resultado
-- operacional/EBITDA/EBIT), por isso ficam de fora.
--
-- tp_periodo distingue a DRE anual (income_stmt) da trimestral (quarterly_income_stmt).
-- Sem fn_popula_* aqui -- igual ao balanco, e dado raspado direto, nao depende de nenhuma
-- outra tabela do projeto.
--
-- vl_resultado_financeiro vem do "Net Interest Income" do yfinance (linha propria na DRE
-- brasileira, padrao CPC 26). NAO desmembramos em receita/despesa financeira separadas:
-- testado, "Interest Income" + "Interest Expense" do yfinance nao reconstroi o "Net Interest
-- Income" pra nenhuma das 30 acoes com esse dado (falta variacao monetaria/cambial e outros
-- itens) -- apresentar como receita/despesa financeira "oficiais" seria enganoso, mesmo
-- problema que ja vimos com o "Net Debt" pronto do yfinance no balanco.
--
-- vl_lucro_liquido_total ("Net Income Including Noncontrolling Interests") e
-- vl_lucro_liquido ("Net Income", atribuivel aos controladores) sao colunas distintas de
-- proposito -- CPC 26 exige separar quando ha subsidiaria nao 100%-controlada.
-- vl_participacao_nao_controladores reconcilia os dois; fica NULL/zero quando nao aplicavel
-- (empresa sem participacao minoritaria), nao e dado faltando.
--
-- BRBI11 (banco de investimento) nao tem LPA nem resultado financeiro separado -- o "juro" ja
-- esta dentro da receita principal dele.

CREATE TABLE public.tb_dre_old_yfinance (
    id_dre SERIAL PRIMARY KEY,
    id_ativo INTEGER NOT NULL REFERENCES public.tb_ativo(id_ativo),
    dt_referencia DATE NOT NULL,
    tp_periodo TEXT NOT NULL CHECK (tp_periodo IN ('ANUAL', 'TRIMESTRAL')),
    vl_receita_total NUMERIC(20,2),
    vl_custo_receita NUMERIC(20,2),
    vl_lucro_bruto NUMERIC(20,2),
    vl_despesas_operacionais NUMERIC(20,2),
    vl_resultado_operacional NUMERIC(20,2),
    vl_resultado_financeiro NUMERIC(20,2),
    vl_ebitda NUMERIC(20,2),
    vl_ebit NUMERIC(20,2),
    vl_lucro_antes_impostos NUMERIC(20,2),
    vl_impostos NUMERIC(20,2),
    vl_lucro_liquido_total NUMERIC(20,2),
    vl_participacao_nao_controladores NUMERIC(20,2),
    vl_lucro_liquido NUMERIC(20,2),
    vl_lpa_basico NUMERIC(10,4),
    vl_lpa_diluido NUMERIC(10,4),
    ds_origem TEXT NOT NULL DEFAULT 'yfinance',
    dh_criacao TIMESTAMP NOT NULL DEFAULT now(),
    dh_atualizacao TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (id_ativo, dt_referencia, tp_periodo)
);
