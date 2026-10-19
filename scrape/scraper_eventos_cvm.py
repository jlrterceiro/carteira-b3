"""
Eventos corporativos a partir dos avisos/atas da CVM (IPE) -- a unica fonte OFICIAL que cobre desde 2003 o que a
API de eventos da B3 deixa de fora (Bradesco 2004-2021, Itau 2011...). Reusa o extrator do protótipo
(`prototipo_eventos_cvm.py`): o aviso dá o fator e o dia ex, o preço bruto do COTAHIST confirma.

Escopo conservador de proposito -- este scraper NUNCA mexe em evento de origem B3 / B3-OSC / B3-OPCOES / B3-PRECO
(essas fontes ja sao exatas ou foram verificadas contra o preço). So age sobre o que veio do yfinance
(`ds_origem='yfinance'`, sem scraper pra renovar) e sobre o que falta:

  CONFIRMA  evento do yfinance que o aviso confirma (mesmo fator, a até 10 dias)  -> ds_origem vira 'CVM'
            (e a data vai pra data oficial, se for diferente e nao colidir)
  REPLACE   evento do yfinance com OUTRO fator que o aviso + preço desmentem       -> troca (o antigo vai pra tb_evento_rejeitado)
  ADD       aviso + preço mostram um evento que nao existe no banco                -> insere com ds_origem='CVM'
  REVISAR   o resto (aviso e banco divergem sem prova suficiente) -- so aparece no relatório

Confiança exigida pra CRIAR/TROCAR evento: 'OFICIAL+PRECO' / 'FATOR-CVM+PRECO' (aviso e salto de preço concordam).
Pra CONFIRMAR um evento que ja existe basta o fator do aviso bater (|ln F| <= 0,25 sem salto de preço verificavel),
mas a DATA do banco nunca é trocada pela do texto: a data extraída do PDF erra de 2 a 4 dias (BBDC4 2013: texto
diz 28/3, opções e preço dizem 26/3).

CARGA ÚNICA DO PASSADO (decisão do usuário, 2026-10-18): este scraper lê PDFs/anexos e serve só pra melhorar o
histórico. A rotina DIÁRIA daqui pra frente usa apenas dados estruturados (arquivo diário da B3 com OscnPctg,
ajuste de strike das opções, API de eventos da B3) -- nada de PDF.

    python3 scrape/scraper_eventos_cvm.py [TICKER ...]             # relatorio (le PDFs/anexos, cache em scrape/cvm_cache/)
    python3 scrape/scraper_eventos_cvm.py [TICKER ...] --aplica    # grava (depois: SELECT fn_rebuild_tudo())
    python3 scrape/scraper_eventos_cvm.py --so-yfinance            # so ativos que ainda tem evento do yfinance
Depois de --aplica sem ticker rodar SELECT fn_rebuild_tudo() e backend/tests/test_validacoes.sql.
"""
import contextlib
import csv
import io
import math
import os
import sys
import traceback
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn
import prototipo_eventos_cvm as proto

ORIGENS_PROTEGIDAS = ('B3', 'B3-OSC', 'B3-OPCOES', 'B3-PRECO', 'CVM')
FORTES = ('OFICIAL+PRECO', 'FATOR-CVM+PRECO')
CERTO_SEM_PRECO = 0.25     # |ln F| ate o qual o texto oficial (dia ex explicito) basta sozinho


def tipo_de(F):
    return 'GRUP' if F < 1 else ('SPLIT' if F >= 2 and abs(F - round(F)) < 1e-6 else 'BONIF')


def aceita(conf, F):
    """pra CRIAR/TROCAR evento: so com aviso e salto de preco concordando. A data tirada do TEXTO do aviso erra
    de 2 a 4 dias (BBDC4 2013: texto 28/3, opcoes e preco 26/3), entao 'OFICIAL' sozinho nunca basta."""
    return conf in FORTES


def decide(cur, id_ativo, data_ev, F, conf):
    """-> (acao, detalhe, ids). acao em CONFIRMA | REPLACE | ADD | OK | REVISAR"""
    cur.execute('''SELECT id_evento_corporativo, dt_evento, vl_fator, ds_origem FROM tb_evento_corporativo
                   WHERE id_ativo = %s AND dt_evento BETWEEN %s AND %s ORDER BY dt_evento''',
                (id_ativo, data_ev - proto.timedelta(days=10), data_ev + proto.timedelta(days=10)))
    near = [(i, d, float(f), o) for i, d, f, o in cur.fetchall()]
    mesmo = [x for x in near if abs(math.log(x[2] / F)) < 0.05]
    if mesmo:
        yf = [x for x in mesmo if x[3] not in ORIGENS_PROTEGIDAS]
        if yf and (aceita(conf, F) or conf.startswith('OFICIAL') and abs(math.log(F)) <= CERTO_SEM_PRECO):
            return 'CONFIRMA', f'{yf[0][1]} x{yf[0][2]:g}', [x[0] for x in yf]
        return 'OK', f'{mesmo[0][1]} x{mesmo[0][2]:g} ({mesmo[0][3]})', []
    if near:
        yf = [x for x in near if x[3] not in ORIGENS_PROTEGIDAS]
        if yf and len(yf) == len(near) and conf in FORTES:
            return 'REPLACE', ' & '.join(f'{x[1]} x{x[2]:g}' for x in yf), [x[0] for x in yf]
        return 'REVISAR', 'banco tem ' + ' & '.join(f'{x[1]} x{x[2]:g} ({x[3]})' for x in near), []
    if aceita(conf, F):
        return 'ADD', '', []
    return 'REVISAR', f'aviso sugere x{F:g} em {data_ev} ({conf}) sem prova suficiente', []


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    aplica, so_yf, verboso = '--aplica' in sys.argv, '--so-yfinance' in sys.argv, '--verbose' in sys.argv
    conn = get_conn(); cur = conn.cursor()
    if args:
        cur.execute('SELECT sg_ticker, id_ativo FROM tb_ativo WHERE sg_ticker = ANY(%s) ORDER BY 1', (args,))
    else:
        cur.execute('''SELECT a.sg_ticker, a.id_ativo FROM tb_ativo a JOIN tb_emissor e USING (id_emissor)
                       WHERE e.nr_cnpj IS NOT NULL AND e.nr_cnpj <> 'None'
                         AND EXISTS (SELECT 1 FROM tb_cotacao_bruta c WHERE c.id_ativo = a.id_ativo)
                         AND (NOT %s OR EXISTS (SELECT 1 FROM tb_evento_corporativo v WHERE v.id_ativo = a.id_ativo AND v.ds_origem = 'yfinance'))
                       ORDER BY 1''', (so_yf,))
    ativos = cur.fetchall()
    cur.execute('SELECT id_tipo_operacao, sg_tipo_operacao FROM tb_tipo_operacao')
    tipo_id = {sg: i for i, sg in cur.fetchall()}
    print(f'{len(ativos)} ativos; {"APLICANDO" if aplica else "so relatorio"}')

    linhas, contagem, alterados, falhas = [], defaultdict(int), set(), []
    for n, (tk, id_ativo) in enumerate(ativos, 1):
        try:
            with contextlib.redirect_stdout(io.StringIO() if not verboso else sys.stdout):
                achados = proto.analisa(conn, tk, True)
        except Exception as e:
            falhas.append((tk, repr(e))); conn.rollback()
            if verboso:
                traceback.print_exc()
            continue
        for ep, ts, pernas, fonte, data_ev, F, conf, status in achados:
            if not data_ev or not F or conf in (None, 'NEUTRO', 'REVISAR', 'INFERIDO(preco)'):
                continue
            acao, det, ids = decide(cur, id_ativo, data_ev, F, conf)
            contagem[acao] += 1
            linhas.append((tk, acao, data_ev, F, conf, det))
            if not aplica or acao in ('OK', 'REVISAR'):
                continue
            if acao in ('CONFIRMA', 'REPLACE'):
                for i in ids:
                    cur.execute('SELECT dt_evento, vl_fator, ds_origem FROM tb_evento_corporativo WHERE id_evento_corporativo = %s', (i,))
                    d0, f0, o0 = cur.fetchone()
                    if acao == 'REPLACE':
                        cur.execute('''INSERT INTO tb_evento_rejeitado (id_ativo, dt_evento, vl_fator, ds_origem, ds_motivo)
                                       VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                                    (id_ativo, d0, f0, o0, f'REPLACE por aviso CVM ({conf})'))
                        cur.execute('DELETE FROM tb_evento_corporativo WHERE id_evento_corporativo = %s', (i,))
                    else:
                        # confirma fator e existencia do evento; a DATA do banco fica como esta (a do texto erra dias)
                        cur.execute('UPDATE tb_evento_corporativo SET ds_origem = %s, dh_atualizacao = now() '
                                    'WHERE id_evento_corporativo = %s', ('CVM', i))
            if acao in ('ADD', 'REPLACE'):
                cur.execute('''INSERT INTO tb_evento_corporativo (id_ativo, id_tipo_operacao, dt_evento, vl_fator, ds_origem)
                               VALUES (%s,%s,%s,%s,'CVM')
                               ON CONFLICT (id_ativo, id_tipo_operacao, dt_evento)
                               DO UPDATE SET vl_fator = EXCLUDED.vl_fator, ds_origem = 'CVM', dh_atualizacao = now()''',
                            (id_ativo, tipo_id[tipo_de(F)], data_ev, round(F, 12)))
            alterados.add(tk)
        if aplica:
            conn.commit()
        if n % 25 == 0:
            print(f'  {n}/{len(ativos)}...', flush=True)

    with open('/tmp/eventos_cvm.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['ticker', 'acao', 'data', 'fator', 'confianca', 'detalhe']); w.writerows(linhas)
    print('\nRESUMO:', dict(contagem), '| falhas:', len(falhas))
    for acao in ('ADD', 'REPLACE', 'CONFIRMA', 'REVISAR'):
        itens = [l for l in linhas if l[1] == acao]
        print(f'\n--- {acao} ({len(itens)}) ---')
        for tk, _, d, F, conf, det in itens[:60]:
            print(f'  {tk:7} {d} x{F:<10.6g} {conf:<22} {det}')
    for tk, e in falhas[:10]:
        print('FALHA', tk, e)
    if aplica and alterados:
        print(f'\n{len(alterados)} ativos alterados; rodar agora: SELECT fn_rebuild_tudo();')
    conn.close()


if __name__ == '__main__':
    main()
