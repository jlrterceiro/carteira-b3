-- Tabela auxiliar/raw da DRE -- guarda TODAS as contas (plano de contas da CVM) de TODOS os
-- periodos, sem curadoria. E o "fato bruto" raspado direto do dado aberto da CVM
-- (dados.cvm.gov.br, arquivos itr_cia_aberta_<ano>.zip / dfp_cia_aberta_<ano>.zip,
-- ..._DRE_con_<ano>.csv), imune a qualquer particularidade setorial -- serve de auditoria e
-- de fonte pra qualquer metrica que a curadoria de tb_dre nao cobrir.
--
-- cd_conta segue o plano de contas oficial da CVM (ex: '3.01', '3.06.01') -- so serve pra
-- navegar a hierarquia (achar contas-filhas de uma conta-pai), NAO e estavel como chave de
-- identificacao entre empresas: o numero da conta final de resultado, por exemplo, e '3.11'
-- pro BBAS3 mas '3.09' pro BPAC3 (bancos com numero diferente de contas intermediarias). A
-- identificacao confiavel de "qual conta e o resultado financeiro/lucro liquido/etc" e por
-- texto (ds_conta), feita em scraper_dre.py na hora de popular tb_dre -- aqui fica so o dado
-- bruto como veio da CVM.
--
-- ds_origem e sempre 'CVM' (sem fallback de outra fonte, diferente de tb_balanco_patrimonial).
-- Sem fn_popula_* -- raspagem direta, nao depende de outra tabela do projeto.
--
-- vl_conta e NUMERIC(20,4) (nao 20,2) -- as contas de LPA (3.99.*) sao valores pequenos com
-- 4 casas decimais relevantes (ex: 0.3934); com so 2 casas, perderia precisao silenciosamente
-- (0.3934 arredondaria pra 0.39, erro de ~1% sem nenhum aviso). Achado depois de comparar a
-- curadoria contra um valor ja validado manualmente (ITSA4) e ver o LPA mudar de 0.3934 pra
-- 0.3900 -- o resto das contas (totais monetarios grandes) nao e afetado por essa diferenca.

CREATE TABLE public.tb_dre_conta (
    id_dre_conta SERIAL PRIMARY KEY,
    id_ativo INTEGER NOT NULL REFERENCES public.tb_ativo(id_ativo),
    dt_referencia DATE NOT NULL,
    tp_periodo TEXT NOT NULL CHECK (tp_periodo IN ('ANUAL', 'TRIMESTRAL')),
    cd_conta TEXT NOT NULL,
    ds_conta TEXT NOT NULL,
    vl_conta NUMERIC(20,4),
    ds_origem TEXT NOT NULL DEFAULT 'CVM',
    dh_criacao TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (id_ativo, dt_referencia, tp_periodo, cd_conta)
);
