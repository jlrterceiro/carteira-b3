import os
import sys

from fastapi import Cookie, HTTPException, status

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from db_lib import get_conn

from security import decodifica_token


def get_db():
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def get_current_user(access_token: str | None = Cookie(default=None)):
    if access_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'nao autenticado')

    id_usuario = decodifica_token(access_token)
    if id_usuario is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'token invalido ou expirado')

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id_usuario, nm_usuario, ds_email, sg_usuario FROM public.tb_usuario WHERE id_usuario = %s AND fl_ativo',
                (id_usuario,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'usuario nao encontrado')

    return {'id_usuario': row[0], 'nm_usuario': row[1], 'ds_email': row[2], 'sg_usuario': row[3]}
