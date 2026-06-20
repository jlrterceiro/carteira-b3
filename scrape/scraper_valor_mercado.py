import os
import sys
from datetime import date

import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn


def fetch_ativos(conn, ticker_filter=None):
    query = '''
        SELECT a.id_ativo, a.sg_ticker
        FROM public.tb_ativo a
        JOIN public.tb_tipo_ativo ta ON ta.id_tipo_ativo = a.id_tipo_ativo
        WHERE ta.sg_tipo_ativo = 'ACAO'
    '''
    params = ()
    if ticker_filter:
        query += ' AND a.sg_ticker = %s'
        params = (ticker_filter,)
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def fetch_market_cap(ticker):
    t = yf.Ticker(f'{ticker}.SA')
    valor = t.fast_info.get('marketCap')
    return float(valor) if valor else None


def upsert_valor_mercado(conn, id_ativo, dt_referencia, vl_valor_mercado):
    with conn.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO public.tb_valor_mercado (id_ativo, dt_referencia, vl_valor_mercado)
            VALUES (%s, %s, %s)
            ON CONFLICT (id_ativo, dt_referencia) DO UPDATE SET
                vl_valor_mercado = EXCLUDED.vl_valor_mercado
            ''',
            (id_ativo, dt_referencia, vl_valor_mercado),
        )
    conn.commit()


def process_ativo(conn, id_ativo, ticker, dt_referencia):
    valor = fetch_market_cap(ticker)
    if valor is None:
        print(f'  {ticker}: marketCap nao encontrado')
        return
    upsert_valor_mercado(conn, id_ativo, dt_referencia, valor)
    print(f'  {ticker}: valor de mercado de {dt_referencia} = {valor:,.2f}')


def run(ticker_filter=None):
    conn = get_conn()
    ativos = fetch_ativos(conn, ticker_filter)
    total = len(ativos)
    dt_referencia = date.today()
    print(f'processing {total} ativos')
    for index, (id_ativo, ticker) in enumerate(ativos, start=1):
        print(f'[{index}/{total}] {ticker}')
        process_ativo(conn, id_ativo, ticker, dt_referencia)
    conn.close()


def main():
    ticker_filter = sys.argv[1] if len(sys.argv) > 1 else None
    run(ticker_filter)


if __name__ == '__main__':
    main()
