import os
import sys
import urllib.request
import zipfile
from datetime import date
from functools import lru_cache

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cvm_cache')
ANO_INICIAL = 2011
ANO_FINAL = date.today().year

FATOR_ESCALA = {'MIL': 1000, 'MILHAO': 1_000_000, 'UNIDADE': 1}

# a CVM ocasionalmente reporta LPA (3.99.*) com erro grosseiro de carga (confirmado em
# AMAR3 2021-12-31: R$ -27,44 QUATRILHOES/acao, estourando NUMERIC(20,4) na hora do INSERT --
# mesma categoria de erro pontual ja documentada em popula_dre.py pra MRVE3 2017-06-30, R$614
# milhoes/acao, so que aquele nao chegava a estourar a coluna). Zera aqui, na raspagem, antes
# do erro quebrar o INSERT -- mesmo limiar usado em popula_dre.py.
LIMITE_LPA = 10_000


def fetch_emissores(conn, ticker_filter=None):
    query = '''
        SELECT DISTINCT e.id_emissor, e.nr_cnpj
        FROM public.tb_emissor e
        JOIN public.tb_ativo a ON a.id_emissor = e.id_emissor
        JOIN public.tb_tipo_ativo ta ON ta.id_tipo_ativo = a.id_tipo_ativo
        WHERE ta.sg_tipo_ativo = 'ACAO' AND e.nr_cnpj IS NOT NULL
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
            SELECT a.id_ativo
            FROM public.tb_ativo a
            JOIN public.tb_tipo_ativo ta ON ta.id_tipo_ativo = a.id_tipo_ativo
            WHERE a.id_emissor = %s AND ta.sg_tipo_ativo = 'ACAO'
            ''',
            (id_emissor,),
        )
        return [row[0] for row in cur.fetchall()]


def download_cvm_csv(tipo, ano, grupo):
    os.makedirs(CACHE_DIR, exist_ok=True)
    csv_name = f'{tipo}_cia_aberta_DRE_{grupo}_{ano}.csv'
    csv_path = os.path.join(CACHE_DIR, csv_name)
    if os.path.exists(csv_path):
        return csv_path

    zip_path = os.path.join(CACHE_DIR, f'{tipo}_cia_aberta_{ano}.zip')
    if not os.path.exists(zip_path):
        url = f'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{tipo.upper()}/DADOS/{tipo}_cia_aberta_{ano}.zip'
        try:
            urllib.request.urlretrieve(url, zip_path)
        except Exception:
            return None

    try:
        with zipfile.ZipFile(zip_path) as z:
            if csv_name not in z.namelist():
                return None
            z.extract(csv_name, CACHE_DIR)
    except zipfile.BadZipFile:
        return None
    return csv_path


@lru_cache(maxsize=None)
def carrega_ano(tipo, ano, grupo):
    csv_path = download_cvm_csv(tipo, ano, grupo)
    if csv_path is None:
        return None
    df = pd.read_csv(csv_path, sep=';', encoding='ISO-8859-1', dtype={'CNPJ_CIA': str, 'CD_CONTA': str})
    df = df[df['ORDEM_EXERC'] == 'ÚLTIMO'].copy()
    if tipo == 'itr':
        # a CVM reporta tanto o trimestre isolado (DT_INI_EXERC = inicio daquele trimestre)
        # quanto o acumulado desde o inicio do ano (DT_INI_EXERC = 1o de janeiro) pro mesmo
        # DT_REFER, a partir do 2o trimestre -- sem filtrar, pegariamos o acumulado por
        # engano. Mantem so o trimestre isolado (intervalo <= ~95 dias); pro 1o trimestre os
        # dois coincidem. O DFP (tipo='dfp') nao tem essa ambiguidade -- e sempre o ano
        # inteiro (~365 dias), nao filtra.
        dt_ini = pd.to_datetime(df['DT_INI_EXERC'])
        dt_fim = pd.to_datetime(df['DT_FIM_EXERC'])
        df = df[(dt_fim - dt_ini).dt.days <= 95]
    return df


def contas_por_periodo(df, cnpj, tp_periodo):
    if df is None:
        return []
    subset = df[df['CNPJ_CIA'] == cnpj]
    periodos = []
    for dt_referencia, df_periodo in subset.groupby('DT_REFER'):
        contas = []
        for row in df_periodo.itertuples():
            # LPA (3.99.*) e sempre reportado em reais por acao, nunca na escala do resto da
            # demonstracao (ninguem reporta "R$ 0,00065 mil por acao") -- so escala o resto.
            fator = 1 if row.CD_CONTA.startswith('3.99') else FATOR_ESCALA.get(row.ESCALA_MOEDA, 1)
            valor = None if pd.isna(row.VL_CONTA) else float(row.VL_CONTA) * fator
            if valor is not None and row.CD_CONTA.startswith('3.99') and abs(valor) >= LIMITE_LPA:
                valor = None
            contas.append({'cd_conta': row.CD_CONTA, 'ds_conta': row.DS_CONTA, 'vl_conta': valor})
        periodos.append((tp_periodo, date.fromisoformat(dt_referencia), contas))
    return periodos


def fetch_periodos_cvm(cnpj):
    # consolidado em primeiro lugar (mesma escolha do resto do projeto -- lucro atribuivel
    # aos controladores, etc.); cai pro individual so nos periodos que faltarem no
    # consolidado -- empresa sem subsidiaria pra consolidar (Sanepar, Comgas, bancos
    # estaduais pequenos etc.) simplesmente nao tem "_con", so "_ind".
    #
    # ITR (trimestral) cobre 1T/2T/3T -- nao existe "4o ITR", a CVM so publica o ano inteiro
    # via DFP (anual) depois do encerramento do exercicio. Grava o DFP com tp_periodo='ANUAL'
    # (sem filtro de isolamento, ver carrega_ano) -- popula_dre.py deriva o 4T isolado por
    # subtracao (Anual - 1T - 2T - 3T) na curadoria, ver comentario la.
    periodos_por_chave = {}
    for tipo, tp_periodo in (('itr', 'TRIMESTRAL'), ('dfp', 'ANUAL')):
        for ano in range(ANO_INICIAL, ANO_FINAL + 1):
            df_con = carrega_ano(tipo, ano, 'con')
            for periodo in contas_por_periodo(df_con, cnpj, tp_periodo):
                periodos_por_chave[(periodo[1], periodo[0])] = periodo
        for ano in range(ANO_INICIAL, ANO_FINAL + 1):
            df_ind = carrega_ano(tipo, ano, 'ind')
            for periodo in contas_por_periodo(df_ind, cnpj, tp_periodo):
                periodos_por_chave.setdefault((periodo[1], periodo[0]), periodo)
    return list(periodos_por_chave.values())


def upsert_dre_conta(conn, id_ativo, dt_referencia, tp_periodo, contas):
    with conn.cursor() as cur:
        for conta in contas:
            cur.execute(
                '''
                INSERT INTO public.tb_dre_conta (id_ativo, dt_referencia, tp_periodo, cd_conta, ds_conta, vl_conta)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_ativo, dt_referencia, tp_periodo, cd_conta) DO UPDATE SET
                    ds_conta = EXCLUDED.ds_conta, vl_conta = EXCLUDED.vl_conta
                ''',
                (id_ativo, dt_referencia, tp_periodo, conta['cd_conta'], conta['ds_conta'], conta['vl_conta']),
            )
    conn.commit()


def process_emissor(conn, id_emissor, cnpj):
    ids_ativo = fetch_ativos_do_emissor(conn, id_emissor)
    if not ids_ativo:
        return
    periodos = fetch_periodos_cvm(cnpj)
    if not periodos:
        print(f'  {cnpj}: nenhuma dre encontrada')
        return
    for tp_periodo, dt_referencia, contas in periodos:
        for id_ativo in ids_ativo:
            upsert_dre_conta(conn, id_ativo, dt_referencia, tp_periodo, contas)
        print(f'  {cnpj}: dre_conta {tp_periodo} de {dt_referencia} gravada ({len(contas)} contas)')


def run(ticker_filter=None):
    conn = get_conn()
    emissores = fetch_emissores(conn, ticker_filter)
    total = len(emissores)
    print(f'processing {total} emissores')
    for index, (id_emissor, cnpj) in enumerate(emissores, start=1):
        print(f'[{index}/{total}] {cnpj}')
        process_emissor(conn, id_emissor, cnpj)
    conn.close()


def main():
    ticker_filter = sys.argv[1] if len(sys.argv) > 1 else None
    run(ticker_filter)


if __name__ == '__main__':
    main()
