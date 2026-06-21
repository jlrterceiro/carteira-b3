# Curadoria do fluxo de caixa: le o dado bruto ja raspado em tb_dfc_conta (por
# scraper_dfc.py) e preenche tb_dfc. Diferente de popula_dre.py/popula_balanco.py: a posicao
# por cd_conta (6.01-6.05) e estavel em todos os perfis testados (banco, seguradora, padrao),
# entao a extracao por periodo e direta, sem casamento por texto nem deteccao de perfil --
# mas precisa de um passo extra que a DRE/balanco nao tem: a CVM so publica o fluxo de caixa
# acumulado desde o inicio do ano (nunca o trimestre isolado), entao isola o trimestre por
# subtracao DEPOIS de extrair os valores YTD de cada periodo.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

COLUNAS_TB_DFC = (
    'vl_caixa_operacional',
    'vl_caixa_investimento',
    'vl_caixa_financiamento',
    'vl_variacao_cambial',
    'vl_variacao_caixa',
)

CODIGOS = {
    'vl_caixa_operacional': '6.01',
    'vl_caixa_investimento': '6.02',
    'vl_caixa_financiamento': '6.03',
    'vl_variacao_cambial': '6.04',
    'vl_variacao_caixa': '6.05',
}


def fetch_ativos(conn, ticker_filter=None):
    query = '''
        SELECT a.id_ativo
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
        return [row[0] for row in cur.fetchall()]


def fetch_periodos_locais(conn, id_ativo):
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT dt_referencia, tp_periodo, cd_conta, vl_conta
            FROM public.tb_dfc_conta
            WHERE id_ativo = %s AND cd_conta IN ('6.01', '6.02', '6.03', '6.04', '6.05')
            ORDER BY dt_referencia, tp_periodo
            ''',
            (id_ativo,),
        )
        return cur.fetchall()


def extrai_ytd_por_periodo(conn, id_ativo):
    colunas_por_codigo = {cd: coluna for coluna, cd in CODIGOS.items()}
    valores_por_chave = {}
    for dt_referencia, tp_periodo, cd_conta, vl_conta in fetch_periodos_locais(conn, id_ativo):
        coluna = colunas_por_codigo[cd_conta]
        chave = (dt_referencia, tp_periodo)
        valores_por_chave.setdefault(chave, dict.fromkeys(COLUNAS_TB_DFC))
        valores_por_chave[chave][coluna] = None if vl_conta is None else float(vl_conta)
    return valores_por_chave


def subtrai(a, b):
    if a is None or b is None:
        return None
    return a - b


def isola_trimestres(valores_por_chave):
    # agrupa por ano fiscal (assume ano civil, igual o resto do mercado B3) e ordena
    # cronologicamente dentro do ano -- 1o trimestre do ano fica como esta (YTD do 1T e o
    # proprio 1T); os seguintes (2T, 3T) sao isolados subtraindo o YTD do trimestre anterior
    # do mesmo ano.
    #
    # O ANUAL (DFP, sempre o ultimo periodo do ano civil quando existe) gera DOIS registros:
    # o proprio total anual (tp_periodo='ANUAL', sem nenhuma transformacao -- valor util por
    # si so, ex: "fluxo de caixa operacional do ano inteiro") E, quando o periodo
    # imediatamente anterior e especificamente o 3T (mes 9), o 4T isolado por subtracao do
    # acumulado de 9 meses (tp_periodo='TRIMESTRAL', mesma logica do 2T/3T). Se faltar o 3T
    # daquele ano (ITR nao entregue, falha de scraping etc.), so grava o ANUAL -- subtrair do
    # periodo errado geraria um 4T silenciosamente errado.
    por_ano = {}
    for (dt_referencia, tp_periodo), valores in valores_por_chave.items():
        por_ano.setdefault(dt_referencia.year, []).append((dt_referencia, tp_periodo, valores))

    isolados = {}
    for ano, periodos in por_ano.items():
        periodos.sort(key=lambda p: p[0])
        anterior = None
        anterior_dt = None
        for dt_referencia, tp_periodo, valores in periodos:
            if tp_periodo == 'ANUAL':
                isolados[(dt_referencia, 'ANUAL')] = valores
                if anterior is not None and anterior_dt.month == 9:
                    isolados[(dt_referencia, 'TRIMESTRAL')] = {
                        coluna: subtrai(valores[coluna], anterior[coluna]) for coluna in COLUNAS_TB_DFC
                    }
            elif anterior is None:
                isolados[(dt_referencia, tp_periodo)] = valores
            else:
                isolados[(dt_referencia, tp_periodo)] = {
                    coluna: subtrai(valores[coluna], anterior[coluna]) for coluna in COLUNAS_TB_DFC
                }
            anterior, anterior_dt = valores, dt_referencia
    return isolados


def upsert_dfc(conn, id_ativo, dt_referencia, tp_periodo, valores):
    colunas = list(COLUNAS_TB_DFC)
    placeholders = ', '.join(['%s'] * len(colunas))
    update_clause = ', '.join(f'{c} = EXCLUDED.{c}' for c in colunas)
    with conn.cursor() as cur:
        cur.execute(
            f'''
            INSERT INTO public.tb_dfc (
                id_ativo, dt_referencia, tp_periodo, {', '.join(colunas)}
            ) VALUES (%s, %s, %s, {placeholders})
            ON CONFLICT (id_ativo, dt_referencia, tp_periodo) DO UPDATE SET
                {update_clause}, dh_atualizacao = now()
            ''',
            (id_ativo, dt_referencia, tp_periodo, *[valores[c] for c in colunas]),
        )
    conn.commit()


def process_ativo(conn, id_ativo):
    valores_por_chave = extrai_ytd_por_periodo(conn, id_ativo)
    isolados = isola_trimestres(valores_por_chave)
    for (dt_referencia, tp_periodo), valores in isolados.items():
        upsert_dfc(conn, id_ativo, dt_referencia, tp_periodo, valores)


def run(ticker_filter=None):
    conn = get_conn()
    ids_ativo = fetch_ativos(conn, ticker_filter)
    total = len(ids_ativo)
    print(f'processing {total} ativos')
    for index, id_ativo in enumerate(ids_ativo, start=1):
        print(f'[{index}/{total}] id_ativo={id_ativo}')
        process_ativo(conn, id_ativo)
    conn.close()


def main():
    ticker_filter = sys.argv[1] if len(sys.argv) > 1 else None
    run(ticker_filter)


if __name__ == '__main__':
    main()
