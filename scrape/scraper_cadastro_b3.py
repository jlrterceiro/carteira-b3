"""
Cadastro de emissores e ações a partir da B3 (substitui scraper_emissores.py/scraper_ativos.py,
que raspavam dadosdemercado.com.br).

Fonte: API JSON do site institucional da B3 (listedCompaniesProxy/CompanyCall):
  GetInitialCompanies -> todas as empresas (codigo de 4 letras, CNPJ, nome de pregao)
  GetDetail           -> setor, site, ISINs/tickers de cada empresa

Uso:
    python3 scrape/scraper_cadastro_b3.py            # aplica
    python3 scrape/scraper_cadastro_b3.py --dry-run  # so imprime o que faria
"""
import csv
import os
import re
import sys
import time
import urllib.request

from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn
from scraper_eventos_corporativos_b3 import _get

ID_TIPO_EMISSOR = 1
ID_TIPO_ATIVO_ACAO = 1
TIPOS_SEM_ACOES = {'7'}  # emissores de divida/nao listados (~2600 empresas), nunca tem acao
TICKER_RE = re.compile(r'^[A-Z0-9]{4}\d{1,2}B?$')  # sufixo B: EQMA3B/MRSA3B (ON/PNA/PNB da Equatorial MA e MRS)
# units aparecem na B3 com ISIN CDA (maioria), UNT (BPAC11) ou TRV (PSVM11); so valem com ticker final 11
TIPOS_ISIN_UNIT = {'CDA', 'UNT', 'TRV'}


def fetch_empresas():
    empresas, pagina = [], 1
    while True:
        r = _get('GetInitialCompanies', {'language': 'pt-br', 'pageNumber': pagina, 'pageSize': 120})
        empresas += r['results']
        if pagina >= r['page']['totalPages']:
            return empresas
        pagina += 1


def fetch_detalhe(cod_cvm):
    for _ in range(3):
        try:
            return _get('GetDetail', {'codeCVM': cod_cvm, 'language': 'pt-br'})
        except Exception:
            time.sleep(1)
    return None


def cnpj_digitos(cnpj):
    # a B3 devolve o CNPJ como numero, sem os zeros a esquerda (BBAS: '191')
    return re.sub(r'\D', '', cnpj or '').zfill(14) if cnpj else ''


def cnpj_formatado(d):
    return f'{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}'


def classe_do_isin(isin, ticker):
    tipo, classe = isin[6:9], isin[9:11]
    if tipo in TIPOS_ISIN_UNIT:
        return 'UNIT'
    if classe == 'OR':
        return 'ON'
    if classe.startswith('P'):
        return 'PN'
    return None


def acoes_do_detalhe(detalhe):
    """tickers de acao (ON/PN/UNIT) da empresa; descarta debenture, direito/recibo (sufixo 9x), BDR etc."""
    out = {}
    for o in detalhe.get('otherCodes') or []:
        code, isin = o['code'], o['isin']
        if len(isin) < 11 or not TICKER_RE.match(code):
            continue
        tipo = isin[6:9]
        if tipo != 'ACN' and not (tipo in TIPOS_ISIN_UNIT and code.endswith('11')):
            continue
        if re.search(r'9\d$', code.rstrip('B')):
            continue
        classe = classe_do_isin(isin, code)
        if classe:
            out[code] = classe
    return out


CVM_CADASTRO_URL = 'https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv'
CVM_CADASTRO_CACHE = os.path.join(os.path.dirname(__file__), 'cvm_cache', 'cad_cia_aberta.csv')


def raiz(cnpj):
    # os 8 primeiros digitos identificam a empresa; o resto e o estabelecimento (matriz/filial).
    # B3 e CVM as vezes usam estabelecimentos diferentes da mesma empresa (TUPY: B3 /0003-00, CVM /0001-49).
    d = re.sub(r'\D', '', cnpj or '')
    return d[:8] if len(d) >= 8 else ''


def carrega_cadastro_cvm():
    """cad_cia_aberta da CVM: CNPJ formatado -> linha (situacao, razao social, setor...). Cache de 1 dia."""
    import time as _t
    os.makedirs(os.path.dirname(CVM_CADASTRO_CACHE), exist_ok=True)
    if not os.path.exists(CVM_CADASTRO_CACHE) or _t.time() - os.path.getmtime(CVM_CADASTRO_CACHE) > 86400:
        urllib.request.urlretrieve(CVM_CADASTRO_URL, CVM_CADASTRO_CACHE)
    with open(CVM_CADASTRO_CACHE, encoding='latin-1') as f:
        return {r['CNPJ_CIA']: r for r in csv.DictReader(f, delimiter=';')}


def site(url):
    if not url:
        return None
    url = url.strip()
    return url if re.match(r'https?://', url, re.I) else f'https://{url}'


def run(dry_run=False):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute('SELECT id_emissor, sg_emissor, nr_cnpj, nm_emissor, ds_site, info FROM public.tb_emissor')
    emissores = cur.fetchall()
    por_cnpj = {cnpj_digitos(r[2]): r for r in emissores if r[2]}
    por_sg = {r[1]: r for r in emissores}
    por_raiz = {}
    for r in emissores:
        if r[2]:
            por_raiz.setdefault(raiz(r[2]), r)
    cvm = carrega_cadastro_cvm()
    cur.execute('SELECT sg_ticker, sg_classe, id_emissor, fl_ativo, id_ativo FROM public.tb_ativo')
    ativos = {r[0]: r for r in cur.fetchall()}

    empresas = [e for e in fetch_empresas() if e['type'] not in TIPOS_SEM_ACOES]
    print(f'{len(empresas)} empresas candidatas (type != 7)')

    listados = set()
    novos_emissores = novos_ativos = atualizados = 0
    divergencias = []

    for i, e in enumerate(empresas, start=1):
        detalhe = fetch_detalhe(e['codeCVM'])
        time.sleep(0.15)
        if not detalhe:
            print(f'  [{i}/{len(empresas)}] {e["issuingCompany"]}: erro ao buscar detalhe')
            continue
        acoes = acoes_do_detalhe(detalhe)
        if not acoes:
            continue
        listados.update(acoes)

        sg = e['issuingCompany']
        cnpj = cnpj_digitos(e['cnpj'])
        setor = detalhe.get('industryClassification')
        razao = detalhe.get('companyName')
        ds_site = site(detalhe.get('website'))

        emissor = por_cnpj.get(cnpj)
        cnpj_b3_outro = False
        if emissor is None and raiz(cnpj) in por_raiz:
            emissor = por_raiz[raiz(cnpj)]        # mesma empresa, estabelecimento diferente (TUPY)
            cnpj_b3_outro = True
        if emissor is None and sg in por_sg:
            # raiz diferente = outra pessoa juridica (ex: BRST, holding cancelada x operadora)
            divergencias.append(f'{sg}: ja existe no banco com CNPJ {por_sg[sg][2]}, B3 diz {cnpj_formatado(cnpj)} (raiz diferente) — nao alterado')
            emissor = por_sg[sg]
        if emissor is None:
            nome = (e['tradingName'] or sg).strip().title()
            print(f'  novo emissor {sg} ({nome}) {cnpj_formatado(cnpj)}')
            if not dry_run:
                cur.execute(
                    '''
                    INSERT INTO public.tb_emissor (id_tipo_emissor, sg_emissor, nm_emissor, nr_cnpj, ds_site, nm_pais, info)
                    VALUES (%s,%s,%s,%s,%s,'Brasil',%s)
                    ON CONFLICT DO NOTHING RETURNING id_emissor
                    ''',
                    (ID_TIPO_EMISSOR, sg, nome, cnpj_formatado(cnpj), ds_site, Json({'razao_social': razao, 'setor': setor})),
                )
                row = cur.fetchone()
                if row is None:
                    divergencias.append(f'{sg}: INSERT de emissor bloqueado por chave unica (nome/CNPJ/sigla ja usados)')
                    conn.rollback()
                    continue
                id_emissor = row[0]
            else:
                id_emissor = None
            novos_emissores += 1
        else:
            id_emissor = emissor[0]
            if emissor[1] != sg:
                divergencias.append(f'{emissor[1]}: sigla do banco difere do codigo da B3 ({sg}) — nao alterado')
            info = dict(emissor[5] or {})
            mudou = False
            if cnpj_b3_outro and info.get('cnpj_b3') != cnpj_formatado(cnpj):
                info['cnpj_b3'] = cnpj_formatado(cnpj)   # so rastreabilidade; a chave continua sendo o CNPJ da CVM
                mudou = True
            for k, v in (('razao_social', razao), ('setor', setor)):
                if v and not info.get(k):
                    info[k] = v
                    mudou = True
            novo_site = emissor[4] or ds_site
            if (mudou or novo_site != emissor[4]) and not dry_run:
                cur.execute(
                    'UPDATE public.tb_emissor SET info=%s, ds_site=%s, dh_atualizacao=now() WHERE id_emissor=%s',
                    (Json(info), novo_site, id_emissor),
                )
                atualizados += 1

        for ticker, classe in acoes.items():
            existente = ativos.get(ticker)
            if existente is None:
                nome_emissor = emissor[3] if emissor else (e['tradingName'] or sg).strip().title()
                print(f'    novo ativo {ticker} ({classe})')
                if not dry_run and id_emissor is not None:
                    cur.execute(
                        '''
                        INSERT INTO public.tb_ativo (id_tipo_ativo, id_emissor, sg_ticker, sg_classe, nm_ativo)
                        VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                        ''',
                        (ID_TIPO_ATIVO_ACAO, id_emissor, ticker, classe, f'{nome_emissor} - {ticker}'),
                    )
                novos_ativos += 1
            else:
                if existente[1] is None and not dry_run:
                    cur.execute('UPDATE public.tb_ativo SET sg_classe=%s WHERE sg_ticker=%s', (classe, ticker))
                elif existente[1] != classe:
                    divergencias.append(f'{ticker}: classe no banco {existente[1]} x B3 {classe} — nao alterado')
                if existente[2] is None and id_emissor is not None and not dry_run:
                    cur.execute('UPDATE public.tb_ativo SET id_emissor=%s WHERE sg_ticker=%s', (id_emissor, ticker))
        if not dry_run:
            conn.commit()

    # sincroniza fl_ativo com o que a B3 lista hoje; quem saiu da bolsa fica inativo e
    # dt_fim_negociacao = ultimo pregao que temos (nao apaga nada, historico segue valendo)
    saiu = sorted(t for t, r in ativos.items() if t not in listados and r[3])
    voltou = sorted(t for t, r in ativos.items() if t in listados and not r[3])
    print(f'\nsairam da B3 (fl_ativo -> false): {saiu}')
    print(f'voltaram a ser listados (fl_ativo -> true): {voltou}')
    if not dry_run:
        if saiu:
            cur.execute(
                '''
                UPDATE public.tb_ativo a SET fl_ativo = false, dh_atualizacao = now(),
                       dt_fim_negociacao = COALESCE(dt_fim_negociacao, (SELECT max(dt_cotacao) FROM public.tb_cotacao_bruta c WHERE c.id_ativo = a.id_ativo))
                WHERE sg_ticker = ANY(%s)
                ''',
                (saiu,),
            )
        if voltou:
            cur.execute('UPDATE public.tb_ativo SET fl_ativo = true, dt_fim_negociacao = NULL, dh_atualizacao = now() WHERE sg_ticker = ANY(%s)', (voltou,))
        conn.commit()

    # conciliacao com a CVM: emissor cujo CNPJ nao esta ATIVO no cadastro da CVM mas ainda tem ticker listado
    for sg_e, (id_e, sg_e2, cnpj_e, nm_e, _, _) in por_sg.items():
        r = cvm.get(cnpj_e)
        if r is None:
            if cnpj_e:
                divergencias.append(f'{sg_e}: CNPJ {cnpj_e} nao consta no cadastro da CVM (emissor estrangeiro?)')
        elif r['SIT'] != 'ATIVO':
            vivos = [t for t, a in ativos.items() if a[2] == id_e and t in listados]
            if vivos:
                data = r['DT_CANCEL'] or r['DT_INI_SIT']
                divergencias.append(f'{sg_e} ({nm_e}): CVM diz {r["SIT"]} desde {data} e a B3 ainda lista {vivos} — possivel troca de CNPJ, revisar')

    print(f'\nemissores novos: {novos_emissores}, emissores atualizados (info/site): {atualizados}, ativos novos: {novos_ativos}')
    if divergencias:
        print('divergencias (revisar):')
        for d in divergencias:
            print('  -', d)
    conn.close()


if __name__ == '__main__':
    run(dry_run='--dry-run' in sys.argv[1:])
