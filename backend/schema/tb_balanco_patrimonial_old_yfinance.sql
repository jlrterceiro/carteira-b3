-- HISTORICO/DESCONTINUADA -- substituida por tb_balanco_patrimonial (fonte CVM). Mantida so
-- como registro -- nao roda mais (scraper_balanco_patrimonial_old_yfinance.py).
--
-- Balanco patrimonial por ativo (so acoes), raspado do yfinance (balance_sheet e
-- quarterly_balance_sheet). Subconjunto curado de ~12 metricas "headline" que aparecem
-- consistentemente em todos os setores testados (banco, construtora, varejo) -- os ~88
-- campos granulares do yfinance variam muito por setor (ex: banco nao tem o conceito de
-- ativo/passivo circulante), por isso ficam de fora.
--
-- tp_periodo distingue o balanco anual (balance_sheet) do trimestral (quarterly_balance_sheet).
-- Sem fn_popula_* aqui -- diferente de provento/posicao, balanco e dado raspado direto, nao
-- depende de nenhuma outra tabela do projeto.
--
-- vl_caixa usa "Cash Cash Equivalents And Short Term Investments" quando disponivel (caixa +
-- aplicacoes financeiras de curto prazo), com fallback pro caixa estreito "Cash And Cash
-- Equivalents" quando o campo amplo nao existe.
--
-- vl_divida_liquida e SEMPRE calculada como vl_divida_total - vl_caixa -- o campo "Net Debt"
-- pronto do yfinance nao e confiavel (testado contra StatusInvest: pra PETR4 vinha com
-- metodologia diferente e errada, pra EVEN3/MELK3 so abatia o caixa estreito, inflando a
-- divida liquida quase ao nivel da divida bruta).

CREATE TABLE public.tb_balanco_patrimonial_old_yfinance (
    id_balanco_patrimonial SERIAL PRIMARY KEY,
    id_ativo INTEGER NOT NULL REFERENCES public.tb_ativo(id_ativo),
    dt_referencia DATE NOT NULL,
    tp_periodo TEXT NOT NULL CHECK (tp_periodo IN ('ANUAL', 'TRIMESTRAL')),
    vl_ativo_total NUMERIC(20,2),
    vl_ativo_circulante NUMERIC(20,2),
    vl_passivo_total NUMERIC(20,2),
    vl_passivo_circulante NUMERIC(20,2),
    vl_patrimonio_liquido NUMERIC(20,2),
    vl_divida_total NUMERIC(20,2),
    vl_divida_liquida NUMERIC(20,2),
    vl_caixa NUMERIC(20,2),
    vl_capital_giro NUMERIC(20,2),
    vl_imobilizado NUMERIC(20,2),
    vl_valor_patrimonial_tangivel NUMERIC(20,2),
    qt_acoes NUMERIC(20,2),
    ds_origem TEXT NOT NULL DEFAULT 'yfinance',
    dh_criacao TIMESTAMP NOT NULL DEFAULT now(),
    dh_atualizacao TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (id_ativo, dt_referencia, tp_periodo)
);
