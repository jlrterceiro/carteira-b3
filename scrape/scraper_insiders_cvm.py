"""
Insiders (administradores, conselhos, controladores e vinculados) -- dados abertos da CVM, VLMO "Posicao Consolidada":
    https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS/vlmo_cia_aberta_<ano>.zip
      vlmo_cia_aberta_<ano>.csv      indice dos formularios entregues (protocolo, link do documento)
      vlmo_cia_aberta_con_<ano>.csv  as movimentacoes (uma linha por cargo, ativo e movimento; tem 'Saldo Inicial', guardado em tb_insider_saldo)
So gravamos movimentacoes de emissores do nosso cadastro, so a ULTIMA versao de cada (companhia, mes), com o link do documento.
Substitui a leitura de PDF do scraper_insider.py. Por ano: apaga o ano e regrava (idempotente).

    python3 scrape/scraper_insiders_cvm.py [--desde 2018]
"""
import csv
import io
import os
import sys
import time
import urllib.request
import zipfile
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn
from cnpj_emissor import fetch_emissores_cnpj

URL = 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS/vlmo_cia_aberta_{ano}.zip'
CACHE = os.path.join(os.path.dirname(__file__), 'cvm_cache')
H = {'User-Agent': 'Mozilla/5.0'}


def baixa(ano):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f'vlmo_cia_aberta_{ano}.zip')
    if os.path.exists(p) and (ano < date.today().year or time.time() - os.path.getmtime(p) < 86400):
        return p
    for t in range(1, 5):
        try:
            with urllib.request.urlopen(urllib.request.Request(URL.format(ano=ano), headers=H), timeout=180) as r:
                dados = r.read()
            open(p + '.part', 'wb').write(dados); os.replace(p + '.part', p)
            return p
        except Exception as e:
            print(f'  VLMO {ano}: {e!r} (tentativa {t}/4)'); time.sleep(3 * t)
    raise RuntimeError(f'nao baixou VLMO {ano}')


def num(s):
    s = (s or '').strip()
    return float(s) if s else None


def le(z, nome):
    return csv.DictReader(io.TextIOWrapper(z.open(nome), encoding='latin-1'), delimiter=';')


def main():
    desde = int(sys.argv[sys.argv.index('--desde') + 1]) if '--desde' in sys.argv else 2018
    conn = get_conn(); cur = conn.cursor()
    cnpj2emissor = {c.strip(): ide for ide, c, _, _ in fetch_emissores_cnpj(conn)}
    print(len(set(cnpj2emissor.values())), 'emissores no cadastro')
    for ano in range(desde, date.today().year + 1):
        z = zipfile.ZipFile(baixa(ano))
        # indice: (cnpj, referencia, versao) -> (protocolo, link)
        link = {}
        entrega = {}     # (cnpj, referencia) -> 1a entrega (a informacao ficou publica nela, mesmo que depois tenha sido reapresentada)
        for r in le(z, f'vlmo_cia_aberta_{ano}.csv'):
            link[(r['CNPJ_Companhia'].strip(), r['Data_Referencia'], r['Versao'])] = (r['Protocolo_Entrega'], r['Link_Download'])
            k = (r['CNPJ_Companhia'].strip(), r['Data_Referencia'])
            if r['Data_Entrega'] and (k not in entrega or r['Data_Entrega'][:10] < entrega[k]):
                entrega[k] = r['Data_Entrega'][:10]
        todas = [r for r in le(z, f'vlmo_cia_aberta_con_{ano}.csv') if r['CNPJ_Companhia'].strip() in cnpj2emissor]
        linhas = [r for r in todas if r['Data_Movimentacao']]
        # saldo inicial do mes por cargo: soma das empresas declarantes na ultima versao entregue
        ver_saldo = {}
        for r in todas:
            if r['Tipo_Movimentacao'] == 'Saldo Inicial':
                k = (r['CNPJ_Companhia'].strip(), r['Data_Referencia'])
                ver_saldo[k] = max(ver_saldo.get(k, 0), int(r['Versao']))
        saldo = {}
        for r in todas:
            k = (r['CNPJ_Companhia'].strip(), r['Data_Referencia'])
            if r['Tipo_Movimentacao'] == 'Saldo Inicial' and int(r['Versao']) == ver_saldo[k]:
                kk = (cnpj2emissor[k[0]], r['Data_Referencia'], r['Tipo_Cargo'], r['Tipo_Ativo'], r['Caracteristica_Valor_Mobiliario'])
                saldo[kk] = saldo.get(kk, 0) + (num(r['Quantidade']) or 0)
        cur.execute('DELETE FROM public.tb_insider_saldo WHERE EXTRACT(YEAR FROM dt_referencia) = %s', (ano,))
        for (ide, ref, cargo, ativo, car), q in saldo.items():
            cur.execute('''INSERT INTO public.tb_insider_saldo (id_emissor, dt_referencia, tipo_cargo, tipo_ativo, ds_caracteristica, qt_saldo_inicial)
                           VALUES (%s,%s,%s,%s,%s,%s)''', (ide, ref, cargo, ativo, car, q))
        ultima = {}
        for r in linhas:
            k = (r['CNPJ_Companhia'].strip(), r['Data_Referencia'])
            ultima[k] = max(ultima.get(k, 0), int(r['Versao']))
        cur.execute('DELETE FROM public.tb_insider_movimentacao WHERE EXTRACT(YEAR FROM dt_referencia) = %s', (ano,))
        n = 0
        for r in linhas:
            cnpj = r['CNPJ_Companhia'].strip()
            if int(r['Versao']) != ultima[(cnpj, r['Data_Referencia'])]:
                continue
            proto, lk = link.get((cnpj, r['Data_Referencia'], r['Versao']), (None, None))
            cur.execute(
                '''INSERT INTO public.tb_insider_movimentacao (id_emissor, dt_referencia, nr_versao, tipo_empresa, ds_empresa, tipo_cargo,
                       tipo_movimentacao, ds_movimentacao, tipo_operacao, tipo_ativo, ds_caracteristica, ds_intermediario,
                       dt_movimentacao, qt_ativo, vl_preco, vl_volume, ds_protocolo, ds_link, dt_entrega)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (cnpj2emissor[cnpj], r['Data_Referencia'], int(r['Versao']), r['Tipo_Empresa'], r['Empresa'], r['Tipo_Cargo'],
                 r['Tipo_Movimentacao'], r['Descricao_Movimentacao'] or None, r['Tipo_Operacao'], r['Tipo_Ativo'],
                 r['Caracteristica_Valor_Mobiliario'] or None, r['Intermediario'] or None, r['Data_Movimentacao'],
                 num(r['Quantidade']), num(r['Preco_Unitario']), num(r['Volume']), proto, lk, entrega.get((cnpj, r['Data_Referencia']))))
            n += 1
        conn.commit()
        print(f'{ano}: {n} movimentacoes e {len(saldo)} saldos iniciais gravados', flush=True)
    cur.execute('SELECT public.fn_popula_insider_mercado()')
    print('valor de mercado da epoca calculado em', cur.fetchone()[0], 'movimentacoes')
    conn.commit()
    cur.execute('SELECT public.fn_popula_insider_rotina()')
    print('operacoes marcadas como rotina/oportunistas:', cur.fetchone()[0])
    conn.commit()
    cur.execute('SELECT public.fn_popula_insider_evento()')
    print('eventos do estudo de retorno:', cur.fetchone()[0])
    conn.commit()
    cur.execute('SELECT count(*), min(dt_movimentacao), max(dt_movimentacao) FROM public.tb_insider_movimentacao')
    print('total:', cur.fetchone())
    conn.close()


if __name__ == '__main__':
    main()
