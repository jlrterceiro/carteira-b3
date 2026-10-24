from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3
import unicodedata

from fastapi import APIRouter, Depends

from deps import get_current_user, get_db

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

router = APIRouter(prefix='/acoes', tags=['acoes'])

SI_SEARCH_URL = 'https://statusinvest.com.br/home/mainsearchquery?q={}'
_SI_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
}


def _parentid_si(ticker: str):
    """Resolve ticker -> parentId do Status Invest (logo da empresa).
    Se o ticker exato nao existir (ex: SHUL4, SI so tem SHUL3), tenta a ON (ultimo digito -> 3)
    e depois o prefixo de 4 letras: empresas com ON/PN compartilham o mesmo parentId/logo.
    """
    try:
        for candidato in [ticker, ticker[:-1] + '3', ticker[:4]]:
            resp = requests.get(SI_SEARCH_URL.format(candidato), headers=_SI_HEADERS, verify=False, timeout=5)
            for item in resp.json():
                if item.get('type') == 1 and str(item.get('code', '')).upper()[:4] == ticker.upper()[:4]:
                    return item.get('parentId')
    except Exception:
        pass
    return None


@router.get('/logos')
def logos(tickers: str):
    """tickers separados por virgula -> {ticker: parentId|null}."""
    lista = [t.strip().upper() for t in tickers.split(',') if t.strip()]
    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(zip(lista, ex.map(_parentid_si, lista)))


def _norm(t: str) -> str:
    """minusculo e sem acento (o banco nao tem a extensao unaccent)"""
    return ''.join(c for c in unicodedata.normalize('NFD', t or '') if unicodedata.category(c) != 'Mn').lower().strip()


@router.get('/busca')
def busca(q: str, limite: int = 8, usuario=Depends(get_current_user), conn=Depends(get_db)):
    """Autocomplete de acao: aceita ticker ou nome da empresa (sem acento, em qualquer parte do nome), melhores resultados primeiro:
    ticker exato, ticker que comeca com o texto, sigla da empresa (PETR -> PETR3, PETR4), palavra do nome que comeca com o texto, nome
    que contem o texto. Em empate, ativas antes das que sairam de negociacao."""
    termo = _norm(q)
    if not termo:
        return []
    with conn.cursor() as cur:
        cur.execute('''SELECT a.sg_ticker, e.nm_emissor, e.sg_emissor, a.sg_classe, COALESCE(a.fl_ativo, true)
                       FROM public.tb_ativo a LEFT JOIN public.tb_emissor e USING (id_emissor)''')
        achados = []
        for ticker, nome, sigla, classe, ativa in cur.fetchall():
            t, n, sg = _norm(ticker), _norm(nome), _norm(sigla)
            if t == termo:
                score = 0
            elif t.startswith(termo):
                score = 1
            elif sg and sg.startswith(termo):
                score = 2
            elif any(p.startswith(termo) for p in n.split()):
                score = 3
            elif termo in n:
                score = 4
            elif termo in t:
                score = 5
            else:
                continue
            achados.append((score, not ativa, len(ticker), ticker, nome, classe, ativa))
    achados.sort()
    return [{'ticker': a[3], 'nome': a[4], 'classe': a[5], 'ativo': a[6]} for a in achados[:max(1, min(limite, 20))]]
