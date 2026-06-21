# Curadoria do balanco patrimonial: le o dado bruto ja raspado em tb_balanco_conta (por
# scraper_balanco_patrimonial.py) e preenche tb_balanco_patrimonial, casando cada coluna por
# texto de ds_conta (normalizado), exceto ativo/passivo total (cd_conta '1'/'2', estaveis nos
# dois perfis -- ver detecta_perfil). Mesmo motivo da separacao em popula_dre.py: e so leitura
# local, corrigir um bug de casamento nao exige rebaixar nada da CVM.
import os
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

COLUNAS_TB_BALANCO = (
    'vl_ativo_total',
    'vl_ativo_circulante',
    'vl_passivo_total',
    'vl_passivo_circulante',
    'vl_patrimonio_liquido_total',
    'vl_participacao_nao_controladores',
    'vl_patrimonio_liquido',
    'vl_divida_total',
    'vl_divida_liquida',
    'vl_caixa',
    'vl_capital_giro',
    'vl_imobilizado',
    'vl_valor_patrimonial_tangivel',
)


def normaliza(texto):
    texto = texto.strip().lower()
    texto = unicodedata.normalize('NFKD', texto)
    return ''.join(c for c in texto if not unicodedata.combining(c))


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
            SELECT dt_referencia, tp_periodo, cd_conta, ds_conta, vl_conta
            FROM public.tb_balanco_conta
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
    # profundidade ascendente, e dentro do mesmo nivel, cd_conta numerico DESCENDENTE --
    # mesma correcao aplicada em popula_dre.py: algumas empresas repetem o mesmo texto de
    # conta em mais de um nivel da hierarquia, com a ocorrencia mais cedo zerada (campo
    # estrutural sem valor real) -- preferir o cd_conta mais alto entre empates pega a
    # ocorrencia "final" certa.
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


def soma(*valores):
    presentes = [v for v in valores if v is not None]
    return sum(presentes) if presentes else None


def subtrai(a, b):
    if a is None or b is None:
        return None
    return a - b


def passivo_arrendamento_fora_emprestimos(contas):
    # achado validando vl_divida_total contra o yfinance: "Passivos de Arrendamentos" (IFRS
    # 16) mora numa posicao TOTALMENTE diferente de "Emprestimos e Financiamentos" em varias
    # empresas (ITSA4: 2.01.05.02.05 + 2.02.02.02.04 = 62.000.000 + 878.000.000 = 940.000.000,
    # bate exato com o gap contra o yfinance). Restrito a frase "passivo(s) de
    # arrendamento(s)" (familia de texto limpa e isolada, ~31 empresas) -- as outras ~111
    # variacoes de "arrendamento" (arrendamento mercantil, financiamento por arrendamento
    # etc.) ficam de fora de proposito, mesma decisao ja documentada acima (texto/posicao
    # variam demais nessas pra confiar numa heuristica generica). Restrito a contas-folha (sem
    # filhos) pra nao somar uma conta-pai E suas filhas juntas; exclui 2.01.04/2.02.01 pra nao
    # duplicar o que ja entra em divida_circulante/divida_nao_circulante acima.
    todos_cd = {c['cd_conta'] for c in contas}
    candidatos = [
        c
        for c in contas
        if c['cd_conta'].startswith('2.')
        and not (c['cd_conta'].startswith('2.01.04') or c['cd_conta'].startswith('2.02.01'))
        and 'passivo' in normaliza(c['ds_conta'])
        and 'arrendamento' in normaliza(c['ds_conta'])
        and not any(outro.startswith(c['cd_conta'] + '.') for outro in todos_cd)
    ]
    return soma(*(c['vl_conta'] for c in candidatos)) if candidatos else None


def detecta_perfil(contas):
    # banco "de deposito" (BBAS3, BPAC3 etc.) usa um plano de contas sem o conceito de
    # circulante/nao circulante -- cd_conta '1.01' e "Caixa e Equivalentes de Caixa" em vez
    # de "Ativo Circulante". BRBI11 (banco de investimento) segue o plano padrao, nao cai
    # nesse perfil.
    conta_101 = next((c for c in contas if c['cd_conta'] == '1.01'), None)
    if conta_101 and 'caixa e equivalentes' in normaliza(conta_101['ds_conta']):
        return 'banco'
    return 'padrao'


def extrai_wide(contas, perfil):
    valores = {
        'vl_ativo_total': por_codigo(contas, '1'),
        'vl_passivo_total': por_codigo(contas, '2'),
        'vl_imobilizado': acha(contas, 'imobilizado'),
    }
    # "Patrimonio Liquido Consolidado" inclui participacao de nao controladores -- mesmo
    # padrao da DRE (lucro liquido total vs. atribuivel aos controladores). A frase de
    # nao-controladores varia (EVEN3: "Participacao dos Acionistas Nao Controladores" como
    # irma das reservas; BBAS3: "Patrimonio Liquido Atribuido aos Nao Controladores" como
    # filho direto) -- "nao controlador" casa as duas.
    contas_passivo = [c for c in contas if c['cd_conta'].startswith('2')]
    valores['vl_patrimonio_liquido_total'] = acha(contas_passivo, 'patrimonio liquido')
    valores['vl_participacao_nao_controladores'] = acha(contas_passivo, 'nao controlador')
    if valores['vl_participacao_nao_controladores'] is None:
        valores['vl_patrimonio_liquido'] = valores['vl_patrimonio_liquido_total']
    else:
        valores['vl_patrimonio_liquido'] = subtrai(
            valores['vl_patrimonio_liquido_total'], valores['vl_participacao_nao_controladores']
        )

    intangivel = acha(contas, 'intangivel')
    valores['vl_valor_patrimonial_tangivel'] = subtrai(valores['vl_patrimonio_liquido'], intangivel)

    if perfil == 'banco':
        valores['vl_ativo_circulante'] = None
        valores['vl_passivo_circulante'] = None
        valores['vl_capital_giro'] = None
        valores['vl_caixa'] = por_codigo(contas, '1.01')
        # banco nao tem "Emprestimos e Financiamentos" -- usa todo o passivo financeiro ao
        # custo amortizado (inclui deposito de cliente, mesmo problema ja aceito pro "Total
        # Debt" do yfinance nesse setor -- ver comentario em tb_balanco_patrimonial.sql).
        valores['vl_divida_total'] = acha(contas, 'passivos financeiros ao custo amortizado')
    else:
        ativo_circulante = por_codigo(contas, '1.01')
        passivo_circulante = por_codigo(contas, '2.01')
        valores['vl_ativo_circulante'] = ativo_circulante
        valores['vl_passivo_circulante'] = passivo_circulante
        valores['vl_capital_giro'] = subtrai(ativo_circulante, passivo_circulante)
        # algumas empresas (25 confirmadas, ex: LOGG3) escondem um valor de "Titulos e
        # Valores Mobiliarios" dentro de "Outros Ativos Circulantes" (1.01.08) em vez da
        # linha padrao de Aplicacoes Financeiras (1.01.02) -- economicamente e a mesma coisa
        # (titulo/aplicacao de curto prazo), e o yfinance inclui esse valor no "caixa" dele;
        # sem somar aqui, vl_caixa ficava ~90% menor que o real pra essas empresas (achado
        # validando contra o yfinance: LOGG3 1T26, 7.405+43.036+339.582 = 390.023 mil, bate
        # exato com o yfinance). Restrito ao ramo 1.01.08 de proposito -- o mesmo texto
        # aparece tambem dentro de 1.01.01/1.01.02 (ja contado, seria duplicar) e de 1.01.03
        # "Contas a Receber" (nao e caixa, e recebivel).
        titulos_em_outros = acha([c for c in contas if c['cd_conta'].startswith('1.01.08')], 'titulos e valores mobiliarios')
        valores['vl_caixa'] = soma(por_codigo(contas, '1.01.01'), por_codigo(contas, '1.01.02'), titulos_em_outros)
        # restringe por prefixo de cd_conta -- "Emprestimos e Financiamentos" existe em
        # 2.01 (circulante) E 2.02 (nao circulante) com a MESMA profundidade (2 pontos), sem
        # restringir o acha() poderia empatar e pegar a conta errada.
        divida_circulante = acha([c for c in contas if c['cd_conta'].startswith('2.01')], 'emprestimos e financiamentos')
        divida_nao_circulante = acha([c for c in contas if c['cd_conta'].startswith('2.02')], 'emprestimos e financiamentos')
        arrendamento = passivo_arrendamento_fora_emprestimos(contas)
        valores['vl_divida_total'] = soma(divida_circulante, divida_nao_circulante, arrendamento)

    valores['vl_divida_liquida'] = subtrai(valores['vl_divida_total'], valores['vl_caixa'])
    return valores


def upsert_balanco(conn, id_ativo, dt_referencia, tp_periodo, valores):
    colunas = list(COLUNAS_TB_BALANCO)
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


def process_ativo(conn, id_ativo):
    periodos = fetch_periodos_locais(conn, id_ativo)
    for tp_periodo, dt_referencia, contas in periodos:
        perfil = detecta_perfil(contas)
        valores = extrai_wide(contas, perfil)
        upsert_balanco(conn, id_ativo, dt_referencia, tp_periodo, valores)


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
