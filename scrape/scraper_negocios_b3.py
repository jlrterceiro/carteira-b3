"""
Coletor diario dos negocios consolidados do pregao da B3 (so acoes/units do nosso cadastro).

    python3 scrape/scraper_negocios_b3.py                    # dias uteis que faltam desde o ultimo gravado (ou 2025-06-11)
    python3 scrape/scraper_negocios_b3.py 2026-10-16          # um dia
    python3 scrape/scraper_negocios_b3.py --desde 2025-06-11  # backfill (a B3 so serve ~16 meses)

Fonte: arquivos.b3.com.br (fileName=TradeInformationConsolidatedFile). O download pede um token por dia;
dia sem pregao devolve arquivo vazio.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

from psycopg2.extras import execute_values

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

PRIMEIRO_DIA = date(2025, 6, 11)   # antes disso a B3 devolve arquivo vazio
H = {'User-Agent': 'Mozilla/5.0'}


def baixa_dia(dia):
    """linhas do arquivo (cabecalho incluso) ou [] se nao houve pregao"""
    for tentativa in range(1, 7):
        try:
            u = f'https://arquivos.b3.com.br/api/download/requestname?fileName=TradeInformationConsolidatedFile&date={dia}&recaptchaToken='
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=60).read())
            tok = urllib.parse.parse_qs(urllib.parse.urlparse(j['redirectUrl'].lstrip('~')).query)['token'][0]
            req = urllib.request.Request('https://arquivos.b3.com.br/api/download/?token=' + urllib.parse.quote(tok), headers=H)
            dados = urllib.request.urlopen(req, timeout=180).read()
            return dados.decode('latin-1').splitlines() if dados else []
        except urllib.error.HTTPError as e:
            if e.code == 400:      # data fora do que a B3 guarda
                return []
            time.sleep(5 * tentativa)
        except Exception:
            time.sleep(5 * tentativa)
    raise RuntimeError(f'nao baixou {dia}')


def num(s):
    s = (s or '').strip()
    return float(s.replace('.', '').replace(',', '.')) if s else None


def linhas_cash(linhas, tickers):
    if len(linhas) < 3:
        return []
    cab = linhas[1].split(';')
    i = {c: k for k, c in enumerate(cab)}
    out = []
    for l in linhas[2:]:
        c = l.split(';')
        if len(c) < len(cab) or c[i['SgmtNm']] != 'CASH' or c[i['TckrSymb']] not in tickers:
            continue
        out.append((c[i['RptDt']], c[i['TckrSymb']], c[i['ISIN']] or None, num(c[i['MinPric']]), num(c[i['MaxPric']]),
                    num(c[i['TradAvrgPric']]), num(c[i['LastPric']]), num(c[i['OscnPctg']]),
                    int(c[i['TradQty']]) if c[i['TradQty']].strip() else None, num(c[i['FinInstrmQty']]), num(c[i['NtlFinVol']])))
    return out


def grava(conn, linhas):
    with conn.cursor() as cur:
        execute_values(cur, '''
            INSERT INTO public.tb_negocio_diario (dt_pregao, sg_ticker, cd_isin, vl_minimo, vl_maximo, vl_medio, vl_ultimo,
                                                  pc_oscilacao, qt_negocios, qt_titulos, vl_financeiro)
            VALUES %s ON CONFLICT (dt_pregao, sg_ticker) DO UPDATE SET
                vl_ultimo = EXCLUDED.vl_ultimo, pc_oscilacao = EXCLUDED.pc_oscilacao, vl_minimo = EXCLUDED.vl_minimo,
                vl_maximo = EXCLUDED.vl_maximo, vl_medio = EXCLUDED.vl_medio, qt_negocios = EXCLUDED.qt_negocios,
                qt_titulos = EXCLUDED.qt_titulos, vl_financeiro = EXCLUDED.vl_financeiro
        ''', linhas)
    conn.commit()


def dias_uteis(ini, fim):
    d = ini
    while d <= fim:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def main():
    args = sys.argv[1:]
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute('SELECT sg_ticker FROM public.tb_ativo')
        tickers = {r[0] for r in cur.fetchall()}
        cur.execute('SELECT dt_pregao FROM public.tb_negocio_diario GROUP BY 1')
        feitos = {r[0] for r in cur.fetchall()}
    if '--desde' in args:
        ini = date.fromisoformat(args[args.index('--desde') + 1])
        dias = list(dias_uteis(max(ini, PRIMEIRO_DIA), date.today()))
    elif [a for a in args if not a.startswith('--')]:
        dias = [date.fromisoformat(a) for a in args if not a.startswith('--')]
    else:
        ini = (max(feitos) + timedelta(days=1)) if feitos else PRIMEIRO_DIA
        dias = list(dias_uteis(ini, date.today()))
    dias = [d for d in dias if d not in feitos or len(args) and not '--desde' in args]
    print(f'{len(dias)} dias a baixar ({dias[0] if dias else "-"} .. {dias[-1] if dias else "-"})')
    falharam = []
    for rodada in (1, 2, 3):
        pendentes = dias if rodada == 1 else falharam
        falharam = []
        for k, d in enumerate(pendentes, start=1):
            try:
                linhas = baixa_dia(d.isoformat())
                rows = linhas_cash(linhas, tickers)
                if rows:
                    grava(conn, rows)
                print(f'[{rodada}:{k}/{len(pendentes)}] {d}: {len(rows)} linhas' if rows else f'[{rodada}:{k}/{len(pendentes)}] {d}: sem pregao', flush=True)
            except Exception as e:
                conn.rollback()
                falharam.append(d)
                print(f'[{rodada}:{k}/{len(pendentes)}] {d}: FALHOU ({e})', flush=True)
        if not falharam:
            break
        time.sleep(20)
    if falharam:
        print(f'AINDA FALTAM {len(falharam)} dias: {[str(x) for x in falharam]}')
    conn.close()


if __name__ == '__main__':
    main()
