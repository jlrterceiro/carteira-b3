# Curadoria da DRE: le o dado bruto ja raspado em tb_dre_conta (por scraper_dre.py) e
# preenche tb_dre, casando cada coluna por texto de ds_conta (normalizado), nunca por
# cd_conta fixo -- o plano de contas da CVM varia por perfil de empresa (padrao vs. banco)
# e a posicao numerica do resultado final varia ate entre bancos (3.11 no BBAS3, 3.09 no
# BPAC3). Separado de scraper_dre.py de proposito: e so leitura local (sem download/parse de
# CSV da CVM), entao rodar de novo pra corrigir um bug de casamento e rapido e nao depende de
# rebaixar nada.
import os
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

COLUNAS_TB_DRE = (
    'vl_receita_total',
    'vl_custo_receita',
    'vl_lucro_bruto',
    'vl_despesas_operacionais',
    'vl_resultado_operacional',
    'vl_receitas_financeiras',
    'vl_despesas_financeiras',
    'vl_resultado_financeiro',
    'vl_lucro_antes_impostos',
    'vl_impostos',
    'vl_lucro_liquido_total',
    'vl_participacao_nao_controladores',
    'vl_lucro_liquido',
    'vl_lpa_basico',
    'vl_lpa_diluido',
)

# a CVM ocasionalmente reporta LPA com erro grosseiro de carga (confirmado em MRVE3:
# 2017-06-30 trouxe R$ 614 milhoes/acao) -- vl_lpa_basico/vl_lpa_diluido sao NUMERIC(10,4),
# que aceita ate ~10^6; descarta (fica NULL) em vez de deixar o INSERT estourar, mesmo
# limiar usado pelo scraper antigo (scraper_dre_old_yfinance.py) pro mesmo tipo de erro.
LIMITE_LPA = 10_000


def normaliza(texto):
    texto = texto.strip().lower()
    texto = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in texto if not unicodedata.combining(c))


def fetch_ativos(conn, ticker_filter=None):
    query = '''
        SELECT a.id_ativo, a.sg_classe
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


def fetch_periodos_locais(conn, id_ativo):
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT dt_referencia, tp_periodo, cd_conta, ds_conta, vl_conta
            FROM public.tb_dre_conta
            WHERE id_ativo = %s
            ORDER BY dt_referencia, tp_periodo
            ''',
            (id_ativo,),
        )
        linhas = cur.fetchall()
    periodos = {}
    for dt_referencia, tp_periodo, cd_conta, ds_conta, vl_conta in linhas:
        chave = (dt_referencia, tp_periodo)
        periodos.setdefault(chave, []).append(
            {'cd_conta': cd_conta, 'ds_conta': ds_conta, 'vl_conta': None if vl_conta is None else float(vl_conta)}
        )
    return [(tp_periodo, dt_referencia, contas) for (dt_referencia, tp_periodo), contas in periodos.items()]


def chave_ordenacao_conta(cd_conta):
    # profundidade ascendente (prefere conta mais "resumo"/proxima da raiz), e dentro do
    # mesmo nivel, cd_conta numerico DESCENDENTE -- algumas empresas (achado em BBAS3)
    # repetem o mesmo texto de conta ("Atribuido aos Socios da Empresa Controladora") em
    # mais de um nivel da hierarquia (ex: 3.09.01 E 3.11.01), com a ocorrencia mais cedo
    # zerada (so um campo estrutural do formulario, sem valor real preenchido) e a real
    # ficando na ocorrencia de cd_conta mais alto -- preferir o cd_conta mais alto entre
    # empates de profundidade pega a conta "final" certa.
    partes = tuple(int(p) for p in cd_conta.split('.'))
    return (len(partes), tuple(-p for p in partes))


def acha(contas, *frases, excluir=()):
    candidatos = []
    for c in contas:
        ds = normaliza(c['ds_conta'])
        if all(normaliza(f) in ds for f in frases) and not any(normaliza(e) in ds for e in excluir):
            candidatos.append(c)
    if not candidatos:
        return None
    candidatos.sort(key=lambda c: chave_ordenacao_conta(c['cd_conta']))
    return candidatos[0]['vl_conta']


def por_codigo(contas, cd_conta):
    conta = next((c for c in contas if c['cd_conta'] == cd_conta), None)
    return conta['vl_conta'] if conta else None


def filhos_diretos(contas, cd_pai):
    nivel_pai = cd_pai.count('.')
    return [c for c in contas if c['cd_conta'].startswith(cd_pai + '.') and c['cd_conta'].count('.') == nivel_pai + 1]


def extrai_lpa(contas, sg_classe):
    resultado = {}
    for prefixo, coluna in (('3.99.01', 'vl_lpa_basico'), ('3.99.02', 'vl_lpa_diluido')):
        filhos = filhos_diretos(contas, prefixo)
        if not filhos:
            valor = por_codigo(contas, prefixo)
        else:
            alvo = None
            if sg_classe:
                alvo = next((f for f in filhos if normaliza(f['ds_conta']) == normaliza(sg_classe)), None)
                if alvo is None:
                    alvo = next((f for f in filhos if normaliza(sg_classe) in normaliza(f['ds_conta'])), None)
            if alvo is None:
                alvo = filhos[0]
            valor = alvo['vl_conta']
        resultado[coluna] = None if valor is not None and abs(valor) >= LIMITE_LPA else valor
    return resultado


def detecta_perfil(contas):
    valor_301 = next((c for c in contas if c['cd_conta'] == '3.01'), None)
    if valor_301 and 'intermediacao financeira' in normaliza(valor_301['ds_conta']):
        return 'banco'
    return 'padrao'


def extrai_wide(contas, perfil):
    valores = {
        'vl_receita_total': por_codigo(contas, '3.01'),
        'vl_custo_receita': por_codigo(contas, '3.02'),
        'vl_lucro_bruto': por_codigo(contas, '3.03'),
        'vl_despesas_operacionais': por_codigo(contas, '3.04'),
        'vl_resultado_operacional': por_codigo(contas, '3.05'),
        'vl_receitas_financeiras': acha(contas, 'receitas financeiras'),
        'vl_despesas_financeiras': acha(contas, 'despesas financeiras'),
        'vl_resultado_financeiro': acha(contas, 'resultado financeiro', excluir=('antes',)),
        'vl_lucro_antes_impostos': acha(contas, 'resultado antes', 'tributos', excluir=('resultado financeiro',)),
        'vl_impostos': acha(contas, 'imposto de renda'),
        # "Lucro/Prejuizo CONSOLIDADO do Periodo" pra quem consolida, "Lucro/Prejuizo do
        # Periodo" (sem "consolidado") pra quem so tem DRE individual (sem subsidiaria) --
        # frase sem "consolidado" casa com os dois.
        'vl_lucro_liquido_total': acha(contas, 'prejuizo', 'periodo'),
        'vl_lucro_liquido': acha(contas, 'atribu', 'controladora'),
        'vl_participacao_nao_controladores': acha(contas, 'atribu', 'nao controladores'),
    }
    if valores['vl_lucro_liquido'] is None:
        # sem subsidiaria pra consolidar, nao existe linha "atribuido a controladores" --
        # todo o resultado e da propria empresa, sem split de participacao minoritaria
        valores['vl_lucro_liquido'] = valores['vl_lucro_liquido_total']
    if perfil == 'banco':
        # banco nao tem resultado financeiro separado -- a intermediacao financeira (3.01-3.03)
        # JA E o resultado financeiro, nao existe desmembramento em receita/despesa financeira
        if valores['vl_resultado_financeiro'] is None:
            valores['vl_resultado_financeiro'] = valores['vl_lucro_bruto']
        valores['vl_receitas_financeiras'] = None
        valores['vl_despesas_financeiras'] = None
    return valores


def upsert_dre(conn, id_ativo, dt_referencia, tp_periodo, valores):
    colunas = list(COLUNAS_TB_DRE)
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


def process_ativo(conn, id_ativo, sg_classe):
    periodos = fetch_periodos_locais(conn, id_ativo)
    for tp_periodo, dt_referencia, contas in periodos:
        perfil = detecta_perfil(contas)
        valores = extrai_wide(contas, perfil)
        valores.update(extrai_lpa(contas, sg_classe))
        upsert_dre(conn, id_ativo, dt_referencia, tp_periodo, valores)


def run(ticker_filter=None):
    conn = get_conn()
    ativos = fetch_ativos(conn, ticker_filter)
    total = len(ativos)
    print(f'processing {total} ativos')
    for index, (id_ativo, sg_classe) in enumerate(ativos, start=1):
        print(f'[{index}/{total}] id_ativo={id_ativo}')
        process_ativo(conn, id_ativo, sg_classe)
    conn.close()


def main():
    ticker_filter = sys.argv[1] if len(sys.argv) > 1 else None
    run(ticker_filter)


if __name__ == '__main__':
    main()
