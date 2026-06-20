import os
import sys

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

CAMPOS = {
    'vl_ativo_total': 'Total Assets',
    'vl_ativo_circulante': 'Current Assets',
    'vl_passivo_total': 'Total Liabilities Net Minority Interest',
    'vl_passivo_circulante': 'Current Liabilities',
    'vl_patrimonio_liquido': 'Stockholders Equity',
    'vl_divida_total': 'Total Debt',
    'vl_capital_giro': 'Working Capital',
    'vl_imobilizado': 'Net PPE',
    'vl_valor_patrimonial_tangivel': 'Tangible Book Value',
    'qt_acoes': 'Ordinary Shares Number',
}

# "Net Debt" pronto do yfinance nao e confiavel (confirmado contra o StatusInvest: pra
# PETR4 vem com metodologia diferente/errada, pra EVEN3/MELK3 so abate o caixa estreito).
# Por isso vl_divida_liquida e sempre calculada por nos como divida_total - caixa, usando
# o caixa "amplo" (caixa + aplicacoes financeiras de curto prazo) quando disponivel --
# bateu exatamente com StatusInvest pra PETR4 e EVEN3.
CAMPO_CAIXA_AMPLO = 'Cash Cash Equivalents And Short Term Investments'
CAMPO_CAIXA_ESTREITO = 'Cash And Cash Equivalents'


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


def fetch_balanco(ticker):
    t = yf.Ticker(f'{ticker}.SA')
    periodos = []
    for tp_periodo, df in (('ANUAL', t.balance_sheet), ('TRIMESTRAL', t.quarterly_balance_sheet)):
        if df is None or df.empty:
            continue
        for dt_referencia in df.columns:
            valores = {}
            for coluna, campo in CAMPOS.items():
                if campo not in df.index:
                    valores[coluna] = None
                    continue
                valor = df.loc[campo, dt_referencia]
                valores[coluna] = None if pd.isna(valor) else float(valor)

            for campo_caixa in (CAMPO_CAIXA_AMPLO, CAMPO_CAIXA_ESTREITO):
                if campo_caixa in df.index and not pd.isna(df.loc[campo_caixa, dt_referencia]):
                    valores['vl_caixa'] = float(df.loc[campo_caixa, dt_referencia])
                    break
            else:
                valores['vl_caixa'] = None

            if valores['vl_divida_total'] is not None and valores['vl_caixa'] is not None:
                valores['vl_divida_liquida'] = valores['vl_divida_total'] - valores['vl_caixa']
            else:
                valores['vl_divida_liquida'] = None

            if all(v is None for v in valores.values()):
                continue
            periodos.append((tp_periodo, dt_referencia.date(), valores))
    return periodos


def upsert_balanco(conn, id_ativo, tp_periodo, dt_referencia, valores):
    colunas = list(valores.keys())
    placeholders = ', '.join(['%s'] * len(colunas))
    update_clause = ', '.join(f'{c} = EXCLUDED.{c}' for c in colunas)
    with conn.cursor() as cur:
        cur.execute(
            f'''
            INSERT INTO public.tb_balanco_patrimonial (
                id_ativo, dt_referencia, tp_periodo, {', '.join(colunas)}
            ) VALUES (%s, %s, %s, {placeholders})
            ON CONFLICT (id_ativo, dt_referencia, tp_periodo) DO UPDATE SET
                {update_clause}, dh_atualizacao = now()
            ''',
            (id_ativo, dt_referencia, tp_periodo, *[valores[c] for c in colunas]),
        )
    conn.commit()


def process_ativo(conn, id_ativo, ticker):
    periodos = fetch_balanco(ticker)
    if not periodos:
        print(f'  {ticker}: nenhum balanco encontrado')
        return
    for tp_periodo, dt_referencia, valores in periodos:
        upsert_balanco(conn, id_ativo, tp_periodo, dt_referencia, valores)
        print(f'  {ticker}: balanco {tp_periodo} de {dt_referencia} gravado')


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
