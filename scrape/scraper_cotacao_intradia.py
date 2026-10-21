"""
Cotacao DURANTE o pregao, direto do endpoint que o site da B3 usa (cotacao.b3.com.br/mds/api/v1/DailyFluctuationHistory/<TICKER>,
barras de 1 min, atraso de ~15 min, preco REAL do dia). Grava a ultima cotacao de cada ativo em tb_cotacao_intradia (upsert, sem historico).

ATENCAO: o campo Msg.dtTm das respostas da B3 e a hora da REQUISICAO, nao a do negocio (fora do pregao ele devolve o ultimo preco
com a hora de agora). A data do pregao vem de TradgFlr.date e a hora do negocio da ultima barra; so conta barra ate 18:00 (pregao
regular + leilao de fechamento), pra nao pegar o after-market, que difere do fechamento oficial.

Por padrao so os ativos com posicao aberta de algum usuario (poucas dezenas de chamadas); --todos pega os ativos ativos.
So grava se a data da cotacao for hoje (pregao fechado/feriado devolve o ultimo dia, que o COTAHIST ja cobre).

    python3 scrape/scraper_cotacao_intradia.py [--todos] [TICKER ...]
    python3 scrape/scraper_cotacao_intradia.py --loop      # a cada 5 min, de 9h50 a 18h40 (Brasilia) em dia util
"""
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, time as dtime

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

URL = 'https://cotacao.b3.com.br/mds/api/v1/DailyFluctuationHistory/{t}'
FIM_PREGAO = '18:00:00'
INTERVALO = 300


def busca(ticker):
    req = urllib.request.Request(URL.format(t=ticker), headers={'User-Agent': 'Mozilla/5.0'})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.load(r)
            t = d['TradgFlr']
            barras = [x for x in t['scty']['lstQtn'] if x['dtTm'] <= FIM_PREGAO]
            if not barras or not t.get('date'):
                return None
            ult = barras[-1]
            precos = [x['closPric'] for x in barras]
            return {'preco': ult['closPric'], 'abertura': barras[0]['closPric'], 'minimo': min(precos), 'maximo': max(precos),
                    'variacao': ult.get('prcFlcn'),
                    'dh': datetime.combine(date.fromisoformat(t['date']), dtime.fromisoformat(ult['dtTm']))}
        except (KeyError, IndexError, TypeError):
            return None            # ticker sem negocio / desconhecido
        except Exception:
            time.sleep(1 + tentativa)
    return None


def coleta(conn, tickers=None, todos=False):
    cur = conn.cursor()
    if tickers:
        cur.execute('SELECT id_ativo, sg_ticker FROM public.tb_ativo WHERE sg_ticker = ANY(%s)', (tickers,))
    elif todos:
        cur.execute('SELECT id_ativo, sg_ticker FROM public.tb_ativo WHERE fl_ativo')
    else:
        cur.execute('''SELECT DISTINCT a.id_ativo, a.sg_ticker FROM public.tb_posicao_diaria p
                       JOIN public.tb_ativo a USING (id_ativo)
                       WHERE p.dt_posicao = (SELECT MAX(dt_posicao) FROM public.tb_posicao_diaria) AND p.qt_ativo > 0''')
    ativos = cur.fetchall()
    hoje = datetime.now().date()
    gravados = 0
    for ida, tk in ativos:
        q = busca(tk)
        if q is None or q['dh'].date() != hoje:
            continue
        cur.execute('''INSERT INTO public.tb_cotacao_intradia
                         (id_ativo, dt_pregao, dh_cotacao, vl_preco, vl_abertura, vl_minimo, vl_maximo, pc_variacao, dh_coleta)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
                       ON CONFLICT (id_ativo) DO UPDATE SET dt_pregao = EXCLUDED.dt_pregao, dh_cotacao = EXCLUDED.dh_cotacao,
                         vl_preco = EXCLUDED.vl_preco, vl_abertura = EXCLUDED.vl_abertura, vl_minimo = EXCLUDED.vl_minimo,
                         vl_maximo = EXCLUDED.vl_maximo, pc_variacao = EXCLUDED.pc_variacao, dh_coleta = now()''',
                    (ida, q['dh'].date(), q['dh'], q['preco'], q['abertura'], q['minimo'], q['maximo'], q['variacao']))
        gravados += 1
        time.sleep(0.1)
    conn.commit()
    return len(ativos), gravados


def em_pregao(agora):
    return agora.weekday() < 5 and (9, 50) <= (agora.hour, agora.minute) <= (18, 40)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    todos = '--todos' in sys.argv
    if '--loop' not in sys.argv:
        conn = get_conn()
        n, g = coleta(conn, args or None, todos)
        print(f'{g}/{n} ativos com cotacao de hoje gravados')
        conn.close()
        return
    while True:
        agora = datetime.now()
        if em_pregao(agora):
            try:
                conn = get_conn()
                n, g = coleta(conn, args or None, todos)
                conn.close()
                print(f'{agora:%H:%M} {g}/{n} gravados', flush=True)
            except Exception as e:
                print(f'{agora:%H:%M} falhou: {e!r}', flush=True)
        time.sleep(INTERVALO - (time.time() % INTERVALO))      # alinha em 5 min cheios


if __name__ == '__main__':
    main()
