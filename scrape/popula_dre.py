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
from datetime import date

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


def nivel_superior(contas):
    # restringe a contas de "grupo" (ex: '3.06'), excluindo sub-contas de detalhe (ex:
    # '3.06.01') -- usado quando o texto de uma sub-conta pode coincidir por acaso com o de
    # outra sub-conta em outro ramo da hierarquia (ver vl_impostos abaixo).
    return [c for c in contas if c['cd_conta'].count('.') == 1]


def soma(*valores):
    presentes = [v for v in valores if v is not None]
    return sum(presentes) if presentes else None


def filhos_diretos(contas, cd_pai):
    nivel_pai = cd_pai.count('.')
    return [c for c in contas if c['cd_conta'].startswith(cd_pai + '.') and c['cd_conta'].count('.') == nivel_pai + 1]


def receita_em_outras_operacionais(contas):
    # achado validando contra o yfinance: em empresas onde 3.01 e genuinamente zero (sem
    # venda de bens/servicos no sentido tradicional -- holdings, seguradoras de distribuicao),
    # a receita real (comissao, prestacao de servico) as vezes fica dentro de "Outras Receitas
    # Operacionais" (3.04.04) em vez de 3.01. Posicao inconsistente: as vezes numa conta-filha
    # com "receita" no nome (CXSE3, UNIP3), as vezes na propria conta-pai sem filha informativa
    # (TELB3, RPAD3) -- testa as duas, nessa ordem. So usa o texto "receita" (nunca pega
    # "custo"/"despesa" da mesma sub-arvore por engano) e so quando a busca em 3.01 deu zero --
    # holdings puras (BRAP3/4) ficam corretamente de fora, porque nenhuma conta sob 3.04.04
    # tem "receita" no nome pra elas.
    #
    # Variante adicional achada testando a base inteira (RPAD3 2025-09-30): a conta-pai tem
    # valor real (243.000) mas a unica filha com "receita" no nome vem ZERADA na propria CVM
    # (mesma categoria do bug de split controlador/nao-controlador zerado, documentado acima,
    # so que numa arvore diferente) -- usa a soma das filhas SO se ela for diferente de zero,
    # senao cai pro valor da propria conta-pai.
    candidatos = [f for f in filhos_diretos(contas, '3.04.04') if 'receita' in normaliza(f['ds_conta'])]
    soma_filhos = soma(*(c['vl_conta'] for c in candidatos)) if candidatos else None
    if soma_filhos:
        return soma_filhos
    pai = next((c for c in contas if c['cd_conta'] == '3.04.04'), None)
    if pai and pai['vl_conta'] and 'receita' in normaliza(pai['ds_conta']):
        return pai['vl_conta']
    return None


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
        # frase generica de proposito -- a CVM usa "Resultado Antes dos Tributos sobre o
        # Lucro" pra maioria das empresas, mas "Resultado Antes Tributacao/Participacoes"
        # pros mesmos 25 bancos que dividem o imposto em IR corrente + diferido (ver
        # vl_impostos abaixo) -- so as 3 variacoes de "resultado antes ..." no projeto
        # inteiro sao essa, a de cima, e "Resultado Antes do Resultado Financeiro e dos
        # Tributos" (excluida explicitamente, e uma conta intermediaria diferente).
        'vl_lucro_antes_impostos': acha(contas, 'resultado antes', excluir=('resultado financeiro',)),
        # "Lucro/Prejuizo CONSOLIDADO do Periodo" pra quem consolida, "Lucro/Prejuizo do
        # Periodo" (sem "consolidado") pra quem so tem DRE individual (sem subsidiaria) --
        # frase sem "consolidado" casa com os dois.
        'vl_lucro_liquido_total': acha(contas, 'prejuizo', 'periodo'),
        'vl_lucro_liquido': acha(contas, 'atribu', 'controladora'),
        'vl_participacao_nao_controladores': acha(contas, 'atribu', 'nao controladores'),
    }
    # "Imposto de Renda e Contribuicao Social sobre o Lucro" e uma linha de grupo unica na
    # maioria dos periodos -- MAS a CVM tambem usa, em outros periodos (achado em 25 bancos,
    # incluindo BBAS3/BBDC4/ITUB4/BPAC3 -- nao e fixo por empresa, varia ano a ano pra mesma
    # empresa, parece mudanca de formulario da CVM ao longo do tempo), uma versao dividida em
    # DUAS linhas de grupo separadas ("Provisao para IR e Contribuicao Social" + "IR
    # Diferido"), sem nenhuma linha combinada. Restrito a contas de grupo (nivel_superior) pra
    # nao casar com a sub-conta-filha "Provisao para imposto de renda" que existe DENTRO de
    # cada uma dessas (current e diferido), o que pegaria so um pedaco do efeito fiscal total.
    if not valores['vl_receita_total']:
        escondida = receita_em_outras_operacionais(contas)
        if escondida:
            valores['vl_receita_total'] = escondida
    grupo = nivel_superior(contas)
    valores['vl_impostos'] = acha(grupo, 'imposto de renda', 'contribuicao social', 'sobre o lucro')
    if valores['vl_impostos'] is None:
        valores['vl_impostos'] = soma(acha(grupo, 'provisao para ir'), acha(grupo, 'ir diferido'))
    if valores['vl_lucro_liquido'] is None:
        # sem subsidiaria pra consolidar, nao existe linha "atribuido a controladores" --
        # todo o resultado e da propria empresa, sem split de participacao minoritaria
        valores['vl_lucro_liquido'] = valores['vl_lucro_liquido_total']
    elif (
        valores['vl_lucro_liquido'] == 0
        and valores['vl_participacao_nao_controladores'] == 0
        and valores['vl_lucro_liquido_total']
    ):
        # achado em CAMB3/CGRA4/VSTE3/RECV3 e outras 137 acoes (1001 linhas no total): a
        # empresa as vezes preenche as DUAS sub-contas de split ("atribuido aos
        # controladores"/"nao controladores") com 0, em vez de deixar de fora ou preencher o
        # total inteiro em "controladores" -- a propria CVM nao reconcilia (0+0 != total) nesse
        # caso, sinal de que nao ha participacao minoritaria real e o formulario so nao foi
        # preenchido. Mesmo fallback do caso "conta nao existe" acima, so que aqui a conta
        # EXISTE com valor 0 em vez de ausente.
        valores['vl_lucro_liquido'] = valores['vl_lucro_liquido_total']
    if perfil == 'banco':
        # banco nao tem resultado financeiro separado -- a intermediacao financeira (3.01-3.03)
        # JA E o resultado financeiro, nao existe desmembramento em receita/despesa financeira
        if valores['vl_resultado_financeiro'] is None:
            valores['vl_resultado_financeiro'] = valores['vl_lucro_bruto']
        valores['vl_receitas_financeiras'] = None
        valores['vl_despesas_financeiras'] = None
    return valores


def deriva_quarto_trimestre(valores_por_periodo):
    # ITR (trimestral) so cobre 1T/2T/3T -- nao existe "4o ITR" da CVM, so o anual (DFP),
    # entregue depois do fim do exercicio. Deriva o 4T isolado por subtracao (Anual - 1T - 2T
    # - 3T) quando os 4 periodos do mesmo ano civil estao disponiveis -- mesma ideia adotada
    # pro DFC (ver popula_dfc.py), so que aqui os trimestres ja vem isolados (nao YTD), entao
    # subtrai os 3 de uma vez em vez de so o trimestre anterior.
    #
    # vl_lpa_basico/vl_lpa_diluido ficam de fora da subtracao -- LPA e ponderado pela
    # quantidade de acoes em circulacao em cada trimestre, nao um valor monetario que soma
    # linearmente ("Anual - 1T - 2T - 3T" daria um numero sem sentido matematico, nao so
    # impreciso, se a empresa emitiu/recomprou acoes no meio do ano). Em vez disso, estima
    # pela quantidade de acoes IMPLICITA no 3T (lucro_liquido_3T / lpa_3T) -- assume que essa
    # quantidade nao muda muito entre 3T e 4T (corporativamente, a maioria das emissoes/
    # recompras e gradual, nao um salto abrupto so no ultimo trimestre). Testado contra
    # qt_acoes (yfinance) em ITSA4: a serie de acoes implicitas e suave e plausivel (~10,3B em
    # 2024, subindo gradualmente pra ~11,2B em 2026 -- bate com o real). Mas em EVEN3 o LPA
    # trimestral as vezes vem ZERADO na propria fonte CVM (problema da fonte, nao da
    # curadoria) -- nesse caso a divisao fica indefinida e o resultado e NULL, corretamente
    # (nao um numero forcado). So usa o 3T como referencia (nao o anual) porque e o periodo
    # mais proximo no tempo do 4T que estamos estimando.
    por_ano = {}
    for (dt_referencia, tp_periodo), valores in valores_por_periodo.items():
        chave_periodo = 'ANUAL' if tp_periodo == 'ANUAL' else dt_referencia.month
        por_ano.setdefault(dt_referencia.year, {})[chave_periodo] = valores

    derivados = {}
    for ano, periodos in por_ano.items():
        if 'ANUAL' not in periodos or not all(mes in periodos for mes in (3, 6, 9)):
            continue
        anual = periodos['ANUAL']
        trimestres = [periodos[mes] for mes in (3, 6, 9)]
        terceiro_trimestre = trimestres[-1]
        derivado = {}
        for coluna in COLUNAS_TB_DRE:
            if coluna in ('vl_lpa_basico', 'vl_lpa_diluido'):
                lpa_3t = terceiro_trimestre[coluna]
                lucro_liquido_3t = terceiro_trimestre['vl_lucro_liquido']
                lucro_liquido_4t = derivado['vl_lucro_liquido']
                if lpa_3t and lucro_liquido_3t and lucro_liquido_4t is not None:
                    estimado = lucro_liquido_4t * lpa_3t / lucro_liquido_3t
                    # mesma guarda de LIMITE_LPA usada em extrai_lpa() -- aqui a explosao tem
                    # uma causa adicional: lucro_liquido_3t proximo de zero (mesmo um lucro
                    # minusculo, tipo R$ -12 mil) faz a "quantidade de acoes implicita"
                    # (lucro_liquido_3t / lpa_3t) ficar minuscula, e dividir por ela de novo
                    # explode o resultado pra ordem de milhoes (confirmado em SOND5 2012-09-30:
                    # lucro_3t=-12.000, lpa_3t=-614 -> estimado ~5,2 milhoes, estourando
                    # NUMERIC(10,4)) -- sem essa guarda o INSERT quebrava o scraper inteiro.
                    derivado[coluna] = None if abs(estimado) >= LIMITE_LPA else estimado
                else:
                    derivado[coluna] = None
                continue
            valor_anual = anual[coluna]
            valores_trimestrais = [t[coluna] for t in trimestres]
            if valor_anual is None or any(v is None for v in valores_trimestrais):
                derivado[coluna] = None
            else:
                derivado[coluna] = valor_anual - sum(valores_trimestrais)
        derivados[(date(ano, 12, 31), 'TRIMESTRAL')] = derivado
    return derivados


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
    valores_por_periodo = {}
    for tp_periodo, dt_referencia, contas in periodos:
        perfil = detecta_perfil(contas)
        valores = extrai_wide(contas, perfil)
        valores.update(extrai_lpa(contas, sg_classe))
        valores_por_periodo[(dt_referencia, tp_periodo)] = valores
        upsert_dre(conn, id_ativo, dt_referencia, tp_periodo, valores)

    for (dt_referencia, tp_periodo), valores in deriva_quarto_trimestre(valores_por_periodo).items():
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
