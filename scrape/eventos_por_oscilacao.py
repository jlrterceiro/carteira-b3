"""
Eventos corporativos EXATOS a partir da oscilacao oficial da B3 (tb_negocio_diario.pc_oscilacao).

A B3 calcula a oscilacao do dia contra o fechamento anterior JA ajustado (eventos e proventos em dinheiro).
Logo  F_total = (1 + osc) x fechamento_anterior / fechamento_do_dia  e  F_total = F_evento x F_dividendo,
com F_dividendo = P / (P - provento_liquido). O que sobra (R = F_total / F_dividendo) e o fator do evento:
bonificacao 10% -> 1,1; grupamento 10:1 -> 0,1. O movimento real do mercado aparece nos dois lados e se
cancela, por isso o fator sai exato.

    python3 scrape/eventos_por_oscilacao.py              # relatorio (nao grava)
"""
import math
import os
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

GAP_MAX_DIAS = 6
TOL_MIN = 0.01        # |ln R| abaixo disso e ruido/dividendo
TICK = 0.01           # a B3 arredonda a referencia ao centavo


def detecta(conn):
    cur = conn.cursor()
    cur.execute('''SELECT sg_ticker, dt_pregao, vl_ultimo, pc_oscilacao FROM public.tb_negocio_diario
                   WHERE vl_ultimo > 0 AND pc_oscilacao IS NOT NULL ORDER BY sg_ticker, dt_pregao''')
    por_ticker = defaultdict(list)
    for tk, d, last, osc in cur.fetchall():
        por_ticker[tk].append((d, float(last), float(osc)))
    cur.execute('SELECT min(dt_pregao) FROM public.tb_negocio_diario')
    d_min = cur.fetchone()[0]
    # pregoes de cada ticker no COTAHIST (o arquivo diario da B3 pode ter dias faltando; a oscilacao e sempre
    # contra o fechamento do ULTIMO pregao do ticker, nao contra a linha anterior da minha tabela)
    cur.execute('''SELECT a.sg_ticker, c.dt_cotacao FROM public.tb_cotacao_bruta c JOIN public.tb_ativo a USING (id_ativo)
                   WHERE c.dt_cotacao >= %s - 20 ORDER BY 1, 2''', (d_min,))
    pregoes = defaultdict(list)
    for tk, d in cur.fetchall():
        pregoes[tk].append(d)
    cache_bruto = {}

    def fech_bruto(tk, d):
        k = (tk, d)
        if k not in cache_bruto:
            cur.execute('''SELECT c.vl_fechamento
                           FROM public.tb_cotacao_bruta c JOIN public.tb_ativo a USING (id_ativo)
                           WHERE a.sg_ticker = %s AND c.dt_cotacao = %s''', (tk, d))
            r = cur.fetchone()
            cache_bruto[k] = float(r[0]) if r and r[0] else None
        return cache_bruto[k]

    cur.execute('''SELECT a.sg_ticker, p.dt_ex, sum(COALESCE(p.vl_unitario_liquido, p.vl_unitario))
                   FROM public.tb_provento p JOIN public.tb_ativo a USING (id_ativo) GROUP BY 1, 2''')
    prov = {(tk, d): float(v) for tk, d, v in cur.fetchall()}
    out = []
    for tk, linhas in por_ticker.items():
        do_arquivo = {d: last for d, last, _ in linhas}
        datas = pregoes.get(tk, [])
        for d1, p1, osc in linhas:
            ant = [x for x in datas if x < d1]
            if not ant:
                continue
            d0 = ant[-1]
            if (d1 - d0).days > GAP_MAX_DIAS:
                continue
            p0 = do_arquivo.get(d0) or fech_bruto(tk, d0)
            if not p0 or p0 <= 0:
                continue
            F_total = (1 + osc / 100) * p0 / p1
            D = prov.get((tk, d1), 0.0)
            F_div = p0 / (p0 - D) if D and p0 > D else 1.0
            R = F_total / F_div
            ref = p1 / (1 + osc / 100) if osc > -100 else p1
            tol = max(TOL_MIN, 3 * (TICK / 2) / max(ref, 0.01))
            out.append((tk, d1, p0, p1, osc, F_total, D, F_div, R, abs(math.log(R)) > tol, abs(math.log(F_total)) > tol, d0))
    return out


if __name__ == '__main__':
    conn = get_conn()
    res = detecta(conn)
    eventos = [r for r in res if r[9]]
    amb = [r for r in res if not r[9] and r[10] and r[6] == 0]    # ajuste sem provento cadastrado e sem evento claro
    print(f'{len(res)} pares ticker-dia; {len(eventos)} eventos (apos remover dividendo); {len(amb)} ajustes pequenos sem provento no banco')
    for tk, d, p0, p1, osc, Ft, D, Fd, R, *_ in sorted(eventos, key=lambda r: (r[1], r[0])):
        print(f'  {tk:7} {d}  fech {p0:9.4f} -> {p1:9.4f}  osc {osc:+7.2f}%  F_total {Ft:8.4f}  div {D:7.4f}  => EVENTO x{R:.4f}')
