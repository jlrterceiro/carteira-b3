"""
PROTOTIPO (so leitura, nao grava nada): reconstroi eventos corporativos de uma empresa so com fontes
oficiais — avisos/atas da CVM (IPE) dizem QUE houve evento e QUAL fator/dia ex; o COTAHIST confirma pelo
preco bruto.

    python3 scrape/prototipo_eventos_cvm.py BBDC4 [ITUB4 ...] [--pdf]

--pdf: le o anexo (Link_Download: PDF, .doc antigo ou HTML) dos avisos do episodio.
"""
import csv
import hashlib
import io
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

CACHE = os.path.join(os.path.dirname(__file__), 'cvm_cache')
IPE_URL = 'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip'
EVENTO_RE = re.compile(r'bonifica|desdobr|grupament|split', re.I)
AMPLO_RE = re.compile(r'aumento d[eo] capital|banco central|bacen|homologa|data-base|capitaliza', re.I)
OBJ_RE = re.compile(r'bonifica|desdobr|grupament', re.I)
DIV_RE = re.compile(r'dividend|juros|jcp|jscp', re.I)
AGRUPA_DIAS = 75
JANELA_POS = 150
FATORES_BONS = [1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 40, 50, 100, 200, 500, 1000]

MESES = {'janeiro': 1, 'fevereiro': 2, 'marco': 3, 'março': 3, 'abril': 4, 'maio': 5, 'junho': 6, 'julho': 7,
         'agosto': 8, 'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12}
DATA_RX = re.compile(
    r'(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})'
    r'|(\d{1,2})\s*(?:º|°|o|\.o)?\s*(?:de\s+)?(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})',
    re.I)


# ---------------------------------------------------------------- IPE (indice dos avisos)
def baixa_ipe(ano):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f'ipe_cia_aberta_{ano}.zip')
    if os.path.exists(p) and (ano < date.today().year or time.time() - os.path.getmtime(p) < 86400):
        return p
    for t in range(1, 5):
        try:
            with urllib.request.urlopen(IPE_URL.format(ano=ano), timeout=120) as r:
                dados = r.read()
            open(p + '.part', 'wb').write(dados); os.replace(p + '.part', p)
            return p
        except Exception as e:
            print(f'  IPE {ano}: {e} (tentativa {t}/4)'); time.sleep(3 * t)
    raise RuntimeError(f'nao baixou IPE {ano}')


def avisos(cnpj, ano_ini, ano_fim, amplos=False):
    out = []
    alvo = AMPLO_RE if amplos else EVENTO_RE
    for ano in range(ano_ini, ano_fim + 1):
        with zipfile.ZipFile(baixa_ipe(ano)) as z:
            nome = [n for n in z.namelist() if n.endswith('.csv')][0]
            with z.open(nome) as f:
                for r in csv.DictReader(io.TextIOWrapper(f, encoding='latin-1'), delimiter=';'):
                    if r['CNPJ_Companhia'].strip() == cnpj and alvo.search(r['Assunto'] + ' ' + r['Categoria']):
                        out.append({'dt': date.fromisoformat(r['Data_Entrega'][:10]), 'cat': r['Categoria'],
                                    'assunto': r['Assunto'], 'link': r['Link_Download']})
    return sorted(out, key=lambda x: x['dt'])


# ---------------------------------------------------------------- texto dos anexos
def _texto_de_bytes(dados):
    """PDF -> pdftotext; .doc (OLE2) -> antiword; HTML/RTF -> remove marcacao"""
    if dados[:4] == b'%PDF':
        with tempfile.NamedTemporaryFile(suffix='.pdf') as t:
            t.write(dados); t.flush()
            return subprocess.run(['pdftotext', '-layout', t.name, '-'], capture_output=True, text=True, timeout=60).stdout
    if dados[:4] == b'\xd0\xcf\x11\xe0':
        with tempfile.NamedTemporaryFile(suffix='.doc') as t:
            t.write(dados); t.flush()
            return subprocess.run(['antiword', '-m', 'UTF-8.txt', t.name], capture_output=True, text=True, timeout=60).stdout
    txt = dados.decode('latin-1', errors='replace')
    if txt.lstrip().startswith('{\\rtf'):
        return re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode('latin-1'), re.sub(r'\\[a-z]+-?\d* ?|[{}]', ' ', txt))
    return re.sub(r'<[^>]+>', ' ', txt)


def texto_anexo(link):
    os.makedirs(os.path.join(CACHE, 'ipe_txt'), exist_ok=True)
    cache = os.path.join(CACHE, 'ipe_txt', hashlib.md5(link.encode()).hexdigest() + '.txt')
    if os.path.exists(cache):
        return open(cache, encoding='utf-8').read()
    texto = ''
    try:
        req = urllib.request.Request(link, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            texto = _texto_de_bytes(r.read())
    except Exception:
        return ''
    if texto:
        open(cache, 'w', encoding='utf-8').write(texto)
    return texto


def norm(t):
    t = t.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
    return re.sub(r'\s+', ' ', t)


# ---------------------------------------------------------------- datas
def _dt(m):
    try:
        if m.group(1):
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return date(int(m.group(6)), MESES[m.group(5).lower()], int(m.group(4)))
    except (ValueError, KeyError):
        return None


def data_ex_do_texto(texto, pregoes=None):
    """(data_ex, como). Ordem: frase 'ex' explicita > data efetiva do desdobramento/grupamento > data-base + 1 pregao."""
    t = norm(texto)
    # 1) "... ex-direitos a bonificacao a partir do dia DATA"  ou  "a partir de DATA as acoes passarao a ser negociadas ex-..."
    for m in re.finditer(r'ex[- ]?(?:direitos?|bonifica\w*|desdobr\w*|grupament\w*)', t, re.I):
        d = DATA_RX.search(t, m.end(), m.end() + 170)
        if d:
            obj = t[m.start():d.start()]
            if OBJ_RE.search(obj) and not DIV_RE.search(obj) and _dt(d):
                return _dt(d), 'ex'
        ant = t[max(0, m.start() - 170):m.start()]
        ds = list(DATA_RX.finditer(ant))
        if ds and _dt(ds[-1]) and re.search(r'partir', ant[max(0, ds[-1].start() - 25):ds[-1].start()], re.I):
            obj = t[max(0, m.start() - 170) + ds[-1].end():m.end() + 40]
            if OBJ_RE.search(obj + t[m.start():m.end() + 60]) and not DIV_RE.search(obj):
                return _dt(ds[-1]), 'ex'
    # 2) "cada acao ... sera desdobrada, no dia DATA, em N acoes"
    for m in re.finditer(r'(?:desdobrad|grupad|agrupad)\w+[^.]{0,40}?(?:no\s+dia|em|a\s+partir\s+de)\s+', t, re.I):
        d = DATA_RX.match(t, m.end())
        if d and _dt(d):
            return _dt(d), 'efetiva'
    # 3) "Data-base: ... posicao final do dia DATA" -> ex = pregao seguinte
    for m in re.finditer(r'data[- ]base', t, re.I):
        ctx = t[max(0, m.start() - 350):m.start() + 300]
        d = DATA_RX.search(t, m.end(), m.end() + 260)
        if d and OBJ_RE.search(ctx) and not DIV_RE.search(t[m.end():d.start()]) and _dt(d) and pregoes:
            prox = next((x for x in pregoes if x > _dt(d)), None)
            if prox:
                return prox, 'data-base+1'
    # 3b) outras formas de dizer a data-base (direito): "posicao acionaria final de DATA", "posicoes detidas no dia DATA",
    #     "a bonificacao sera efetivada nas Bolsas em DATA" -> ex = pregao seguinte
    for rx in (r'posi[cç][aã]o\s+(?:acion[aá]ria\s+)?(?:final\s+)?(?:do\s+dia|de|em)\s+',
               r'posi[cç][oõ]es\s+detidas\s+(?:no\s+dia|em)\s+',
               r'(?:bonifica\w+|desdobramento|grupamento)\s+(?:em\s+a[cç][oõ]es\s+)?ser[aá]\s+efetivad\w+[^.]{0,60}?\bem\s+'):
        for m in re.finditer(rx, t, re.I):
            ctx = t[max(0, m.start() - 300):m.start() + 200]
            d = DATA_RX.match(t, m.end())
            if d and _dt(d) and OBJ_RE.search(ctx) and not DIV_RE.search(t[max(0, m.start() - 60):m.start()]) and pregoes:
                prox = next((x for x in pregoes if x > _dt(d)), None)
                if prox:
                    return prox, 'data-base+1'
    return None, None


# ---------------------------------------------------------------- fatores
def _num(s):
    return float(s.replace('.', '').replace(',', '.')) if ',' in s else float(s)


def fator_do_texto(texto):
    """pernas [(F, descricao, tipo)] em ordem de aparicao; F = novas acoes por acao antiga."""
    t = norm(texto)
    out = []
    bonif = bool(re.search(r'bonifica', t, re.I))
    for m in re.finditer(r'bonifica\w*[^%\d]{0,80}?(\d+(?:[.,]\d+)?)\s*%', t, re.I):
        x = _num(m.group(1)); out.append((1 + x / 100, f'bonificacao {x:g}%', 'bonif', m.start()))
    for m in re.finditer(r'propor[cç][aã]o\s+de\s+(\d+(?:[.,]\d+)?)\s*%\s+para\s+cada', t, re.I):
        if bonif:
            x = _num(m.group(1)); out.append((1 + x / 100, f'bonificacao {x:g}% (proporcao)', 'bonif', m.start()))
    if bonif:
        for m in re.finditer(r'(\d+)\s*(?:\([^)]*\)\s*)?nova[s]?\s+a[cç][aã]o(?:\s+\w+){0,5}?\s+para\s+cada\s+(?:grupo\s+de\s+)?(\d+)', t, re.I):
            out.append((1 + int(m.group(1)) / int(m.group(2)), f'{m.group(1)} nova para cada {m.group(2)}', 'bonif', m.start()))
        for m in re.finditer(r'propor[cç][aã]o:?\s*(0[,.]\d+)\s+a[cç][oõ]es', t, re.I):
            out.append((1 + _num(m.group(1)), f'proporcao {m.group(1)}', 'bonif', m.start()))
    for m in re.finditer(r'(\d+)\s*(?:\([^)]*\)\s*)?a[cç][aã]o\s+nova\s+para\s+cada\s+(?:grupo\s+de\s+|lote\s+de\s+)?(\d+)', t, re.I):
        if bonif:
            out.append((1 + int(m.group(1)) / int(m.group(2)), f'{m.group(1)} acao nova para cada {m.group(2)}', 'bonif', m.start()))
    for m in re.finditer(r'desdobrad\w+[^.]{0,120}?\bem\s+(\d+)\s*(?:\([^)]*\)\s*)?a[cç][oõ]es', t, re.I):
        out.append((float(m.group(1)), f'desdobrada em {m.group(1)}', 'desd', m.start()))
    for m in re.finditer(r'desdobr\w*[^.]{0,200}?propor[cç][aã]o\s+de\s+(\d+)\s*(?:\([^)]*\)\s*)?novas?\s+a[cç][oõ]es\s+para\s+cada', t, re.I):
        out.append((1.0 + int(m.group(1)), f'desdobramento {m.group(1)} novas por acao', 'desd', m.start()))
    for m in re.finditer(r'(desdobr|grupament)\w*[^.]{0,160}?\b(\d[\d.]*)\s*(?:\([^)]*\)\s*)?(?:a[cç][oõ]es?\s+)?(?::|para|por)\s*(?:cada\s*)?(\d[\d.]*)\b', t, re.I):
        a, b = (float(g.replace('.', '')) for g in (m.group(2), m.group(3)))
        if a > 0 and b > 0 and a != b and max(a, b) / min(a, b) >= 1.5:
            out.append((b / a, f'razao {m.group(2)} para {m.group(3)}', 'desd' if m.group(1).lower().startswith('desd') else 'grup', m.start()))
    uniq, vistos = [], set()
    for f, d, k, pos in sorted(out, key=lambda x: x[3]):
        if round(f, 5) not in vistos:
            vistos.add(round(f, 5)); uniq.append((f, d, k))
    return uniq


# ---------------------------------------------------------------- episodios e preco
def agrupa(av):
    eps, atual = [], None
    for a in av:
        if atual and (a['dt'] - atual['fim']).days <= AGRUPA_DIAS:
            atual['avisos'].append(a); atual['fim'] = a['dt']
        else:
            atual = {'ini': a['dt'], 'fim': a['dt'], 'avisos': [a]}; eps.append(atual)
    return eps


def tipos(ep):
    t = ' '.join(a['assunto'] for a in ep['avisos']).lower()
    return [k for k in ('bonifica', 'desdobr', 'grupament') if k in t]


def serie_bruta(conn, id_ativo):
    """preco BRUTO (real do dia, direto do COTAHIST) -- independe da tabela de eventos."""
    with conn.cursor() as cur:
        cur.execute('SELECT dt_cotacao, vl_fechamento, qt_volume '
                    'FROM public.tb_cotacao_bruta WHERE id_ativo = %s ORDER BY dt_cotacao', (id_ativo,))
        return [(d, float(p), float(v or 0)) for d, p, v in cur.fetchall()]


def saltos(serie):
    out = []
    for i in range(1, len(serie)):
        d, p, v = serie[i]; d0, p0, _ = serie[i - 1]
        if p0 <= 0 or p <= 0 or v <= 0 or (d - d0).days > 10:
            continue
        antes = [x[1] for x in serie[max(0, i - 10):i]]
        depois = [x[1] for x in serie[i:i + 10]]
        r = p / p0
        rm = statistics.median(depois) / statistics.median(antes)
        out.append((d, r, abs(math.log(rm / r)) < 0.12))
    return out


def snap(f):
    cand = FATORES_BONS + [1 / x for x in FATORES_BONS]
    melhor = min(cand, key=lambda c: abs(math.log(f / c)))
    return melhor if abs(math.log(f / melhor)) < 0.05 else None


def eventos_db(conn, id_ativo):
    with conn.cursor() as cur:
        cur.execute('SELECT e.dt_evento, e.vl_fator, e.ds_origem FROM public.tb_evento_corporativo e WHERE e.id_ativo = %s ORDER BY 1', (id_ativo,))
        return [(d, float(f), o) for d, f, o in cur.fetchall()]


# ---------------------------------------------------------------- analise
def analisa(conn, ticker, usa_pdf):
    with conn.cursor() as cur:
        cur.execute('SELECT a.id_ativo, e.nr_cnpj FROM public.tb_ativo a JOIN public.tb_emissor e USING (id_emissor) WHERE a.sg_ticker = %s', (ticker,))
        id_ativo, cnpj = cur.fetchone()
    serie = serie_bruta(conn, id_ativo)
    sal = saltos(serie)
    pregoes = [x[0] for x in serie]
    db = eventos_db(conn, id_ativo)
    a0 = max(2003, serie[0][0].year - 1)
    av = avisos(cnpj, a0, date.today().year)
    amplos = avisos(cnpj, a0, date.today().year, amplos=True)
    eps = agrupa(av)
    for ep in eps:
        ja = {a['link'] for a in ep['avisos']}
        ep['avisos'] += [a for a in amplos if ep['ini'] <= a['dt'] <= ep['fim'] + timedelta(days=60) and a['link'] not in ja]
    print(f'\n##### {ticker} ({cnpj}): {len(av)} avisos CVM -> {len(eps)} episodios; serie {serie[0][0]}..{serie[-1][0]}; {len(db)} eventos no banco')

    usados, achados = set(), []
    for ep in eps:
        ts = tipos(ep)
        pernas = fator_do_texto(' | '.join(a['assunto'] for a in ep['avisos']))
        fonte = 'assunto' if pernas else None
        data_ex = como = None
        if usa_pdf:
            docs = [x for x in ep['avisos'] if x['cat'] in ('Aviso aos Acionistas', 'Fato Relevante', 'Comunicado ao Mercado')]
            docs.sort(key=lambda x: ('data-base' not in x['assunto'].lower(), -x['dt'].toordinal()))
            melhor_doc = []
            for a in docs[:6]:
                t = texto_anexo(a['link'])
                if not t:
                    continue
                if data_ex is None:
                    data_ex, como = data_ex_do_texto(t, pregoes)
                f = fator_do_texto(t)
                if len(f) > len(melhor_doc):
                    melhor_doc = f
                if data_ex and melhor_doc:
                    break
            if melhor_doc:
                pernas, fonte = melhor_doc, 'anexo'
        jan_ini, jan_fim = ep['ini'] - timedelta(days=3), ep['fim'] + timedelta(days=JANELA_POS)
        cands = [(d, r) for d, r, pers in sal if jan_ini <= d <= jan_fim and pers]
        valores = sorted({round(f, 6) for f, _, _ in pernas})
        data_ev = fator_ev = conf = None

        # combinacoes possiveis das pernas (cada uma, produto de todas, desdobramento x grupamento); o preco escolhe
        combos = set(valores)
        if len(valores) >= 2:
            combos.add(round(math.prod(valores), 6))
            for fa, _, ka in pernas:
                for fb, _, kb in pernas:
                    if ka == 'desd' and kb == 'grup':
                        combos.add(round(fa * fb, 6))
        def erro_preco(F):
            alvo = [(d, r) for d, r in cands if data_ex is None or abs((d - data_ex).days) <= 4]
            return min((abs(math.log(r * F)) for d, r in alvo), default=9)
        liquido = None
        if valores:
            nao_neutros = [(erro_preco(F), F) for F in sorted(combos) if abs(math.log(F)) > 0.05]
            melhor = min(nao_neutros, default=(9, None))
            if melhor[0] < 0.12 and abs(math.log(melhor[1])) > 0.25:
                liquido = melhor[1]                      # o preco confirma esta combinacao
            elif len(valores) >= 2 and any(abs(math.log(F)) < 0.05 for F in combos if F not in valores):
                liquido = 1.0                            # pernas se anulam e o preco nao pulou
            else:
                liquido = math.prod(valores) if len(valores) >= 2 and {k for _, _, k in pernas} & {'desd', 'grup'} else valores[0]
        if liquido is not None and len(valores) >= 2 and abs(math.log(liquido)) < 0.05:
            net_db = {}
            for d, f, o in db:
                if jan_ini <= d <= jan_fim:
                    net_db[d] = net_db.get(d, 1.0) * f
            ruim = {d: f for d, f in net_db.items() if abs(math.log(f)) > 0.05}
            status = 'NEUTRO (pernas se anulam), banco ok' if not ruim else f'NEUTRO na CVM mas BANCO TEM {[(str(d), round(f, 4)) for d, f in ruim.items()]} -> REMOVER'
            achados.append((ep, ts, pernas, fonte, None, 1.0, 'NEUTRO', status))
            print(f"{ep['ini']}..{ep['fim']} [{','.join(ts) or '-'}] pernas {valores} => NEUTRO  {status}")
            continue

        if data_ex and liquido:
            data_ev, fator_ev, conf = data_ex, liquido, 'OFICIAL' if como in ('ex', 'efetiva') else 'OFICIAL(base+1)'
            if abs(math.log(liquido)) > 0.25:
                visto = [d for d, r in cands if abs((d - data_ex).days) <= 4 and abs(math.log(r * liquido)) < 0.12]
                conf = 'OFICIAL+PRECO' if visto else conf + ' (sem salto no preco)'
        elif liquido and abs(math.log(liquido)) > 0.25:
            ok = [(abs(math.log(r * liquido)), d) for d, r in cands if abs(math.log(r * liquido)) < 0.05]
            if ok:
                _, data_ev = min(ok); fator_ev = liquido; conf = 'FATOR-CVM+PRECO'
        if data_ev is None:
            grandes = [(abs(math.log(r)), d, r) for d, r in cands if abs(math.log(r)) > 0.35]
            if grandes:
                _, data_ev, r = max(grandes); sn = snap(1 / r)
                fator_ev = sn if sn else round(1 / r, 4); conf = 'INFERIDO(preco)' if sn else 'REVISAR'
        status = 'sem salto no preco'
        if data_ev:
            perto = [(abs((d - data_ev).days), d, f, o) for d, f, o in db if abs((d - data_ev).days) <= 10]
            mesmo = [x for x in perto if abs(math.log(x[2] / fator_ev)) < 0.05]
            if mesmo:
                _, d, f, o = min(mesmo); usados.add(d)
                status = f'JA NO BANCO ({d}, x{f:g}, {o})'
            elif perto:
                _, d, f, o = min(perto); usados.add(d)
                status = f'NO BANCO COM OUTRO FATOR ({d}, x{f:g} {o})'
            else:
                status = '** FALTA NO BANCO **'
        achados.append((ep, ts, pernas, fonte, data_ev, fator_ev, conf, status))
        print(f"{ep['ini']}..{ep['fim']} [{','.join(ts) or '-'}] fator:{[d for _, d, _ in pernas][:3] or '-'}({fonte or '-'}) "
              f"=> {str(data_ev or '?'):<10} x{(f'{fator_ev:g}' if fator_ev else '?'):<8} {conf or '-':<22} {status}")
    sem_cvm = [(str(d), round(f, 4), o) for d, f, o in db if d not in usados and abs(math.log(f)) >= 0.2]
    print(f'--- eventos GRANDES do banco sem episodio CVM/salto casado: {sem_cvm}')
    return achados


def classifica(conf, status):
    tipo = ('OFICIAL' if str(conf).startswith('OFICIAL') else 'NEUTRO' if conf == 'NEUTRO' else
            'CVM-fator+preco' if conf == 'FATOR-CVM+PRECO' else 'PRECO' if conf in ('INFERIDO(preco)', 'REVISAR') else 'sem dado')
    res = ('no banco igual' if status.startswith('JA NO BANCO') else 'FALTA no banco' if status.startswith('**') else
           'banco com outro fator' if status.startswith('NO BANCO COM') else 'neutro ok' if 'banco ok' in status else
           'neutro, BANCO ERRADO' if 'REMOVER' in status else 'sem salto/sem match')
    return tipo, res


if __name__ == '__main__':
    tickers = [a for a in sys.argv[1:] if not a.startswith('--')]
    conn = get_conn()
    total = {}
    for t in tickers or ['BBDC4']:
        for a in analisa(conn, t, '--pdf' in sys.argv):
            k = classifica(a[6] or 'sem dado', a[7])
            total[k] = total.get(k, 0) + 1
    if len(tickers) > 1:
        print('\n===== TOTAL (todos os tickers) =====')
        for k in sorted(total):
            print(f'  {k[0]:16} {k[1]:26} {total[k]}')
