import base64
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

BASE_URL = 'https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall'
HEADERS = {
    'Origin': 'https://www.b3.com.br',
    'Referer': 'https://www.b3.com.br/',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
}

# IRRF de 15% retido na fonte sobre JCP (Lei 9.249/95, art. 9, paragrafo unico) -- dividendo,
# rendimento e restituicao de capital sao isentos de IR pra pessoa fisica. Valor da B3 e
# sempre o bruto declarado pela empresa.
ALIQUOTA_IMPOSTO = {
    'JRS CAP PROPRIO': 0.15,
    'DIVIDENDO': 0.0,
    'RENDIMENTO': 0.0,
    'REST CAP DIN': 0.0,
}

# sg_classe (tb_ativo, ON/PN/UNIT) -> typeStock retornado pela B3.
TYPESTOCK_POR_CLASSE = {'ON': 'ON', 'PN': 'PN', 'UNIT': 'UNT'}


def _get(endpoint, params):
    b64 = base64.b64encode(json.dumps(params).encode()).decode()
    url = f'{BASE_URL}/{endpoint}/{b64}'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def fetch_emissores(conn, ticker_filter=None):
    query = '''
        SELECT DISTINCT e.id_emissor
        FROM public.tb_emissor e
        JOIN public.tb_ativo a ON a.id_emissor = e.id_emissor
        JOIN public.tb_tipo_ativo ta ON ta.id_tipo_ativo = a.id_tipo_ativo
        WHERE ta.sg_tipo_ativo = 'ACAO'
    '''
    params = ()
    if ticker_filter:
        query += ' AND a.sg_ticker = %s'
        params = (ticker_filter,)
    with conn.cursor() as cur:
        cur.execute(query, params)
        return [row[0] for row in cur.fetchall()]


def fetch_ativos_do_emissor(conn, id_emissor):
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT a.id_ativo, a.sg_ticker, a.sg_classe
            FROM public.tb_ativo a
            JOIN public.tb_tipo_ativo ta ON ta.id_tipo_ativo = a.id_tipo_ativo
            WHERE a.id_emissor = %s AND ta.sg_tipo_ativo = 'ACAO'
            ''',
            (id_emissor,),
        )
        return cur.fetchall()


def resolve_trading_name(ticker):
    resp = _get('GetInitialCompanies', {
        'language': 'pt-br', 'pageNumber': 1, 'pageSize': 5, 'company': ticker,
    })
    results = resp.get('results') or []
    if not results:
        return None
    return results[0]['tradingName']


def fetch_cash_dividends(trading_name):
    # pageSize acima de ~120 faz a API devolver vazio silenciosamente (sem erro) -- paginar
    # de propósito em vez de pedir tudo de uma vez.
    pagina = 1
    eventos = []
    while True:
        resp = _get('GetListedCashDividends', {
            'language': 'pt-br', 'pageNumber': pagina, 'pageSize': 120, 'tradingName': trading_name,
        })
        resultados = resp.get('results') or []
        eventos.extend(resultados)
        total_paginas = (resp.get('page') or {}).get('totalPages') or 0
        if pagina >= total_paginas:
            break
        pagina += 1
        time.sleep(0.2)
    return eventos


def parse_valor_br(texto):
    return float(texto.replace('.', '').replace(',', '.'))


def parse_data_br(texto):
    dia, mes, ano = texto.split('/')
    return f'{ano}-{mes}-{dia}'


def proxima_data_pregao(conn, id_ativo, dt_referencia):
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT MIN(dt_cotacao) FROM public.tb_cotacao
            WHERE id_ativo = %s AND dt_cotacao > %s
            ''',
            (id_ativo, dt_referencia),
        )
        row = cur.fetchone()
    if row and row[0]:
        return row[0]
    # sem cotacao disponivel depois dessa data (ticker novo/delistado/nao raspado ainda) --
    # aproxima pelo dia seguinte, que e o caso comum (evento no meio da semana).
    from datetime import date, timedelta
    ano, mes, dia = dt_referencia.split('-')
    return date(int(ano), int(mes), int(dia)) + timedelta(days=1)


def agrupa_por_tipo_e_data(conn, id_ativo, eventos, type_stock):
    agregados = {}
    for ev in eventos:
        if ev['typeStock'] != type_stock:
            continue
        tipo = ev['corporateAction']
        dt_prior_ex = parse_data_br(ev['lastDatePriorEx'])
        valor = parse_valor_br(ev['valueCash'])
        chave = (dt_prior_ex, tipo)
        agregados[chave] = agregados.get(chave, 0.0) + valor

    eventos_finais = []
    for (dt_prior_ex, tipo), valor_bruto in agregados.items():
        dt_ex = proxima_data_pregao(conn, id_ativo, dt_prior_ex)
        aliquota = ALIQUOTA_IMPOSTO.get(tipo, 0.0)
        vl_imposto = round(valor_bruto * aliquota, 8)
        vl_liquido = round(valor_bruto - vl_imposto, 8)
        eventos_finais.append((dt_ex, tipo, valor_bruto, vl_liquido, vl_imposto))
    return eventos_finais


def replace_proventos(conn, id_ativo, eventos):
    with conn.cursor() as cur:
        cur.execute('DELETE FROM public.tb_provento WHERE id_ativo = %s', (id_ativo,))
        for dt_ex, tipo, bruto, liquido, imposto in eventos:
            cur.execute(
                '''
                INSERT INTO public.tb_provento (
                    id_ativo, dt_ex, vl_unitario, ds_tipo_provento,
                    vl_unitario_liquido, vl_imposto_unitario, ds_origem
                ) VALUES (%s,%s,%s,%s,%s,%s,'B3')
                ON CONFLICT (id_ativo, dt_ex, ds_tipo_provento) DO UPDATE SET
                    vl_unitario = EXCLUDED.vl_unitario,
                    vl_unitario_liquido = EXCLUDED.vl_unitario_liquido,
                    vl_imposto_unitario = EXCLUDED.vl_imposto_unitario,
                    ds_origem = EXCLUDED.ds_origem,
                    dh_atualizacao = now()
                ''',
                (id_ativo, dt_ex, bruto, tipo, liquido, imposto),
            )
    conn.commit()
    return len(eventos)


def process_emissor(conn, id_emissor):
    ativos = fetch_ativos_do_emissor(conn, id_emissor)
    if not ativos:
        return
    trading_name = None
    for _, ticker, _ in ativos:
        trading_name = resolve_trading_name(ticker)
        if trading_name:
            break
    if not trading_name:
        print(f'  emissor {id_emissor}: nao encontrado na B3')
        return

    eventos_brutos = fetch_cash_dividends(trading_name)
    for id_ativo, ticker, sg_classe in ativos:
        type_stock = TYPESTOCK_POR_CLASSE.get(sg_classe, 'ON')
        eventos = agrupa_por_tipo_e_data(conn, id_ativo, eventos_brutos, type_stock)
        inserted = replace_proventos(conn, id_ativo, eventos)
        print(f'  {ticker} ({trading_name}): {inserted} proventos')


def run(ticker_filter=None):
    conn = get_conn()
    emissores = fetch_emissores(conn, ticker_filter)
    total = len(emissores)
    print(f'processing {total} emissores')
    for index, id_emissor in enumerate(emissores, start=1):
        print(f'[{index}/{total}] emissor {id_emissor}')
        try:
            process_emissor(conn, id_emissor)
        except Exception as e:
            print(f'  erro: {e}')
        time.sleep(0.3)
    conn.close()


def main():
    ticker_filter = sys.argv[1] if len(sys.argv) > 1 else None
    run(ticker_filter)


if __name__ == '__main__':
    main()
