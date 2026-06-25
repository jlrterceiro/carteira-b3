from datetime import date

from fastapi import APIRouter, Depends

from deps import get_db

router = APIRouter(prefix='/acoes', tags=['acoes'])


@router.get('/lista')
def lista(conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT a.sg_ticker
            FROM public.tb_ativo a
            JOIN public.tb_tipo_ativo ta ON ta.id_tipo_ativo = a.id_tipo_ativo
            WHERE ta.sg_tipo_ativo = 'ACAO'
            ORDER BY a.sg_ticker
            ''',
        )
        return [row[0] for row in cur.fetchall()]


@router.get('/cotacao')
def cotacao(ticker: str, inicio: date | None = None, fim: date | None = None, conn=Depends(get_db)):
    fim = fim or date.today()
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT
                c.dt_cotacao,
                c.vl_fechamento * public.fn_fator_acumulado(c.id_ativo, c.dt_cotacao) AS vl_fechamento_nominal,
                c.vl_fechamento,
                c.vl_fechamento_ajustado
            FROM public.tb_cotacao c
            JOIN public.tb_ativo a ON a.id_ativo = c.id_ativo
            WHERE a.sg_ticker = %s
              AND c.dt_cotacao <= %s
              AND (%s::date IS NULL OR c.dt_cotacao >= %s)
            ORDER BY c.dt_cotacao
            ''',
            (ticker, fim, inicio, inicio),
        )
        return [
            {
                'dt_cotacao': row[0].isoformat(),
                'vl_fechamento_nominal': float(row[1]),
                'vl_fechamento': float(row[2]),
                'vl_fechamento_ajustado': float(row[3]) if row[3] is not None else None,
            }
            for row in cur.fetchall()
        ]
