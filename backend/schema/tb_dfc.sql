-- Demonstracao de Fluxo de Caixa por ativo (so acoes), raspada dos dados abertos da CVM
-- (dados.cvm.gov.br, ..._DFC_MI_<ano>.csv -- Metodo Indireto, preferido -- com fallback pra
-- ..._DFC_MD_<ano>.csv -- Metodo Direto, poucas empresas -- ver tb_dfc_conta.sql pro dado
-- bruto e scraper_dfc.py/popula_dfc.py pra como a curadoria abaixo e extraida).
--
-- tp_periodo distingue o anual (DFP) do trimestral (ITR) -- por ora so ITR esta
-- implementado, igual tb_dre/tb_balanco_patrimonial. Sem fn_popula_* -- raspagem direta, nao
-- depende de outra tabela do projeto.
--
-- DIFERENCA em relacao a tb_dre/tb_balanco_patrimonial: a CVM so publica o fluxo de caixa
-- acumulado desde o inicio do ano fiscal (nunca o trimestre isolado, ao contrario da DRE que
-- publica os dois). Pra manter tp_periodo='TRIMESTRAL' significando "so aquele trimestre"
-- (mesma convencao usada em toda a DRE/balanco do projeto), popula_dfc.py ISOLA o trimestre
-- por subtracao dentro do mesmo ano fiscal: 1T = igual ao acumulado (sem subtracao, YTD 1T e
-- o proprio 1T); 2T = YTD 2T - YTD 1T; 3T = YTD 3T - YTD 2T. 4T fica de fora por enquanto --
-- dependeria do dado anual (DFP), fora de escopo igual a DRE/balanco.
--
-- Curadoria validada contra a carteira atual (3 usuarios) + 15 acoes aleatorias: a posicao
-- por cd_conta (6.01 a 6.05) e estavel em TODOS os perfis testados, incluindo banco (BBAS3)
-- e seguradora (BBSE3, so com o nome de 6.01 mudando pra "Caixa Liquido Atividades
-- Seguradora/Resseguradora") -- diferente da DRE/balanco, nao precisou de deteccao de
-- perfil nem casamento por texto pros 5 totais.
--
-- vl_caixa_operacional/investimento/financiamento/variacao_cambial somam exatamente
-- vl_variacao_caixa (identidade contabil, conferida na curadoria) -- serve de checagem de
-- consistencia.
--
-- Capex (aquisicao de imobilizado/intangivel, sub-conta de 6.02) ficou FORA da curadoria de
-- proposito -- a posicao e o texto variam muito mais que o resto do plano de contas testado
-- (EVEN3: "Aquisicao de Bens para o Ativo Imobilizado" em 6.02.01; VALE3: "Adicoes ao
-- imobilizado" em 6.02.05, com outras sub-contas de investimento financeiro misturadas;
-- KLBN3: capex florestal numa sub-conta separada da de imobilizado/intangivel) -- tentar
-- extrair de forma confiavel arriscaria number errado silenciosamente pra muitas empresas.
-- Quem precisar de capex especifico de uma empresa pode consultar tb_dfc_conta direto.

CREATE TABLE public.tb_dfc (
    id_dfc SERIAL PRIMARY KEY,
    id_ativo INTEGER NOT NULL REFERENCES public.tb_ativo(id_ativo),
    dt_referencia DATE NOT NULL,
    tp_periodo TEXT NOT NULL CHECK (tp_periodo IN ('ANUAL', 'TRIMESTRAL')),
    vl_caixa_operacional NUMERIC(20,2),
    vl_caixa_investimento NUMERIC(20,2),
    vl_caixa_financiamento NUMERIC(20,2),
    vl_variacao_cambial NUMERIC(20,2),
    vl_variacao_caixa NUMERIC(20,2),
    ds_origem TEXT NOT NULL DEFAULT 'CVM',
    dh_criacao TIMESTAMP NOT NULL DEFAULT now(),
    dh_atualizacao TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (id_ativo, dt_referencia, tp_periodo)
);
