"""
Scraper de negociação de insiders — CVM Instrução 358, Art. 11 (Formulário Consolidado)

Para cada emissor em tb_emissor, baixa os relatórios mensais de negociação de valores
mobiliários por administradores e pessoas ligadas da CVM e grava em tb_insider_negociacao.

Uso:
    python3 scrape/scraper_insider.py              # todos os emissores, todos os anos
    python3 scrape/scraper_insider.py EVEN3        # só o emissor do ticker EVEN3
    python3 scrape/scraper_insider.py EVEN3 2023   # ticker + ano específico
"""

import csv
import io
import os
import re
import sys
import time
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime

import pdfplumber

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'insider_cache')
IPE_BASE = 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS'
ANO_INICIAL = 2009
ANO_FINAL = date.today().year
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
CATEGORIA = 'Valores Mobiliários negociados e detidos (art. 11 da Instr. CVM nº 358)'
TIPO = 'Posição Consolidada'

# Mapeamento grupo → nome normalizado
GRUPOS = [
    ('Controlador',                   'Controladores'),
    ('Conselho de Administração',     'Conselho de Administração'),
    ('Conselho Administração',        'Conselho de Administração'),
    ('Diretoria',                     'Diretoria'),
    ('Conselho Fiscal',               'Conselho Fiscal'),
    ('Órgãos Técnicos',               'Órgãos Técnicos'),
    ('Orgãos Técnicos',               'Órgãos Técnicos'),
    ('Órgãos Consultivos',            'Órgãos Técnicos'),
]


# ─── helpers de texto ──────────────────────────────────────────────────────────

def norm(txt):
    return re.sub(r'\s+', ' ', (txt or '').replace('\n', ' ')).strip()


def parse_br(txt, inteiro=False):
    if not txt or not txt.strip():
        return None
    limpo = txt.strip().replace(' ', '').replace('.', '').replace(',', '.')
    try:
        return int(float(limpo)) if inteiro else float(limpo)
    except ValueError:
        return None


# ─── download ──────────────────────────────────────────────────────────────────

def _baixa(url, destino, timeout=60):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(destino, 'wb') as f:
        f.write(resp.read())


def baixa_ipe(ano):
    os.makedirs(CACHE_DIR, exist_ok=True)
    caminho = os.path.join(CACHE_DIR, f'ipe_{ano}.zip')
    if ano == date.today().year and os.path.exists(caminho):
        os.remove(caminho)
    if not os.path.exists(caminho):
        print(f'  baixando IPE {ano}...')
        _baixa(f'{IPE_BASE}/ipe_cia_aberta_{ano}.zip', caminho)
    return caminho


def baixa_pdf(protocolo, link):
    os.makedirs(CACHE_DIR, exist_ok=True)
    caminho = os.path.join(CACHE_DIR, f'{protocolo}.pdf')
    if not os.path.exists(caminho):
        _baixa(link, caminho)
        time.sleep(0.3)
    return caminho


# ─── leitura do CSV de IPE ────────────────────────────────────────────────────

def le_docs_ipe(ano, cnpjs_alvo):
    """
    Retorna lista de docs relevantes do ano, filtrando por CNPJ.
    Mantém só a versão mais recente de cada protocolo (alguns são retificados).
    """
    caminho = baixa_ipe(ano)
    docs_por_base = defaultdict(list)

    with zipfile.ZipFile(caminho) as z:
        with z.open(z.namelist()[0]) as raw:
            reader = csv.DictReader(
                io.TextIOWrapper(raw, encoding='iso-8859-1'), delimiter=';'
            )
            for row in reader:
                if row['Categoria'].strip() != CATEGORIA:
                    continue
                if row['Tipo'].strip() != TIPO:
                    continue
                cnpj = row['CNPJ_Companhia'].strip()
                if cnpj not in cnpjs_alvo:
                    continue
                protocolo = row['Protocolo_Entrega'].strip()
                # Base do protocolo sem sufixo de versão (últimos 2 chars são número)
                base = protocolo[:-2] if re.search(r'\d\d$', protocolo) else protocolo
                docs_por_base[base].append({
                    'cnpj':         cnpj,
                    'id_emissor':   cnpjs_alvo[cnpj],
                    'dt_referencia': row['Data_Referencia'].strip(),
                    'protocolo':    protocolo,
                    'versao':       int(row['Versao'].strip() or '1'),
                    'link':         row['Link_Download'].strip(),
                })

    return [max(vs, key=lambda d: d['versao']) for vs in docs_por_base.values()]


# ─── parser de PDF ────────────────────────────────────────────────────────────

def extrai_grupo(row):
    """
    Dada uma linha da tabela do PDF, retorna o grupo marcado com (X).
    O formulário tem checkboxes tipo '( X ) Controlador' ou '( ) Diretoria'.
    """
    for cell in (row or []):
        limpo = norm(cell)
        if '(X)' not in limpo and '( X )' not in limpo:
            continue
        sem_box = re.sub(r'\(\s*X?\s*\)', '', limpo).strip()
        for chave, nome in GRUPOS:
            if chave.lower() in sem_box.lower():
                return nome
        return sem_box or None
    return None


def _indices_cabecalho(row):
    """
    Dado o cabeçalho da tabela de movimentações, retorna dict col→índice.
    O número de colunas varia por empresa/período (9, 10, 12 cols com vazias
    intercaladas), então detectamos pelo texto em vez de usar posição fixa.
    """
    idx = {}
    for i, cell in enumerate(row):
        t = norm(cell or '')
        if not t:
            continue
        if 'Mobili' in t and 'Derivativo' in t:
            idx.setdefault('vm', i)
        elif 'Caracter' in t:
            idx.setdefault('carac', i)
        elif 'Interm' in t:
            idx.setdefault('intermed', i)
        elif t == 'Operação' or t.startswith('Opera'):
            idx.setdefault('operacao', i)
        elif t == 'Dia':
            idx.setdefault('dia', i)
        elif 'Quantidade' in t:
            idx.setdefault('qtd', i)
        elif 'Preço' in t or t.startswith('Pre'):
            idx.setdefault('preco', i)
        elif 'Volume' in t:
            idx.setdefault('volume', i)
    return idx


def parse_pdf(pdf_path, dt_referencia_str):
    """
    Parseia Formulário Consolidado de Art. 11.
    dt_referencia_str: '2026-05-01' (primeiro dia do mês, vindo do CSV do IPE).
    Retorna lista de dicts com as transações encontradas.
    """
    dt_ref = datetime.strptime(dt_referencia_str[:10], '%Y-%m-%d')
    ano, mes = dt_ref.year, dt_ref.month
    transacoes = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in (page.extract_tables() or []):
                grupo_atual = None
                in_movim = False
                col_idx = {}  # índices detectados do cabeçalho

                for row in table:
                    if not row:
                        continue
                    primeira = norm(row[0] or '')

                    # Atualizar mês/ano a partir do cabeçalho do formulário ("Em MM/YYYY")
                    m = re.search(r'Em\s+(\d{2})/(\d{4})', primeira)
                    if m:
                        mes, ano = int(m.group(1)), int(m.group(2))

                    # Detectar grupo marcado
                    textos = ' '.join(norm(c) for c in row if c)
                    if 'Controlador' in textos or 'Diretoria' in textos or 'Conselho' in textos:
                        g = extrai_grupo(row)
                        if g:
                            grupo_atual = g

                    if 'Movimentações no Mês' in primeira:
                        in_movim = True
                        col_idx = {}
                        continue

                    if 'Saldo Final' in primeira:
                        in_movim = False
                        continue

                    if not in_movim:
                        continue

                    # Cabeçalho da seção de movimentações — detectar índices das colunas
                    if any('Operação' in norm(c or '') for c in row):
                        col_idx = _indices_cabecalho(row)
                        continue

                    if not col_idx:
                        continue

                    # Linha de transação — usar índices detectados
                    vals = [norm(c) for c in row]
                    if not any(vals):
                        continue

                    def v(key):
                        i = col_idx.get(key)
                        return vals[i] if i is not None and i < len(vals) else ''

                    vm       = v('vm')
                    carac    = v('carac')
                    intermed = v('intermed')
                    operacao = v('operacao')
                    dia_str  = v('dia')
                    qtd_str  = v('qtd')
                    preco_str = v('preco')
                    vol_str  = v('volume')

                    if not vm and not operacao:
                        continue

                    dt_op = None
                    if dia_str and re.fullmatch(r'\d{1,2}', dia_str):
                        try:
                            dt_op = f'{ano}-{mes:02d}-{int(dia_str):02d}'
                        except Exception:
                            pass

                    transacoes.append({
                        'grupo':            grupo_atual,
                        'valor_mobiliario': vm or None,
                        'caracteristicas':  carac or None,
                        'intermediario':    intermed or None,
                        'operacao':         operacao or None,
                        'dt_operacao':      dt_op,
                        'qt_quantidade':    parse_br(qtd_str, inteiro=True),
                        'vl_preco':         parse_br(preco_str),
                        'vl_volume':        parse_br(vol_str),
                    })

    return transacoes


# ─── banco ────────────────────────────────────────────────────────────────────

def fetch_emissores(conn, ticker_filter=None):
    q = '''
        SELECT DISTINCT e.nr_cnpj, e.id_emissor
        FROM tb_emissor e
        JOIN tb_ativo a ON a.id_emissor = e.id_emissor
        JOIN tb_tipo_ativo ta ON ta.id_tipo_ativo = a.id_tipo_ativo
        WHERE ta.sg_tipo_ativo = 'ACAO' AND e.nr_cnpj IS NOT NULL
    '''
    params = ()
    if ticker_filter:
        q += ' AND a.sg_ticker = %s'
        params = (ticker_filter,)
    with conn.cursor() as cur:
        cur.execute(q, params)
        return {row[0]: row[1] for row in cur.fetchall()}


def fetch_protocolos_feitos(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT ds_protocolo FROM public.tb_insider_protocolo')
        return {row[0] for row in cur.fetchall()}


def insere(conn, protocolo, id_emissor, dt_ref, transacoes):
    with conn.cursor() as cur:
        cur.execute(
            'DELETE FROM public.tb_insider_negociacao WHERE ds_protocolo = %s',
            (protocolo,)
        )
        for t in transacoes:
            cur.execute(
                '''
                INSERT INTO public.tb_insider_negociacao (
                    ds_protocolo, id_emissor, dt_referencia, ds_grupo,
                    ds_valor_mobiliario, ds_caracteristicas, ds_intermediario,
                    ds_operacao, dt_operacao, qt_quantidade, vl_preco, vl_volume
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ''',
                (
                    protocolo, id_emissor, dt_ref,
                    t['grupo'] or 'Desconhecido',
                    t['valor_mobiliario'], t['caracteristicas'], t['intermediario'],
                    t['operacao'] or 'N/A',
                    t['dt_operacao'], t['qt_quantidade'], t['vl_preco'], t['vl_volume'],
                )
            )
        cur.execute(
            '''
            INSERT INTO public.tb_insider_protocolo (ds_protocolo, id_emissor, dt_referencia, qt_transacoes)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (ds_protocolo) DO UPDATE SET qt_transacoes = EXCLUDED.qt_transacoes
            ''',
            (protocolo, id_emissor, dt_ref, len(transacoes))
        )
    conn.commit()


# ─── main ─────────────────────────────────────────────────────────────────────

def run(ticker_filter=None, ano_filter=None):
    conn = get_conn()
    emissores = fetch_emissores(conn, ticker_filter)
    if not emissores:
        print('nenhum emissor encontrado')
        conn.close()
        return

    print(f'{len(emissores)} emissor(es) alvo')
    protocolos_feitos = fetch_protocolos_feitos(conn)

    anos = [ano_filter] if ano_filter else range(ANO_INICIAL, ANO_FINAL + 1)
    total_docs = total_tx = 0

    for ano in anos:
        print(f'\n[{ano}]')
        try:
            docs = le_docs_ipe(ano, emissores)
        except Exception as e:
            print(f'  erro ao ler IPE {ano}: {e}')
            continue

        novos = [d for d in docs if d['protocolo'] not in protocolos_feitos]
        print(f'  {len(docs)} docs encontrados, {len(novos)} novos')

        for doc in novos:
            protocolo = doc['protocolo']
            try:
                pdf_path = baixa_pdf(protocolo, doc['link'])
                tx = parse_pdf(pdf_path, doc['dt_referencia'])
                # Filtrar linhas sem VM ou operação (artefatos do parse)
                tx = [t for t in tx if t['valor_mobiliario'] or t['operacao']]
                insere(conn, protocolo, doc['id_emissor'], doc['dt_referencia'][:10], tx)
                protocolos_feitos.add(protocolo)
                total_docs += 1
                total_tx += len(tx)
                if tx:
                    print(f'  {doc["cnpj"]} {doc["dt_referencia"][:7]}: {len(tx)} linhas')
            except Exception as e:
                conn.rollback()
                print(f'  erro {protocolo}: {e}')

    print(f'\npronto: {total_docs} docs, {total_tx} linhas inseridas')
    conn.close()


def main():
    ticker_filter = ano_filter = None
    for arg in sys.argv[1:]:
        if re.fullmatch(r'\d{4}', arg):
            ano_filter = int(arg)
        else:
            ticker_filter = arg
    run(ticker_filter, ano_filter)


if __name__ == '__main__':
    main()
