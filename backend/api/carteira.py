from datetime import date

from fastapi import APIRouter, Depends

from deps import get_current_user, get_db

router = APIRouter(prefix='/carteira', tags=['carteira'])


@router.get('/posicao')
def posicao(usuario=Depends(get_current_user), conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute('SELECT * FROM fn_posicao_atual(%s)', (usuario['sg_usuario'],))
        colunas = [c.name for c in cur.description]
        linhas = [dict(zip(colunas, row)) for row in cur.fetchall()]
    return linhas


@router.get('/ganhos')
def ganhos(usuario=Depends(get_current_user), conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT * FROM fn_ganho_total(NULL, NULL, NULL, NULL, %s)',
            (usuario['sg_usuario'],),
        )
        colunas = [c.name for c in cur.description]
        linhas = [dict(zip(colunas, row)) for row in cur.fetchall()]
    return linhas


@router.get('/rentabilidade')
def rentabilidade(
    inicio: date | None = None,
    fim: date | None = None,
    usuario=Depends(get_current_user),
    conn=Depends(get_db),
):
    fim = fim or date.today()

    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT dt_dia, rentabilidade_pct
            FROM public.tb_rentabilidade_diaria
            WHERE id_usuario = %s AND id_carteira IS NULL AND id_corretora IS NULL
              AND dt_dia <= %s
              AND (%s::date IS NULL OR dt_dia >= %s)
            ORDER BY dt_dia
            ''',
            (usuario['id_usuario'], fim, inicio, inicio),
        )
        diaria = [{'dt_dia': row[0].isoformat(), 'rentabilidade_pct': float(row[1])} for row in cur.fetchall()]

        cur.execute(
            '''
            SELECT to_char(date_trunc('month', dt_dia), 'YYYY-MM') AS periodo,
                   round((exp(sum(ln(1 + rentabilidade_pct / 100.0))) - 1) * 100, 4) AS rentabilidade_pct
            FROM public.tb_rentabilidade_diaria
            WHERE id_usuario = %s AND id_carteira IS NULL AND id_corretora IS NULL
              AND dt_dia <= %s
              AND (%s::date IS NULL OR dt_dia >= %s)
            GROUP BY 1
            ORDER BY 1
            ''',
            (usuario['id_usuario'], fim, inicio, inicio),
        )
        mensal = [{'periodo': row[0], 'rentabilidade_pct': float(row[1])} for row in cur.fetchall()]

        cur.execute(
            '''
            SELECT to_char(date_trunc('year', dt_dia), 'YYYY') AS periodo,
                   round((exp(sum(ln(1 + rentabilidade_pct / 100.0))) - 1) * 100, 4) AS rentabilidade_pct
            FROM public.tb_rentabilidade_diaria
            WHERE id_usuario = %s AND id_carteira IS NULL AND id_corretora IS NULL
              AND dt_dia <= %s
              AND (%s::date IS NULL OR dt_dia >= %s)
            GROUP BY 1
            ORDER BY 1
            ''',
            (usuario['id_usuario'], fim, inicio, inicio),
        )
        anual = [{'periodo': row[0], 'rentabilidade_pct': float(row[1])} for row in cur.fetchall()]

        cur.execute(
            '''
            SELECT round((exp(sum(ln(1 + rentabilidade_pct / 100.0))) - 1) * 100, 4)
            FROM public.tb_rentabilidade_diaria
            WHERE id_usuario = %s AND id_carteira IS NULL AND id_corretora IS NULL
              AND dt_dia <= %s
              AND (%s::date IS NULL OR dt_dia >= %s)
            ''',
            (usuario['id_usuario'], fim, inicio, inicio),
        )
        total_row = cur.fetchone()
        total_pct = float(total_row[0]) if total_row and total_row[0] is not None else None

    return {'diaria': diaria, 'mensal': mensal, 'anual': anual, 'total_pct': total_pct}
