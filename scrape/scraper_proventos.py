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


def fetch_dividends(ticker):
    t = yf.Ticker(f'{ticker}.SA')
    return t.dividends


def upsert_provento(conn, id_ativo, dt_ex, vl_unitario):
    with conn.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO public.tb_provento (id_ativo, dt_ex, vl_unitario)
            VALUES (%s,%s,%s)
            ON CONFLICT (id_ativo, dt_ex) DO NOTHING
            ''',
            (id_ativo, dt_ex, vl_unitario),
        )
        inserted = cur.rowcount > 0
    conn.commit()
    return inserted


def process_ativo(conn, id_ativo, ticker):
    dividends = fetch_dividends(ticker)
    if dividends is None or dividends.empty:
        return
    for dt, valor in dividends.items():
        if upsert_provento(conn, id_ativo, dt.date(), float(valor)):
            print(f'  {ticker}: provento de {valor} em {dt.date()}')
        else:
            print(f'  {ticker}: provento em {dt.date()} ja importado')


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
