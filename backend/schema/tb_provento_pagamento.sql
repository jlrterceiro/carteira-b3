-- Data de PAGAMENTO de cada provento em dinheiro. A B3 so informa (GetListedSupplementCompany.cashDividends.paymentDate)
-- os ultimos ~12 meses, e o scraper de proventos apaga e regrava tb_provento a cada execucao, por isso esta tabela e
-- SEPARADA e so recebe upsert: a data real acumula com o tempo. Eventos antigos (sem data real) ficam com data
-- ESTIMADA (fl_estimado = true): data-com + mediana do atraso observado da mesma empresa e tipo (ou do tipo, se a empresa
-- tiver menos de 2 observacoes). Conferido contra o extrato de Movimentacao da B3: 35 de 35 datas reais batem.
CREATE TABLE IF NOT EXISTS public.tb_provento_pagamento (
    id_provento_pagamento SERIAL PRIMARY KEY,
    id_ativo         INTEGER NOT NULL REFERENCES public.tb_ativo (id_ativo),
    ds_tipo_provento TEXT    NOT NULL,
    dt_ex            DATE    NOT NULL,
    dt_com           DATE,                      -- ultimo pregao antes do ex (data-com)
    dt_pagamento     DATE    NOT NULL,
    fl_estimado      BOOLEAN NOT NULL DEFAULT false,
    dh_atualizacao   TIMESTAMP DEFAULT now(),
    CONSTRAINT uk_tb_provento_pagamento_01 UNIQUE (id_ativo, ds_tipo_provento, dt_ex)
);
