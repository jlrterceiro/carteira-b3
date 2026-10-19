"""
Descobre, so com o COTAHIST, os codigos ANTIGOS de cada ativo (troca de ticker) pra emendar a
serie historica (tb_ticker_historico). Sem gravar nada por padrao.

Dois tipos de ligacao, do mais ao menos confiavel:
  ISIN    mesmo ISIN, codigo diferente, sem sobreposicao -> mesma acao (ex: a recodificacao de
          03/1998, 'ACE 3' -> 'ACES3'; os arquivos de 1994-1997 usam codigos de 3 letras).
  PRECO   ISIN mudou (o ISIN carrega as 4 letras do emissor: BRFJTAACNPR2 -> BRTASAACNPR4), mas a
          serie antiga termina colada no inicio da nova, mesma classe, preco continuo
          (FJTA4 4,74 em 11/11/2019 -> TASA4 4,98 em 12/11/2019).

Uso:
    python3 scrape/descobre_trocas_ticker.py                # relatorio
    python3 scrape/descobre_trocas_ticker.py --aplica       # grava as ligacoes ISIN e as PRECO 'fortes'
"""
import math
import os
import re
import sys
import zipfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn
from scraper_cotacoes_b3 import CACHE_DIR, parse_linha

ANO_INICIAL, ANO_FINAL = 1994, date.today().year
GAP_MAX_DIAS = 10          # fim do codigo antigo -> inicio do novo
RAZAO_FRACA = (0.4, 2.5)   # fechamento novo / fechamento antigo


def carrega_series():
    """{(codneg, isin): {ini, fim, n, ci, cf, nome, esp}} -- so mercado a vista em R$."""
    series = {}
    for ano in range(ANO_INICIAL, ANO_FINAL + 1):
        with zipfile.ZipFile(os.path.join(CACHE_DIR, f'COTAHIST_A{ano}.ZIP')) as z:
            with z.open(z.namelist()[0]) as f:
                for raw in f:
                    if raw[0:2] != b'01' or raw[24:27] != b'010':
                        continue
                    linha = raw.decode('latin1')
                    c = parse_linha(linha)
                    if c['modref'] != 'R$':
                        continue
                    chave = (c['codneg'], c['isin'])
                    d = f"{c['data'][0:4]}-{c['data'][4:6]}-{c['data'][6:8]}"
                    s = series.get(chave)
                    if s is None:
                        s = series[chave] = {'ini': d, 'fim': d, 'n': 0, 'ci': c['preult'], 'cf': c['preult'],
                                             'nome': linha[27:39].strip(), 'esp': linha[39:49].strip()}
                    s['fim'] = d
                    s['n'] += 1
                    s['cf'] = c['preult']
    return series


def sufixo(codigo):
    m = re.search(r'(\d+)\s*[A-Z]?$', codigo)
    return m.group(1) if m else ''


def classe_esp(esp):
    e = esp.upper()
    if e.startswith('ON'):
        return 'ON'
    if e.startswith('PN') or e.startswith('PR'):
        return 'PN'
    if e.startswith('UNT') or e.startswith('UNIT'):
        return 'UNIT'
    return e[:3]


def dias(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def tokens(nome):
    return {t for t in re.split(r'[^A-Z0-9]+', nome.upper()) if len(t) >= 4}


def nome_parecido(a, b):
    """compartilham uma palavra de 4+ letras OU o prefixo de 4 letras (ITAUBANCO ~ ITAUUNIBANCO)"""
    ta, tb = tokens(a), tokens(b)
    if ta & tb:
        return True
    return any(x[:4] == y[:4] for x in ta for y in tb)


def codigo_parecido(a, b):
    return a[:3].strip().upper() == b[:3].strip().upper()


def qualifica(series, cabeca, s_cab, chave, s, gap_max):
    if chave[1] == cabeca[1] or s['n'] < 20 or s['cf'] <= 0 or s_cab['ci'] <= 0:
        return None
    gap = dias(s['fim'], s_cab['ini'])
    if gap < -2 or gap > gap_max:
        return None
    if sufixo(chave[0]) != sufixo(cabeca[0]) and classe_esp(s['esp']) != classe_esp(s_cab['esp']):
        return None
    razao = s_cab['ci'] / s['cf']
    if not (RAZAO_FRACA[0] <= razao <= RAZAO_FRACA[1]):
        return None
    return gap, razao


def acha_predecessoras(series, atual):
    """cadeia de series anteriores a `atual` ((codneg, isin)): [(chave, tipo, razao)].
    tipo: ISIN (certo) | PRECO-A (nome/codigo parecido + preco continuo) | PRECO-B (unico candidato,
    gap<=5d, preco 0.9-1.12) | PRECO-fraco (so relatorio, nunca aplicado e a cadeia para)."""
    por_isin = {}
    for (cod, isin), s in series.items():
        por_isin.setdefault(isin, []).append((cod, s))
    cadeia, vistos, cabeca = [], {atual}, atual
    while True:
        s_cab = series[cabeca]
        achou = None
        for cod, s in por_isin.get(cabeca[1], []):
            chave = (cod, cabeca[1])
            if chave in vistos or s['fim'] >= s_cab['ini'] or dias(s['fim'], s_cab['ini']) > 400:
                continue
            if achou is None or s['fim'] > series[achou]['fim']:
                achou = chave
        if achou:
            cadeia.append((achou, 'ISIN', 1.0)); vistos.add(achou); cabeca = achou
            continue

        cands = []
        for chave, s in series.items():
            if chave in vistos:
                continue
            q = qualifica(series, cabeca, s_cab, chave, s, GAP_MAX_DIAS)
            if q:
                gap, razao = q
                sim = nome_parecido(s['nome'], s_cab['nome']) or codigo_parecido(chave[0], cabeca[0])
                cands.append((chave, s, gap, razao, sim))
        if not cands:
            break
        com_sim = [c for c in cands if c[4]]
        if com_sim:
            chave, s, gap, razao, _ = min(com_sim, key=lambda c: abs(math.log(c[3])) + c[2] / 100)
            tipo = 'PRECO-A' if RAZAO_FRACA[0] <= razao <= RAZAO_FRACA[1] else 'PRECO-fraco'
        else:
            apertados = [c for c in cands if c[2] <= 5 and 0.9 <= c[3] <= 1.12]
            if len(apertados) == 1 and len(cands) == 1:
                chave, s, gap, razao, _ = apertados[0]
                tipo = 'PRECO-B'
            else:
                chave, s, gap, razao, _ = min(cands, key=lambda c: abs(math.log(c[3])) + c[2] / 100)
                tipo = 'PRECO-fraco'
        cadeia.append((chave, tipo, razao))
        if tipo == 'PRECO-fraco':
            break
        vistos.add(chave); cabeca = chave
    return cadeia


def main():
    aplica = '--aplica' in sys.argv[1:]
    print('indexando COTAHIST...', flush=True)
    series = carrega_series()
    conn = get_conn(); cur = conn.cursor()
    cur.execute('SELECT id_ativo, sg_ticker FROM public.tb_ativo ORDER BY sg_ticker')
    ativos = cur.fetchall()
    cur.execute('SELECT sg_ticker_antigo FROM public.tb_ticker_historico')
    ja = {r[0] for r in cur.fetchall()}

    # serie "atual" de cada ativo = a (codigo, isin) com maior fim
    propostas = []
    for id_ativo, ticker in ativos:
        cand = [(k, s) for k, s in series.items() if k[0] == ticker]
        if not cand:
            continue
        atual = max(cand, key=lambda x: x[1]['fim'])[0]
        # inicio da serie propria do ticker atual (pode ter varias series com o mesmo codigo/ISIN diferentes: pega a mais recente)
        for chave, tipo, razao in acha_predecessoras(series, atual):
            s = series[chave]
            if (chave[0] in ja and chave[0] != ticker) or (chave[0] == ticker and series[atual] is s):
                continue
            propostas.append((ticker, id_ativo, chave, tipo, razao, s))

    por_tipo = {}
    for p in propostas:
        por_tipo.setdefault(p[3], []).append(p)
    print(f"{len(propostas)} ligacoes propostas: " + ', '.join(f'{k}={len(v)}' for k, v in sorted(por_tipo.items())))
    for ticker, id_ativo, chave, tipo, razao, s in propostas:
        print(f"{ticker:8} <- {chave[0]:10} {tipo:11} {s['ini']}..{s['fim']} ({s['n']}d) {s['nome']:14} razao {razao:.2f}")

    if aplica:
        n = 0
        for ticker, id_ativo, chave, tipo, razao, s in propostas:
            if tipo == 'PRECO-fraco':
                continue
            if chave[0] == ticker and tipo == 'ISIN':
                continue
            dt_alt = date.fromisoformat(s['fim']).toordinal() + 1
            cur.execute(
                '''
                INSERT INTO public.tb_ticker_historico (sg_ticker_antigo, id_ativo, dt_alteracao, ds_motivo, cd_isin)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT (sg_ticker_antigo, cd_isin) DO NOTHING
                ''',
                (chave[0], id_ativo, date.fromordinal(dt_alt), f'COTAHIST ({tipo}): {chave[0]} -> {ticker}', chave[1]),
            )
            n += cur.rowcount
        conn.commit()
        print(f'{n} ligacoes gravadas em tb_ticker_historico')
    conn.close()


if __name__ == '__main__':
    main()
