"""
Benchmarks pro grafico de Rentabilidade (tb_benchmark_diario), so upsert:
  IBOV  fechamento diario do Ibovespa, do arquivo de indices da B3 (www.b3.com.br/pesquisapregao/download?filelist=IR<aammdd>.zip,
        zip dentro de zip com o XML BVBG.087.01; vazio em dia sem pregao; historico de ~2018 em diante). So busca os pregoes
        (tb_cotacao_bruta) que ainda nao estao na tabela.
  CDI   taxa diaria (% a.d.) do BCB, SGS 12 (aceito no projeto so pra CDI/SELIC e indices).

    python3 scrape/scraper_benchmarks.py [--desde 2018-01-02]
"""
import http.client
import io
import json
import os
import re
import socket
import sys
import time
import urllib.request
import zipfile
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

H = {'User-Agent': 'Mozilla/5.0'}

# o BCB resolve pra IPv6 e a conexao pendura ate estourar o timeout: forca IPv4
_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: [r for r in _orig_getaddrinfo(*a, **k) if r[0] == socket.AF_INET] or _orig_getaddrinfo(*a, **k)

FALHOU = 'falhou'      # sentinela: a rodada seguinte tenta de novo (so busca o que falta)
IBOV_RX = re.compile(r'<TckrSymb>IBOV</TckrSymb>.*?<ClsgPric[^>]*>([\d.]+)</ClsgPric>', re.S)


class B3:
    """conexao HTTPS reaproveitada, UM download por vez: com varios em paralelo a B3 (Cloudflare) derruba as conexoes"""
    def __init__(self):
        self.con = None

    def get(self, path):
        for tentativa in range(1, 7):
            try:
                if self.con is None:
                    self.con = http.client.HTTPSConnection('www.b3.com.br', timeout=60)
                self.con.request('GET', path, headers=H)
                r = self.con.getresponse()
                dados = r.read()
                if r.status == 200:
                    return dados
                raise RuntimeError(f'HTTP {r.status}')
            except Exception:
                try:
                    self.con.close()
                except Exception:
                    pass
                self.con = None
                time.sleep(3 * tentativa)
        return None


def ibov_do_dia(b3, d):
    """fechamento do Ibovespa em d; None = sem pregao; FALHOU = nao deu pra baixar"""
    b = b3.get(f'/pesquisapregao/download?filelist=IR{d:%y%m%d}.zip')
    if b is None:
        return FALHOU
    try:
        if b[:2] != b'PK':
            return None
        z = zipfile.ZipFile(io.BytesIO(b))
        if not z.namelist():
            return None
        inner = zipfile.ZipFile(io.BytesIO(z.read(z.namelist()[0])))
        if not inner.namelist():
            return None
        xml = inner.read(sorted(inner.namelist())[-1]).decode('utf-8', 'replace')    # ultima versao do dia
        m = IBOV_RX.search(xml)
        return float(m.group(1)) if m else None
    except zipfile.BadZipFile:
        return FALHOU


def cdi(inicio, fim):
    """[(data, % a.d.)] do SGS 12, em janelas de 5 anos (o BCB limita o intervalo)"""
    out, a = [], inicio
    while a <= fim:
        b = min(date(a.year + 5, a.month, a.day) - timedelta(days=1), fim)
        url = ('https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json'
               f'&dataInicial={a:%d/%m/%Y}&dataFinal={b:%d/%m/%Y}')
        for tentativa in range(1, 5):
            try:
                dados = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=60).read())
                out += [(datetime.strptime(x['data'], '%d/%m/%Y').date(), float(x['valor'])) for x in dados]
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:       # janela sem dado
                    break
                time.sleep(3 * tentativa)
            except Exception:
                time.sleep(3 * tentativa)
        else:
            raise RuntimeError(f'nao baixou o CDI de {a} a {b}')
        a = b + timedelta(days=1)
    return out


def main():
    desde = date.fromisoformat(sys.argv[sys.argv.index('--desde') + 1]) if '--desde' in sys.argv else date(2018, 1, 2)
    conn = get_conn(); cur = conn.cursor()

    # ---- IBOV: so os pregoes que faltam
    cur.execute('SELECT DISTINCT dt_cotacao FROM public.tb_cotacao_bruta WHERE dt_cotacao >= %s ORDER BY 1', (desde,))
    pregoes = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT dt_dia FROM public.tb_benchmark_diario WHERE cd_benchmark = 'IBOV'")
    tem = {r[0] for r in cur.fetchall()}
    faltam = [d for d in pregoes if d not in tem]
    # hoje ainda nao esta em tb_cotacao_bruta enquanto o COTAHIST nao sai, mas o arquivo de indices ja pode ter saido
    if date.today() not in tem and date.today() not in faltam and date.today().weekday() < 5:
        faltam.append(date.today())
    print(f'IBOV: {len(faltam)} dias a buscar')
    b3 = B3()
    n, falhas = 0, []
    for k, d in enumerate(faltam, 1):
        v = ibov_do_dia(b3, d)
        if v == FALHOU:
            falhas.append(d)
        elif v is not None:
            cur.execute('''INSERT INTO public.tb_benchmark_diario (cd_benchmark, dt_dia, vl_nivel) VALUES ('IBOV', %s, %s)
                           ON CONFLICT (cd_benchmark, dt_dia) DO UPDATE SET vl_nivel = EXCLUDED.vl_nivel, dh_atualizacao = now()''', (d, v))
            n += 1
        if k % 100 == 0:
            conn.commit()
            print(f'  IBOV {k}/{len(faltam)} ({d})', flush=True)
        time.sleep(0.15)
    # retorno do dia sobre o fechamento anterior
    cur.execute('''UPDATE public.tb_benchmark_diario t SET vl_retorno_pct = 100 * (t.vl_nivel / p.ant - 1)
                   FROM (SELECT dt_dia, LAG(vl_nivel) OVER (ORDER BY dt_dia) AS ant FROM public.tb_benchmark_diario
                         WHERE cd_benchmark = 'IBOV') p
                   WHERE t.cd_benchmark = 'IBOV' AND t.dt_dia = p.dt_dia AND p.ant IS NOT NULL
                     AND t.vl_retorno_pct IS DISTINCT FROM 100 * (t.vl_nivel / p.ant - 1)''')
    conn.commit()
    print(f'IBOV: {n} dias gravados' + (f' | {len(falhas)} falharam (rodar de novo): {falhas[:5]}' if falhas else ''))

    # ---- CDI
    taxas = cdi(desde, date.today())
    for d, v in taxas:
        cur.execute('''INSERT INTO public.tb_benchmark_diario (cd_benchmark, dt_dia, vl_retorno_pct) VALUES ('CDI', %s, %s)
                       ON CONFLICT (cd_benchmark, dt_dia) DO UPDATE SET vl_retorno_pct = EXCLUDED.vl_retorno_pct, dh_atualizacao = now()''', (d, v))
    conn.commit()
    print(f'CDI: {len(taxas)} dias gravados')
    cur.execute('SELECT cd_benchmark, count(*), min(dt_dia), max(dt_dia) FROM public.tb_benchmark_diario GROUP BY 1')
    for r in cur.fetchall():
        print(' ', r)
    conn.close()


if __name__ == '__main__':
    main()
