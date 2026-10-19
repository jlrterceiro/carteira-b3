"""
Rotina DIARIA, so com dados estruturados (nada de PDF): cotacoes do COTAHIST, negocios consolidados da B3
(com a oscilacao oficial), eventos da API da B3, correcao dos eventos pelo arquivo diario (OscnPctg), proventos
e recalculo da carteira. Cada passo roda como processo separado e a rotina para no primeiro que falhar.

    python3 scrape/atualiza_diario.py                 # tudo
    python3 scrape/atualiza_diario.py --sem-proventos # pula a raspagem de proventos (a mais demorada)

O reconstrutor com --diario so olha os eventos dos ultimos 15 dias e so enxerga o arquivo diario da B3 (a CVM em PDF
foi uma carga unica do passado: scraper_eventos_cvm.py).
"""
import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)


def passo(nome, cmd):
    t0 = time.time()
    print(f'\n===== {nome} =====', flush=True)
    r = subprocess.run(cmd, cwd=RAIZ)
    print(f'===== {nome}: {"ok" if r.returncode == 0 else "FALHOU (" + str(r.returncode) + ")"} em {time.time() - t0:.0f}s', flush=True)
    if r.returncode != 0:
        sys.exit(r.returncode)


def main():
    py = sys.executable
    passo('cotacoes (COTAHIST, incremental)', [py, 'scrape/scraper_cotacoes_b3.py'])
    passo('negocios consolidados da B3', [py, 'scrape/scraper_negocios_b3.py'])
    passo('eventos corporativos (API da B3)', [py, 'scrape/scraper_eventos_corporativos_b3.py'])
    passo('eventos pela oscilacao oficial (arquivo diario)', [py, 'scrape/reconstroi_eventos.py', '--diario', '--aplica'])
    if '--sem-proventos' not in sys.argv:
        passo('proventos (B3)', [py, 'scrape/scraper_proventos.py'])
    from db_lib import get_conn
    conn = get_conn()
    with conn.cursor() as cur:
        print('\n===== fn_rebuild_tudo =====', flush=True)
        cur.execute('SELECT fn_rebuild_tudo()')
    conn.commit(); conn.close()
    print('===== fim =====')


if __name__ == '__main__':
    main()
