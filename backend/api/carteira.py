import math
from datetime import date

from fastapi import APIRouter, Depends

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


@router.get('/rentabilidade')
def rentabilidade(
    inicio: date | None = None,
    fim: date | None = None,
    id_corretora: int | None = None,
    usuario=Depends(get_current_user),
    conn=Depends(get_db),
):
    fim = fim or date.today()

    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT dt_dia, rentabilidade_pct
            FROM public.tb_rentabilidade_diaria
            WHERE id_usuario = %s AND id_carteira IS NULL AND id_corretora IS NOT DISTINCT FROM %s::int
              AND dt_dia <= %s
              AND (%s::date IS NULL OR dt_dia >= %s)
            ORDER BY dt_dia
            ''',
            (usuario['id_usuario'], id_corretora, fim, inicio, inicio),
        )
        diaria = [{'dt_dia': row[0].isoformat(), 'rentabilidade_pct': float(row[1])} for row in cur.fetchall()]

        cur.execute(
            '''
            SELECT to_char(date_trunc('month', dt_dia), 'YYYY-MM') AS periodo,
                   round((exp(sum(ln(1 + rentabilidade_pct / 100.0))) - 1) * 100, 4) AS rentabilidade_pct
            FROM public.tb_rentabilidade_diaria
            WHERE id_usuario = %s AND id_carteira IS NULL AND id_corretora IS NOT DISTINCT FROM %s::int
              AND dt_dia <= %s
              AND (%s::date IS NULL OR dt_dia >= %s)
            GROUP BY 1
            ORDER BY 1
            ''',
            (usuario['id_usuario'], id_corretora, fim, inicio, inicio),
        )
        mensal = [{'periodo': row[0], 'rentabilidade_pct': float(row[1])} for row in cur.fetchall()]

        cur.execute(
            '''
            SELECT to_char(date_trunc('year', dt_dia), 'YYYY') AS periodo,
                   round((exp(sum(ln(1 + rentabilidade_pct / 100.0))) - 1) * 100, 4) AS rentabilidade_pct
            FROM public.tb_rentabilidade_diaria
            WHERE id_usuario = %s AND id_carteira IS NULL AND id_corretora IS NOT DISTINCT FROM %s::int
              AND dt_dia <= %s
              AND (%s::date IS NULL OR dt_dia >= %s)
            GROUP BY 1
            ORDER BY 1
            ''',
            (usuario['id_usuario'], id_corretora, fim, inicio, inicio),
        )
        anual = [{'periodo': row[0], 'rentabilidade_pct': float(row[1])} for row in cur.fetchall()]

        cur.execute(
            '''
            SELECT round((exp(sum(ln(1 + rentabilidade_pct / 100.0))) - 1) * 100, 4)
            FROM public.tb_rentabilidade_diaria
            WHERE id_usuario = %s AND id_carteira IS NULL AND id_corretora IS NOT DISTINCT FROM %s::int
              AND dt_dia <= %s
              AND (%s::date IS NULL OR dt_dia >= %s)
            ''',
            (usuario['id_usuario'], id_corretora, fim, inicio, inicio),
        )
        total_row = cur.fetchone()
        total_pct = float(total_row[0]) if total_row and total_row[0] is not None else None

    return {'diaria': diaria, 'mensal': mensal, 'anual': anual, 'total_pct': total_pct}
