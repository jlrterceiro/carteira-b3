-- DERIVADA (fn_popula_provento_recebido_tipo): tb_provento_recebido aberto por TIPO de provento e com a data de
-- pagamento, pra rentabilidade "com caixa". vl_total e o liquido recebido (mesma base de tb_provento_recebido).
CREATE TABLE IF NOT EXISTS public.tb_provento_recebido_tipo (
    id_carteira      INTEGER NOT NULL,
    id_corretora     INTEGER NOT NULL,
    id_ativo         INTEGER NOT NULL,
    dt_ex            DATE    NOT NULL,
    ds_tipo_provento TEXT    NOT NULL,
    dt_pagamento     DATE    NOT NULL,
    fl_estimado      BOOLEAN NOT NULL,
    vl_total         NUMERIC(20,4) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tb_provento_recebido_tipo_01 ON public.tb_provento_recebido_tipo (id_carteira, id_corretora, dt_pagamento);
