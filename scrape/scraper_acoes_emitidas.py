"""
Quantidade de acoes por emissor e trimestre (CVM, composicao do capital: itr_/dfp_cia_aberta_composicao_capital_<ano>.csv dentro dos zips que o
scraper_dre.py ja baixa em scrape/cvm_cache/). Grava tb_acoes_emissor (upsert), em ACOES.

A unidade informada varia por empresa (algumas em milhares). Pra cada (emissor, trimestre) testa escala 1 e 1000 e fica com a que faz
(acoes em circulacao x preco do fim do trimestre) / patrimonio liquido cair em P/VP 0,02-100 (nos ultimos trimestres, a quantidade do
yfinance, quando bate com uma delas, decide primeiro); se as duas servem (P/VP baixo) ou nenhuma, herda
a escala do trimestre confiavel mais proximo; sem nenhum, escala 1 e fl_confiavel=false.

    python3 scrape/scraper_acoes_emitidas.py [--desde 2011]
"""
import csv
import glob
import io
import os
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from psycopg2.extras import execute_values

from cnpj_emissor import fetch_emissores_cnpj
from db_lib import get_conn

CACHE = os.path.join(os.path.dirname(__file__), 'cvm_cache')
PVP_MIN, PVP_MAX = 0.02, 100.0


def num(s):
    s = (s or '').strip()
    return float(s) if s else None


def le_zips(desde):
    """{(cnpj, dt_refer): linha} com a maior VERSAO de cada (empresa, data)"""
    out = {}
    for f in sorted(glob.glob(os.path.join(CACHE, '*_cia_aberta_20??.zip'))):
        m = re.search(r'(itr|dfp)_cia_aberta_(\d{4})\.zip$', f)
        if not m or int(m.group(2)) < desde:
            continue
        z = zipfile.ZipFile(f)
        nome = f'{m.group(1)}_cia_aberta_composicao_capital_{m.group(2)}.csv'
        if nome not in z.namelist():
            continue
        for r in csv.DictReader(io.TextIOWrapper(z.open(nome), encoding='latin-1'), delimiter=';'):
            k = (r['CNPJ_CIA'].strip(), r['DT_REFER'])
            if k not in out or int(r['VERSAO']) >= int(out[k]['VERSAO']):
                out[k] = r
    return out


def main():
    desde = int(sys.argv[sys.argv.index('--desde') + 1]) if '--desde' in sys.argv else 2011
    conn = get_conn(); cur = conn.cursor()
    cnpj2emissor = {c.strip(): ide for ide, c, _, _ in fetch_emissores_cnpj(conn)}
    bruto = {}
    for (cnpj, dt), r in le_zips(desde).items():
        ide = cnpj2emissor.get(cnpj)
        total = num(r['QT_ACAO_TOTAL_CAP_INTEGR'])
        if ide is None or not total or total <= 0:
            continue
        bruto[(ide, dt)] = (total, num(r['QT_ACAO_ORDIN_CAP_INTEGR']), num(r['QT_ACAO_PREF_CAP_INTEGR']), num(r['QT_ACAO_TOTAL_TESOURO']) or 0.0)
    print(len(bruto), 'registros (emissor, trimestre) lidos')

    # patrimonio liquido e preco do fim do trimestre (ticker ON, ou o primeiro do emissor)
    cur.execute(
        '''WITH q AS (
               SELECT a.id_emissor, b.dt_referencia, max(b.vl_patrimonio_liquido_total) AS pl,
                      (SELECT a2.id_ativo FROM public.tb_ativo a2 WHERE a2.id_emissor = a.id_emissor ORDER BY (a2.sg_classe <> 'ON'), a2.id_ativo LIMIT 1) AS id_ativo
               FROM public.tb_balanco_patrimonial b JOIN public.tb_ativo a USING (id_ativo)
               WHERE a.id_emissor IS NOT NULL GROUP BY a.id_emissor, b.dt_referencia, 4)
           SELECT q.id_emissor, q.dt_referencia, q.pl,
                  (SELECT c.vl_fechamento FROM public.tb_cotacao_bruta c WHERE c.id_ativo = q.id_ativo AND c.dt_cotacao <= q.dt_referencia
                   ORDER BY c.dt_cotacao DESC LIMIT 1) AS preco
           FROM q''')
    ref = {(r[0], r[1].isoformat()): (float(r[2]) if r[2] else None, float(r[3]) if r[3] else None) for r in cur.fetchall()}

    # 2a evidencia: quantidade de acoes do yfinance (tb_balanco_patrimonial.qt_acoes, so os ultimos trimestres), quando bate com uma das escalas
    cur.execute('''SELECT a.id_emissor, b.dt_referencia, max(b.qt_acoes) FROM public.tb_balanco_patrimonial b JOIN public.tb_ativo a USING (id_ativo)
                   WHERE b.qt_acoes > 1000 AND a.id_emissor IS NOT NULL GROUP BY 1, 2''')
    yf = {(r[0], r[1].isoformat()): float(r[2]) for r in cur.fetchall()}

    # 3a evidencia (so pra trimestre sem as anteriores): insider nao negocia mais acoes do que existem. Maior quantidade negociada numa unica
    # operacao de compra/venda a vista ate 1 ano antes ou depois do trimestre; se ela supera as acoes na escala 1 e cabe na escala 1000, e 1000.
    cur.execute("""SELECT to_regclass('public.tb_insider_movimentacao') IS NOT NULL""")
    maior = defaultdict(list)             # id_emissor -> [(data, qt)]
    if cur.fetchone()[0]:
        cur.execute("""SELECT id_emissor, dt_movimentacao, qt_ativo FROM public.tb_insider_movimentacao
                       WHERE tipo_movimentacao IN ('Compra à vista', 'Venda à vista') AND tipo_ativo IN ('Ações', 'Units') AND qt_ativo > 0""")
        for ide, d, q in cur.fetchall():
            maior[ide].append((d, float(q)))

    por_emissor = defaultdict(list)
    for (ide, dt), v in bruto.items():
        por_emissor[ide].append(dt)
    linhas, nao = [], 0
    for ide, datas in por_emissor.items():
        datas.sort()
        escala, conf = {}, {}
        for dt in datas:
            total, _, _, teso = bruto[(ide, dt)]
            pl, preco = ref.get((ide, dt), (None, None))
            if (ide, dt) in yf:
                ok = [k for k in (1, 1000) if 0.7 <= (total - teso) * k / yf[(ide, dt)] <= 1.4]
                if len(ok) == 1:
                    escala[dt], conf[dt] = ok[0], True
                    continue
            if pl and pl > 0 and preco:
                ok = [k for k in (1, 1000) if PVP_MIN <= (total - teso) * k * preco / pl <= PVP_MAX]
                if len(ok) == 1:
                    escala[dt], conf[dt] = ok[0], True
        for dt in datas:                                   # 3a evidencia: quantidade negociada maior que as acoes existentes
            if dt in escala:
                continue
            d0 = date.fromisoformat(dt)
            qmax = max((q for d, q in maior.get(ide, []) if abs((d - d0).days) <= 365), default=0)
            circ = bruto[(ide, dt)][0] - bruto[(ide, dt)][3]
            if qmax and circ < qmax <= circ * 1000:
                escala[dt], conf[dt] = 1000, True
        for dt in datas:                                   # sem evidencia: herda o trimestre confiavel mais proximo
            if dt in escala:
                continue
            vizinhos = sorted((d for d in escala if conf.get(d)), key=lambda d: abs((date.fromisoformat(d) - date.fromisoformat(dt)).days))
            escala[dt], conf[dt] = (escala[vizinhos[0]] if vizinhos else 1), False
            nao += 1
        for dt in datas:
            total, on, pn, teso = bruto[(ide, dt)]
            k = escala[dt]
            linhas.append((ide, dt, total * k, None if on is None else on * k, None if pn is None else pn * k, teso * k, k, conf[dt]))
    execute_values(cur, '''INSERT INTO public.tb_acoes_emissor (id_emissor, dt_referencia, qt_total, qt_ordinaria, qt_preferencial, qt_tesouraria, nr_escala, fl_confiavel)
                           VALUES %s ON CONFLICT (id_emissor, dt_referencia) DO UPDATE SET qt_total = EXCLUDED.qt_total,
                             qt_ordinaria = EXCLUDED.qt_ordinaria, qt_preferencial = EXCLUDED.qt_preferencial, qt_tesouraria = EXCLUDED.qt_tesouraria,
                             nr_escala = EXCLUDED.nr_escala, fl_confiavel = EXCLUDED.fl_confiavel''', linhas)
    conn.commit()
    cur.execute('SELECT nr_escala, fl_confiavel, count(*) FROM public.tb_acoes_emissor GROUP BY 1, 2 ORDER BY 1, 2')
    print(len(linhas), 'gravados;', nao, 'sem evidencia direta (herdaram escala). Por escala/confianca:', cur.fetchall())
    conn.close()


if __name__ == '__main__':
    main()
