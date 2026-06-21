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


def download_cvm_csv(tipo, ano, demonstrativo, grupo):
    os.makedirs(CACHE_DIR, exist_ok=True)
    csv_name = f'{tipo}_cia_aberta_{demonstrativo}_{grupo}_{ano}.csv'
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
def carrega_ano(tipo, ano, demonstrativo, grupo):
    csv_path = download_cvm_csv(tipo, ano, demonstrativo, grupo)
    if csv_path is None:
        return None
    df = pd.read_csv(csv_path, sep=';', encoding='ISO-8859-1', dtype={'CNPJ_CIA': str, 'CD_CONTA': str})
    # fluxo de caixa e sempre acumulado desde o inicio do ano (nunca trimestre isolado) -- so
    # filtra o comparativo do ano anterior, sem o problema de trimestre-vs-acumulado da DRE.
    return df[df['ORDEM_EXERC'] == 'ÚLTIMO']


def contas_por_periodo(df, cnpj, tp_periodo):
    if df is None:
        return []
    subset = df[df['CNPJ_CIA'] == cnpj]
    periodos = []
    for dt_referencia, df_periodo in subset.groupby('DT_REFER'):
        contas = []
        for row in df_periodo.itertuples():
            fator = FATOR_ESCALA.get(row.ESCALA_MOEDA, 1)
            valor = None if pd.isna(row.VL_CONTA) else float(row.VL_CONTA) * fator
            contas.append({'cd_conta': row.CD_CONTA, 'ds_conta': row.DS_CONTA, 'vl_conta': valor})
        periodos.append((tp_periodo, date.fromisoformat(dt_referencia), contas))
    return periodos


def fetch_periodos_cvm(cnpj):
    # Ordem de prioridade, do mais pro menos preferido -- so usa a fonte seguinte pros
    # periodos que ainda faltarem depois das anteriores: Metodo Indireto consolidado (quase
    # todas as empresas), Metodo Indireto individual (sem subsidiaria pra consolidar), Metodo
    # Direto consolidado, Metodo Direto individual (poucas empresas, ex: HAGA4 -- mesma
    # estrutura de cd_conta top-level 6.01-6.05, serve de fallback final).
    #
    # ITR (trimestral) so cobre 1T/2T/3T (sempre acumulado desde janeiro, ver carrega_ano) --
    # nao existe "4o ITR". O DFP (anual) traz o acumulado do ano inteiro (Jan-Dez), gravado
    # com tp_periodo='ANUAL' -- popula_dfc.py usa esse valor como "mais um periodo do ano" pra
    # isolar o 4T por subtracao do acumulado de 9 meses (ver isola_trimestres()), mesma logica
    # ja usada pra isolar 2T/3T.
    fontes = [
        (tipo, demonstrativo, grupo, tp_periodo)
        for tipo, tp_periodo in (('itr', 'TRIMESTRAL'), ('dfp', 'ANUAL'))
        for demonstrativo, grupo in (('DFC_MI', 'con'), ('DFC_MI', 'ind'), ('DFC_MD', 'con'), ('DFC_MD', 'ind'))
    ]
    contas_por_chave = {}
    for tipo, demonstrativo, grupo, tp_periodo in fontes:
        for ano in range(ANO_INICIAL, ANO_FINAL + 1):
            df = carrega_ano(tipo, ano, demonstrativo, grupo)
            for tpp, dt_referencia, contas in contas_por_periodo(df, cnpj, tp_periodo):
                contas_por_chave.setdefault((dt_referencia, tpp), contas)
    return [(tp_periodo, dt_referencia, contas) for (dt_referencia, tp_periodo), contas in contas_por_chave.items()]


def upsert_dfc_conta(conn, id_ativo, dt_referencia, tp_periodo, contas):
    with conn.cursor() as cur:
        for conta in contas:
            cur.execute(
                '''
                INSERT INTO public.tb_dfc_conta (id_ativo, dt_referencia, tp_periodo, cd_conta, ds_conta, vl_conta)
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
        print(f'  {cnpj}: nenhum dfc encontrado')
        return
    for tp_periodo, dt_referencia, contas in periodos:
        for id_ativo in ids_ativo:
            upsert_dfc_conta(conn, id_ativo, dt_referencia, tp_periodo, contas)
        print(f'  {cnpj}: dfc_conta {tp_periodo} de {dt_referencia} gravado ({len(contas)} contas)')


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
