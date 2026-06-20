import os
import re
import sys

from scraper_lib import BASE, get_html, normalize_ticker, parse_tickers

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

ID_TIPO_ATIVO_ACAO = 1


def classe_from_ticker(ticker):
    m = re.search(r'(\d+)$', ticker)
    if not m:
        return None
    if m.group(1) == '3':
        return 'ON'
    if m.group(1) == '11':
        return 'UNIT'
    return 'PN'


def fetch_emissor_id(conn, sg_emissor):
    with conn.cursor() as cur:
        cur.execute('SELECT id_emissor FROM public.tb_emissor WHERE sg_emissor = %s', (sg_emissor,))
        row = cur.fetchone()
        return row[0] if row else None


def build_ativo(id_emissor, ticker, empresa):
    return {
        'id_tipo_ativo': ID_TIPO_ATIVO_ACAO,
        'id_emissor': id_emissor,
        'sg_ticker': ticker,
        'sg_classe': classe_from_ticker(ticker),
        'nm_ativo': f'{empresa.strip()} - {ticker}',
    }


def upsert_ativo(conn, ativo):
    with conn.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO public.tb_ativo (
                id_tipo_ativo,
                id_emissor,
                sg_ticker,
                sg_classe,
                nm_ativo,
                dh_criacao,
                dh_atualizacao
            ) VALUES (%s,%s,%s,%s,%s,now(),now())
            ON CONFLICT (sg_ticker) DO NOTHING
            ''',
            (
                ativo['id_tipo_ativo'],
                ativo['id_emissor'],
                ativo['sg_ticker'],
                ativo['sg_classe'],
                ativo['nm_ativo'],
            ),
        )
        if cur.rowcount:
            print(f'inserted {ativo["sg_ticker"]}')
        else:
            print(f'  skipped {ativo["sg_ticker"]}: ja existe')
    conn.commit()


def process_ticker(conn, ticker, empresa):
    sg_emissor = normalize_ticker(ticker)
    id_emissor = fetch_emissor_id(conn, sg_emissor)
    if id_emissor is None:
        print(f'  skipped {ticker}: emissor {sg_emissor} nao encontrado')
        return
    ativo = build_ativo(id_emissor, ticker, empresa)
    upsert_ativo(conn, ativo)


def fetch_tickers():
    html = get_html(f'{BASE}/acoes')
    return parse_tickers(html)


def run():
    conn = get_conn()
    tickers = fetch_tickers()
    total = len(tickers)
    print(f'processing {total} ativos')
    for index, (href, ticker, empresa) in enumerate(tickers, start=1):
        print(f'[{index}/{total}] {ticker} - {empresa}')
        process_ticker(conn, ticker, empresa)
    conn.close()


def main():
    run()


if __name__ == '__main__':
    main()
