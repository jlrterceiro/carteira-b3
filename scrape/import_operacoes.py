import os
import sys
from datetime import datetime

import openpyxl

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

CARTEIRA = 'Carteira Aposentadoria'
TIPO_MOVIMENTACAO = {
    'Compra': 'COMPRA',
    'Venda': 'VENDA',
}


def read_operacoes(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    return list(ws.iter_rows(min_row=2, values_only=True))


def parse_date(value):
    if isinstance(value, str):
        return datetime.strptime(value, '%d/%m/%Y').date()
    return value.date() if hasattr(value, 'date') else value


def normalize_ticker(codigo, mercado):
    if mercado == 'Mercado Fracionário' and codigo.endswith('F'):
        return codigo[:-1]
    return codigo


def fetch_carteira_id(conn, nome, sg_usuario):
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT c.id_carteira FROM public.tb_carteira c
            JOIN public.tb_usuario u ON u.id_usuario = c.id_usuario
            WHERE c.nm_carteira = %s AND u.sg_usuario = %s
            ''',
            (nome, sg_usuario),
        )
        row = cur.fetchone()
        return row[0] if row else None


def fetch_tipo_operacao_id(conn, sigla):
    with conn.cursor() as cur:
        cur.execute('SELECT id_tipo_operacao FROM public.tb_tipo_operacao WHERE sg_tipo_operacao = %s', (sigla,))
        row = cur.fetchone()
        return row[0] if row else None


def fetch_ativo_id(conn, ticker):
    with conn.cursor() as cur:
        cur.execute('SELECT id_ativo FROM public.tb_ativo WHERE sg_ticker = %s', (ticker,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute('SELECT id_ativo FROM public.tb_ticker_historico WHERE sg_ticker_antigo = %s', (ticker,))
        row = cur.fetchone()
        return row[0] if row else None


def fetch_or_create_corretora(conn, nome):
    with conn.cursor() as cur:
        cur.execute('SELECT id_corretora FROM public.tb_corretora WHERE nm_corretora = %s', (nome,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute('SELECT id_corretora FROM public.tb_corretora_historico WHERE nm_corretora_antigo = %s', (nome,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            'INSERT INTO public.tb_corretora (nm_corretora) VALUES (%s) RETURNING id_corretora',
            (nome,),
        )
        id_corretora = cur.fetchone()[0]
    conn.commit()
    return id_corretora


def count_existing_operacoes(conn, carteira_id, id_ativo, id_tipo_operacao, dt_operacao, quantidade, preco):
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT count(*) FROM public.tb_operacao
            WHERE id_carteira = %s AND id_ativo = %s AND id_tipo_operacao = %s
              AND dt_operacao = %s AND qt_ativo = %s AND vl_preco_unitario = %s
            ''',
            (carteira_id, id_ativo, id_tipo_operacao, dt_operacao, quantidade, preco),
        )
        return cur.fetchone()[0]


def insert_operacao(conn, operacao):
    with conn.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO public.tb_operacao (
                id_tipo_operacao,
                id_carteira,
                id_corretora,
                id_ativo,
                dt_operacao,
                qt_ativo,
                vl_preco_unitario,
                vl_total_operacao,
                ds_observacao
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ''',
            (
                operacao['id_tipo_operacao'],
                operacao['id_carteira'],
                operacao['id_corretora'],
                operacao['id_ativo'],
                operacao['dt_operacao'],
                operacao['quantidade'],
                operacao['preco'],
                operacao['valor'],
                operacao['mercado'],
            ),
        )
    conn.commit()


def process_row(conn, carteira_id, seen, row):
    dt_negocio, tipo_mov, mercado, _prazo, instituicao, codigo, quantidade, preco, valor = row
    sigla = TIPO_MOVIMENTACAO.get(tipo_mov)
    if not sigla:
        print(f'  skipped {codigo}: tipo de movimentacao desconhecido ({tipo_mov})')
        return False
    id_tipo_operacao = fetch_tipo_operacao_id(conn, sigla)
    ticker = normalize_ticker(codigo, mercado)
    id_ativo = fetch_ativo_id(conn, ticker)
    if id_ativo is None:
        print(f'  skipped {codigo}: ativo nao encontrado')
        return False
    dt_operacao = parse_date(dt_negocio)
    key = (id_ativo, id_tipo_operacao, dt_operacao, quantidade, preco)
    seen[key] = seen.get(key, 0) + 1
    existing_count = count_existing_operacoes(conn, carteira_id, *key)
    if seen[key] <= existing_count:
        print(f'  skipped {codigo}: operacao ja importada')
        return False
    id_corretora = fetch_or_create_corretora(conn, instituicao)
    insert_operacao(
        conn,
        {
            'id_tipo_operacao': id_tipo_operacao,
            'id_carteira': carteira_id,
            'id_corretora': id_corretora,
            'id_ativo': id_ativo,
            'dt_operacao': dt_operacao,
            'quantidade': quantidade,
            'preco': preco,
            'valor': valor,
            'mercado': mercado,
        },
    )
    return True


def run(path, sg_usuario):
    conn = get_conn()
    carteira_id = fetch_carteira_id(conn, CARTEIRA, sg_usuario)
    if carteira_id is None:
        raise SystemExit(f'carteira "{CARTEIRA}" do usuario "{sg_usuario}" nao encontrada')
    rows = read_operacoes(path)
    total = len(rows)
    print(f'processing {total} operacoes')
    inserted = 0
    seen = {}
    for index, row in enumerate(rows, start=1):
        print(f'[{index}/{total}] {row[5]} - {row[1]}')
        if process_row(conn, carteira_id, seen, row):
            inserted += 1
    print(f'{inserted}/{total} operacoes inseridas')
    conn.close()


def main():
    if len(sys.argv) < 3:
        raise SystemExit('uso: python3 import_operacoes.py <arquivo.xlsx> <sg_usuario>')
    run(sys.argv[1], sys.argv[2])


if __name__ == '__main__':
    main()
