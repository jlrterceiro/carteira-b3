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
            'SELECT MIN(dt_cotacao) FROM public.tb_cotacao_bruta WHERE id_ativo = %s AND dt_cotacao > %s',
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


def existe_evento_exato(conn, id_ativo, dt_evento):
    # fontes exatas (oscilacao oficial da B3 / ajuste de strike das opcoes) tem prioridade sobre a API de
    # eventos, que e parcial e as vezes erra o fator (CASH3 2023: x0,01 onde o certo e x0,1)
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT 1 FROM public.tb_evento_corporativo
            WHERE id_ativo = %s AND ds_origem IN ('B3-OPCOES', 'B3-OSC')
              AND dt_evento BETWEEN %s - %s AND %s + %s LIMIT 1
            ''',
            (id_ativo, dt_evento, TOLERANCIA_DIAS, dt_evento, TOLERANCIA_DIAS),
        )
        return cur.fetchone() is not None


def foi_rejeitado(conn, id_ativo, dt_evento, fator):
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT 1 FROM public.tb_evento_rejeitado
            WHERE id_ativo = %s AND dt_evento BETWEEN %s - 3 AND %s + 3
              AND abs(ln(vl_fator / %s::numeric)) < 0.02 LIMIT 1
            ''',
            (id_ativo, dt_evento, dt_evento, fator),
        )
        return cur.fetchone() is not None


def remove_eventos_b3(conn, id_ativo):
    with conn.cursor() as cur:
        cur.execute(
            '''
            DELETE FROM public.tb_evento_corporativo
            WHERE id_ativo = %s AND ds_origem = 'B3'
              AND id_tipo_operacao IN (SELECT id_tipo_operacao FROM tb_tipo_operacao WHERE sg_tipo_operacao IN ('SPLIT','GRUP','BONIF'))
            ''',
            (id_ativo,),
        )


def remove_eventos_proximos(conn, id_ativo, dt_evento):
    with conn.cursor() as cur:
        cur.execute(
            '''
            DELETE FROM public.tb_evento_corporativo
            WHERE id_ativo = %s
              AND id_tipo_operacao IN (SELECT id_tipo_operacao FROM tb_tipo_operacao WHERE sg_tipo_operacao IN ('SPLIT','GRUP','BONIF'))
              AND COALESCE(ds_origem, 'yfinance') NOT IN ('B3', 'B3-OPCOES', 'B3-OSC')
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

    # Dentro do MESMO ISIN, eventos do mesmo tipo/data sao eventos distintos simultaneos (ex:
    # BBAS3 1996, 3 bonificacoes de 20%/30%/50%) -- efeito cumulativo = PRODUTO. Mas a B3
    # repete o mesmo evento uma vez por ISIN da classe (BBAS3 tem 3 ISINs de ON, COCE 2 de PN),
    # entao entre ISINs diferentes da mesma classe NAO se multiplica: usa o de um deles
    # (multiplicar elevava o fator a potencia do numero de ISINs, ex: bonificacao 2.0 virava
    # 8.0, grupamento 0.001 virava 1e-9 -> 0 apos o round).
    por_isin = {}
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
            chave = (id_ativo, tipo_sigla, dt_referencia, isin)
            por_isin[chave] = por_isin.get(chave, 1.0) * multiplicador

    agregados = {}
    for (id_ativo, tipo_sigla, dt_referencia, isin), fator in por_isin.items():
        chave = (id_ativo, tipo_sigla, dt_referencia)
        if chave not in agregados:
            agregados[chave] = fator
        elif abs(agregados[chave] - fator) > 1e-9 * max(abs(fator), 1.0):
            print(f'  aviso: {sg_emissor} {tipo_sigla} {dt_referencia}: ISINs da mesma classe divergem ({agregados[chave]} vs {fator}), mantendo o primeiro')

    # Duas fases: primeiro limpa (eventos B3 antigos do ativo + eventos yfinance proximos de
    # algum evento B3), depois grava tudo. Limpar e gravar evento a evento fazia um evento B3
    # apagar o irmao recem-gravado (ex: desdobramento+grupamento no mesmo dia, VIVT3/LEVE3, ou
    # bonificacao e grupamento a 5 dias, SANB3).
    novos = []
    for (id_ativo, tipo_sigla, dt_referencia), fator in agregados.items():
        novos.append((id_ativo, tipo_sigla, proxima_data_pregao(conn, id_ativo, dt_referencia), round(fator, 12)))

    # mesma regra do remove_duplicados (yfinance): mesmo ativo+tipo+fator a ate 14 dias de
    # distancia e o mesmo evento listado sob ISINs com lastDatePrior diferentes -- fica o mais antigo.
    novos.sort(key=lambda n: (n[0], n[1], n[3], n[2]))
    unicos = []
    for n in novos:
        if unicos and unicos[-1][:2] == n[:2] and unicos[-1][3] == n[3] and (n[2] - unicos[-1][2]).days <= TOLERANCIA_DIAS:
            continue
        unicos.append(n)
    novos = unicos

    for id_ativo in {n[0] for n in novos}:
        remove_eventos_b3(conn, id_ativo)
    for id_ativo, tipo_sigla, dt_evento, fator in novos:
        remove_eventos_proximos(conn, id_ativo, dt_evento)
    for id_ativo, tipo_sigla, dt_evento, fator in novos:
        if existe_evento_exato(conn, id_ativo, dt_evento) or foi_rejeitado(conn, id_ativo, dt_evento, fator):
            continue
        upsert_evento(conn, id_ativo, tipo_ids[tipo_sigla], dt_evento, fator)
        print(f'  {sg_emissor}: {tipo_sigla} em {dt_evento} (fator {fator})')


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
            conn.rollback()
            print(f'  erro: {e}')
        time.sleep(0.3)
    conn.close()


def main():
    ticker_filter = sys.argv[1] if len(sys.argv) > 1 else None
    run(ticker_filter)


if __name__ == '__main__':
    main()
