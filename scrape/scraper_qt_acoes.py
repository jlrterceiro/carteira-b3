# Atualiza so qt_acoes em tb_balanco_patrimonial, via yfinance -- unico campo que continua
# vindo do yfinance depois da migracao do balanco pra CVM (composicao_capital, o arquivo da
# CVM equivalente, tem erro de escala -- 1000x menor -- em pelo menos VALE3 e ITSA4, sem como
# validar algoritmicamente quais empresas sao afetadas). So faz UPDATE (nunca INSERT) -- a
# linha precisa ja existir, criada por popula_balanco.py.
import os
import sys

import pandas as pd
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


def fetch_qt_acoes(ticker):
    t = yf.Ticker(f'{ticker}.SA')
    periodos = []
    for tp_periodo, df in (('ANUAL', t.balance_sheet), ('TRIMESTRAL', t.quarterly_balance_sheet)):
        if df is None or df.empty or 'Ordinary Shares Number' not in df.index:
            continue
        for dt_referencia in df.columns:
            valor = df.loc['Ordinary Shares Number', dt_referencia]
            if pd.isna(valor):
                continue
            periodos.append((tp_periodo, dt_referencia.date(), float(valor)))
    return periodos


def update_qt_acoes(conn, id_ativo, tp_periodo, dt_referencia, qt_acoes):
    with conn.cursor() as cur:
        cur.execute(
            '''
            UPDATE public.tb_balanco_patrimonial
            SET qt_acoes = %s, dh_atualizacao = now()
            WHERE id_ativo = %s AND dt_referencia = %s AND tp_periodo = %s
            ''',
            (qt_acoes, id_ativo, dt_referencia, tp_periodo),
        )
        atualizou = cur.rowcount > 0
    conn.commit()
    return atualizou


def process_ativo(conn, id_ativo, ticker):
    periodos = fetch_qt_acoes(ticker)
    if not periodos:
        print(f'  {ticker}: nenhum dado de qt_acoes encontrado')
        return
    for tp_periodo, dt_referencia, qt_acoes in periodos:
        atualizou = update_qt_acoes(conn, id_ativo, tp_periodo, dt_referencia, qt_acoes)
        if atualizou:
            print(f'  {ticker}: qt_acoes {tp_periodo} de {dt_referencia} atualizado')


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
