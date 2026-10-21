import math
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status

from deps import get_current_user, get_db


def _f(v):
    """float seguro: None e NaN viram None."""
    if v is None:
        return None
    f = float(v)
    return None if math.isnan(f) or math.isinf(f) else f

router = APIRouter(prefix='/carteira', tags=['carteira'])


@router.get('/acoes-historico')
def acoes_historico(usuario=Depends(get_current_user), conn=Depends(get_db)):
    """Tickers que o usuário já negociou (tem dados em tb_rentabilidade_acao_diaria)."""
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT DISTINCT a.sg_ticker
            FROM public.tb_rentabilidade_acao_diaria r
            JOIN public.tb_ativo a ON a.id_ativo = r.id_ativo
            WHERE r.id_usuario = %s
              AND r.id_carteira IS NULL AND r.id_corretora IS NULL
            ORDER BY a.sg_ticker
            ''',
            (usuario['id_usuario'],),
        )
        return [row[0] for row in cur.fetchall()]


@router.get('/rentabilidade-acao')
def rentabilidade_acao(ticker: str, usuario=Depends(get_current_user), conn=Depends(get_db)):
    """Série diária de retorno acumulado para um ticker específico do usuário."""
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT r.dt_dia,
                   COALESCE(NULLIF(r.vl_retorno_pct, 'NaN'::numeric), 0),
                   NULLIF(r.vl_retorno_acumulado, 'NaN'::numeric),
                   r.fl_tem_posicao
            FROM public.tb_rentabilidade_acao_diaria r
            JOIN public.tb_ativo a ON a.id_ativo = r.id_ativo
            WHERE a.sg_ticker = %s
              AND r.id_usuario = %s
              AND r.id_carteira IS NULL AND r.id_corretora IS NULL
              AND r.vl_retorno_acumulado::text != 'NaN'
            ORDER BY r.dt_dia
            ''',
            (ticker, usuario['id_usuario']),
        )
        return [
            {
                'dt_dia': row[0].isoformat(),
                'vl_retorno_pct': _f(row[1]) or 0.0,
                'vl_retorno_acumulado': _f(row[2]),
                'fl_tem_posicao': bool(row[3]),
            }
            for row in cur.fetchall()
        ]


@router.get('/corretoras')
def corretoras(usuario=Depends(get_current_user), conn=Depends(get_db)):
    """Corretoras em que o usuario ja operou (alimenta o filtro de corretora de todas as telas)."""
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT k.id_corretora, k.nm_corretora
            FROM public.tb_corretora k
            WHERE k.id_corretora IN (
                SELECT o.id_corretora FROM public.tb_operacao o
                JOIN public.tb_carteira c ON c.id_carteira = o.id_carteira
                WHERE c.id_usuario = %s)
            ORDER BY k.nm_corretora
            ''',
            (usuario['id_usuario'],),
        )
        return [{'id_corretora': r[0], 'nm_corretora': r[1]} for r in cur.fetchall()]


# id_corretora opcional em posicao/ganhos/rentabilidade: sem ele = todas as corretoras do usuario. O filtro SEMPRE
# vem junto com o usuario autenticado, entao um id de corretora alheio so devolve vazio.
@router.get('/posicao')
def posicao(id_corretora: int | None = None, usuario=Depends(get_current_user), conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute('SELECT * FROM fn_posicao_atual(%s, %s)', (usuario['sg_usuario'], id_corretora))
        colunas = [c.name for c in cur.description]
        linhas = [dict(zip(colunas, row)) for row in cur.fetchall()]
    return linhas


@router.get('/ganhos')
def ganhos(id_corretora: int | None = None, usuario=Depends(get_current_user), conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT * FROM fn_ganho_total(NULL, NULL, NULL, %s, %s)',
            (id_corretora, usuario['sg_usuario']),
        )
        colunas = [c.name for c in cur.description]
        linhas = [dict(zip(colunas, row)) for row in cur.fetchall()]
    return linhas


# Retorno diario (em %) por metodo, sobre tb_rentabilidade_diaria r + tb_rentabilidade_caixa_diaria k:
#   receber        : TWR com proventos A RECEBER. O provento (liquido) conta no numerador na data ex e fica no denominador,
#                    sem render, ate o dia do pagamento, quando sai (saque ou reinvestimento).
#   status_invest  : o provento conta so na data de PAGAMENTO (real ou estimada) e o caixa fica no denominador PARA SEMPRE,
#                    sem render. Reproduz o Status Invest com folga de ~1 ponto.
#   acoes          : TWR so das acoes (provento sai da carteira no ex). Nao aparece na tela: e o padrao do endpoint so pra
#                    o Streamlit continuar igual.
METODOS = {
    'acoes': 'r.rentabilidade_pct',
    'receber': '100.0 * r.vl_ganho / NULLIF(r.vl_base + COALESCE(k.vl_receber_ini, 0), 0)',
    'status_invest': '100.0 * (r.vl_ganho - COALESCE(k.vl_prov_ex, 0) + COALESCE(k.vl_prov_pgto, 0))'
                     ' / NULLIF(r.vl_base + COALESCE(k.vl_caixa_pgto_ini, 0), 0)',
}


@router.get('/rentabilidade')
def rentabilidade(
    inicio: date | None = None,
    fim: date | None = None,
    id_corretora: int | None = None,
    metodo: str = 'acoes',
    usuario=Depends(get_current_user),
    conn=Depends(get_db),
):
    if metodo not in METODOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f'metodo invalido (use {", ".join(METODOS)})')
    fim = fim or date.today()
    # a expressao vem de um dicionario fixo (nunca do cliente), entao interpolar aqui e seguro
    serie = f'''
        WITH s AS (
            SELECT r.dt_dia, {METODOS[metodo]} AS pct
            FROM public.tb_rentabilidade_diaria r
            LEFT JOIN public.tb_rentabilidade_caixa_diaria k
                   ON k.id_usuario = r.id_usuario AND k.dt_dia = r.dt_dia AND k.id_corretora IS NOT DISTINCT FROM r.id_corretora
            WHERE r.id_usuario = %s AND r.id_carteira IS NULL AND r.id_corretora IS NOT DISTINCT FROM %s::int
              AND r.dt_dia <= %s AND (%s::date IS NULL OR r.dt_dia >= %s)
        )
    '''
    params = (usuario['id_usuario'], id_corretora, fim, inicio, inicio)
    composto = 'round((exp(sum(ln(1 + pct / 100.0))) - 1) * 100, 4)'

    with conn.cursor() as cur:
        cur.execute(serie + 'SELECT dt_dia, pct FROM s WHERE pct IS NOT NULL ORDER BY dt_dia', params)
        diaria = [{'dt_dia': row[0].isoformat(), 'rentabilidade_pct': float(row[1])} for row in cur.fetchall()]

        # pct <= -100 (preco zerado por erro de dado) faria o LN falhar e derrubaria a tela inteira: fica de fora
        def por_periodo(unidade, formato):
            cur.execute(serie + f"SELECT to_char(date_trunc('{unidade}', dt_dia), '{formato}') AS periodo, {composto} "
                                "FROM s WHERE pct > -100 GROUP BY 1 ORDER BY 1", params)
            return [{'periodo': row[0], 'rentabilidade_pct': float(row[1])} for row in cur.fetchall()]

        mensal = por_periodo('month', 'YYYY-MM')
        anual = por_periodo('year', 'YYYY')

        cur.execute(serie + f'SELECT {composto} FROM s WHERE pct > -100', params)
        total_row = cur.fetchone()
        total_pct = float(total_row[0]) if total_row and total_row[0] is not None else None

    return {'metodo': metodo, 'diaria': diaria, 'mensal': mensal, 'anual': anual, 'total_pct': total_pct}


@router.get('/benchmarks')
def benchmarks(
    de: date,
    ate: date,
    usuario=Depends(get_current_user),
    conn=Depends(get_db),
):
    """Ibovespa e CDI acumulados (%) nos pregoes de `de` ate `ate`, a partir do fechamento do pregao ANTERIOR a `de`
    (a carteira, no TWR, tambem parte do fechamento anterior). Pra por no mesmo grafico da rentabilidade: o front passa a
    data do 1o ponto da carteira. IBOV = fechamento do indice (retorno total: a metodologia da B3 reinveste os proventos); CDI = taxa diaria composta, onde a taxa do
    dia t rende de t ate o proximo dia util. Dado de mercado, igual pra todos os usuarios."""
    with conn.cursor() as cur:
        cur.execute(
            '''
            WITH cdi AS (
                SELECT dt_dia, COALESCE(SUM(LN(1 + vl_retorno_pct / 100)) OVER (
                           ORDER BY dt_dia ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS l
                FROM public.tb_benchmark_diario WHERE cd_benchmark = 'CDI'
            ),
            ib AS (SELECT dt_dia, vl_nivel FROM public.tb_benchmark_diario WHERE cd_benchmark = 'IBOV'),
            base AS (SELECT max(dt_dia) AS b FROM ib WHERE dt_dia < %s),
            nivel0 AS (SELECT ib.vl_nivel FROM ib JOIN base ON ib.dt_dia = base.b),
            l0 AS (SELECT l FROM cdi, base WHERE cdi.dt_dia <= base.b ORDER BY cdi.dt_dia DESC LIMIT 1)
            SELECT d.dt_dia,
                   100 * (d.vl_nivel / NULLIF((SELECT vl_nivel FROM nivel0), 0) - 1) AS ibov_pct,
                   100 * (EXP((SELECT l FROM cdi WHERE cdi.dt_dia <= d.dt_dia ORDER BY cdi.dt_dia DESC LIMIT 1)
                              - (SELECT l FROM l0)) - 1) AS cdi_pct
            FROM ib d
            WHERE d.dt_dia BETWEEN %s AND %s
            ORDER BY d.dt_dia
            ''', (de, de, ate))
        return [{'dt_dia': r[0].isoformat(), 'ibov_pct': _f(r[1]), 'cdi_pct': _f(r[2])} for r in cur.fetchall()]
