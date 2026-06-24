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

# A B3 ja distingue desdobramento de bonificacao (o yfinance jogava os dois em SPLIT, sem
# diferenciar) -- mapeia direto pro tipo certo de tb_tipo_operacao.
TIPO_POR_LABEL = {'DESDOBRAMENTO': 'SPLIT', 'BONIFICACAO': 'BONIF', 'GRUPAMENTO': 'GRUP'}

# DESDOBRAMENTO/BONIFICACAO: a B3 reporta o "factor" em percentual (ex: 100 = dobro das
# acoes, 30 = 30% de bonus) -- confirmado contra o multiplicador real ja validado no banco
# (PETR4 2008: B3 factor=100 -> 1+100/100=2.0, bate exato com o split 2:1 conhecido; CMIG
# 2024: factor=30 -> 1.30, bate exato). GRUPAMENTO: o "factor" ja E o multiplicador direto
# (CMIG 2007: factor=0.002, bate exato sem nenhuma conversao).
LABELS_PERCENTUAL = {'DESDOBRAMENTO', 'BONIFICACAO'}

# mesma janela de tolerancia ja usada pra remover duplicata do yfinance (ver
# scraper_eventos_corporativos.py/remove_duplicados) -- usada aqui pra achar o evento
# existente (vindo do yfinance, sem diferenciar split/bonificacao) que corresponde ao mesmo
# evento real reportado pela B3, e substitui-lo pelo tipo/fator corretos.
TOLERANCIA_DIAS = 14


def _get(endpoint, params):
    b64 = base64.b64encode(json.dumps(params).encode()).decode()
    url = f'{BASE_URL}/{endpoint}/{b64}'
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def fetch_emissores(conn, ticker_filter=None):
    query = '''
        SELECT DISTINCT e.id_emissor, e.sg_emissor
        FROM public.tb_emissor e
        JOIN public.tb_ativo a ON a.id_emissor = e.id_emissor
        JOIN public.tb_tipo_ativo ta ON ta.id_tipo_ativo = a.id_tipo_ativo
        WHERE ta.sg_tipo_ativo = 'ACAO' AND e.sg_emissor IS NOT NULL
    '''
    params = ()
    if ticker_filter:
        query += ' AND a.sg_ticker = %s'
        params = (ticker_filter,)
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


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


def fetch_tipo_operacao_ids(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sg_tipo_operacao, id_tipo_operacao FROM public.tb_tipo_operacao WHERE sg_tipo_operacao IN ('SPLIT','GRUP','BONIF')"
        )
        return dict(cur.fetchall())


def fetch_stock_dividends(issuing_company):
    resp = _get('GetListedSupplementCompany', {'issuingCompany': issuing_company, 'language': 'pt-br'})
    if not resp:
        return []
    return resp[0].get('stockDividends') or []


def parse_valor_br(texto):
    return float(texto.replace('.', '').replace(',', '.'))


def parse_data_br(texto):
    dia, mes, ano = texto.split('/')
    return f'{ano}-{mes}-{dia}'


def classe_do_isin(isin):
    # posicoes 10-11 do ISIN (ISO 6166): OR=ordinaria, PR/PA/PB=preferencial (qualquer
    # classe de PN colapsa pra 'PN', mesma convencao de tb_ativo.sg_classe). Units tem
    # estrutura de ISIN diferente (CDA em vez de ACN+classe) -- nao identificavel por essa
    # regra, tratado por fallback em process_emissor.
    if not isin or len(isin) < 11:
        return None
    classe = isin[9:11]
    if classe == 'OR':
        return 'ON'
    if classe in ('PR', 'PA', 'PB'):
        return 'PN'
    return None


def proxima_data_pregao(conn, id_ativo, dt_referencia):
    from datetime import date, timedelta
    ano, mes, dia = dt_referencia.split('-')
    fallback = date(int(ano), int(mes), int(dia)) + timedelta(days=1)

    with conn.cursor() as cur:
        cur.execute(
            'SELECT MIN(dt_cotacao) FROM public.tb_cotacao WHERE id_ativo = %s AND dt_cotacao > %s',
            (id_ativo, dt_referencia),
        )
        row = cur.fetchone()
    if row and row[0]:
        # se o pregao mais proximo que achamos fica muito longe da referencia, e porque
        # nossa cotacao nao cobre essa epoca (evento anterior ao inicio do historico
        # raspado) -- usar esse pregao distante geraria uma data errada, melhor cair no
        # fallback de +1 dia corrido (impreciso, mas nao absurdo).
        if (row[0] - fallback).days <= 30:
            return row[0]
    return fallback


def remove_eventos_proximos(conn, id_ativo, dt_evento):
    with conn.cursor() as cur:
        cur.execute(
            '''
            DELETE FROM public.tb_evento_corporativo
            WHERE id_ativo = %s
              AND id_tipo_operacao IN (SELECT id_tipo_operacao FROM tb_tipo_operacao WHERE sg_tipo_operacao IN ('SPLIT','GRUP','BONIF'))
              AND dt_evento BETWEEN %s - %s AND %s + %s
            ''',
            (id_ativo, dt_evento, TOLERANCIA_DIAS, dt_evento, TOLERANCIA_DIAS),
        )
        return cur.rowcount


def upsert_evento(conn, id_ativo, id_tipo_operacao, dt_evento, fator):
    with conn.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO public.tb_evento_corporativo (id_ativo, id_tipo_operacao, dt_evento, vl_fator, ds_origem)
            VALUES (%s,%s,%s,%s,'B3')
            ON CONFLICT (id_ativo, id_tipo_operacao, dt_evento) DO UPDATE SET
                vl_fator = EXCLUDED.vl_fator, ds_origem = 'B3', dh_atualizacao = now()
            ''',
            (id_ativo, id_tipo_operacao, dt_evento, fator),
        )
    conn.commit()


def process_emissor(conn, id_emissor, sg_emissor, tipo_ids):
    ativos = fetch_ativos_do_emissor(conn, id_emissor)
    if not ativos:
        return
    eventos = fetch_stock_dividends(sg_emissor)
    if not eventos:
        return

    ativos_por_classe = {}
    for id_ativo, ticker, sg_classe in ativos:
        ativos_por_classe.setdefault(sg_classe, []).append((id_ativo, ticker))

    # agrupa por (classe, label, lastDatePrior) multiplicando os fatores -- alguns emissores
    # tem mais de um evento do mesmo tipo na mesma data pra o mesmo ISIN (ex: BBAS3 1996, 3
    # bonificacoes simultaneas de 20%/30%/50%); o efeito cumulativo correto e o PRODUTO dos
    # multiplicadores, nao um substituindo o outro.
    agregados = {}
    for ev in eventos:
        label = ev['label']
        tipo_sigla = TIPO_POR_LABEL.get(label)
        if tipo_sigla is None:
            continue
        isin = ev.get('isinCode') or ev.get('assetIssued') or ''
        classe = classe_do_isin(isin)
        dt_referencia = parse_data_br(ev['lastDatePrior'])
        fator_raw = parse_valor_br(ev['factor'])
        multiplicador = 1 + fator_raw / 100 if label in LABELS_PERCENTUAL else fator_raw

        if classe is None:
            # ISIN nao bate com padrao ON/PN (provavelmente UNIT, estrutura de ISIN
            # diferente) -- atribui ao(s) ativo(s) classe UNIT do emissor, se existir.
            destinos = ativos_por_classe.get('UNIT', [])
        else:
            destinos = ativos_por_classe.get(classe, [])

        for id_ativo, ticker in destinos:
            chave = (id_ativo, tipo_sigla, dt_referencia)
            if chave in agregados:
                agregados[chave] *= multiplicador
            else:
                agregados[chave] = multiplicador

    for (id_ativo, tipo_sigla, dt_referencia), fator in agregados.items():
        dt_evento = proxima_data_pregao(conn, id_ativo, dt_referencia)
        remove_eventos_proximos(conn, id_ativo, dt_evento)
        upsert_evento(conn, id_ativo, tipo_ids[tipo_sigla], dt_evento, round(fator, 6))
        print(f'  {sg_emissor}: {tipo_sigla} em {dt_evento} (fator {round(fator, 6)})')


def run(ticker_filter=None):
    conn = get_conn()
    tipo_ids = fetch_tipo_operacao_ids(conn)
    emissores = fetch_emissores(conn, ticker_filter)
    total = len(emissores)
    print(f'processing {total} emissores')
    for index, (id_emissor, sg_emissor) in enumerate(emissores, start=1):
        print(f'[{index}/{total}] {sg_emissor}')
        try:
            process_emissor(conn, id_emissor, sg_emissor, tipo_ids)
        except Exception as e:
            print(f'  erro: {e}')
        time.sleep(0.3)
    conn.close()


def main():
    ticker_filter = sys.argv[1] if len(sys.argv) > 1 else None
    run(ticker_filter)


if __name__ == '__main__':
    main()
