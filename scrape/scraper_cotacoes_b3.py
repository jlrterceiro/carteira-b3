import os
import sys
import time
import urllib.request
import zipfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cotahist_cache')
BASE_URL = 'https://bvmf.bmfbovespa.com.br/InstDados/SerHist'
ANO_FINAL = date.today().year
ANO_INICIAL_FULL = 1994  # COTAHIST disponivel desde 1994
# Cloudflare bloqueia o User-Agent generico do urllib (Python-urllib/x.y) com 403 -- mesmo
# header de navegador ja usado nos scrapers da B3 (scraper_proventos.py etc) resolve.
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}

# Grava o preco REAL do dia (COTAHIST, dividido por FATCOT) em tb_cotacao_bruta -- nunca ajusta.
# Dois modos: incremental (padrao, so dias depois do ultimo salvo) e --full (substitui o historico do
# ativo, 1994+). O preco ajustado por evento/provento e derivado (tb_cotacao_ajustada).

# Layout fixo do COTAHIST (manual oficial B3, posicoes 1-indexadas) -- confirmado campo a
# campo contra cotacao ja existente (PETR4 20/01/2025: abertura 37,22, maxima 37,43, minima
# 37,11, fechamento 37,29, quantidade 13.912.800 -- bate exato com o que ja tinhamos do
# yfinance pra essa data, sem nenhum split no meio).
def parse_linha(linha):
    # FATCOT (posicoes 211-217): ate ~2005 varios papeis eram cotados POR LOTE de 1.000 (ou 100,
    # 10.000...) acoes; o preco unitario e o preco do arquivo / FATCOT. Ignorar isso gerava saltos
    # x1000 (e x20) nas series antigas (BRKM6, CEGR3...).
    fatcot = int(linha[210:217]) or 1
    return {
        'tipreg': linha[0:2],
        'data': linha[2:10],
        'codneg': linha[12:24].strip(),
        'tpmerc': linha[24:27],
        'modref': linha[52:56].strip(),
        'preabe': int(linha[56:69]) / 100 / fatcot,
        'premax': int(linha[69:82]) / 100 / fatcot,
        'premin': int(linha[82:95]) / 100 / fatcot,
        'preult': int(linha[108:121]) / 100 / fatcot,
        'quatot': int(linha[152:170]),
        'fatcot': fatcot,
        'isin': linha[230:242],
    }


def baixa_ano(ano):
    os.makedirs(CACHE_DIR, exist_ok=True)
    caminho = os.path.join(CACHE_DIR, f'COTAHIST_A{ano}.ZIP')
    # ano corrente: o arquivo cresce dia a dia, so aproveita o cache se tiver sido baixado hoje
    # (varias execucoes no mesmo dia nao rebaixam 60MB toda vez).
    if ano == date.today().year and os.path.exists(caminho):
        if date.fromtimestamp(os.path.getmtime(caminho)) < date.today():
            os.remove(caminho)
    if not os.path.exists(caminho):
        url = f'{BASE_URL}/COTAHIST_A{ano}.ZIP'
        print(f'  baixando {url}...')
        req = urllib.request.Request(url, headers=HEADERS)
        ultimo_erro = None
        for tentativa in range(1, 5):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    dados = resp.read()
                with open(caminho + '.part', 'wb') as out:   # so vira o arquivo final se baixou inteiro
                    out.write(dados)
                os.replace(caminho + '.part', caminho)
                break
            except Exception as e:
                ultimo_erro = e
                print(f'  download falhou ({e}), tentativa {tentativa}/4')
                time.sleep(3 * tentativa)
        else:
            raise ultimo_erro
    return caminho


def le_ano(ano, resolve_id_ativo, dt_minima):
    # resolve_id_ativo(ticker, dt, isin) -> id_ativo ou None. dt_minima: ignora linhas
    # dt_cotacao <= dt_minima (ja temos, vindas do refresh yfinance ou de execucao anterior).
    caminho = baixa_ano(ano)
    cotacoes = {}
    with zipfile.ZipFile(caminho) as z:
        nome_txt = z.namelist()[0]
        with z.open(nome_txt) as f:
            for linha_bytes in f:
                if linha_bytes[0:2] != b'01' or linha_bytes[24:27] != b'010':
                    continue
                ticker = linha_bytes[12:24].decode('latin1').strip()
                campos = parse_linha(linha_bytes.decode('latin1'))
                if campos['modref'] != 'R$':   # 1994 antes do Plano Real vem em CR$ (cruzeiro real)
                    continue
                dt = f"{campos['data'][0:4]}-{campos['data'][4:6]}-{campos['data'][6:8]}"
                if dt <= dt_minima:
                    continue
                id_ativo = resolve_id_ativo(ticker, dt, campos['isin'])
                if id_ativo is None:
                    continue
                cotacoes.setdefault(id_ativo, []).append(
                    (dt, campos['preabe'], campos['premax'], campos['premin'], campos['preult'], campos['quatot'])
                )
    return cotacoes


def fetch_ativos(conn, ticker_filter=None):
    query = 'SELECT id_ativo, sg_ticker FROM public.tb_ativo'
    params = ()
    if ticker_filter:
        query += ' WHERE sg_ticker = %s'
        params = (ticker_filter,)
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def fetch_ticker_historico(conn, ids_alvo):
    # codigos antigos de ativos renomeados (tb_ticker_historico). cd_isin preenchido = a ligacao so
    # vale pras linhas daquele ISIN (um mesmo codigo antigo pode ter ISINs diferentes ao longo do
    # tempo, e codigo pode ser reaproveitado por outra empresa); NULL = vale pro codigo todo.
    with conn.cursor() as cur:
        cur.execute('SELECT sg_ticker_antigo, id_ativo, dt_alteracao, cd_isin FROM public.tb_ticker_historico')
        return [
            (row[0], row[1], row[2].isoformat(), row[3])
            for row in cur.fetchall()
            if row[1] in ids_alvo
        ]


def fetch_max_cotacao(conn, id_ativo):
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT dt_cotacao, vl_fechamento
            FROM public.tb_cotacao_bruta
            WHERE id_ativo = %s
            ORDER BY dt_cotacao DESC
            LIMIT 1
            ''',
            (id_ativo,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return (row[0].isoformat(), float(row[1]))


_MAX_PRECO = 1e11  # ~R$100bi; NUMERIC(20,8) max e ~1T, mas preco acima de 100bi e espurio


def insere_cotacoes(conn, id_ativo, linhas):
    import math
    skipped = 0
    with conn.cursor() as cur:
        for dt, abe, mx, mn, ult, qtd in linhas:
            vals = (abe, mx, mn, ult)
            if not all(math.isfinite(v) for v in vals) or max(vals) > _MAX_PRECO:
                skipped += 1
                continue
            cur.execute(
                '''
                INSERT INTO public.tb_cotacao_bruta (
                    id_ativo, dt_cotacao, vl_abertura, vl_maxima, vl_minima, vl_fechamento, qt_volume
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id_ativo, dt_cotacao) DO UPDATE SET
                    vl_abertura = EXCLUDED.vl_abertura,
                    vl_maxima = EXCLUDED.vl_maxima,
                    vl_minima = EXCLUDED.vl_minima,
                    vl_fechamento = EXCLUDED.vl_fechamento,
                    qt_volume = EXCLUDED.qt_volume
                ''',
                (id_ativo, dt, abe, mx, mn, ult, qtd),
            )
    conn.commit()
    if skipped:
        print(f'    ({skipped} linhas ignoradas: preco inviavel)')
    return len(linhas) - skipped


def process_ativo(conn, id_ativo, ticker, linhas_novas, full_refresh=False):
    # Grava o preco REAL do COTAHIST em tb_cotacao_bruta. Nada de ajuste aqui: o ajustado por evento/provento
    # e derivado em tb_cotacao_ajustada (fn_popula_cotacao_ajustada, chamada por fn_rebuild_tudo).
    max_existente = fetch_max_cotacao(conn, id_ativo)
    if full_refresh:
        # --full SUBSTITUI o historico: sem apagar antes, linhas que o COTAHIST nao cobre ficavam misturadas.
        with conn.cursor() as cur:
            cur.execute('DELETE FROM public.tb_cotacao_bruta WHERE id_ativo = %s', (id_ativo,))
            if cur.rowcount:
                print(f'  {ticker}: {cur.rowcount} cotacoes antigas apagadas')
    if max_existente is None and not full_refresh:
        print(f'  {ticker}: sem cotacao existente, fora de escopo do modo incremental')
        return
    if not linhas_novas:
        print(f'  {ticker}: nada novo')
        return
    linhas_novas.sort(key=lambda r: r[0])
    inserted = insere_cotacoes(conn, id_ativo, linhas_novas)
    modo = 'full' if full_refresh else f'apos {max_existente[0]}'
    print(f'  {ticker}: {inserted} cotacoes (B3, {linhas_novas[0][0]} a {linhas_novas[-1][0]}, {modo})')


def run(ticker_filter=None, full_refresh=False, so_novos=False):
    conn = get_conn()
    ativos = fetch_ativos(conn, ticker_filter)
    if so_novos:
        # carga completa so pra ativos que ainda nao tem nenhuma cotacao (cadastro novo)
        ativos = [(i, t) for i, t in ativos if fetch_max_cotacao(conn, i) is None]
        full_refresh = True
        print(f'{len(ativos)} ativos sem cotacao -- carga completa so pra eles')
    ids_alvo = {id_ativo for id_ativo, _ in ativos}
    id_ativo_por_ticker_atual = {ticker: id_ativo for id_ativo, ticker in ativos}
    historico = fetch_ticker_historico(conn, ids_alvo)
    id_ativo_e_corte_por_ticker_antigo = {(antigo, isin): (id_ativo, dt_alt) for antigo, id_ativo, dt_alt, isin in historico}

    if full_refresh:
        dt_minima_global = '1900-01-01'
        ano_inicial = ANO_INICIAL_FULL
        print(f'processando {len(ativos)} ativos, modo FULL (anos {ano_inicial}-{ANO_FINAL})')
    else:
        dt_max_por_ativo = {}
        for id_ativo, ticker in ativos:
            max_existente = fetch_max_cotacao(conn, id_ativo)
            dt_max_por_ativo[id_ativo] = max_existente[0] if max_existente else None
        dt_minima_global = min((d for d in dt_max_por_ativo.values() if d is not None), default=None)
        if dt_minima_global is None:
            print('nenhum ativo tem cotacao existente -- rodar com --full para carga inicial')
            conn.close()
            return
        ano_inicial = int(dt_minima_global[0:4])
        print(f'processando {len(ativos)} ativos, modo incremental a partir de {dt_minima_global} (anos {ano_inicial}-{ANO_FINAL})')

    corte_por_id = {}
    for _, id_ativo, dt_alt, _ in historico:
        corte_por_id[id_ativo] = max(dt_alt, corte_por_id.get(id_ativo, '0000-00-00'))

    def resolve_id_ativo(ticker, dt, isin):
        # ligacao explicita (codigo antigo, e opcionalmente ISIN): vale ate dt_alteracao
        entry = id_ativo_e_corte_por_ticker_antigo.get((ticker, isin)) or id_ativo_e_corte_por_ticker_antigo.get((ticker, None))
        if entry and dt < entry[1]:
            return entry[0]
        if ticker in id_ativo_por_ticker_atual:
            id_ativo = id_ativo_por_ticker_atual[ticker]
            # antes da data de alteracao o ativo e a serie do ticker ANTIGO (e o que a carteira
            # realmente segurava, ex: AESB3 -> AURE3). A serie propria do ticker novo nesse
            # periodo e de outra empresa/classe que negociava em paralelo (AURE3 vs AESB3,
            # CPLE3 ON vs CPLE6) -- misturar alternava os precos dia a dia.
            if dt < corte_por_id.get(id_ativo, '0000-00-00'):
                return None
            return id_ativo
        return None

    cotacoes_por_ativo = {}
    for ano in range(ano_inicial, ANO_FINAL + 1):
        print(f'[ano {ano}] lendo COTAHIST...')
        cotacoes_ano = le_ano(ano, resolve_id_ativo, dt_minima_global)
        for id_ativo, linhas in cotacoes_ano.items():
            cotacoes_por_ativo.setdefault(id_ativo, []).extend(linhas)
        print(f'[ano {ano}] {sum(len(v) for v in cotacoes_ano.values())} linhas casadas')

    total = len(ativos)
    if full_refresh:
        dt_max_por_ativo = {id_ativo: '1900-01-01' for id_ativo, _ in ativos}
    for index, (id_ativo, ticker) in enumerate(ativos, start=1):
        print(f'[{index}/{total}] {ticker}')
        try:
            dt_max_ativo = dt_max_por_ativo[id_ativo]
            linhas_novas = [l for l in cotacoes_por_ativo.get(id_ativo, []) if dt_max_ativo is None or l[0] > dt_max_ativo]
            process_ativo(conn, id_ativo, ticker, linhas_novas, full_refresh=full_refresh)
        except Exception as e:
            conn.rollback()
            print(f'  erro: {e}')
    conn.close()


def main():
    args = [a for a in sys.argv[1:] if a not in ('--full', '--novos')]
    full_refresh = '--full' in sys.argv[1:]
    ticker_filter = args[0] if args else None
    run(ticker_filter, full_refresh=full_refresh, so_novos='--novos' in sys.argv[1:])


if __name__ == '__main__':
    main()
