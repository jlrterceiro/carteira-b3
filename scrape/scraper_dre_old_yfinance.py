import os
import statistics
import sys

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

CAMPOS = {
    'vl_receita_total': 'Total Revenue',
    'vl_custo_receita': 'Cost Of Revenue',
    'vl_lucro_bruto': 'Gross Profit',
    'vl_despesas_operacionais': 'Operating Expense',
    'vl_resultado_operacional': 'Operating Income',
    'vl_resultado_financeiro': 'Net Interest Income',
    'vl_ebitda': 'EBITDA',
    'vl_ebit': 'EBIT',
    'vl_lucro_antes_impostos': 'Pretax Income',
    'vl_impostos': 'Tax Provision',
    'vl_lucro_liquido_total': 'Net Income Including Noncontrolling Interests',
    'vl_participacao_nao_controladores': 'Minority Interests',
    'vl_lucro_liquido': 'Net Income',
    'vl_lpa_basico': 'Basic EPS',
    'vl_lpa_diluido': 'Diluted EPS',
}

# yfinance ocasionalmente retorna LPA com valores absurdos (ex: AZUL3 em reestruturacao
# financeira severa chegou a mostrar R$ 28 milhoes/acao) -- erro de dado deles, nao um valor
# real. vl_lpa_basico/vl_lpa_diluido sao NUMERIC(10,4), que aceita ate ~10^6; descartamos
# (vira NULL) qualquer LPA fora desse intervalo em vez de deixar o INSERT estourar.
CAMPOS_LPA = ('vl_lpa_basico', 'vl_lpa_diluido')
LIMITE_LPA = 10_000

# yfinance tambem corrompe, vez ou outra, o bloco receita->custo->lucro bruto->despesas->
# resultado operacional num periodo especifico de uma acao (confirmado em CMIG4: o trimestre
# 2026-03-31 voltou com R$ 10,3 trilhoes de receita, ~1000x o normal, enquanto EBITDA/lucro
# liquido no mesmo trimestre estavam normais -- o erro fica isolado nesse bloco). Comparamos
# cada um desses campos contra a mediana dos OUTROS periodos do mesmo tipo (ANUAL ou
# TRIMESTRAL) da mesma acao; se vier mais de FATOR_OUTLIER vezes a mediana, descartamos
# (NULL) so aquele campo naquele periodo, mantendo o resto da linha.
CAMPOS_BLOCO_OPERACIONAL = (
    'vl_receita_total',
    'vl_custo_receita',
    'vl_lucro_bruto',
    'vl_despesas_operacionais',
    'vl_resultado_operacional',
)
FATOR_OUTLIER = 100


def remove_outliers(periodos):
    for tp_periodo in ('ANUAL', 'TRIMESTRAL'):
        do_tipo = [valores for tp, _, valores in periodos if tp == tp_periodo]
        for campo in CAMPOS_BLOCO_OPERACIONAL:
            amostras = [abs(v[campo]) for v in do_tipo if v.get(campo) is not None]
            if len(amostras) < 3:
                continue
            mediana = statistics.median(amostras)
            if mediana == 0:
                continue
            for valores in do_tipo:
                valor = valores.get(campo)
                if valor is not None and abs(valor) > mediana * FATOR_OUTLIER:
                    valores[campo] = None
    return periodos


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


def fetch_dre(ticker):
    t = yf.Ticker(f'{ticker}.SA')
    periodos = []
    for tp_periodo, df in (('ANUAL', t.income_stmt), ('TRIMESTRAL', t.quarterly_income_stmt)):
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

            for coluna in CAMPOS_LPA:
                if valores[coluna] is not None and abs(valores[coluna]) >= LIMITE_LPA:
                    valores[coluna] = None

            if all(v is None for v in valores.values()):
                continue
            periodos.append((tp_periodo, dt_referencia.date(), valores))
    remove_outliers(periodos)
    return periodos


def upsert_dre(conn, id_ativo, tp_periodo, dt_referencia, valores):
    colunas = list(valores.keys())
    placeholders = ', '.join(['%s'] * len(colunas))
    update_clause = ', '.join(f'{c} = EXCLUDED.{c}' for c in colunas)
    with conn.cursor() as cur:
        cur.execute(
            f'''
            INSERT INTO public.tb_dre (
                id_ativo, dt_referencia, tp_periodo, {', '.join(colunas)}
            ) VALUES (%s, %s, %s, {placeholders})
            ON CONFLICT (id_ativo, dt_referencia, tp_periodo) DO UPDATE SET
                {update_clause}, dh_atualizacao = now()
            ''',
            (id_ativo, dt_referencia, tp_periodo, *[valores[c] for c in colunas]),
        )
    conn.commit()


def process_ativo(conn, id_ativo, ticker):
    periodos = fetch_dre(ticker)
    if not periodos:
        print(f'  {ticker}: nenhuma dre encontrada')
        return
    for tp_periodo, dt_referencia, valores in periodos:
        upsert_dre(conn, id_ativo, tp_periodo, dt_referencia, valores)
        print(f'  {ticker}: dre {tp_periodo} de {dt_referencia} gravada')


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
