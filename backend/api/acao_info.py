"""
Pagina de uma acao: cadastro, cotacao, indicadores fundamentalistas, rentabilidade contra Ibovespa e CDI, proventos, resultados (DRE/balanco/fluxo
de caixa da CVM), eventos corporativos e resumo de insiders. Tudo calculado so com o que ha no nosso banco (COTAHIST, B3, CVM); sem fonte externa.

Convencoes dos indicadores (ficam nas explicacoes da tela):
  - valor de mercado = fn_valor_mercado_em (acoes da CVM x preco por classe); TTM = soma dos 4 ultimos trimestres CONSECUTIVOS da DRE;
  - lucro = "atribuido aos controladores" (P/L, LPA, ROE) e consolidado (margem liquida, ROA); EBIT = resultado antes do resultado financeiro e dos tributos;
  - EV/EBITDA e margem EBITDA nao existem: a depreciacao nao esta na curadoria da CVM (so EBIT).
Rotas fixas (/logos, /busca) estao em acoes.py, registrado antes deste modulo.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from deps import get_current_user, get_db

router = APIRouter(prefix='/acoes', tags=['acao'])

ALIQUOTA_NOPAT = 0.34          # IRPJ + CSLL, pra ROIC (aproximacao, igual a de outros sites)
PERIODOS_COTACAO = {'1m': 31, '6m': 183, '1a': 366, '5a': 1827, '10a': 3653, 'max': None}
MAX_PONTOS = 1200


def _f(v):
    return None if v is None else float(v)


def _div(a, b, minimo=None):
    """a / b, ou None se faltar dado / divisor zero; `minimo`: so devolve se b > minimo (ex.: lucro positivo pra P/L)"""
    if a is None or b is None or b == 0:
        return None
    if minimo is not None and b <= minimo:
        return None
    return a / b


def _ativo(cur, ticker):
    cur.execute(
        '''SELECT a.id_ativo, a.id_emissor, a.sg_ticker, a.sg_classe, a.nm_ativo, a.dt_inicio_negociacao, a.dt_fim_negociacao, COALESCE(a.fl_ativo, true),
                  e.nm_emissor, e.sg_emissor, e.nr_cnpj, e.ds_site, e.info
           FROM public.tb_ativo a LEFT JOIN public.tb_emissor e USING (id_emissor) WHERE a.sg_ticker = %s''', (ticker.upper(),))
    r = cur.fetchone()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'ticker desconhecido')
    return dict(zip(('id_ativo', 'id_emissor', 'ticker', 'classe', 'nome_ativo', 'dt_inicio', 'dt_fim', 'ativo', 'emissor', 'sg_emissor', 'cnpj', 'site', 'info'), r))


def _preco_em(cur, id_ativo, dt, campo='vl_fechamento'):
    """ultimo fechamento <= dt (coluna de tb_cotacao_ajustada) e a data dele"""
    cur.execute(f'SELECT {campo}, dt_cotacao FROM public.tb_cotacao_ajustada WHERE id_ativo = %s AND dt_cotacao <= %s ORDER BY dt_cotacao DESC LIMIT 1', (id_ativo, dt))
    r = cur.fetchone()
    return (_f(r[0]), r[1]) if r else (None, None)


def _ttm(linhas, campos):
    """soma de 4 trimestres consecutivos (os mais recentes); None se faltar trimestre. `linhas` em ordem decrescente de data."""
    if len(linhas) < 4:
        return None
    for a, b in zip(linhas[:3], linhas[1:4]):
        if not 80 <= (a['dt'] - b['dt']).days <= 100:
            return None
    out = {}
    for c in campos:
        vs = [l[c] for l in linhas[:4]]
        out[c] = None if any(v is None for v in vs) else sum(vs)
    return out


def _retornos(cur, id_ativo, ultima):
    """retorno total (com proventos) da acao no periodo, contra Ibovespa (so de 2018 em diante) e CDI, ate o ultimo pregao"""
    cur.execute('SELECT vl_nivel FROM public.tb_benchmark_diario WHERE cd_benchmark = %s AND dt_dia <= %s ORDER BY dt_dia DESC LIMIT 1', ('IBOV', ultima))
    r = cur.fetchone()
    ibov_fim = _f(r[0]) if r else None
    fim_aj, _ = _preco_em(cur, id_ativo, ultima, 'vl_fechamento_ajustado')
    pedidos = [('1 mês', ultima - timedelta(days=31)), ('3 meses', ultima - timedelta(days=92)), ('6 meses', ultima - timedelta(days=183)),
               ('No ano', date(ultima.year - 1, 12, 31)), ('12 meses', ultima - timedelta(days=366)), ('2 anos', ultima - timedelta(days=731)),
               ('5 anos', ultima - timedelta(days=1827)), ('10 anos', ultima - timedelta(days=3653))]
    cur.execute('SELECT min(dt_cotacao) FROM public.tb_cotacao_ajustada WHERE id_ativo = %s', (id_ativo,))
    primeira = cur.fetchone()[0]
    cur.execute('SELECT min(dt_dia) FROM public.tb_benchmark_diario WHERE cd_benchmark = %s', ('IBOV',))
    primeira_ibov = cur.fetchone()[0]
    saida = []
    for rotulo, d0 in pedidos:
        acao = ibov = cdi = None
        if primeira and primeira <= d0 and fim_aj:
            p0, _ = _preco_em(cur, id_ativo, d0, 'vl_fechamento_ajustado')
            acao = (fim_aj / p0 - 1) * 100 if p0 else None
        if primeira_ibov and primeira_ibov <= d0 and ibov_fim:
            cur.execute('SELECT vl_nivel FROM public.tb_benchmark_diario WHERE cd_benchmark = %s AND dt_dia <= %s ORDER BY dt_dia DESC LIMIT 1', ('IBOV', d0))
            r = cur.fetchone()
            ibov = (ibov_fim / float(r[0]) - 1) * 100 if r and r[0] else None
            cur.execute('SELECT exp(sum(ln(1 + vl_retorno_pct / 100))) FROM public.tb_benchmark_diario WHERE cd_benchmark = %s AND dt_dia > %s AND dt_dia <= %s',
                        ('CDI', d0, ultima))
            r = cur.fetchone()
            cdi = (float(r[0]) - 1) * 100 if r and r[0] else None
        saida.append({'periodo': rotulo, 'acao': acao, 'ibov': ibov, 'cdi': cdi})
    return saida


def _indicadores(vm, preco, acoes, dy, ttm, bal, anuais):
    """grupos de indicadores; valor None quando falta dado ou nao se aplica (ex.: P/L com prejuizo, EBIT de banco)"""
    rec = ttm['vl_receita_total'] if ttm else None
    bruto = ttm['vl_lucro_bruto'] if ttm else None
    ebit = ttm['vl_resultado_operacional'] if ttm else None
    ll = ttm['vl_lucro_liquido'] if ttm else None
    llt = ttm['vl_lucro_liquido_total'] if ttm else None
    b = bal or {}
    # banco: o plano de contas nao tem circulante/nao circulante, "divida" inclui depositos e o EBIT nao existe; esses indicadores nao se aplicam
    financeira = bal is not None and bal.get('ativo_circ') is None
    if financeira:
        ebit = bruto = None
        b = {**b, 'div_liquida': None, 'div_total': None, 'cap_giro': None}
    pl, pl_total, ativo, passivo = b.get('pl'), b.get('pl_total'), b.get('ativo'), b.get('passivo')
    div_liq, div_bruta, caixa, cg = b.get('div_liquida'), b.get('div_total'), b.get('caixa'), b.get('cap_giro')
    ac, pc = b.get('ativo_circ'), b.get('passivo_circ')
    ev = None if vm is None or div_liq is None else vm + div_liq
    capital = None if pl_total is None or div_liq is None else pl_total + div_liq
    ativo_circ_liq = None if ac is None or passivo is None else ac - passivo
    def _cagr(campo):
        v = [(a['dt'], a[campo]) for a in anuais if a[campo] is not None]
        if len(v) < 2:
            return None
        fim, ini = v[0], v[min(5, len(v) - 1)]
        anos = round((fim[0] - ini[0]).days / 365.25)
        if anos < 1 or ini[1] <= 0 or fim[1] <= 0:
            return None
        return ((fim[1] / ini[1]) ** (1 / anos) - 1) * 100
    G = lambda nome, itens: {'grupo': nome, 'itens': [dict(zip(('chave', 'rotulo', 'valor', 'tipo', 'dica'), i)) for i in itens]}
    pct = lambda v: None if v is None else v * 100
    grupos = [
        G('Valuation', [
            ('dy', 'Dividend yield', pct(dy), 'pct', 'Proventos por ação pagos nos últimos 12 meses (valor bruto, ajustado por desdobramentos) ÷ preço atual.'),
            ('pl', 'P/L', _div(vm, ll, 0), 'x', 'Valor de mercado ÷ lucro líquido dos últimos 4 trimestres (atribuído aos controladores). Vazio com prejuízo.'),
            ('pvp', 'P/VP', _div(vm, pl, 0), 'x', 'Valor de mercado ÷ patrimônio líquido (atribuído aos controladores) do último balanço.'),
            ('psr', 'P/Receita (PSR)', _div(vm, rec, 0), 'x', 'Valor de mercado ÷ receita dos últimos 4 trimestres.'),
            ('ev_ebit', 'EV/EBIT', _div(ev, ebit, 0), 'x', 'Valor da firma (valor de mercado + dívida líquida) ÷ EBIT dos últimos 4 trimestres. Não se aplica a bancos.'),
            ('p_ebit', 'P/EBIT', _div(vm, ebit, 0), 'x', 'Valor de mercado ÷ EBIT dos últimos 4 trimestres.'),
            ('p_ativo', 'P/Ativo', _div(vm, ativo, 0), 'x', 'Valor de mercado ÷ ativo total.'),
            ('p_cap_giro', 'P/Capital de giro', _div(vm, cg), 'x', 'Valor de mercado ÷ capital de giro (ativo circulante − passivo circulante). Pode ser negativo.'),
            ('p_acl', 'P/Ativo circ. líquido', _div(vm, ativo_circ_liq), 'x', 'Valor de mercado ÷ (ativo circulante − passivo total): o NCAV de Graham. Negativo quando o passivo supera o ativo circulante.'),
            ('lpa', 'LPA', _div(ll, acoes), 'brl', 'Lucro líquido dos últimos 4 trimestres ÷ ações em circulação.'),
            ('vpa', 'VPA', _div(pl, acoes), 'brl', 'Patrimônio líquido ÷ ações em circulação.'),
        ]),
        G('Endividamento', [
            ('dl_pl', 'Dív. líquida/PL', _div(div_liq, pl, 0), 'x', 'Dívida líquida (empréstimos e arrendamentos − caixa e aplicações) ÷ patrimônio líquido. Não se aplica a bancos.'),
            ('dl_ebit', 'Dív. líquida/EBIT', _div(div_liq, ebit, 0), 'x', 'Dívida líquida ÷ EBIT dos últimos 4 trimestres.'),
            ('db_pl', 'Dív. bruta/PL', _div(div_bruta, pl, 0), 'x', 'Dívida bruta ÷ patrimônio líquido.'),
            ('pl_ativo', 'PL/Ativos', _div(pl_total, ativo, 0), 'x', 'Patrimônio líquido ÷ ativo total.'),
            ('passivo_ativo', 'Passivos/Ativos', _div(passivo, ativo, 0), 'x', 'Passivo exigível (sem patrimônio líquido) ÷ ativo total.'),
            ('liq_corrente', 'Liquidez corrente', _div(ac, pc, 0), 'x', 'Ativo circulante ÷ passivo circulante. Não se aplica a bancos.'),
        ]),
        G('Eficiência', [
            ('m_bruta', 'Margem bruta', pct(_div(bruto, rec, 0)), 'pct', 'Lucro bruto ÷ receita, últimos 4 trimestres.'),
            ('m_ebit', 'Margem EBIT', pct(_div(ebit, rec, 0)), 'pct', 'EBIT ÷ receita, últimos 4 trimestres.'),
            ('m_liquida', 'Margem líquida', pct(_div(llt, rec, 0)), 'pct', 'Lucro líquido consolidado ÷ receita, últimos 4 trimestres.'),
            ('giro', 'Giro do ativo', _div(rec, ativo, 0), 'x', 'Receita dos últimos 4 trimestres ÷ ativo total.'),
        ]),
        G('Rentabilidade', [
            ('roe', 'ROE', pct(_div(ll, pl, 0)), 'pct', 'Lucro líquido (controladores) dos últimos 4 trimestres ÷ patrimônio líquido do último balanço.'),
            ('roa', 'ROA', pct(_div(llt, ativo, 0)), 'pct', 'Lucro líquido consolidado dos últimos 4 trimestres ÷ ativo total.'),
            ('roic', 'ROIC', pct(_div(None if ebit is None else ebit * (1 - ALIQUOTA_NOPAT), capital, 0)), 'pct',
             'EBIT × (1 − 34%) ÷ (patrimônio líquido + dívida líquida). Aproximação: a alíquota é fixa. Não se aplica a bancos.'),
        ]),
        G('Crescimento', [
            ('cagr_rec', 'CAGR receitas (5 anos)', _cagr('receita'), 'pct', 'Crescimento anual composto da receita anual, do último ano fechado até 5 anos antes (ou o que houver).'),
            ('cagr_lucro', 'CAGR lucros (5 anos)', _cagr('lucro'), 'pct', 'Idem, para o lucro líquido anual (vazio se algum dos extremos for prejuízo).'),
        ]),
    ]
    return grupos, financeira


@router.get('/{ticker}')
def resumo(ticker: str, usuario=Depends(get_current_user), conn=Depends(get_db)):
    with conn.cursor() as cur:
        a = _ativo(cur, ticker)
        ida, ide = a['id_ativo'], a['id_emissor']

        cur.execute('SELECT sg_ticker, sg_classe, COALESCE(fl_ativo, true) FROM public.tb_ativo WHERE id_emissor = %s ORDER BY sg_classe, sg_ticker', (ide,))
        irmaos = [{'ticker': r[0], 'classe': r[1], 'ativo': r[2]} for r in cur.fetchall()]

        # cotacao
        cur.execute('SELECT vl_preco_atual, vl_preco_anterior, dt_cotacao, ds_fonte FROM public.vw_cotacao_atual WHERE id_ativo = %s', (ida,))
        c = cur.fetchone()
        preco = preco_ant = ultima = fonte = None
        if c:
            preco, preco_ant, ultima, fonte = _f(c[0]), _f(c[1]), c[2], c[3]
        cotacao = {'preco': preco, 'anterior': preco_ant, 'data': ultima.isoformat() if ultima else None, 'fonte': fonte,
                   'variacao_dia': (preco / preco_ant - 1) * 100 if preco and preco_ant else None}

        faixas = {}
        if ultima:
            for nome, ini in (('52 semanas', ultima - timedelta(days=364)), ('mês', date(ultima.year, ultima.month, 1))):
                cur.execute('''SELECT min(COALESCE(vl_minima, vl_fechamento)), max(COALESCE(vl_maxima, vl_fechamento))
                               FROM public.tb_cotacao_ajustada WHERE id_ativo = %s AND dt_cotacao >= %s''', (ida, ini))
                r = cur.fetchone()
                faixas[nome] = {'min': _f(r[0]), 'max': _f(r[1])}
            p12, _ = _preco_em(cur, ida, ultima - timedelta(days=366))
            pmes, _ = _preco_em(cur, ida, date(ultima.year, ultima.month, 1) - timedelta(days=1))
            pano, _ = _preco_em(cur, ida, date(ultima.year - 1, 12, 31))
            cotacao['valorizacao'] = {'12 meses': (preco / p12 - 1) * 100 if p12 and preco else None,
                                      'mês': (preco / pmes - 1) * 100 if pmes and preco else None,
                                      'ano': (preco / pano - 1) * 100 if pano and preco else None}

        # valor de mercado e acoes
        vm = acoes = None
        if ultima and ide:
            cur.execute('SELECT acoes, mercado FROM public.fn_valor_mercado_em(%s, %s)', (ide, ultima))
            r = cur.fetchone()
            if r:
                acoes, vm = _f(r[0]), _f(r[1])
        cur.execute('SELECT dt_referencia, qt_total, qt_ordinaria, qt_preferencial, qt_tesouraria FROM public.tb_acoes_emissor WHERE id_emissor = %s ORDER BY dt_referencia DESC LIMIT 1', (ide,))
        r = cur.fetchone()
        capital = None if not r else {'data': r[0].isoformat(), 'total': _f(r[1]), 'ordinarias': _f(r[2]), 'preferenciais': _f(r[3]), 'tesouraria': _f(r[4])}

        # dividendos 12 meses (base de hoje: valor bruto ÷ fator dos eventos posteriores)
        dy = prov12 = None
        if ultima:
            cur.execute('''SELECT COALESCE(sum(p.vl_unitario / public.fn_fator_acumulado(p.id_ativo, p.dt_ex)), 0), count(*)
                           FROM public.tb_provento p WHERE p.id_ativo = %s AND p.dt_ex > %s AND p.dt_ex <= %s''', (ida, ultima - timedelta(days=365), ultima))
            r = cur.fetchone()
            prov12 = _f(r[0]) if r and r[1] else 0.0
            dy = prov12 / preco if preco else None

        # demonstracoes
        cur.execute('''SELECT dt_referencia, vl_receita_total, vl_lucro_bruto, vl_resultado_operacional, vl_lucro_liquido, vl_lucro_liquido_total, vl_lpa_basico
                       FROM public.tb_dre WHERE id_ativo = %s AND tp_periodo = 'TRIMESTRAL' ORDER BY dt_referencia DESC LIMIT 8''', (ida,))
        campos = ('dt', 'vl_receita_total', 'vl_lucro_bruto', 'vl_resultado_operacional', 'vl_lucro_liquido', 'vl_lucro_liquido_total', 'vl_lpa_basico')
        tri = [dict(zip(campos, (r[0],) + tuple(_f(x) for x in r[1:]))) for r in cur.fetchall()]
        ttm = _ttm(tri, campos[1:])
        cur.execute('''SELECT dt_referencia, vl_receita_total, vl_lucro_liquido FROM public.tb_dre WHERE id_ativo = %s AND tp_periodo = 'ANUAL'
                       ORDER BY dt_referencia DESC LIMIT 7''', (ida,))
        anuais = [{'dt': r[0], 'receita': _f(r[1]), 'lucro': _f(r[2])} for r in cur.fetchall()]
        cur.execute('''SELECT dt_referencia, vl_ativo_total, vl_ativo_circulante, vl_passivo_total, vl_passivo_circulante, vl_patrimonio_liquido_total,
                              vl_patrimonio_liquido, vl_divida_total, vl_divida_liquida, vl_caixa, vl_capital_giro
                       FROM public.tb_balanco_patrimonial WHERE id_ativo = %s AND tp_periodo = 'TRIMESTRAL' ORDER BY dt_referencia DESC LIMIT 1''', (ida,))
        r = cur.fetchone()
        bal = None
        if r:
            bal = dict(zip(('dt', 'ativo', 'ativo_circ', 'passivo', 'passivo_circ', 'pl_total', 'pl', 'div_total', 'div_liquida', 'caixa', 'cap_giro'),
                           (r[0],) + tuple(_f(x) for x in r[1:])))
        indicadores, financeira = _indicadores(vm, preco, acoes, dy, ttm, bal, anuais)

        retornos = _retornos(cur, ida, ultima) if ultima else []
        cur.execute('SELECT min(dt_cotacao) FROM public.tb_cotacao_ajustada WHERE id_ativo = %s', (ida,))
        primeira_cotacao = cur.fetchone()[0]

        # insiders 12 meses (compra e venda a vista de acoes/units, sem dado suspeito)
        insiders = None
        if ide and ultima:
            ini = date(ultima.year - 1, ultima.month, 1)
            cur.execute('''SELECT COALESCE(sum(vl_volume) FILTER (WHERE tipo_movimentacao = 'Compra à vista'), 0),
                                  COALESCE(sum(vl_volume) FILTER (WHERE tipo_movimentacao = 'Venda à vista'), 0),
                                  count(*) FILTER (WHERE vl_volume > 0), max(dt_movimentacao) FILTER (WHERE vl_volume > 0), count(*) FILTER (WHERE COALESCE(vl_volume, 0) = 0)
                           FROM public.tb_insider_movimentacao
                           WHERE id_emissor = %s AND dt_referencia >= %s AND tipo_ativo IN ('Ações', 'Units')
                             AND tipo_movimentacao IN ('Compra à vista', 'Venda à vista') AND NOT COALESCE(fl_suspeito, false)''', (ide, ini))
            r = cur.fetchone()
            insiders = {'compras': _f(r[0]), 'vendas': _f(r[1]), 'operacoes': r[2], 'ultima': r[3].isoformat() if r[3] else None, 'sem_valor': r[4]}

        # eventos corporativos
        cur.execute('SELECT dt_evento, vl_fator FROM public.tb_evento_corporativo WHERE id_ativo = %s ORDER BY dt_evento DESC', (ida,))
        eventos = [{'data': r[0].isoformat(), 'fator': _f(r[1])} for r in cur.fetchall()]

    info = a['info'] or {}
    partes = [p.strip() for p in (info.get('setor') or '').split('/') if p.strip()]
    return {
        'ticker': a['ticker'], 'classe': a['classe'], 'nome': a['emissor'] or a['nome_ativo'], 'nome_ativo': a['nome_ativo'],
        'cadastro': {'emissor': a['sg_emissor'], 'cnpj': a['cnpj'], 'site': a['site'], 'ativo': a['ativo'],
                     'inicio_negociacao': a['dt_inicio'].isoformat() if a['dt_inicio'] else None,
                     'primeira_cotacao': primeira_cotacao.isoformat() if primeira_cotacao else None,
                     'fim_negociacao': a['dt_fim'].isoformat() if a['dt_fim'] else None,
                     'setor': partes[0] if partes else None, 'subsetor': partes[1] if len(partes) > 1 else None, 'segmento': partes[2] if len(partes) > 2 else None},
        'irmaos': irmaos, 'cotacao': cotacao, 'faixas': faixas, 'valor_mercado': vm, 'acoes': acoes, 'capital': capital,
        'proventos_12m': prov12, 'dividend_yield': dy * 100 if dy is not None else None,
        'indicadores': indicadores, 'financeira': financeira, 'retornos': retornos, 'insiders': insiders, 'eventos': eventos,
        'demonstracoes': {'ultimo_trimestre': tri[0]['dt'].isoformat() if tri else None, 'ultimo_balanco': bal['dt'].isoformat() if bal else None,
                          'ttm_completo': ttm is not None},
    }


@router.get('/{ticker}/cotacoes')
def cotacoes(ticker: str, periodo: str = '1a', serie: str = 'ajustada', usuario=Depends(get_current_user), conn=Depends(get_db)):
    """Serie de fechamentos pra o grafico. serie: ajustada (ajustada por desdobramentos/bonificacoes, a padrao) | nominal (o preco real de cada dia) |
    total (retorno total: alem dos eventos, desconta os proventos). Ate ~1.200 pontos (series longas sao decimadas, mantendo o ultimo)."""
    if periodo not in PERIODOS_COTACAO or serie not in ('ajustada', 'nominal', 'total'):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f'periodo: {", ".join(PERIODOS_COTACAO)}; serie: ajustada|nominal|total')
    campo = {'ajustada': 'vl_fechamento', 'nominal': 'vl_fechamento_nominal', 'total': 'vl_fechamento_ajustado'}[serie]
    dias = PERIODOS_COTACAO[periodo]
    with conn.cursor() as cur:
        a = _ativo(cur, ticker)
        cur.execute(
            f'''SELECT dt_cotacao, {campo} FROM public.tb_cotacao_ajustada
                WHERE id_ativo = %s AND {campo} IS NOT NULL AND (%s::int IS NULL OR dt_cotacao >= (SELECT max(dt_cotacao) FROM public.tb_cotacao_ajustada WHERE id_ativo = %s) - %s::int)
                ORDER BY dt_cotacao''', (a['id_ativo'], dias, a['id_ativo'], dias or 0))
        linhas = [(r[0].isoformat(), float(r[1])) for r in cur.fetchall()]
    passo = max(1, -(-len(linhas) // MAX_PONTOS))
    if passo > 1:
        ult = linhas[-1]
        linhas = linhas[::passo]
        if linhas[-1] != ult:
            linhas.append(ult)
    return {'ticker': a['ticker'], 'periodo': periodo, 'serie': serie, 'pontos': [{'x': x, 'y': y} for x, y in linhas]}


@router.get('/{ticker}/proventos')
def proventos(ticker: str, usuario=Depends(get_current_user), conn=Depends(get_db)):
    """Todos os proventos da acao (valor por acao da epoca), com data-com e de pagamento (real ou estimada), total por ano na base de hoje
    (valor ÷ fator dos eventos posteriores) e payout por ano = proventos do ano ÷ LPA do ano (os dois na base da epoca)."""
    with conn.cursor() as cur:
        a = _ativo(cur, ticker)
        ida = a['id_ativo']
        cur.execute(
            '''SELECT p.dt_ex, p.ds_tipo_provento, p.vl_unitario, p.vl_unitario_liquido, pg.dt_com, pg.dt_pagamento, COALESCE(pg.fl_estimado, true),
                      p.vl_unitario / public.fn_fator_acumulado(p.id_ativo, p.dt_ex), COALESCE(p.vl_unitario_liquido, p.vl_unitario) / public.fn_fator_acumulado(p.id_ativo, p.dt_ex)
               FROM public.tb_provento p LEFT JOIN public.tb_provento_pagamento pg ON pg.id_ativo = p.id_ativo AND pg.ds_tipo_provento = p.ds_tipo_provento AND pg.dt_ex = p.dt_ex
               WHERE p.id_ativo = %s ORDER BY p.dt_ex DESC, p.ds_tipo_provento''', (ida,))
        lista = []
        por_ano = {}
        nominal_ano = {}
        for dt_ex, tipo, bruto, liq, dt_com, dt_pg, est, bruto_hoje, liq_hoje in cur.fetchall():
            lista.append({'dt_ex': dt_ex.isoformat(), 'tipo': tipo, 'bruto': _f(bruto), 'liquido': _f(liq),
                          'dt_com': dt_com.isoformat() if dt_com else None, 'dt_pagamento': dt_pg.isoformat() if dt_pg else None, 'pagamento_estimado': bool(est)})
            y = dt_ex.year
            acc = por_ano.setdefault(y, {'ano': y, 'bruto': 0.0, 'liquido': 0.0, 'eventos': 0})
            acc['bruto'] += float(bruto_hoje); acc['liquido'] += float(liq_hoje); acc['eventos'] += 1
            nominal_ano[y] = nominal_ano.get(y, 0.0) + float(bruto)
        cur.execute("SELECT EXTRACT(YEAR FROM dt_referencia)::int, vl_lpa_basico FROM public.tb_dre WHERE id_ativo = %s AND tp_periodo = 'ANUAL'", (ida,))
        lpa = {r[0]: _f(r[1]) for r in cur.fetchall()}
        for y, acc in por_ano.items():
            l = lpa.get(y)
            acc['payout'] = nominal_ano[y] / l * 100 if l and l > 0 else None
    anos = [por_ano[y] for y in sorted(por_ano)]
    pays = [(x['payout'], x['ano']) for x in anos if x['payout'] is not None]
    payout = None
    if pays:
        payout = {'atual': pays[-1][0], 'ano_atual': pays[-1][1], 'menor': min(pays)[0], 'ano_menor': min(pays)[1], 'maior': max(pays)[0], 'ano_maior': max(pays)[1]}
    return {'ticker': a['ticker'], 'proventos': lista, 'por_ano': anos, 'payout': payout}


@router.get('/{ticker}/resultados')
def resultados(ticker: str, periodo: str = 'trimestral', n: int = 12, usuario=Depends(get_current_user), conn=Depends(get_db)):
    """DRE, balanco e fluxo de caixa (CVM) por periodo, do mais novo pro mais antigo. trimestral: trimestres isolados (4T derivado do anual);
    anual: exercicio inteiro (o balanco e o de 31/12). Valores em R$ (a tela formata)."""
    if periodo not in ('trimestral', 'anual') or not 1 <= n <= 40:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, 'periodo: trimestral|anual; n entre 1 e 40')
    tp = periodo.upper()
    with conn.cursor() as cur:
        a = _ativo(cur, ticker)
        ida = a['id_ativo']
        cur.execute('''SELECT dt_referencia, vl_receita_total, vl_lucro_bruto, vl_resultado_operacional, vl_resultado_financeiro, vl_lucro_antes_impostos, vl_impostos,
                              vl_lucro_liquido_total, vl_lucro_liquido, vl_lpa_basico
                       FROM public.tb_dre WHERE id_ativo = %s AND tp_periodo = %s ORDER BY dt_referencia DESC LIMIT %s''', (ida, tp, n))
        dre = cur.fetchall()
        datas = [r[0] for r in dre]
        bal = {}
        dfc = {}
        if datas:
            cur.execute('''SELECT dt_referencia, vl_ativo_total, vl_ativo_circulante, vl_passivo_total, vl_patrimonio_liquido_total, vl_patrimonio_liquido, vl_divida_total,
                                  vl_divida_liquida, vl_caixa
                           FROM public.tb_balanco_patrimonial WHERE id_ativo = %s AND tp_periodo = 'TRIMESTRAL' AND dt_referencia = ANY(%s)''', (ida, datas))
            bal = {r[0]: r[1:] for r in cur.fetchall()}
            cur.execute('''SELECT dt_referencia, vl_caixa_operacional, vl_caixa_investimento, vl_caixa_financiamento FROM public.tb_dfc
                           WHERE id_ativo = %s AND tp_periodo = %s AND dt_referencia = ANY(%s)''', (ida, tp, datas))
            dfc = {r[0]: r[1:] for r in cur.fetchall()}
    saida = []
    for r in dre:
        b = bal.get(r[0]) or (None,) * 8
        d = dfc.get(r[0]) or (None,) * 3
        saida.append({
            'data': r[0].isoformat(), 'receita': _f(r[1]), 'lucro_bruto': _f(r[2]), 'ebit': _f(r[3]), 'resultado_financeiro': _f(r[4]),
            'lucro_antes_impostos': _f(r[5]), 'impostos': _f(r[6]), 'lucro_liquido_total': _f(r[7]), 'lucro_liquido': _f(r[8]), 'lpa': _f(r[9]),
            'ativo_total': _f(b[0]), 'ativo_circulante': _f(b[1]), 'passivo_total': _f(b[2]), 'patrimonio_liquido_total': _f(b[3]), 'patrimonio_liquido': _f(b[4]),
            'divida_total': _f(b[5]), 'divida_liquida': _f(b[6]), 'caixa': _f(b[7]),
            'caixa_operacional': _f(d[0]), 'caixa_investimento': _f(d[1]), 'caixa_financiamento': _f(d[2]),
        })
    return {'ticker': a['ticker'], 'periodo': periodo, 'periodos': saida}
