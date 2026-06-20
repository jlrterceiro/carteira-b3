-- Balanco patrimonial por ativo (so acoes), raspado dos dados abertos da CVM
-- (dados.cvm.gov.br, ..._BPA_<ano>.csv pro ativo e ..._BPP_<ano>.csv pro passivo -- ver
-- tb_balanco_conta.sql pro dado bruto e scraper_balanco_patrimonial.py/popula_balanco.py pra
-- como a curadoria abaixo e extraida). Substitui a versao anterior baseada em yfinance
-- (tb_balanco_patrimonial_old_yfinance).
--
-- tp_periodo distingue o balanco anual (DFP) do trimestral (ITR) -- por ora so ITR esta
-- implementado, igual tb_dre. Sem fn_popula_* -- raspagem direta, nao depende de outra
-- tabela do projeto (exceto qt_acoes, ver abaixo).
--
-- Curadoria validada contra a carteira atual (3 usuarios) + 15 acoes aleatorias entre as
-- negociadas no ultimo pregao, cobrindo banco, construtora, mineracao, petroleo, varejo,
-- papel/celulose entre outros. Mesmo achado da DRE: bancos "de deposito" (BBAS3, BPAC3 etc.
-- -- nao BRBI11, banco de investimento, que segue o plano padrao) tem plano de contas
-- diferente pro ativo/passivo, sem o conceito de circulante/nao circulante (cd_conta '1.01'
-- e 'Caixa e Equivalentes de Caixa' pro banco, 'Ativo Circulante' pro padrao -- mesmo codigo,
-- conceito totalmente diferente). Por isso popula_balanco.py casa cada coluna por TEXTO de
-- ds_conta (normalizado), nunca por cd_conta fixo, exceto vl_ativo_total ('1') e
-- vl_passivo_total ('2') que sao estaveis nos dois perfis.
--
-- vl_ativo_circulante/vl_passivo_circulante/vl_capital_giro ficam NULL pro perfil banco --
-- esse conceito nao existe nesse plano de contas, nao e dado faltando.
--
-- vl_caixa: caixa + aplicacoes financeiras de curto prazo (1.01.01 + 1.01.02) pro perfil
-- padrao; so o caixa estreito (1.01, "Caixa e Equivalentes de Caixa") pro perfil banco --
-- o equivalente bancario de "aplicacoes financeiras" (1.02 "Ativos Financeiros") inclui
-- carteira de credito/emprestimos a clientes, que nao e caixa.
--
-- vl_patrimonio_liquido_total ("Patrimonio Liquido Consolidado") e vl_patrimonio_liquido
-- (atribuivel aos controladores) sao colunas distintas -- mesmo padrao da DRE (CPC 26 exige
-- separar quando ha subsidiaria nao 100%-controlada). Confirmado em EVEN3: total 2.305.504 -
-- participacao nao controladores 377.994 = 1.927.510, bate exato com o "Stockholders Equity"
-- do yfinance (que so contava a parte dos controladores, sem deixar isso explicito).
-- vl_participacao_nao_controladores reconcilia os dois; fica igual a vl_patrimonio_liquido_total
-- (e vl_participacao fica NULL) quando nao ha participacao minoritaria.
--
-- vl_divida_total pro perfil padrao soma "Emprestimos e Financiamentos" circulante e nao
-- circulante (2.01.04 + 2.02.01, texto estavel em todos os setores nao-financeiros
-- testados). Pro perfil banco usa "Passivos Financeiros ao Custo Amortizado" (2.02) inteiro
-- -- inclui depositos de cliente, mesmo problema ja documentado pro "Total Debt" do
-- yfinance (CLAUDE.md, decisao do usuario foi manter o numero "imperfeito" em vez de
-- nulificar pra esse setor; mantido aqui pela mesma razao). vl_divida_liquida SEMPRE
-- calculada como vl_divida_total - vl_caixa.
--
-- vl_valor_patrimonial_tangivel calculado como vl_patrimonio_liquido - "Intangivel" (texto)
-- -- a CVM nao tem uma linha pronta de "tangible book value" como o yfinance tinha.
--
-- qt_acoes CONTINUA vindo do yfinance (scraper_qt_acoes.py, so esse campo) -- o arquivo
-- composicao_capital da CVM tem erro de escala (1000x menor) em pelo menos VALE3 e ITSA4,
-- mas bate certo em PETR4 e EVEN3 -- sem como validar algoritmicamente quais empresas sao
-- afetadas sem outra fonte, optou-se por nao usar esse arquivo da CVM pra esse campo.

CREATE TABLE public.tb_balanco_patrimonial (
    id_balanco_patrimonial SERIAL PRIMARY KEY,
    id_ativo INTEGER NOT NULL REFERENCES public.tb_ativo(id_ativo),
    dt_referencia DATE NOT NULL,
    tp_periodo TEXT NOT NULL CHECK (tp_periodo IN ('ANUAL', 'TRIMESTRAL')),
    vl_ativo_total NUMERIC(20,2),
    vl_ativo_circulante NUMERIC(20,2),
    vl_passivo_total NUMERIC(20,2),
    vl_passivo_circulante NUMERIC(20,2),
    vl_patrimonio_liquido_total NUMERIC(20,2),
    vl_participacao_nao_controladores NUMERIC(20,2),
    vl_patrimonio_liquido NUMERIC(20,2),
    vl_divida_total NUMERIC(20,2),
    vl_divida_liquida NUMERIC(20,2),
    vl_caixa NUMERIC(20,2),
    vl_capital_giro NUMERIC(20,2),
    vl_imobilizado NUMERIC(20,2),
    vl_valor_patrimonial_tangivel NUMERIC(20,2),
    qt_acoes NUMERIC(20,2),
    ds_origem TEXT NOT NULL DEFAULT 'CVM',
    dh_criacao TIMESTAMP NOT NULL DEFAULT now(),
    dh_atualizacao TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (id_ativo, dt_referencia, tp_periodo)
);
