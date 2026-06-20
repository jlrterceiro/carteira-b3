import os
import sys

import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn


def fetch_ativos(conn, ticker_filter=None):
    query = 'SELECT id_ativo, sg_ticker FROM public.tb_ativo'
    params = ()
    if ticker_filter:
        query += ' WHERE sg_ticker = %s'
        params = (ticker_filter,)
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def fetch_quotes(ticker):
    t = yf.Ticker(f'{ticker}.SA')
    return t.history(period='max', auto_adjust=False)


def replace_cotacoes(conn, id_ativo, df):
    with conn.cursor() as cur:
        cur.execute('DELETE FROM public.tb_cotacao WHERE id_ativo = %s', (id_ativo,))
        for dt, row in df.iterrows():
            cur.execute(
                '''
                INSERT INTO public.tb_cotacao (
                    id_ativo,
                    dt_cotacao,
                    vl_abertura,
                    vl_maxima,
                    vl_minima,
                    vl_fechamento,
                    vl_fechamento_ajustado,
                    qt_volume
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ''',
                (
                    id_ativo,
                    dt.date(),
                    float(row['Open']),
                    float(row['High']),
                    float(row['Low']),
                    float(row['Close']),
                    float(row['Adj Close']),
                    float(row['Volume']),
                ),
            )
    conn.commit()
    return len(df)


def process_ativo(conn, id_ativo, ticker):
    df = fetch_quotes(ticker)
    if df.empty:
        print(f'  {ticker}: nenhuma cotacao encontrada')
        return
    inserted = replace_cotacoes(conn, id_ativo, df)
    print(f'  {ticker}: {inserted} cotacoes inseridas (historico completo)')


def run(ticker_filter=None):
    conn = get_conn()
    ativos = fetch_ativos(conn, ticker_filter)
    total = len(ativos)
    print(f'processing {total} ativos')
    for index, (id_ativo, ticker) in enumerate(ativos, start=1):
        print(f'[{index}/{total}] {ticker}')
        process_ativo(conn, id_ativo, ticker)
    conn.close()


def main():
    ticker_filter = sys.argv[1] if len(sys.argv) > 1 else None
    run(ticker_filter)


if __name__ == '__main__':
    main()
