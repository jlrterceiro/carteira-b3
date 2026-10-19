"""
Data de PAGAMENTO dos proventos em dinheiro (tb_provento_pagamento), sem apagar nada: so upsert.

Fonte: B3, GetListedSupplementCompany -> cashDividends {label, lastDatePrior (data-com), paymentDate, rate}. Esse
endpoint so lista ~12 meses; o que ficou de fora do que ja foi gravado continua la (por isso a tabela e persistente
e o scraper de proventos, que apaga e regrava tb_provento, nao a afeta). A data real sobrescreve a estimada.

Casamento: tb_provento (ativo, tipo, dt_ex) <-> cashDividends (tipo, lastDatePrior). dt_ex e o 1o pregao DEPOIS de
lastDatePrior, entao procuro lastDatePrior no pregao anterior ao ex (ate 5 dias antes, p/ feriado). A data de pagamento
e a mesma pra todas as classes da empresa.

Sem data real (evento antigo): estimada = data-com + mediana do atraso (dt_pagamento - dt_com) JA OBSERVADO da mesma
empresa e tipo (>= 1 observacao), senao da mesma empresa em qualquer tipo, senao 1 ano (365 dias). Nunca antes do ex.

    python3 scrape/scraper_pagamentos_b3.py [SG_EMISSOR]      # todos os emissores com acao, ou um so
"""
import bisect
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn
from scraper_eventos_corporativos_b3 import _get


def data_br(s):
    return datetime.strptime(s, '%d/%m/%Y').date()


def main():
    filtro = sys.argv[1] if len(sys.argv) > 1 else None
    conn = get_conn(); cur = conn.cursor()
    cur.execute('''SELECT e.id_emissor, e.sg_emissor FROM public.tb_emissor e
                   WHERE EXISTS (SELECT 1 FROM public.tb_ativo a JOIN public.tb_tipo_ativo ta USING (id_tipo_ativo)
                                 WHERE a.id_emissor = e.id_emissor AND ta.sg_tipo_ativo = 'ACAO')
                     AND (%s::text IS NULL OR e.sg_emissor = %s) ORDER BY 2''', (filtro, filtro))
    emissores = cur.fetchall()
    print(f'{len(emissores)} emissores')

    # 1) datas REAIS vindas da B3, por emissor
    reais = {}      # id_emissor -> {(tipo, data_com): dt_pagamento}
    falhas = []
    for k, (ide, sg) in enumerate(emissores, 1):
        try:
            r = _get('GetListedSupplementCompany', {'issuingCompany': sg, 'language': 'pt-br'})
            mapa = {}
            for e in (r[0].get('cashDividends') or []) if r else []:
                try:
                    pg = data_br(e['paymentDate'])
                    if pg.year < 2100:      # 31/12/9999 = "a definir" na B3: nao e data
                        mapa[(e['label'], data_br(e['lastDatePrior']))] = pg
                except Exception:
                    continue
            reais[ide] = mapa
        except Exception as ex:
            falhas.append((sg, repr(ex))); reais[ide] = {}
        if k % 50 == 0:
            print(f'  {k}/{len(emissores)} emissores consultados', flush=True)
        time.sleep(0.15)

    # 'a definir' (9999-12-31) gravado antes desta regra: volta a ser estimativa
    cur.execute("DELETE FROM public.tb_provento_pagamento WHERE dt_pagamento >= '2100-01-01'")
    print(cur.rowcount, 'datas 9999-12-31 removidas (viram estimativa)')

    # 2) calendario de pregao por ativo
    cur.execute('SELECT id_ativo, dt_cotacao FROM public.tb_cotacao_bruta ORDER BY 1, 2')
    cal = defaultdict(list)
    for ida, d in cur.fetchall():
        cal[ida].append(d)

    def data_com(ida, dx):
        L = cal.get(ida) or []
        i = bisect.bisect_left(L, dx)
        return L[i - 1] if i > 0 else dx - timedelta(days=1)

    # 3) eventos de provento (tb_provento) por emissor
    cur.execute('''SELECT a.id_emissor, p.id_ativo, p.ds_tipo_provento, p.dt_ex FROM public.tb_provento p
                   JOIN public.tb_ativo a USING (id_ativo) JOIN public.tb_tipo_ativo ta USING (id_tipo_ativo)
                   WHERE ta.sg_tipo_ativo = 'ACAO' AND a.id_emissor = ANY(%s)''', ([e[0] for e in emissores],))
    eventos = cur.fetchall()
    print(len(eventos), 'eventos de provento')

    # 4) atrasos reais ja conhecidos (inclui os gravados em execucoes anteriores) -> base das estimativas
    cur.execute('''SELECT a.id_emissor, pg.ds_tipo_provento, (pg.dt_pagamento - pg.dt_com) FROM public.tb_provento_pagamento pg
                   JOIN public.tb_ativo a USING (id_ativo) WHERE NOT pg.fl_estimado AND pg.dt_com IS NOT NULL''')
    lag_emp, lag_emp_any = defaultdict(list), defaultdict(list)
    for ide, tp, dias in cur.fetchall():
        if -5 <= dias <= 700:
            lag_emp[(ide, tp)].append(dias); lag_emp_any[ide].append(dias)

    def novos_reais():
        out = []
        for ide, ida, tp, dx in eventos:
            mapa = reais.get(ide) or {}
            dc = data_com(ida, dx)
            pg = next((mapa[(tp, dc - timedelta(days=k))] for k in range(0, 6) if (tp, dc - timedelta(days=k)) in mapa), None)
            if pg is not None:
                out.append((ida, tp, dx, dc, max(pg, dx)))
        return out

    reais_lista = novos_reais()
    for ida, tp, dx, dc, pg in reais_lista:   # atualiza as bases de atraso com o que chegou agora
        cur.execute('SELECT id_emissor FROM public.tb_ativo WHERE id_ativo = %s', (ida,))
        ide = cur.fetchone()[0]
        if -5 <= (pg - dc).days <= 700:
            lag_emp[(ide, tp)].append((pg - dc).days); lag_emp_any[ide].append((pg - dc).days)

    def estima(ide, tp, dc, dx):
        v = lag_emp.get((ide, tp)) or lag_emp_any.get(ide) or []
        dias = statistics.median(v) if v else 365
        return max(dc + timedelta(days=int(dias)), dx)

    # 5) grava: real sobrescreve; estimada so entra se nao houver real
    n_real = n_est = 0
    ja_real = {(ida, tp, dx) for ida, tp, dx, _, _ in reais_lista}
    for ida, tp, dx, dc, pg in reais_lista:
        cur.execute('''INSERT INTO public.tb_provento_pagamento (id_ativo, ds_tipo_provento, dt_ex, dt_com, dt_pagamento, fl_estimado)
                       VALUES (%s,%s,%s,%s,%s,false)
                       ON CONFLICT (id_ativo, ds_tipo_provento, dt_ex) DO UPDATE
                       SET dt_com = EXCLUDED.dt_com, dt_pagamento = EXCLUDED.dt_pagamento, fl_estimado = false, dh_atualizacao = now()''',
                    (ida, tp, dx, dc, pg))
        n_real += 1
    for ide, ida, tp, dx in eventos:
        if (ida, tp, dx) in ja_real:
            continue
        dc = data_com(ida, dx)
        cur.execute('''INSERT INTO public.tb_provento_pagamento (id_ativo, ds_tipo_provento, dt_ex, dt_com, dt_pagamento, fl_estimado)
                       VALUES (%s,%s,%s,%s,%s,true)
                       ON CONFLICT (id_ativo, ds_tipo_provento, dt_ex) DO UPDATE
                       SET dt_com = EXCLUDED.dt_com, dt_pagamento = EXCLUDED.dt_pagamento, dh_atualizacao = now()
                       WHERE public.tb_provento_pagamento.fl_estimado''',
                    (ida, tp, dx, dc, estima(ide, tp, dc, dx)))
        n_est += cur.rowcount
    conn.commit()
    print(f'datas REAIS gravadas: {n_real} | estimadas gravadas/atualizadas: {n_est} | falhas de consulta: {len(falhas)}')
    for sg, e in falhas[:5]:
        print('  falha', sg, e)
    conn.close()


if __name__ == '__main__':
    main()
