-- Tabela auxiliar/raw do balanco patrimonial -- guarda TODAS as contas (plano de contas da
-- CVM) de TODOS os periodos, sem curadoria. E o "fato bruto" raspado direto do dado aberto da
-- CVM (dados.cvm.gov.br, arquivos itr_cia_aberta_<ano>.zip, ..._BPA_<ano>.csv pro ativo e
-- ..._BPP_<ano>.csv pro passivo) -- mesmo padrao de tb_dre_conta. cd_conta comecando com '1'
-- e do ativo (BPA), comecando com '2' e do passivo (BPP); por isso as duas demonstracoes
-- cabem na mesma tabela sem precisar de uma coluna extra pra distinguir.
--
-- cd_conta segue o plano de contas oficial da CVM (ex: '1.01', '2.02.01') -- so serve pra
-- navegar a hierarquia, NAO e estavel como chave de identificacao entre empresas: bancos "de
-- deposito" (BBAS3, BPAC3 etc.) usam um plano de contas completamente diferente pro ativo/
-- passivo (sem o conceito de circulante/nao circulante). A identificacao confiavel de "qual
-- conta e patrimonio liquido/imobilizado/etc" e por texto (ds_conta), feita em
-- popula_balanco.py na hora de popular tb_balanco_patrimonial -- aqui fica so o dado bruto
-- como veio da CVM.
--
-- ds_origem e sempre 'CVM'. Sem fn_popula_* -- raspagem direta, nao depende de outra tabela
-- do projeto.

CREATE TABLE public.tb_balanco_conta (
    id_balanco_conta SERIAL PRIMARY KEY,
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
