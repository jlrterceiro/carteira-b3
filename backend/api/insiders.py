"""
Insiders por acao: o que administradores, conselhos, controladores e pessoas ligadas compraram e venderam de valores mobiliarios da propria
companhia (dados abertos da CVM, VLMO; tabela tb_insider_movimentacao, carga por scrape/scraper_insiders_cvm.py). Cada mes tem o link do
documento entregue a CVM. "Compra" e "venda" = movimentacao a vista de Acoes/Units; o resto (bonificacao, emprestimo, plano de remuneracao...)
aparece na lista de operacoes mas nao entra na conta liquida. Dado publico de mercado, mas o app todo exige login.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from deps import get_current_user, get_db

router = APIRouter(prefix='/insiders', tags=['insiders'])

ATIVOS = ('Ações', 'Units')
COMPRA, VENDA = 'Compra à vista', 'Venda à vista'
LIMITE_OPERACOES = 2000

# Grupo de insiders pelo campo Tipo_Cargo do formulario da CVM (o proprio declarante classifica; "ou Vinculado" inclui parentes e empresas ligadas)
ADMINISTRACAO = ('Conselho de Administração ou Vinculado', 'Diretor ou Vinculado', 'Conselho Fiscal ou Vinculado', 'Órgão Estatutário ou Vinculado')
CONTROLADOR = ('Controlador ou Vinculado',)
GRUPOS = {'todos': None, 'administracao': list(ADMINISTRACAO), 'controlador': list(CONTROLADOR)}


def _cargos(grupo: str):
    if grupo not in GRUPOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f'grupo invalido (use {", ".join(GRUPOS)})')
    return GRUPOS[grupo]


FILTRO_CARGO = ' AND (%s::text[] IS NULL OR tipo_cargo = ANY(%s))'
# operacao "em bloco" (oferta, venda em bloco, operacao casada) e dado provavelmente errado no formulario: ficam de fora das contas, a menos que se peca
# (marcas calculadas por fn_popula_insider_mercado)
# (fl_rotina, de fn_popula_insider_rotina, so alimenta a etiqueta da lista de operacoes e o estudo; nao e filtro de tela)
FILTRO_QUALIDADE = ' AND (%s OR NOT COALESCE(fl_bloco, false)) AND (%s OR NOT COALESCE(fl_suspeito, false))'


def _soma_meses(d: date, n: int) -> date:
    m = d.year * 12 + (d.month - 1) + n
    return date(m // 12, m % 12 + 1, 1)


def _f(v):
    return None if v is None else float(v)


CLASSE_DA_CARACTERISTICA = {'ON': 'ON', 'PN': 'PN', 'UNT': 'UNIT', 'UNIT': 'UNIT'}


def _valor_mercado(cur, id_emissor, fim):
    """valor de mercado da empresa em `fim` (fn_valor_mercado_em: acoes da CVM x preco real por classe) ou None"""
    cur.execute('SELECT mercado FROM public.fn_valor_mercado_em(%s, %s)', (id_emissor, fim))
    r = cur.fetchone()
    return float(r[0]) if r and r[0] else None


@router.get('/ranking/liquido')
def ranking(
    meses: int = 6,
    n: int = 10,
    grupo: str = 'todos',
    medida: str = 'bruto',
    ordenar: str = 'valor',
    com_blocos: bool = True,
    com_suspeitos: bool = False,
    tickers: str | None = None,
    vm_min: float = 200_000_000,
    data_ref: date | None = None,
    usuario=Depends(get_current_user),
    conn=Depends(get_db),
):
    """Ranking de empresas por compras e vendas de insiders (a vista, Acoes/Units, em R$) na janela dos ultimos `meses` meses (mes de competencia
    do formulario) ate hoje ou `data_ref`. `n` empresas em cada lista (1 a 100).
      medida   bruto (padrao): maiores COMPRAS e maiores VENDAS, cada lista pelo seu total (compra e venda nao se anulam; compra de mercado aberto e o
               sinal mais informativo);  liquido: compra liquida (compras - vendas > 0) e venda liquida (< 0).
      ordenar  valor (R$) | percentual (soma de cada operacao / valor de mercado da empresa NO DIA da operacao) | posicao (acoes negociadas / posicao que o
               grupo tinha no comeco da janela, pelo saldo inicial do formulario).
      com_blocos / com_suspeitos  incluem operacoes em bloco (ofertas, vendas casadas, incluidas por padrao: nao ha evidencia de que sinalizem pior que as normais) e dados provavelmente errados (excluidos por padrao).
      vm_min   valor de mercado minimo da empresa NO DIA de cada operacao (R$; 0 = sem minimo); so vale pras listas de compras/vendas, nao pra `carteira`.
    O ticker mostrado e o da classe (ON/PN/UNIT) mais negociada pelos insiders naquela empresa.
      tickers  lista separada por virgula (ex.: as acoes da carteira): devolve tambem `carteira`, uma linha por empresa dessa lista (mesmo sem operacao no periodo)."""
    if meses <= 0 or not 1 <= n <= 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, 'meses deve ser positivo e n entre 1 e 100')
    if ordenar not in ('valor', 'percentual', 'posicao') or medida not in ('bruto', 'liquido'):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, 'ordenar: valor|percentual; medida: bruto|liquido')
    cargos = _cargos(grupo)
    fim = data_ref if data_ref is not None and data_ref < date.today() else date.today()
    ini = _soma_meses(date(fim.year, fim.month, 1), -(meses - 1))
    qual = (com_blocos, com_suspeitos)
    with conn.cursor() as cur:
        def agrega(minimo, so_ids=None):
            cur.execute(
                '''SELECT id_emissor,
                          COALESCE(sum(vl_volume) FILTER (WHERE tipo_movimentacao = %s), 0),
                          COALESCE(sum(vl_volume) FILTER (WHERE tipo_movimentacao = %s), 0),
                          COALESCE(sum(vl_pct_mercado) FILTER (WHERE tipo_movimentacao = %s), 0),
                          COALESCE(sum(vl_pct_mercado) FILTER (WHERE tipo_movimentacao = %s), 0),
                          sum(vl_valor_mercado * vl_volume) FILTER (WHERE vl_valor_mercado IS NOT NULL) / NULLIF(sum(vl_volume) FILTER (WHERE vl_valor_mercado IS NOT NULL), 0),
                          COALESCE(sum(qt_ativo) FILTER (WHERE tipo_movimentacao = %s), 0),
                          COALESCE(sum(qt_ativo) FILTER (WHERE tipo_movimentacao = %s), 0)
                   FROM public.tb_insider_movimentacao
                   WHERE dt_movimentacao <= %s AND dt_referencia >= %s AND tipo_ativo = ANY(%s) AND tipo_movimentacao IN (%s, %s)
                     AND (%s <= 0 OR vl_valor_mercado >= %s) AND (%s::int[] IS NULL OR id_emissor = ANY(%s))''' + FILTRO_CARGO + FILTRO_QUALIDADE + '''
                   GROUP BY id_emissor''', (COMPRA, VENDA, COMPRA, VENDA, COMPRA, VENDA, fim, ini, list(ATIVOS), COMPRA, VENDA, minimo, minimo, so_ids, so_ids, cargos, cargos) + qual)
            return {r[0]: tuple(float(x) if x is not None else None for x in r[1:]) for r in cur.fetchall()}

        # id_emissor -> (compras, vendas, pct_compras, pct_vendas, vm_epoca, qtd_compras, qtd_vendas)
        linhas = agrega(vm_min)
        sem_vm = sum(1 for v in linhas.values() if v[4] is None)
        # empresas pedidas em `tickers` (ticker mostrado = o pedido); entram em `linhas` zeradas se nao negociaram
        pedidos = {}
        if tickers:
            lista_tk = [t.strip().upper() for t in tickers.split(',') if t.strip()][:200]
            cur.execute('SELECT sg_ticker, id_emissor FROM public.tb_ativo WHERE sg_ticker = ANY(%s)', (lista_tk,))
            por_tk = dict(cur.fetchall())
            for t in lista_tk:
                if t in por_tk:
                    pedidos.setdefault(por_tk[t], t)
        # resumo da carteira: mesmos filtros, SEM o minimo de valor de mercado (quem tem micro-cap quer ve-la)
        linhas_cart = agrega(0, list(pedidos)) if pedidos else {}
        for ide in pedidos:
            linhas_cart.setdefault(ide, (0.0, 0.0, 0.0, 0.0, None, 0.0, 0.0))
        ids = list(set(linhas) | set(linhas_cart))
        info = {}
        saldo_ini = {}
        if ids:
            # posicao do grupo no comeco da janela: saldo do mes mais antigo (>= inicio) com formulario de cada empresa
            cur.execute(
                '''SELECT DISTINCT ON (id_emissor) id_emissor, dt_referencia FROM public.tb_insider_saldo
                   WHERE id_emissor = ANY(%s) AND dt_referencia >= %s AND dt_referencia <= %s ORDER BY id_emissor, dt_referencia''', (ids, ini, fim))
            mes_saldo = dict(cur.fetchall())
            cur.execute(
                '''SELECT id_emissor, dt_referencia, sum(qt_saldo_inicial) FROM public.tb_insider_saldo
                   WHERE id_emissor = ANY(%s) AND dt_referencia >= %s AND dt_referencia <= %s AND tipo_ativo = ANY(%s)''' + FILTRO_CARGO + '''
                   GROUP BY 1, 2''', (ids, ini, fim, list(ATIVOS), cargos, cargos))
            for ide, dt, q in cur.fetchall():
                if mes_saldo.get(ide) == dt:
                    saldo_ini[ide] = float(q)
            # ticker mostrado: a classe mais negociada pelos insiders; sem informacao, o ativo ativo mais antigo da empresa
            cur.execute(
                '''SELECT id_emissor, public.fn_classe_insider(ds_caracteristica), sum(vl_volume) FROM public.tb_insider_movimentacao
                   WHERE id_emissor = ANY(%s) AND dt_referencia >= %s AND dt_movimentacao <= %s AND tipo_ativo = ANY(%s)''' + FILTRO_CARGO + FILTRO_QUALIDADE + '''
                   GROUP BY 1, 2''', (ids, ini, fim, list(ATIVOS), cargos, cargos) + qual)
            vol_classe = {}
            for ide, cl, v in cur.fetchall():
                vol_classe.setdefault(ide, {})[cl] = float(v or 0)
            cur.execute(
                '''SELECT a.id_emissor, a.id_ativo, a.sg_ticker, a.sg_classe, COALESCE(a.fl_ativo, true), e.nm_emissor
                   FROM public.tb_ativo a JOIN public.tb_emissor e USING (id_emissor) WHERE a.id_emissor = ANY(%s)''', (ids,))
            candidatos = {}
            for ide, ida, tk, cl, ativa, nome in cur.fetchall():
                candidatos.setdefault(ide, []).append((ida, tk, (cl or '').upper(), ativa, nome))
            for ide, lista in candidatos.items():
                pesos = vol_classe.get(ide, {})
                lista.sort(key=lambda c: (not c[3], -pesos.get(c[2], 0), c[1]))
                info[ide] = (lista[0][0], lista[0][1], lista[0][4])

    def linha(ide, lado):
        compras, vendas, pc, pv, vm, qc, qv = linhas[ide]
        if medida == 'liquido':
            valor, pct, qtd = compras - vendas, pc - pv, qc - qv
        else:
            valor, pct, qtd = (compras, pc, qc) if lado == 'C' else (-vendas, -pv, -qv)
        sd = saldo_ini.get(ide)
        return {'ticker': info[ide][1], 'nome': info[ide][2], 'compras_valor': compras, 'vendas_valor': vendas, 'liquido_valor': compras - vendas,
                'valor': valor, 'valor_mercado': vm, 'percentual': pct if vm else None,
                'saldo_inicial': sd, 'pct_posicao': qtd / sd * 100 if sd else None}

    def lista(lado):
        sinal = 1 if lado == 'C' else -1
        itens = [linha(ide, lado) for ide in linhas if ide in info]
        campo = {'valor': 'valor', 'percentual': 'percentual', 'posicao': 'pct_posicao'}[ordenar]
        itens = [l for l in itens if sinal * l['valor'] > 0 and (ordenar == 'valor' or l[campo] is not None)]
        itens.sort(key=lambda l: -sinal * l[campo])
        return itens[:n]

    carteira = []
    for ide, tk in pedidos.items():
        compras, vendas, pc, pv, vm, qc, qv = linhas_cart[ide]
        sd = saldo_ini.get(ide)
        carteira.append({'ticker': tk, 'nome': info[ide][2] if ide in info else None, 'compras_valor': compras, 'vendas_valor': vendas,
                         'liquido_valor': compras - vendas, 'valor_mercado': vm, 'percentual': (pc - pv) if vm else None,
                         'compras_pct': pc if vm else None, 'vendas_pct': pv if vm else None, 'saldo_inicial': sd,
                         'pct_posicao': (qc - qv) / sd * 100 if sd else None})
    carteira.sort(key=lambda l: -(l['compras_valor'] + l['vendas_valor']))
    return {'inicio': ini.isoformat(), 'fim': fim.isoformat(), 'meses': meses, 'n': n, 'grupo': grupo, 'medida': medida, 'ordenar': ordenar,
            'com_blocos': com_blocos, 'com_suspeitos': com_suspeitos, 'vm_min': vm_min, 'sem_valor_mercado': sem_vm,
            'compradores': lista('C'), 'vendedores': lista('V'), 'carteira': carteira}


@router.get('/estudo')
def estudo(
    grupo: str = 'todos',
    valor_min: float = 100000,
    desde: date | None = None,
    usuario=Depends(get_current_user),
    conn=Depends(get_db),
):
    """Estudo de eventos: o que aconteceu com a acao depois que os insiders compraram ou venderam? Cada evento = o que o grupo negociou a vista numa empresa
    num mes de competencia (sem bloco e sem dado suspeito, valor >= `valor_min`); o sinal e a DIVULGACAO do formulario (nunca antes da ultima operacao), a
    entrada e o fechamento do pregao seguinte e o retorno e o total (com proventos) em 1, 3, 6 e 12 meses, medido contra o Ibovespa. Separa operacoes
    oportunistas das de rotina (o grupo negocia todo ano no mesmo mes) e traz a linha de base: o mesmo retorno comprando as mesmas empresas em qualquer
    mes. So vale como evidencia o que se afasta da linha de base; eventos de meses vizinhos se sobrepoem, entao o numero efetivo de observacoes
    independentes e menor que `n`."""
    _cargos(grupo)
    horizontes = (1, 3, 6, 12)
    perfis = ('oportunista', 'rotina', 'desconhecido')
    linhas = []
    with conn.cursor() as cur:
        cur.execute('SELECT nr_meses, qt_amostras, vl_media, vl_mediana, pct_acima FROM public.tb_insider_base ORDER BY 1')
        base = {r[0]: {'n': r[1], 'media': _f(r[2]), 'mediana': _f(r[3]), 'pct_acima': _f(r[4])} for r in cur.fetchall()}
        for h in horizontes:
            cur.execute(
                f'''SELECT sg_direcao, sg_perfil, count(*), avg(ret_{h}m - ibov_{h}m), percentile_cont(0.5) WITHIN GROUP (ORDER BY ret_{h}m - ibov_{h}m),
                           100 * avg((ret_{h}m > ibov_{h}m)::int), avg(ret_{h}m)
                    FROM public.tb_insider_evento
                    WHERE sg_grupo = %s AND vl_total >= %s AND (%s::date IS NULL OR dt_sinal >= %s) AND ret_{h}m IS NOT NULL AND ibov_{h}m IS NOT NULL
                    GROUP BY 1, 2''', (grupo, valor_min, desde, desde))
            achados = {(r[0], r[1]): r for r in cur.fetchall()}
            for d in ('C', 'V'):
                for pf in perfis:
                    r = achados.get((d, pf))
                    linhas.append({'direcao': d, 'perfil': pf, 'meses': h, 'n': r[2] if r else 0,
                                   'excesso_medio': _f(r[3]) if r else None, 'excesso_mediana': _f(r[4]) if r else None,
                                   'pct_acima': _f(r[5]) if r else None, 'retorno_medio': _f(r[6]) if r else None})
        cur.execute('SELECT min(dt_sinal), max(dt_sinal), count(*) FROM public.tb_insider_evento WHERE sg_grupo = %s AND vl_total >= %s', (grupo, valor_min))
        ini, fim, total = cur.fetchone()
    return {'grupo': grupo, 'valor_min': valor_min, 'eventos': total, 'primeiro_sinal': ini.isoformat() if ini else None,
            'ultimo_sinal': fim.isoformat() if fim else None, 'base': base, 'linhas': linhas}


@router.get('/{ticker}')
def insiders(
    ticker: str,
    meses: int | None = None,
    grupo: str = 'todos',
    com_blocos: bool = True,
    com_suspeitos: bool = False,
    data_ref: date | None = None,
    usuario=Depends(get_current_user),
    conn=Depends(get_db),
):
    """`com_blocos`/`com_suspeitos`: incluem operacoes em bloco e dados provavelmente errados nas contas (a lista de operacoes mostra todas, com a marca). `grupo` = todos | administracao (conselhos e diretoria) | controlador. `meses` = janela pra tras a partir do mes de `data_ref` (ou de hoje); sem ele = tudo. `data_ref` limita ate aquela data."""
    if meses is not None and meses <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, 'meses deve ser positivo')
    cargos = _cargos(grupo)
    fim = data_ref if data_ref is not None and data_ref < date.today() else date.today()
    ini = _soma_meses(date(fim.year, fim.month, 1), -(meses - 1)) if meses else None
    with conn.cursor() as cur:
        cur.execute('''SELECT a.id_emissor, e.sg_emissor, e.nm_emissor FROM public.tb_ativo a
                       JOIN public.tb_emissor e USING (id_emissor) WHERE a.sg_ticker = %s''', (ticker.upper(),))
        ach = cur.fetchone()
        if ach is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, 'ticker desconhecido')
        id_emissor, sg_emissor, nm_emissor = ach
        mercado = _valor_mercado(cur, id_emissor, fim)
        base_filtro = 'WHERE id_emissor = %s AND dt_movimentacao <= %s AND (%s::date IS NULL OR dt_referencia >= %s)' + FILTRO_CARGO
        base_par = (id_emissor, fim, ini, ini, cargos, cargos)
        filtro = base_filtro + FILTRO_QUALIDADE                      # contas (mensal, por cargo): sem bloco/suspeito, a menos que se peca
        par = base_par + (com_blocos, com_suspeitos)

        # por mes (competencia do formulario), so compra/venda a vista de acoes: o mesmo recorte da pagina do Fundamentus
        cur.execute(
            f'''SELECT dt_referencia,
                       COALESCE(sum(qt_ativo) FILTER (WHERE tipo_movimentacao = %s), 0),
                       COALESCE(sum(vl_volume) FILTER (WHERE tipo_movimentacao = %s), 0),
                       COALESCE(sum(qt_ativo) FILTER (WHERE tipo_movimentacao = %s), 0),
                       COALESCE(sum(vl_volume) FILTER (WHERE tipo_movimentacao = %s), 0),
                       (array_agg(ds_link ORDER BY nr_versao DESC))[1],
                       COALESCE(sum(vl_pct_mercado) FILTER (WHERE tipo_movimentacao = %s), 0) - COALESCE(sum(vl_pct_mercado) FILTER (WHERE tipo_movimentacao = %s), 0)
                FROM public.tb_insider_movimentacao {filtro} AND tipo_ativo = ANY(%s)
                GROUP BY dt_referencia ORDER BY dt_referencia DESC''',
            (COMPRA, COMPRA, VENDA, VENDA, COMPRA, VENDA) + par + (list(ATIVOS),))
        mensal = [{'mes': r[0].isoformat()[:7], 'compras_qtd': _f(r[1]), 'compras_valor': _f(r[2]),
                   'vendas_qtd': _f(r[3]), 'vendas_valor': _f(r[4]), 'link': r[5], 'liquido_pct': _f(r[6])} for r in cur.fetchall()]

        # saldo inicial do grupo em cada mes (quantas acoes/units ele tinha no comeco do mes): denominador do "% da posicao"
        cur.execute(
            '''SELECT dt_referencia, sum(qt_saldo_inicial) FROM public.tb_insider_saldo
               WHERE id_emissor = %s AND tipo_ativo = ANY(%s) AND (%s::date IS NULL OR dt_referencia >= %s) AND dt_referencia <= %s''' + FILTRO_CARGO + '''
               GROUP BY dt_referencia''', (id_emissor, list(ATIVOS), ini, ini, fim, cargos, cargos))
        saldo_mes = {r[0].isoformat()[:7]: float(r[1]) for r in cur.fetchall()}
        for m in mensal:
            sd = saldo_mes.get(m['mes'])
            m['saldo_inicial'] = sd
            m['liquido_pct_posicao'] = (m['compras_qtd'] - m['vendas_qtd']) / sd * 100 if sd else None

        # por cargo (so compra/venda)
        cur.execute(
            f'''SELECT tipo_cargo,
                       COALESCE(sum(CASE WHEN tipo_movimentacao = %s THEN qt_ativo ELSE -qt_ativo END), 0),
                       COALESCE(sum(CASE WHEN tipo_movimentacao = %s THEN vl_volume ELSE -vl_volume END), 0)
                FROM public.tb_insider_movimentacao {filtro} AND tipo_ativo = ANY(%s) AND tipo_movimentacao IN (%s, %s)
                GROUP BY tipo_cargo ORDER BY 3 DESC''',
            (COMPRA, COMPRA) + par + (list(ATIVOS), COMPRA, VENDA))
        por_cargo = [{'cargo': r[0] or '—', 'liquido_qtd': _f(r[1]), 'liquido_valor': _f(r[2])} for r in cur.fetchall()]

        # operacoes (todas as movimentacoes, mais novas primeiro)
        cur.execute(
            f'''SELECT dt_movimentacao, tipo_cargo, ds_empresa, tipo_empresa, tipo_movimentacao, tipo_operacao, tipo_ativo,
                       ds_caracteristica, ds_intermediario, qt_ativo, vl_preco, vl_volume, ds_movimentacao, ds_link,
                       COALESCE(fl_bloco, false), COALESCE(fl_suspeito, false), vl_pct_mercado, fl_rotina
                FROM public.tb_insider_movimentacao {base_filtro}
                ORDER BY dt_movimentacao DESC, id_insider_movimentacao DESC LIMIT %s''', base_par + (LIMITE_OPERACOES,))
        operacoes = [{'dt': r[0].isoformat(), 'cargo': r[1], 'empresa': r[2], 'tipo_empresa': r[3], 'movimentacao': r[4],
                      'operacao': r[5], 'ativo': r[6], 'caracteristica': r[7], 'intermediario': r[8], 'qtd': _f(r[9]),
                      'preco': _f(r[10]), 'volume': _f(r[11]), 'descricao': r[12], 'link': r[13], 'bloco': r[14], 'suspeito': r[15],
                      'pct_mercado': _f(r[16]), 'rotina': r[17]} for r in cur.fetchall()]

    c_v = sum(m['compras_valor'] for m in mensal); v_v = sum(m['vendas_valor'] for m in mensal)
    c_q = sum(m['compras_qtd'] for m in mensal); v_q = sum(m['vendas_qtd'] for m in mensal)
    # posicao do grupo no comeco da janela = saldo do mes mais antigo com formulario; sem saldo (nao entregue / zerado) fica sem %
    meses_saldo = sorted(saldo_mes)
    saldo_ini = saldo_mes[meses_saldo[0]] if meses_saldo else None
    return {
        'ticker': ticker.upper(), 'emissor': sg_emissor, 'nome': nm_emissor,
        'inicio': ini.isoformat() if ini else None, 'fim': fim.isoformat(), 'grupo': grupo, 'com_blocos': com_blocos, 'com_suspeitos': com_suspeitos,
        'resumo': {'compras_qtd': c_q, 'compras_valor': c_v, 'vendas_qtd': v_q, 'vendas_valor': v_v,
                   'liquido_qtd': c_q - v_q, 'liquido_valor': c_v - v_v,
                   'liquido_percentual': sum(m['liquido_pct'] or 0 for m in mensal) if mensal else None,
                   'saldo_inicial': saldo_ini,
                   'compras_pct_posicao': c_q / saldo_ini * 100 if saldo_ini else None,
                   'vendas_pct_posicao': v_q / saldo_ini * 100 if saldo_ini else None,
                   'liquido_pct_posicao': (c_q - v_q) / saldo_ini * 100 if saldo_ini else None},
        'valor_mercado': mercado,
        'mensal': mensal, 'por_cargo': por_cargo, 'operacoes': operacoes,
        'operacoes_truncadas': len(operacoes) >= LIMITE_OPERACOES,
    }
