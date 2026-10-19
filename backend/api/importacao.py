"""
Importacao do extrato de negociacao da B3 (xlsx da Area do Investidor) pra uma carteira do usuario logado.

Mesma regra do scrape/import_operacoes.py (CLI): so COMPRA/VENDA, fracionario perde o "F" do ticker, duplicata e
decidida CONTANDO ocorrencias (ativo, tipo, data, quantidade, preco) ja gravadas na carteira -- reimportar o arquivo
inteiro, ou um periodo que se sobrepoe ao anterior, nao duplica nada. A diferenca e que aqui nada e gravado na
previa e a gravacao e atomica (tudo ou nada).

O arquivo vem de um usuario: tamanho limitado, so .xlsx, cabecalho conferido, nenhuma formula e executada
(openpyxl le o valor em cache) e o total descompactado tambem tem teto (zip bomb).
"""
import io
import re
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import openpyxl

COLUNAS = ['Data do Negócio', 'Tipo de Movimentação', 'Mercado', 'Prazo/Vencimento', 'Instituição',
           'Código de Negociação', 'Quantidade', 'Preço', 'Valor']
TIPOS = {'compra': 'COMPRA', 'venda': 'VENDA'}
MAX_BYTES = 5 * 1024 * 1024
MAX_DESCOMPACTADO = 60 * 1024 * 1024
MAX_LINHAS = 20000
AMOSTRA = 15
OITO = Decimal('0.00000001')


class PlanilhaInvalida(Exception):
    pass


def _dec(v, campo, n):
    try:
        d = Decimal(str(v).replace(',', '.')) if isinstance(v, str) else Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise PlanilhaInvalida(f'linha {n}: {campo} invalido ({v!r})')
    if not d.is_finite():
        raise PlanilhaInvalida(f'linha {n}: {campo} invalido ({v!r})')
    return d.quantize(OITO)


def _data(v, n):
    try:
        if isinstance(v, str):
            d = datetime.strptime(v.strip(), '%d/%m/%Y').date()
        elif isinstance(v, datetime):
            d = v.date()
        elif isinstance(v, date):
            d = v
        else:
            raise ValueError
    except ValueError:
        raise PlanilhaInvalida(f'linha {n}: data invalida ({v!r})')
    if d < date(1990, 1, 1) or d > date.today() + timedelta(days=1):
        raise PlanilhaInvalida(f'linha {n}: data fora do intervalo aceito ({d})')
    return d


def le_planilha(dados: bytes):
    """-> lista de operacoes (dict). Levanta PlanilhaInvalida com mensagem pronta pro usuario."""
    if len(dados) > MAX_BYTES:
        raise PlanilhaInvalida(f'arquivo maior que {MAX_BYTES // 1024 // 1024} MB')
    if dados[:2] != b'PK':
        raise PlanilhaInvalida('o arquivo nao e uma planilha .xlsx')
    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_DESCOMPACTADO:
                raise PlanilhaInvalida('planilha grande demais')
        wb = openpyxl.load_workbook(io.BytesIO(dados), data_only=True)
    except PlanilhaInvalida:
        raise
    except Exception:
        raise PlanilhaInvalida('nao consegui abrir a planilha (arquivo corrompido ou nao e .xlsx)')
    ws = wb.active
    linhas = ws.iter_rows(values_only=True)
    cab = next(linhas, None)
    cab = [(str(c).strip() if c is not None else '') for c in (cab or ())[:len(COLUNAS)]]
    if cab[:3] == ['Entrada/Saída', 'Data', 'Movimentação']:
        raise PlanilhaInvalida('esse e o extrato de MOVIMENTACAO (dividendos, transferencias...). Baixe na Area do '
                               'Investidor da B3 o "Extrato de NEGOCIACAO", que traz as compras e vendas')
    if cab != COLUNAS:
        raise PlanilhaInvalida('cabecalho inesperado: use o "Extrato de Negociacao" da Area do Investidor da B3 '
                               '(colunas: ' + ', '.join(COLUNAS) + ')')
    ops = []
    for n, r in enumerate(linhas, start=2):
        if not any(c is not None and str(c).strip() for c in r):
            continue
        if len(ops) >= MAX_LINHAS:
            raise PlanilhaInvalida(f'mais de {MAX_LINHAS} linhas')
        dt, tipo, mercado, _prazo, inst, codigo, qtd, preco, valor = (list(r) + [None] * 9)[:9]
        sigla = TIPOS.get(str(tipo or '').strip().lower())
        codigo = str(codigo or '').strip().upper()
        mercado = str(mercado or '').strip()
        inst = re.sub(r'\s+', ' ', str(inst or '')).strip()
        if not codigo or not inst:
            raise PlanilhaInvalida(f'linha {n}: codigo de negociacao ou instituicao vazio')
        if len(inst) > 120 or len(codigo) > 20:
            raise PlanilhaInvalida(f'linha {n}: texto longo demais')
        if mercado == 'Mercado Fracionário' and codigo.endswith('F'):
            codigo = codigo[:-1]
        d = _data(dt, n)
        q, p = _dec(qtd, 'quantidade', n), _dec(preco, 'preco', n)
        v = _dec(valor, 'valor', n) if valor is not None else (q * p).quantize(OITO)
        if sigla and (q <= 0 or p <= 0):
            raise PlanilhaInvalida(f'linha {n}: quantidade e preco precisam ser positivos')
        ops.append({'linha': n, 'tipo_txt': str(tipo or '').strip(), 'sigla': sigla, 'dt': d, 'mercado': mercado,
                    'instituicao': inst, 'ticker': codigo, 'qtd': q, 'preco': p, 'valor': v})
    if not ops:
        raise PlanilhaInvalida('a planilha nao tem nenhuma operacao')
    return ops


def carteira_do_usuario(conn, id_usuario):
    """O sistema trabalha so no nivel do usuario. A tabela tb_carteira continua existindo por dentro (as funcoes de
    calculo e as tabelas derivadas ainda se apoiam nela), mas cada usuario tem UMA e ela nao aparece na interface."""
    with conn.cursor() as cur:
        cur.execute('SELECT id_carteira, nm_carteira FROM public.tb_carteira WHERE id_usuario = %s AND fl_ativa ORDER BY id_carteira LIMIT 1',
                    (id_usuario,))
        r = cur.fetchone()
    if r is None:
        raise PlanilhaInvalida('usuario sem carteira interna (cadastro incompleto)')
    return {'id_carteira': r[0], 'nm_carteira': r[1]}


def resumo_importacao(conn, id_usuario):
    with conn.cursor() as cur:
        cur.execute(
            '''SELECT count(*), min(o.dt_operacao), max(o.dt_operacao)
               FROM public.tb_operacao o JOIN public.tb_carteira c USING (id_carteira)
               WHERE c.id_usuario = %s''', (id_usuario,))
        n, primeira, ultima = cur.fetchone()
    return {'total_operacoes': n, 'primeira': primeira.isoformat() if primeira else None,
            'ultima': ultima.isoformat() if ultima else None,
            'sugestao_inicio': (ultima - timedelta(days=7)).isoformat() if ultima else None}


def _resolve_ativos(cur, tickers):
    ids = {}
    cur.execute('SELECT sg_ticker, id_ativo FROM public.tb_ativo WHERE sg_ticker = ANY(%s)', (list(tickers),))
    ids.update(cur.fetchall())
    faltam = [t for t in tickers if t not in ids]
    if faltam:   # ticker antigo (renomeado)
        cur.execute('SELECT sg_ticker_antigo, id_ativo FROM public.tb_ticker_historico WHERE sg_ticker_antigo = ANY(%s)', (faltam,))
        for t, i in cur.fetchall():
            ids.setdefault(t, i)
    return ids


def _norm_corretora(nome):
    """grafia da B3 varia entre extratos ('S/A' x 'S/A.'): compara sem caixa, espacos duplos e ponto final"""
    return re.sub(r'\s+', ' ', nome).strip().rstrip('.').strip().casefold()


def _resolve_corretoras(cur, nomes):
    """{nome_da_planilha: id_corretora} so pras que ja existem (nome atual ou antigo, tolerando a grafia)"""
    cur.execute('SELECT nm_corretora, id_corretora FROM public.tb_corretora')
    conhecidas = {_norm_corretora(n): i for n, i in cur.fetchall()}
    cur.execute('SELECT nm_corretora_antigo, id_corretora FROM public.tb_corretora_historico')
    for n, i in cur.fetchall():
        conhecidas.setdefault(_norm_corretora(n), i)
    return {n: conhecidas[_norm_corretora(n)] for n in nomes if _norm_corretora(n) in conhecidas}


def classifica(conn, id_carteira, ops):
    """marca cada operacao: nova | ja_importada | ativo_desconhecido | tipo_desconhecido. Nao grava nada."""
    with conn.cursor() as cur:
        ativos = _resolve_ativos(cur, {o['ticker'] for o in ops})
        cur.execute('SELECT sg_tipo_operacao, id_tipo_operacao FROM public.tb_tipo_operacao WHERE sg_tipo_operacao IN (%s, %s)', ('COMPRA', 'VENDA'))
        tipos = dict(cur.fetchall())
        cur.execute(
            '''SELECT id_ativo, id_tipo_operacao, dt_operacao, qt_ativo, vl_preco_unitario, count(*)
               FROM public.tb_operacao
               WHERE id_carteira = %s AND dt_operacao BETWEEN %s AND %s AND id_ativo = ANY(%s)
               GROUP BY 1, 2, 3, 4, 5''',
            (id_carteira, min(o['dt'] for o in ops), max(o['dt'] for o in ops), list(set(ativos.values())) or [0]))
        existentes = Counter()
        for ida, idt, dt, q, p, c in cur.fetchall():
            existentes[(ida, idt, dt, Decimal(q).quantize(OITO), Decimal(p).quantize(OITO))] = c
    vistos = Counter()
    for o in ops:
        if o['sigla'] is None:
            o['status'] = 'tipo_desconhecido'
            continue
        ida = ativos.get(o['ticker'])
        if ida is None:
            o['status'] = 'ativo_desconhecido'
            continue
        o['id_ativo'], o['id_tipo'] = ida, tipos[o['sigla']]
        chave = (ida, o['id_tipo'], o['dt'], o['qtd'], o['preco'])
        vistos[chave] += 1
        o['status'] = 'ja_importada' if vistos[chave] <= existentes[chave] else 'nova'
    return ops


def previa(conn, id_carteira, ops):
    classifica(conn, id_carteira, ops)
    por = Counter(o['status'] for o in ops)
    novas = [o for o in ops if o['status'] == 'nova']
    desconhecidos = Counter(o['ticker'] for o in ops if o['status'] == 'ativo_desconhecido')
    tipos_desc = Counter(o['tipo_txt'] for o in ops if o['status'] == 'tipo_desconhecido')
    with conn.cursor() as cur:
        corr = _resolve_corretoras(cur, {o['instituicao'] for o in novas}) if novas else {}
    return {
        'linhas': len(ops),
        'novas': por['nova'],
        'ja_importadas': por['ja_importada'],
        'ativo_desconhecido': por['ativo_desconhecido'],
        'tipo_ignorado': por['tipo_desconhecido'],
        'periodo_novas': [min(o['dt'] for o in novas).isoformat(), max(o['dt'] for o in novas).isoformat()] if novas else None,
        'valor_comprado_novas': float(sum(o['valor'] for o in novas if o['sigla'] == 'COMPRA')),
        'valor_vendido_novas': float(sum(o['valor'] for o in novas if o['sigla'] == 'VENDA')),
        'tickers_desconhecidos': [{'ticker': t, 'linhas': c} for t, c in desconhecidos.most_common()],
        'tipos_ignorados': [{'tipo': t, 'linhas': c} for t, c in tipos_desc.most_common()],
        'corretoras_novas': sorted({o['instituicao'] for o in novas} - set(corr)),
        'amostra_novas': [{'dt': o['dt'].isoformat(), 'tipo': o['sigla'], 'ticker': o['ticker'], 'quantidade': float(o['qtd']),
                           'preco': float(o['preco']), 'valor': float(o['valor']), 'corretora': o['instituicao']}
                          for o in sorted(novas, key=lambda x: (x['dt'], x['linha']))[:AMOSTRA]],
    }


def importa(conn, id_usuario, id_carteira, ops):
    """grava as operacoes novas numa transacao so. Devolve o mesmo resumo da previa + quantas entraram."""
    with conn.cursor() as cur:
        # dois uploads simultaneos do mesmo usuario (duplo clique): o segundo espera e ve tudo ja importado
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (f'importa_operacoes:{id_usuario}',))
    try:
        resumo = previa(conn, id_carteira, ops)
        novas = [o for o in ops if o['status'] == 'nova']
        with conn.cursor() as cur:
            corr = _resolve_corretoras(cur, {o['instituicao'] for o in novas}) if novas else {}
            for nome in sorted({o['instituicao'] for o in novas} - set(corr)):
                cur.execute('INSERT INTO public.tb_corretora (nm_corretora) VALUES (%s) RETURNING id_corretora', (nome,))
                corr[nome] = cur.fetchone()[0]
            cur.executemany(
                '''INSERT INTO public.tb_operacao (id_tipo_operacao, id_carteira, id_corretora, id_ativo, dt_operacao,
                                                   qt_ativo, vl_preco_unitario, vl_total_operacao, ds_observacao)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                [(o['id_tipo'], id_carteira, corr[o['instituicao']], o['id_ativo'], o['dt'], o['qtd'], o['preco'],
                  o['valor'], o['mercado']) for o in sorted(novas, key=lambda x: (x['dt'], x['linha']))])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    resumo['inseridas'] = len(novas)
    return resumo
