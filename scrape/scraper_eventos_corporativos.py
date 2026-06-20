import os
import sys

import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

TIPO_POR_FATOR = {
    'maior': 'SPLIT',
    'menor': 'GRUP',
}


def fetch_ativos(conn, ticker_filter=None):
    query = 'SELECT id_ativo, sg_ticker FROM public.tb_ativo'
    params = ()
    if ticker_filter:
        query += ' WHERE sg_ticker = %s'
        params = (ticker_filter,)
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def fetch_tipo_operacao_ids(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sg_tipo_operacao, id_tipo_operacao FROM public.tb_tipo_operacao WHERE sg_tipo_operacao IN ('SPLIT', 'GRUP')"
        )
        return dict(cur.fetchall())


def fetch_splits(ticker):
    t = yf.Ticker(f'{ticker}.SA')
    return t.splits


def sigla_from_fator(fator):
    if fator > 1:
        return TIPO_POR_FATOR['maior']
    if fator < 1:
        return TIPO_POR_FATOR['menor']
    return None


def upsert_evento(conn, id_ativo, id_tipo_operacao, dt_evento, fator):
    with conn.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO public.tb_evento_corporativo (
                id_ativo,
                id_tipo_operacao,
                dt_evento,
                vl_fator
            ) VALUES (%s,%s,%s,%s)
            ON CONFLICT (id_ativo, id_tipo_operacao, dt_evento) DO NOTHING
            ''',
            (id_ativo, id_tipo_operacao, dt_evento, fator),
        )
        inserted = cur.rowcount > 0
    conn.commit()
    return inserted


def process_ativo(conn, id_ativo, ticker, tipo_operacao_ids):
    splits = fetch_splits(ticker)
    if splits is None or splits.empty:
        return
    for dt, fator in splits.items():
        sigla = sigla_from_fator(fator)
        if sigla is None:
            continue
        id_tipo_operacao = tipo_operacao_ids.get(sigla)
        if id_tipo_operacao is None:
            print(f'  skipped {ticker}: tipo de operacao {sigla} nao encontrado')
            continue
        if upsert_evento(conn, id_ativo, id_tipo_operacao, dt.date(), float(fator)):
            print(f'  {ticker}: {sigla} em {dt.date()} (fator {fator})')
        else:
            print(f'  {ticker}: {sigla} em {dt.date()} ja importado')


def remove_duplicados(conn):
    # yfinance reporta o mesmo split/grupamento duas vezes em algumas acoes, com poucos dias
    # de diferenca entre as datas (bug confirmado contra fontes oficiais varias vezes, ver
    # CLAUDE.md). Mantem a data mais antiga do par, remove a mais recente.
    with conn.cursor() as cur:
        cur.execute(
            '''
            DELETE FROM public.tb_evento_corporativo e2
            WHERE EXISTS (
                SELECT 1 FROM public.tb_evento_corporativo e1
                WHERE e1.id_ativo = e2.id_ativo AND e1.id_tipo_operacao = e2.id_tipo_operacao
                  AND e1.vl_fator = e2.vl_fator AND e1.dt_evento < e2.dt_evento
                  AND e2.dt_evento <= e1.dt_evento + 14
            )
            RETURNING id_evento_corporativo
            '''
        )
        removidos = cur.rowcount
    conn.commit()
    if removidos:
        print(f'removidos {removidos} evento(s) corporativo(s) duplicado(s)')


def run(ticker_filter=None):
    conn = get_conn()
    tipo_operacao_ids = fetch_tipo_operacao_ids(conn)
    ativos = fetch_ativos(conn, ticker_filter)
    total = len(ativos)
    print(f'processing {total} ativos')
    for index, (id_ativo, ticker) in enumerate(ativos, start=1):
        print(f'[{index}/{total}] {ticker}')
        process_ativo(conn, id_ativo, ticker, tipo_operacao_ids)
    remove_duplicados(conn)
    conn.close()


def main():
    ticker_filter = sys.argv[1] if len(sys.argv) > 1 else None
    run(ticker_filter)


if __name__ == '__main__':
    main()
