"""
Data de PAGAMENTO dos proventos antigos, pelo formulario "Relatorio Proventos" que as empresas entregam a CVM (categoria
do indice IPE, de 2022 em diante). A API de proventos da B3 so lista ~12 meses; este formulario cobre o resto.

O PDF e um formulario estruturado: "Ultimo dia de negociacao com Direitos" (data-com) e uma tabela por ISIN com
Valor Bruto (R$/acao), periodo e Data de Pagamento. Casamento com tb_provento: emissor (CNPJ do IPE) + data-com + valor
bruto por acao. A data real so entra onde hoje ha ESTIMATIVA (nunca sobrescreve a da B3).

    python3 scrape/scraper_pagamentos_cvm.py [--aplica] [--ano-ini 2022] [SG_EMISSOR]

Sem --aplica so mede: quantas datas casaram e quantas batem com as datas reais da B3 (validacao).
"""
import bisect
import csv
import io
import os
import re
import sys
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn
from cnpj_emissor import fetch_emissores_cnpj
import prototipo_eventos_cvm as P

DATA = r'(\d{2})/(\d{2})/(\d{4})'
LINHA_RX = re.compile(r'(\d+[.,]\d{4,})\s+.*?(\d{1,2})/(\d{1,2})/(\d{4})\s*$')
COM_RX = re.compile(r'Ultimo dia de negocia[^\n]*\n\s*' + DATA + r'\s+' + DATA)
# layout de 2022: datas em mes/dia/ano com hora ("11/30/2022 12:00:00 AM"), valor com ponto
COM_US_RX = re.compile(r'Ultimo dia de negocia[^\n]*\n\s*\d{1,2}/\d{1,2}/\d{4}[^\n]*?\s+(\d{1,2})/(\d{1,2})/(\d{4})')


def d(g):
    return date(int(g[2]), int(g[1]), int(g[0]))


def data_ambigua(a, b, ano, dcom):
    """Formularios de 2022 (datas com hora AM/PM) misturam dia/mes e mes/dia: so aceita quando so UMA leitura e valida e
    cai depois da data-com; se as duas servem e diferem, descarta (continua estimada)."""
    cand = set()
    for dia, mes in ((a, b), (b, a)):
        try:
            x = date(ano, mes, dia)
        except ValueError:
            continue
        if x >= dcom - timedelta(days=1):
            cand.add(x)
    return cand.pop() if len(cand) == 1 else None


def parse(texto):
    """-> (data_com, [(valor_bruto, dt_pagamento)]) ou None"""
    m = COM_RX.search(texto)
    us = False
    if m:
        dcom = d(m.group(4, 5, 6))
    else:
        us = True
        m = COM_US_RX.search(texto)
        if not m:
            return None
        dcom = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    corpo = texto[m.end():].split('Parcelamento')[0]
    linhas = []
    for ln in corpo.splitlines():
        r = LINHA_RX.search(ln.strip())
        if r:
            if us:
                pg = data_ambigua(int(r.group(2)), int(r.group(3)), int(r.group(4)), dcom)
            else:
                try:
                    pg = date(int(r.group(4)), int(r.group(3)), int(r.group(2)))
                except ValueError:
                    pg = None
            if pg:
                linhas.append((float(r.group(1).replace(',', '.')), pg))
    return (dcom, linhas) if linhas else None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    aplica = '--aplica' in sys.argv
    ano_ini = int(sys.argv[sys.argv.index('--ano-ini') + 1]) if '--ano-ini' in sys.argv else 2022
    args = [a for a in args if not a.isdigit()]
    filtro = args[0] if args else None
    conn = get_conn(); cur = conn.cursor()

    cur.execute('''SELECT e.id_emissor, e.sg_emissor FROM public.tb_emissor e WHERE %s::text IS NULL OR e.sg_emissor = %s''',
                (filtro, filtro))
    sg = dict(cur.fetchall())
    cnpj2emissor = {}
    for ide, cnpj, _, _ in fetch_emissores_cnpj(conn):
        if filtro is None or sg.get(ide) == filtro:
            cnpj2emissor[cnpj.strip()] = ide
    print(f'{len(set(cnpj2emissor.values()))} emissores')

    # 1) formularios no indice IPE
    forms = []
    for ano in range(ano_ini, date.today().year + 1):
        with zipfile.ZipFile(P.baixa_ipe(ano)) as z:
            nome = [n for n in z.namelist() if n.endswith('.csv')][0]
            with z.open(nome) as f:
                for r in csv.DictReader(io.TextIOWrapper(f, encoding='latin-1'), delimiter=';'):
                    ide = cnpj2emissor.get(r['CNPJ_Companhia'].strip())
                    if ide and r['Categoria'] == 'Relatório Proventos' and r['Link_Download']:
                        forms.append((ide, r['Data_Entrega'][:10], r['Link_Download']))
    print(len(forms), 'formularios de proventos')

    # 2) texto dos PDFs (cache em disco, em paralelo)
    with ThreadPoolExecutor(8) as ex:
        textos = list(ex.map(lambda f: P.texto_anexo(f[2]), forms))
    sem_texto = sum(1 for t in textos if not t)

    # 3) por (emissor, data-com): valor -> data de pagamento; a versao entregue por ultimo vence
    base = defaultdict(dict)     # (ide, data_com) -> {valor: dt_pagamento}
    ilegiveis = 0
    for (ide, entrega, _), t in sorted(zip(forms, textos), key=lambda x: x[0][1]):
        p = parse(t) if t else None
        if not p:
            ilegiveis += 1
            continue
        dcom, linhas = p
        for v, pg in linhas:
            base[(ide, dcom)][round(v, 8)] = pg
    print(f'{len(base)} (emissor, data-com) lidos | PDFs sem texto: {sem_texto} | sem formato reconhecido: {ilegiveis}')

    # 4) casa com tb_provento
    cur.execute('SELECT id_ativo, dt_cotacao FROM public.tb_cotacao_bruta ORDER BY 1, 2')
    cal = defaultdict(list)
    for ida, dt in cur.fetchall():
        cal[ida].append(dt)

    def data_com(ida, dx):
        L = cal.get(ida) or []
        i = bisect.bisect_left(L, dx)
        return L[i - 1] if i > 0 else dx - timedelta(days=1)

    cur.execute('''SELECT a.id_emissor, p.id_ativo, p.ds_tipo_provento, p.dt_ex, p.vl_unitario,
                          pg.dt_pagamento, pg.fl_estimado
                   FROM public.tb_provento p JOIN public.tb_ativo a USING (id_ativo)
                   JOIN public.tb_tipo_ativo ta USING (id_tipo_ativo)
                   LEFT JOIN public.tb_provento_pagamento pg ON pg.id_ativo = p.id_ativo
                        AND pg.ds_tipo_provento = p.ds_tipo_provento AND pg.dt_ex = p.dt_ex
                   WHERE ta.sg_tipo_ativo = 'ACAO' AND p.dt_ex >= %s''', (date(ano_ini, 1, 1),))
    stat = defaultdict(int)
    gravar = []
    difs = []
    for ide, ida, tp, dx, vl, pg_atual, estimado in cur.fetchall():
        dc = data_com(ida, dx)
        cand = {}
        for k in range(0, 6):
            cand.update(base.get((ide, dc - timedelta(days=k))) or {})
        if not cand:
            stat['sem formulario'] += 1
            continue
        vl = float(vl)
        pg = next((p for v, p in cand.items() if abs(v - vl) <= max(1e-6, vl * 1e-3)), None)
        modo = 'valor'
        if pg is None:
            datas = set(cand.values())
            if len(datas) == 1:
                pg, modo = datas.pop(), 'data unica'
            else:
                stat['ambiguo'] += 1
                continue
        pg = max(pg, dx)
        if pg_atual is not None and not estimado:           # ja tem data real da B3: so valida
            stat[f'B3 igual ({modo})' if pg == pg_atual else f'B3 diferente ({modo})'] += 1
            if pg != pg_atual:
                difs.append((sg.get(ide), tp, dx, pg_atual, pg))
            continue
        stat[f'novo ({modo})'] += 1
        gravar.append((ida, tp, dx, dc, pg))
    for k in sorted(stat):
        print(f'  {k}: {stat[k]}')
    for x in difs[:12]:
        print('  dif B3 x CVM:', x)

    if aplica:
        for ida, tp, dx, dc, pg in gravar:
            cur.execute('''INSERT INTO public.tb_provento_pagamento (id_ativo, ds_tipo_provento, dt_ex, dt_com, dt_pagamento, fl_estimado)
                           VALUES (%s,%s,%s,%s,%s,false)
                           ON CONFLICT (id_ativo, ds_tipo_provento, dt_ex) DO UPDATE
                           SET dt_com = EXCLUDED.dt_com, dt_pagamento = EXCLUDED.dt_pagamento, fl_estimado = false, dh_atualizacao = now()
                           WHERE public.tb_provento_pagamento.fl_estimado''', (ida, tp, dx, dc, pg))
        conn.commit()
        print(f'{len(gravar)} datas reais gravadas')
    else:
        print('(sem --aplica: nada gravado)')
    conn.close()


if __name__ == '__main__':
    main()
