-- Tabela auxiliar/raw da demonstracao de fluxo de caixa -- guarda TODAS as contas (plano de
-- contas da CVM) de TODOS os periodos, sem curadoria. Mesmo padrao de tb_dre_conta/
-- tb_balanco_conta -- "fato bruto" raspado direto do dado aberto da CVM (dados.cvm.gov.br,
-- arquivos itr_cia_aberta_<ano>.zip, ..._DFC_MI_<ano>.csv -- Metodo Indireto, preferido -- com
-- fallback pra ..._DFC_MD_<ano>.csv -- Metodo Direto -- pras poucas empresas que so publicam
-- assim, ex: HAGA4).
--
-- DIFERENCA IMPORTANTE em relacao a tb_dre_conta: a CVM SO publica o fluxo de caixa
-- acumulado desde o inicio do ano fiscal (nunca o trimestre isolado) -- vl_conta aqui e
-- sempre o acumulado (YTD), nao o trimestre sozinho. dt_referencia e a data de fim do
-- periodo igual sempre, mas o periodo coberto (DT_INI_EXERC->DT_FIM_EXERC) sempre comeca em
-- 1o de janeiro daquele ano. O isolamento do trimestre (2T = YTD 2T - YTD 1T, etc) e feito na
-- curadoria, em popula_dfc.py, sobre os valores ja extraidos (tb_dfc), nao aqui -- aqui fica
-- o valor exatamente como veio da CVM.
--
-- cd_conta segue o plano de contas oficial da CVM (ex: '6.01', '6.02.01') -- so serve pra
-- navegar a hierarquia, nao e chave de identificacao estavel entre empresas (a posicao do
-- imobilizado/capex dentro de 6.02 varia muito mais que o resto do plano de contas testado
-- nesse projeto -- por isso a curadoria nao tenta extrair capex, so os 5 totais de
-- 6.01-6.05, estaveis em todos os perfis testados incluindo banco e seguradora).
--
-- ds_origem e sempre 'CVM'. Sem fn_popula_* -- raspagem direta, nao depende de outra tabela
-- do projeto.

CREATE TABLE public.tb_dfc_conta (
    id_dfc_conta SERIAL PRIMARY KEY,
    id_ativo INTEGER NOT NULL REFERENCES public.tb_ativo(id_ativo),
    dt_referencia DATE NOT NULL,
    tp_periodo TEXT NOT NULL CHECK (tp_periodo IN ('ANUAL', 'TRIMESTRAL')),
    cd_conta TEXT NOT NULL,
    ds_conta TEXT NOT NULL,
    vl_conta NUMERIC(20,2),
    ds_origem TEXT NOT NULL DEFAULT 'CVM',
    dh_criacao TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (id_ativo, dt_referencia, tp_periodo, cd_conta)
);
