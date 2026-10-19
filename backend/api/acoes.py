from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3
from fastapi import APIRouter

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
