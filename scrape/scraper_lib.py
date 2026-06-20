import re
import urllib.request

BASE = 'https://www.dadosdemercado.com.br'


def get_html(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return urllib.request.urlopen(req, timeout=20).read().decode('utf-8')


def parse_tickers(html):
    return re.findall(
        r'<tr>\s*<td><strong><a href="([^"]+)">([^<]+)</a></strong></td>\s*<td>([^<]+)</td>',
        html,
        re.I,
    )


def normalize_ticker(ticker):
    return re.sub(r'\d+$', '', ticker)
