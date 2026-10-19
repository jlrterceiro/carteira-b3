"""
Classifica os ajustes de strike achados por eventos_por_opcoes.py (dividendo x evento) e cruza com
tb_evento_corporativo.

    python3 scrape/compara_eventos_opcoes.py

Ajuste de strike observado F = F_evento x F_dividendo, com F_dividendo = P / (P - provento_liquido)
(P = fechamento bruto da vespera). Resido R = F / F_dividendo: ~1 -> so dividendo; senao evento de fator R.
"""
import csv
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

ERA_CONFIAVEL = date(2008, 1, 1)   # proventos da B3 antes disso vem em escala de lote
TOL_DIV = 0.006


def le_csv(p):
    with open(p) as f:
        return list(csv.DictReader(f))


def classifica_candidatos(conn, cand):
    """-> (classes, eventos[(raiz, data, fator_evento, ticker)]) a partir dos candidatos de eventos_por_opcoes"""
    cur = conn.cursor()
    cur.execute("SELECT id_ativo, sg_ticker FROM tb_ativo")
    tickers = defaultdict(list)
    for ida, tk in cur.fetchall():
        if len(tk) >= 5:
            tickers[tk[:4]].append((ida, tk))
    classes = defaultdict(list)
    eventos = []   # (raiz, data, fator_evento, ticker)
    for c in cand:
        raiz, dt, F = c['raiz'], date.fromisoformat(c['data']), float(c['fator'])
        ativos = tickers.get(raiz)
        if not ativos:
            classes['sem ativo no banco'].append(c); continue
        melhor = None
        for ida, tk in ativos:
            cur.execute("SELECT c.vl_fechamento FROM tb_cotacao_bruta c WHERE c.id_ativo=%s AND c.dt_cotacao < %s ORDER BY c.dt_cotacao DESC LIMIT 1", (ida, dt))
            row = cur.fetchone()
            if not row or not row[0]:
                continue
            P = float(row[0])
            cur.execute("SELECT COALESCE(sum(COALESCE(vl_unitario_liquido, vl_unitario)),0) FROM tb_provento WHERE id_ativo=%s AND dt_ex=%s", (ida, dt))
            D = float(cur.fetchone()[0])
            Fd = P / (P - D) if D and P > D else 1.0
            R = F / Fd
            if melhor is None or abs(math.log(R)) < abs(math.log(melhor[0])):
                melhor = (R, Fd, D, tk)
        if melhor is None:
            classes['sem cotacao'].append(c); continue
        R, Fd, D, tk = melhor
        if dt < ERA_CONFIAVEL:
            classes['era antiga (proventos nao confiaveis)'].append((c, R)); eventos.append((raiz, dt, F, 'antiga')); continue
        if abs(math.log(R)) < TOL_DIV:
            classes['so dividendo/JCP (explicado)'].append(c)
        elif D == 0 and abs(math.log(F)) < 0.06:
            classes['AMBIGUO: pequeno e SEM provento no banco (provento faltando ou bonificacao pequena)'].append(c)
        else:
            classes['EVENTO'].append((c, R, tk)); eventos.append((raiz, dt, R, tk))
    return classes, eventos


def main():
    conn = get_conn()
    cand = le_csv('/tmp/eventos_opcoes.csv')
    cob = defaultdict(set)
    for r in le_csv('/tmp/cobertura_opcoes.csv'):
        cob[r['raiz']].add(r['data'])
    classes, eventos = classifica_candidatos(conn, cand)
    cur = conn.cursor()
    print('===== classificacao dos %d ajustes de strike =====' % len(cand))
    for k, v in sorted(classes.items(), key=lambda kv: -len(kv[1])):
        print(f'  {len(v):4}  {k}')

    # ---- cruzamento com o banco
    cur.execute("""SELECT a.sg_ticker, e.dt_evento, e.vl_fator, e.ds_origem FROM tb_evento_corporativo e JOIN tb_ativo a USING(id_ativo) WHERE e.vl_fator > 0""")
    db = defaultdict(list)
    for tk, d, f, o in cur.fetchall():
        db[tk[:4]].append((d, float(f), o, tk))
    # evento liquido por (raiz, data): produto dos fatores do banco na data (varias classes -> uma por classe; pega a maior classe unica)
    ok, falta, fator_dif = [], [], []
    ja_casados = set()
    for raiz, dt, R, tk in eventos:
        perto = [(abs((d - dt).days), d, f, o, t) for d, f, o, t in db.get(raiz, []) if abs((d - dt).days) <= 3]
        if not perto:
            falta.append((raiz, dt, R, tk)); continue
        # soma log dos eventos do banco na mesma data (ex.: desdobramento+grupamento)
        por_data = defaultdict(float)
        for _, d, f, o, t in perto:
            por_data[d] += math.log(f) / max(1, sum(1 for x in db[raiz] if x[0] == d and x[3] == t) and 1)
        melhor = min(perto)
        if abs(math.log(R / melhor[2])) < 0.02:
            ok.append((raiz, dt, R, melhor[1], melhor[2], melhor[3])); ja_casados.add((raiz, melhor[1]))
        else:
            fator_dif.append((raiz, dt, R, melhor[1], melhor[2], melhor[3]))
    print(f'\n===== eventos (sem dividendo) detectados pelas opcoes: {len(eventos)} =====')
    print(f'  confirmados no banco (mesmo fator, +-3 dias): {len(ok)}')
    print(f'  no banco com OUTRO fator: {len(fator_dif)}')
    print(f'  FALTAM no banco: {len(falta)}')
    open('/tmp/opcoes_faltam.csv', 'w').write('raiz,data,fator,ticker\n' + '\n'.join(f'{r},{d},{f:.4f},{t}' for r, d, f, t in sorted(falta, key=lambda x: (x[0], x[1]))))
    open('/tmp/opcoes_fator_dif.csv', 'w').write('raiz,data_opcoes,fator_opcoes,data_banco,fator_banco,origem\n' + '\n'.join(f'{r},{d},{f:.4f},{dd},{fb:.4f},{o}' for r, d, f, dd, fb, o in sorted(fator_dif)))
    print('\n--- FATORES DIFERENTES (opcoes x banco) ---')
    for r, d, f, dd, fb, o in sorted(fator_dif)[:25]:
        print(f'  {r} {d} opcoes x{f:.4f} | banco {dd} x{fb:.4f} ({o})')
    print('\n--- FALTAM no banco (2008+, mais recentes primeiro) ---')
    for r, d, f, t in sorted([x for x in falta if x[1] >= ERA_CONFIAVEL], key=lambda x: x[1], reverse=True)[:30]:
        print(f'  {r} {d} x{f:.4f}')
    print(f'  ... total 2008+: {sum(1 for x in falta if x[1] >= ERA_CONFIAVEL)}; era antiga: {sum(1 for x in falta if x[1] < ERA_CONFIAVEL)}')

    # ---- eventos do banco SEM respaldo nas opcoes, onde havia opcoes pra ver
    sem = []
    detect = {(r, d) for r, d, _, _ in eventos}
    for raiz, lst in db.items():
        if raiz not in cob:
            continue
        vistos = set()
        for d, f, o, tk in lst:
            if abs(math.log(f)) < 0.03 or (raiz, d) in vistos:
                continue
            vistos.add((raiz, d))
            visivel = any((d + timedelta(days=k)).isoformat() in cob[raiz] for k in (-1, 0, 1))
            if not visivel:
                continue
            if not any(abs((d - dd).days) <= 3 for rr, dd, _, _ in eventos if rr == raiz):
                sem.append((raiz, d, f, o, tk))
    print(f'\n===== eventos GRANDES do banco com opcoes visiveis no dia mas SEM ajuste de strike (suspeitos): {len(sem)} =====')
    for raiz, d, f, o, tk in sorted(sem)[:40]:
        print(f'  {tk} {d} x{f:.4f} ({o})')


if __name__ == '__main__':
    main()
