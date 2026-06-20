import os
import re
import sys
import urllib.error

from psycopg2.extras import Json

from scraper_lib import BASE, get_html, normalize_ticker, parse_tickers

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

ID_TIPO_EMISSOR = 1


def parse_details(html):
    return {
        'razao': re.search(r'<span>Raz[aã]o social</span>\s*<span>([^<]+)', html, re.I | re.S),
        'cnpj': re.search(r'<span>CNPJ</span>\s*<span>([^<]+)', html, re.I | re.S),
        'site': re.search(r'<span>Site do RI</span>\s*<span>(?:<a[^>]*>)?([^<]+)', html, re.I | re.S),
        'setor': re.search(r'<span>Classifica[cç][aã]o setorial B3</span>\s*<span>([^<]+)', html, re.I | re.S),
    }


def upsert_emissor(conn, emissor):
    with conn.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO public.tb_emissor (
                id_tipo_emissor,
                sg_emissor,
                nm_emissor,
                nr_cnpj,
                ds_site,
                nm_pais,
                fl_ativo,
                dh_criacao,
                dh_atualizacao,
                info
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,now(),now(),%s)
            ON CONFLICT (nr_cnpj) DO NOTHING
            ''',
            (
                emissor['id_tipo_emissor'],
                emissor['sg_emissor'],
                emissor['nm_emissor'],
                emissor['nr_cnpj'],
                emissor['ds_site'],
                emissor['nm_pais'],
                emissor['fl_ativo'],
                Json(emissor['info']),
            ),
        )
        if cur.rowcount:
            print(f'inserted {emissor["sg_emissor"]} {emissor["nr_cnpj"]}')
        else:
            print(f'  skipped {emissor["sg_emissor"]} {emissor["nr_cnpj"]}: CNPJ ja existe')
    conn.commit()


def build_emissor(href, ticker, empresa, detail):
    cnpj = detail['cnpj'].group(1).strip() if detail['cnpj'] else ''
    if not cnpj:
        return None
    return {
        'id_tipo_emissor': ID_TIPO_EMISSOR,
        'sg_emissor': normalize_ticker(ticker),
        'nm_emissor': empresa.strip(),
        'nr_cnpj': cnpj,
        'ds_site': detail['site'].group(1).strip() if detail['site'] else None,
        'nm_pais': 'Brasil',
        'fl_ativo': True,
        'info': {
            'razao_social': detail['razao'].group(1).strip() if detail['razao'] else None,
            'setor': detail['setor'].group(1).strip() if detail['setor'] else None,
        },
    }


def fetch_tickers():
    html = get_html(f'{BASE}/acoes')
    return list(reversed(parse_tickers(html)))


def fetch_detail(href):
    try:
        return get_html(BASE + href)
    except urllib.error.HTTPError as e:
        print(f'  skipped: erro {e.code} ao buscar {href}')
        return None


def process_ticker(conn, seen, href, ticker, empresa):
    detail_html = fetch_detail(href)
    if detail_html is None:
        return
    detail = parse_details(detail_html)
    emissor = build_emissor(href, ticker, empresa, detail)
    if not emissor:
        print(f'  skipped {ticker}: sem CNPJ')
        return
    if emissor['nr_cnpj'] in seen:
        print(f'  skipped {ticker}: CNPJ duplicado')
        return
    seen.add(emissor['nr_cnpj'])
    upsert_emissor(conn, emissor)


def run():
    seen = set()
    conn = get_conn()
    tickers = fetch_tickers()
    total = len(tickers)
    print(f'processing {total} empresas (de tras pra frente)')
    for index, (href, ticker, empresa) in enumerate(tickers, start=1):
        print(f'[{index}/{total}] {ticker} - {empresa}')
        process_ticker(conn, seen, href, ticker, empresa)
    conn.close()


def main():
    run()


if __name__ == '__main__':
    main()
