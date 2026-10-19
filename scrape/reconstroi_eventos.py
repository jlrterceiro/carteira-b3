"""
Reconstroi tb_evento_corporativo so com fontes oficiais. Regra de ouro (aprendida na marra): o ajuste do
strike das opcoes e a oscilacao da B3 CONFIRMAM e DATAM eventos, mas a AUSENCIA deles nao prova que o evento nao
existiu (a B3 pode trocar o codigo da serie de opcoes em vez de ajustar; o arquivo diario tem dias faltando
e tickers que estreiam no dia). Quem desmente um evento e o PRECO BRUTO: se o preco nao pulou ~1/F, o evento
e espurio.

Fontes
  S1  oscilacao oficial da B3 (tb_negocio_diario, 2025-06-11+)   fator e dia exatos, por ticker
  S2  ajuste do strike das opcoes no COTAHIST (1994+)            fator e dia exatos, por raiz (papeis com opcoes)
  S3  preco (tb_cotacao_ajustada: serie ajustada pelos eventos do banco)  so desmente / reposiciona eventos GRANDES (>=16%)

Acoes (CSV em /tmp/acoes_eventos.csv)
  ADD         S1/S2 veem o evento e o banco nao tem. Fator pequeno (<~28%) exige 2a evidencia (aviso no INDICE da CVM)
  REPLACE     o banco tem algo a +-3 dias com fator liquido bem diferente: troca pelo fator exato
  FIX_DATA    o banco tem o evento certo no dia errado (S2 ou salto de preco compensatorio)
  REMOVE      S1 cobre o dia e nao houve ajuste, OU o preco bruto nao pulou (evento >=16%)
Pernas que se anulam no mesmo dia (grupamento + desdobramento) NUNCA sao removidas (fator liquido ~1).

    python3 scrape/reconstroi_eventos.py            # so relatorio
    python3 scrape/reconstroi_eventos.py --aplica   # grava (backup em bkp_eventos; rejeitados em tb_evento_rejeitado)
    python3 scrape/reconstroi_eventos.py --diario --aplica   # rotina diaria: so S1 (arquivo diario), ultimos 15 dias
"""
import csv
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn
from compara_eventos_opcoes import classifica_candidatos, le_csv
from eventos_por_oscilacao import detecta as detecta_osc
from prototipo_eventos_cvm import avisos as avisos_cvm

INICIO_S1 = date(2025, 6, 11)
DIAS_DIARIO = 15          # --diario olha so os eventos dos ultimos N dias
MIN_EVENTO = 0.025        # |ln F| minimo pra aceitar um evento novo (abaixo disso e indistinguivel de provento)
MIN_EVENTO_ANTIGO = 0.06  # antes de 2008 os proventos da B3 vem em escala de lote
CERTO = 0.25              # |ln F| a partir do qual um ajuste e evento sozinho (dividendo nao chega a ~22%)
GRANDE = 0.15             # |ln F| a partir do qual o preco bruto TEM que mostrar o salto
TOL_FATOR = 0.02
CANDIDATOS = sorted({1 + p / 100 for p in range(1, 101)} | set(range(2, 1001)) | {1 / n for n in range(2, 1001)})


def snap(R):
    c = min(CANDIDATOS, key=lambda x: abs(math.log(R / x)))
    return round(c, 6) if abs(math.log(R / c)) < 0.0025 else round(R, 4)


def tipo_de(F):
    return 'GRUP' if F < 1 else ('SPLIT' if F >= 2 and abs(F - round(F)) < 1e-6 else 'BONIF')


_cache_cvm = {}


def indice_cvm(cur, ticker, ano):
    cur.execute('SELECT e.nr_cnpj FROM tb_ativo a JOIN tb_emissor e USING (id_emissor) WHERE a.sg_ticker = %s', (ticker,))
    r = cur.fetchone()
    if not r or not r[0] or ano < 2003:
        return []
    k = (r[0], ano)
    if k not in _cache_cvm:
        try:
            _cache_cvm[k] = [a['dt'] for a in avisos_cvm(r[0], ano - 1, ano)]
        except Exception:
            _cache_cvm[k] = []
    return _cache_cvm[k]


def corroborado(cur, ticker, data, F):
    if abs(math.log(F)) >= CERTO:
        return 'grande'
    if any(data - timedelta(days=200) <= d <= data + timedelta(days=3) for d in indice_cvm(cur, ticker, data.year)):
        return 'indice CVM'
    return None


def main():
    aplica = '--aplica' in sys.argv
    diario = '--diario' in sys.argv      # rotina diaria: so o arquivo diario da B3, janela curta
    corte = date.today() - timedelta(days=DIAS_DIARIO)
    conn = get_conn(); cur = conn.cursor()
    cur.execute('SELECT id_ativo, sg_ticker FROM tb_ativo')
    ativos = {tk: ida for ida, tk in cur.fetchall()}
    por_raiz = defaultdict(list)
    for tk in ativos:
        if len(tk) >= 5:
            por_raiz[tk[:4]].append(tk)
    cur.execute('SELECT id_tipo_operacao, sg_tipo_operacao FROM tb_tipo_operacao')
    tipo_id = {sg: i for i, sg in cur.fetchall()}

    # ---------------- banco
    cur.execute('''SELECT e.id_evento_corporativo, a.sg_ticker, e.dt_evento, e.vl_fator, e.ds_origem
                   FROM tb_evento_corporativo e JOIN tb_ativo a USING (id_ativo) WHERE e.vl_fator > 0''')
    db = defaultdict(list)
    for i, tk, d, f, o in cur.fetchall():
        db[tk].append((i, d, float(f), o))

    def agrupa_db(tk, d, dias):
        """eventos do banco a +-dias de d, agrupados por data -> {data: (fator_liquido, [ids])}"""
        g = defaultdict(lambda: [1.0, []])
        for i, dd, f, o in db.get(tk, []):
            if abs((dd - d).days) <= dias:
                g[dd][0] *= f; g[dd][1].append(i)
        return {k: (v[0], v[1]) for k, v in g.items()}

    cur.execute('SELECT a.sg_ticker, r.dt_evento, r.vl_fator FROM tb_evento_rejeitado r JOIN tb_ativo a USING (id_ativo) WHERE r.vl_fator > 0')
    rejeitados = defaultdict(list)
    for tk_, dd_, ff_ in cur.fetchall():
        rejeitados[tk_].append((dd_, float(ff_)))

    # ---------------- S2 (opcoes)
    cand = le_csv('/tmp/eventos_opcoes.csv')
    _, ev2 = classifica_candidatos(conn, cand)
    if diario:
        ev2 = []
    s2 = defaultdict(list)
    for raiz, d, R, _tk in ev2:
        if d >= INICIO_S1:
            continue
        lim = MIN_EVENTO if d >= date(2008, 1, 1) else MIN_EVENTO_ANTIGO
        if abs(math.log(R)) >= lim:
            s2[raiz].append((d, snap(R)))

    # ---------------- S1 (oscilacao oficial)
    s1, obs = defaultdict(list), defaultdict(list)     # obs[ticker] = [(d0, d1, tem_evento)]
    pequenos = 0
    for tk, d, p0, p1, osc, Ft, D, Fd, R, evento, _a, d0 in detecta_osc(conn):
        obs[tk].append((d0, d, evento and abs(math.log(R)) >= MIN_EVENTO))
        if evento and abs(math.log(R)) >= MIN_EVENTO:
            if not diario or d >= corte:
                s1[tk].append((d, snap(R)))
        elif evento:
            pequenos += 1
    cur.execute('SELECT max(dt_pregao) FROM tb_negocio_diario')
    fim_s1 = cur.fetchone()[0]

    acoes, ambiguos, usados = [], [], set()      # acao: (tipo, ticker, data_atual, fator_atual, data_nova, fator_novo, fonte, [ids])

    def resolve(tk, d, F, fonte):
        """aplica a politica de um evento exato (d, F) de uma fonte contra o banco"""
        # evento que ja foi investigado e rejeitado (tb_evento_rejeitado) nao volta: sem isso a rotina diaria
        # reinseriria, por exemplo, o ajuste de referencia de uma subscricao que nao e bonificacao
        if any(abs((dd - d).days) <= 3 and abs(math.log(F / ff)) < 0.02 for dd, ff in rejeitados.get(tk, [])):
            return
        g = agrupa_db(tk, d, 3)
        if any(abs(math.log(F / f)) < TOL_FATOR for f, _ in g.values()):
            for dd, (f, ids) in g.items():
                if abs(math.log(F / f)) < TOL_FATOR:
                    usados.update(ids)
                    if dd != d:      # fonte exata (S1/S2) manda na data: o banco tinha o evento certo com 1-3 dias de erro
                        acoes.append(('FIX_DATA', tk, dd, f, d, F, fonte, ids))
            return
        if g:
            ids = [i for f, l in g.values() for i in l]
            f_db = math.prod(f for f, _ in g.values())
            usados.update(ids)
            # so troca quando a fonte e certa o bastante OU o banco esta claramente errado (evento grande)
            if abs(math.log(F)) >= CERTO or abs(math.log(f_db)) >= 0.1:
                dd = min(g, key=lambda x: abs((x - d).days))
                acoes.append(('REPLACE', tk, dd, f_db, d, F, fonte, ids))
            else:
                ambiguos.append((tk, d, F, f'{fonte}: banco tem x{f_db:.4f} em {min(g)}'))
            return
        longe = agrupa_db(tk, d, 25)
        mesmo = [(abs((dd - d).days), dd, f, ids) for dd, (f, ids) in longe.items() if abs(math.log(F / f)) < TOL_FATOR]
        if mesmo:
            _, dd, f, ids = min(mesmo)
            usados.update(ids)
            acoes.append(('FIX_DATA', tk, dd, f, d, F, fonte, ids))
            return
        c = corroborado(cur, tk, d, F)
        if c:
            acoes.append(('ADD', tk, None, None, d, F, f'{fonte} ({c})', []))
        else:
            ambiguos.append((tk, d, F, fonte))

    for tk, evs in s1.items():
        for d, F in evs:
            resolve(tk, d, F, 'S1-oscilacao')
    for raiz, evs in s2.items():
        for d, F in evs:
            for tk in por_raiz.get(raiz, []):
                cur.execute('SELECT 1 FROM tb_cotacao_bruta c JOIN tb_ativo a USING (id_ativo) WHERE a.sg_ticker=%s AND c.dt_cotacao BETWEEN %s AND %s LIMIT 1', (tk, d - timedelta(days=5), d + timedelta(days=5)))
                if cur.fetchone():
                    resolve(tk, d, F, 'S2-opcoes')

    # ---------------- S1: remocao quando o arquivo diario COBRE o dia (par de pregoes atravessa o evento) e nao viu ajuste
    for tk, linhas in db.items():
        if tk not in obs:
            continue
        for i, dd, f, o in linhas:
            if not (INICIO_S1 <= dd <= fim_s1) or i in usados or (diario and dd < corte):
                continue
            liquido = agrupa_db(tk, dd, 0)[dd][0]
            if abs(math.log(liquido)) < GRANDE:
                continue
            cobre = [(d0, d1, ev) for d0, d1, ev in obs[tk] if d0 < dd <= d1]
            if cobre and not any(ev for _, _, ev in cobre) and not any(abs((e - dd).days) <= 3 for e, _ in s1.get(tk, [])):
                ids = agrupa_db(tk, dd, 0)[dd][1]
                acoes.append(('REMOVE', tk, dd, liquido, None, None, 'S1-oscilacao (B3 cobre o dia e nao ajustou)', ids)); usados.update(ids)

    # ---------------- S3: preco bruto desmente / reposiciona eventos grandes
    cur.execute('''SELECT a.sg_ticker, c.dt_cotacao, c.vl_fechamento, c.qt_volume FROM tb_cotacao_ajustada c JOIN tb_ativo a USING (id_ativo)
                   WHERE c.vl_fechamento > 0 ORDER BY 1, 2''')
    serie = defaultdict(list)
    for tk, d, p, v in cur.fetchall():
        serie[tk].append((d, float(p), float(v or 0)))
    for tk, linhas in ({} if diario else db).items():
        s = serie.get(tk)
        if not s:
            continue
        por_data = defaultdict(list)
        for i, dd, f, o in linhas:
            por_data[dd].append((i, f))
        for dd, legs in por_data.items():
            ids = [i for i, _ in legs]
            if all(i in usados for i in ids):
                continue
            F = math.prod(f for _, f in legs)
            if abs(math.log(F)) < GRANDE:
                continue
            ant = [x for x in s if x[0] < dd and (dd - x[0]).days <= 10]
            dep = [x for x in s if x[0] >= dd and (x[0] - dd).days <= 10]
            if not ant or not dep:
                continue
            dev, lnF = math.log(dep[0][1] / ant[-1][1]), math.log(F)
            if not (abs(dev - lnF) < 0.4 * abs(lnF) and abs(dev) >= 0.6 * abs(lnF)):
                continue          # nao e "o preco nao pulou": confirmado, divergente ou ambiguo
            # a serie ajustada pula por F onde nao devia. Procura o salto compensatorio (~1/F) a +-45 dias
            comp, melhor = None, None
            for j in range(1, len(s)):
                d1 = s[j][0]
                if abs((d1 - dd).days) <= 60 and d1 != dd and s[j][2] > 0 and (d1 - s[j - 1][0]).days <= 60:
                    r = s[j][1] / s[j - 1][1]
                    erro = abs(math.log(r * F))          # r ~ 1/F
                    if erro < max(0.1, 0.3 * abs(lnF)) and (melhor is None or erro < melhor):
                        comp, melhor = d1, erro
            if comp and abs(lnF) < 0.4:
                ambiguos.append((tk, dd, F, f'S3: evento do banco sem salto no dia; ha salto parecido em {comp}, pouco pra reposicionar so por preco'))
                usados.update(ids)
            elif comp:
                acoes.append(('FIX_DATA', tk, dd, F, comp, F, 'S3-preco (salto compensatorio)', ids)); usados.update(ids)
            else:
                acoes.append(('REMOVE', tk, dd, F, None, None, 'S3-preco (o preco bruto nao pulou)', ids)); usados.update(ids)

    vistos, finais = set(), []
    for a in acoes:
        k = (a[0], a[1], a[4] or a[2], tuple(a[7]))
        if k not in vistos:
            vistos.add(k); finais.append(a)
    acoes = finais

    with open('/tmp/acoes_eventos.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['acao', 'ticker', 'data_atual', 'fator_atual', 'data_nova', 'fator_novo', 'fonte', 'ids'])
        w.writerows([(a[0], a[1], a[2], a[3], a[4], a[5], a[6], ';'.join(map(str, a[7]))) for a in sorted(acoes, key=lambda a: (a[0], a[1], str(a[4] or a[2])))])
    res = defaultdict(int)
    for a in acoes:
        res[a[0]] += 1
    print(f'S1 ate {fim_s1}; {sum(len(v) for v in s1.values())} eventos no arquivo diario; {len(s2)} raizes com evento nas opcoes; ajustes pequenos ignorados: {pequenos}')
    print('ACOES:', dict(res), '| ambiguos sem 2a evidencia:', len(ambiguos))
    for tipo in ('REPLACE', 'FIX_DATA', 'REMOVE', 'ADD'):
        itens = [a for a in acoes if a[0] == tipo]
        print(f'\n--- {tipo} ({len(itens)}) ---')
        for a in sorted(itens, key=lambda a: (a[1], str(a[4] or a[2])))[:80]:
            print(f'  {a[1]:7} atual {a[2]} x{(a[3] or 0):.4f} -> {a[4] or "-"} x{(a[5] or 0):.4f}  [{a[6]}]')
    print(f'\n--- AMBIGUOS ({len(ambiguos)}) ---')
    for tk, d, F, f in sorted(ambiguos, key=lambda x: (x[1], x[0]))[:50]:
        print(f'  {tk:7} {d} x{F:.4f} [{f}]')

    if aplica:
        cur.execute('CREATE SCHEMA IF NOT EXISTS bkp_eventos')
        bkp = f'tb_evento_corporativo_pre_diario_{date.today():%Y%m%d}' if diario else 'tb_evento_corporativo_pre_recon'
        cur.execute(f'DROP TABLE IF EXISTS bkp_eventos.{bkp}')
        cur.execute(f'CREATE TABLE bkp_eventos.{bkp} AS SELECT * FROM public.tb_evento_corporativo')
        n = defaultdict(int)
        for acao, tk, d0, f0, d1, f1, fonte, ids in acoes:
            origem = 'B3-OSC' if fonte.startswith('S1') else 'B3-OPCOES' if fonte.startswith('S2') else 'B3-PRECO'
            if acao in ('REMOVE', 'REPLACE'):
                for i in ids:
                    cur.execute('SELECT dt_evento, vl_fator, ds_origem FROM tb_evento_corporativo WHERE id_evento_corporativo=%s', (i,))
                    r = cur.fetchone()
                    if r:
                        cur.execute('INSERT INTO tb_evento_rejeitado (id_ativo, dt_evento, vl_fator, ds_origem, ds_motivo) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                                    (ativos[tk], r[0], r[1], r[2], f'{acao} por {fonte}'))
                        cur.execute('DELETE FROM tb_evento_corporativo WHERE id_evento_corporativo=%s', (i,))
            if acao == 'FIX_DATA':
                for i in ids:
                    cur.execute('UPDATE tb_evento_corporativo SET dt_evento=%s, ds_origem=%s, dh_atualizacao=now() WHERE id_evento_corporativo=%s', (d1, origem, i))
            if acao in ('ADD', 'REPLACE'):
                cur.execute('INSERT INTO tb_evento_corporativo (id_ativo, id_tipo_operacao, dt_evento, vl_fator, ds_origem) VALUES (%s,%s,%s,%s,%s) '
                            'ON CONFLICT (id_ativo, id_tipo_operacao, dt_evento) DO UPDATE SET vl_fator=EXCLUDED.vl_fator, ds_origem=EXCLUDED.ds_origem, dh_atualizacao=now()',
                            (ativos[tk], tipo_id[tipo_de(f1)], d1, f1, origem))
            n[acao] += 1
        conn.commit()
        print('\nAPLICADO:', dict(n))
        print('rodar agora: SELECT fn_rebuild_tudo();   (regera tb_cotacao_ajustada com os eventos novos)')
    conn.close()


if __name__ == '__main__':
    main()
