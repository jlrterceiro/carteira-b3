-- DRE (Demonstracao de Resultado) por ativo (so acoes), raspada dos dados abertos da CVM
-- (dados.cvm.gov.br, ..._DRE_con_<ano>.csv -- ver tb_dre_conta.sql pro dado bruto e
-- scraper_dre.py pra como a curadoria abaixo e extraida). Substitui a versao anterior
-- baseada em yfinance (tb_dre_old_yfinance) -- o "Net Interest Income" do yfinance usado la
-- pra vl_resultado_financeiro nao correspondia a linha oficial "Resultado Financeiro" da CVM
-- (testado contra 3 trimestres da Even: sinal E magnitude errados).
--
-- tp_periodo distingue a DRE anual (DFP) da trimestral (ITR). Sem fn_popula_* -- raspagem
-- direta, nao depende de outra tabela do projeto.
--
-- Curadoria validada contra 31 acoes (16 das 3 carteiras + 15 aleatorias entre as negociadas
-- no ultimo pregao): 28/30 CNPJs encontrados seguem o mesmo plano de contas padrao (CPC 26)
-- com texto de ds_conta identico letra por letra em todos os codigos top-level -- so bancos
-- "de deposito" de verdade (testado em BBAS3, BPAC3; BRBI11 -- banco de investimento --
-- segue o plano padrao) tem plano de contas de "intermediacao financeira" diferente, E o
-- numero da conta de resultado final varia mesmo entre bancos (3.11 no BBAS3, 3.09 no
-- BPAC3). Por isso scraper_dre.py casa cada coluna por TEXTO de ds_conta (normalizado,
-- frases-ancora), nunca por cd_conta fixo.
--
-- vl_receitas_financeiras/vl_despesas_financeiras sao NOVAS em relacao a versao yfinance --
-- agora confiaveis (3.06.01 - 3.06.02 reconcilia exatamente com 3.06 "Resultado Financeiro",
-- testado em EVEN3: 35.160 - 11.036 = 24.124). Ficam NULL pro perfil banco -- esse
-- desmembramento nao existe nesse caso, ja vem embutido dentro de "intermediacao
-- financeira" sem separacao explicita.
--
-- Pro perfil banco, vl_receita_total/vl_custo_receita/vl_lucro_bruto/vl_despesas_operacionais
-- vem das contas de intermediacao financeira (conceitualmente equivalentes, nao "faltando").
-- vl_resultado_operacional e vl_lucro_antes_impostos saem iguais pra esse perfil (banco nao
-- tem um passo de resultado financeiro separado entre despesas operacionais e tributos) --
-- e esperado, nao e bug. vl_resultado_financeiro recebe o mesmo valor de vl_lucro_bruto
-- nesse perfil (pra um banco, o resultado da intermediacao financeira *e* o resultado
-- financeiro).
--
-- vl_ebitda/vl_ebit sairam da curadoria -- nao existem como conta na CVM (metrica voluntaria,
-- regulada por divulgacao mas nao por uma linha fixa da DRE). vl_lucro_liquido_total ("Lucro/
-- Prejuizo Consolidado do Periodo") e vl_lucro_liquido ("Atribuido aos Socios da Empresa
-- Controladora") sao colunas distintas de proposito -- CPC 26 exige separar quando ha
-- subsidiaria nao 100%-controlada. vl_participacao_nao_controladores reconcilia os dois;
-- fica NULL/zero quando nao aplicavel, nao e dado faltando.
--
-- vl_lpa_basico/vl_lpa_diluido: empresas tem 1 a 3 classes de acao (ON / ON+PN / ON+PNA+PNB).
-- A posicao das contas-filhas de LPA basico/diluido NAO e estavel entre empresas (SHUL4 tem
-- PN antes de ON) -- scraper_dre.py casa pelo texto da classe (tb_ativo.sg_classe) contra
-- ds_conta, nunca por posicao.

CREATE TABLE public.tb_dre (
    id_dre SERIAL PRIMARY KEY,
    id_ativo INTEGER NOT NULL REFERENCES public.tb_ativo(id_ativo),
    dt_referencia DATE NOT NULL,
    tp_periodo TEXT NOT NULL CHECK (tp_periodo IN ('ANUAL', 'TRIMESTRAL')),
    vl_receita_total NUMERIC(20,2),
    vl_custo_receita NUMERIC(20,2),
    vl_lucro_bruto NUMERIC(20,2),
    vl_despesas_operacionais NUMERIC(20,2),
    vl_resultado_operacional NUMERIC(20,2),
    vl_receitas_financeiras NUMERIC(20,2),
    vl_despesas_financeiras NUMERIC(20,2),
    vl_resultado_financeiro NUMERIC(20,2),
    vl_lucro_antes_impostos NUMERIC(20,2),
    vl_impostos NUMERIC(20,2),
    vl_lucro_liquido_total NUMERIC(20,2),
    vl_participacao_nao_controladores NUMERIC(20,2),
    vl_lucro_liquido NUMERIC(20,2),
    vl_lpa_basico NUMERIC(10,4),
    vl_lpa_diluido NUMERIC(10,4),
    ds_origem TEXT NOT NULL DEFAULT 'CVM',
    dh_criacao TIMESTAMP NOT NULL DEFAULT now(),
    dh_atualizacao TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (id_ativo, dt_referencia, tp_periodo)
);
