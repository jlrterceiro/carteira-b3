"""
Eventos corporativos EXATOS a partir do proprio COTAHIST: a B3 ajusta o preco de exercicio (PREEXE) das
series de opcoes na data ex de desdobramento/grupamento/bonificacao. Se varias series do mesmo ativo
mudam de strike na MESMA razao entre dois pregoes consecutivos, essa razao e o fator do evento
(F = strike_antes / strike_depois: bonificacao 10% -> 1,1; grupamento 10:1 -> 0,1).

Ajuste de provento em dinheiro e ADITIVO (strike - provento), logo as razoes variam entre series e o
filtro de consistencia multiplicativa o descarta.

    python3 scrape/eventos_por_opcoes.py            # varre 1994..hoje, grava /tmp/eventos_opcoes.csv e compara com o banco
"""
import csv
import os
import statistics
import sys
import zipfile
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cotahist_cache')
MIN_SERIES = 4          # series do mesmo ativo que precisam mudar juntas
CONSISTENCIA = 0.015    # fracao das razoes que devem ficar a ate 1,5% da mediana
MUDANCA_MIN = 0.012     # |razao - 1| minimo pra contar como mudanca de strike


def strikes_do_ano(ano):
    """{data: {codigo_opcao: (strike, vencimento)}} so opcoes (070/080)"""
    out = defaultdict(dict)
    with zipfile.ZipFile(os.path.join(CACHE_DIR, f'COTAHIST_A{ano}.ZIP')) as z:
        with z.open(z.namelist()[0]) as f:
            for raw in f:
                if raw[0:2] != b'01' or raw[24:27] not in (b'070', b'080'):
                    continue
                l = raw.decode('latin1')
                if l[52:56].strip() != 'R$':
                    continue
                try:
                    strike = int(l[188:201]) / 100
                except ValueError:
                    continue
                if strike <= 0:
                    continue
                out[f'{l[2:6]}-{l[6:8]}-{l[8:10]}'][l[12:24].strip()] = (strike, l[202:210])
    return out


def varre(ano_ini=1994, ano_fim=None, cobertura_csv='/tmp/cobertura_opcoes.csv'):
    ano_fim = ano_fim or date.today().year
    eventos = []
    cob = open(cobertura_csv, 'w', newline='')
    cw = csv.writer(cob); cw.writerow(['raiz', 'data', 'series_comparaveis'])
    ant_data, ant = None, {}
    for ano in range(ano_ini, ano_fim + 1):
        dias = strikes_do_ano(ano)
        for dt in sorted(dias):
            hoje = dias[dt]
            if ant:
                por_raiz = defaultdict(list)
                for cod, (strike, venc) in hoje.items():
                    a = ant.get(cod)
                    if a and a[1] == venc and a[0] > 0:
                        por_raiz[cod[:4]].append(a[0] / strike)
                for raiz, rs in por_raiz.items():
                    if len(rs) >= MIN_SERIES:
                        cw.writerow([raiz, dt, len(rs)])      # ha opcoes suficientes pra enxergar um ajuste neste dia
                    mudaram = [r for r in rs if abs(r - 1) > MUDANCA_MIN]
                    if len(mudaram) < MIN_SERIES:
                        continue
                    med = statistics.median(mudaram)
                    consist = sum(1 for r in mudaram if abs(r / med - 1) < CONSISTENCIA) / len(mudaram)
                    # a maioria das series do ativo mudou, e mudou na mesma razao
                    if len(mudaram) / len(rs) >= 0.6 and consist >= 0.8:
                        eventos.append((raiz, dt, round(med, 4), len(mudaram), len(rs), round(consist, 2)))
            ant_data, ant = dt, hoje
        print(f'  {ano}: ok ({len(eventos)} candidatos ate aqui)', flush=True)
    cob.close()
    return eventos


if __name__ == '__main__':
    ev = varre()
    with open('/tmp/eventos_opcoes.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['raiz', 'data', 'fator', 'series_mudaram', 'series_total', 'consistencia']); w.writerows(ev)
    print(f'{len(ev)} eventos candidatos; /tmp/eventos_opcoes.csv')
