from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr

from deps import get_current_user, get_db
from security import cria_token, hash_senha, verifica_senha

router = APIRouter(prefix='/auth', tags=['auth'])

COOKIE_NOME = 'access_token'
COOKIE_MAX_AGE = 7 * 24 * 60 * 60


class CadastroRequest(BaseModel):
    nm_usuario: str
    ds_email: EmailStr
    sg_usuario: str
    senha: str


class LoginRequest(BaseModel):
    ds_email: EmailStr
    senha: str


class UsuarioResponse(BaseModel):
    nm_usuario: str
    ds_email: str
    sg_usuario: str


def _seta_cookie(response: Response, id_usuario: int):
    token = cria_token(id_usuario)
    response.set_cookie(
        key=COOKIE_NOME,
        value=token,
        httponly=True,
        samesite='lax',
        max_age=COOKIE_MAX_AGE,
    )


@router.post('/cadastro', response_model=UsuarioResponse)
def cadastro(dados: CadastroRequest, response: Response, conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id_usuario, nm_usuario, sg_usuario, ds_senha_hash FROM public.tb_usuario WHERE ds_email = %s',
            (dados.ds_email,),
        )
        existente = cur.fetchone()

        if existente and existente[3] is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, 'e-mail ja cadastrado')

        if existente:
            id_usuario, nm_usuario, sg_usuario = existente[0], existente[1], existente[2]
            cur.execute(
                'UPDATE public.tb_usuario SET ds_senha_hash = %s, dh_atualizacao = now() WHERE id_usuario = %s',
                (hash_senha(dados.senha), id_usuario),
            )
        else:
            cur.execute('SELECT 1 FROM public.tb_usuario WHERE sg_usuario = %s', (dados.sg_usuario,))
            if cur.fetchone():
                raise HTTPException(status.HTTP_409_CONFLICT, 'nome de usuario ja em uso')

            cur.execute(
                '''
                INSERT INTO public.tb_usuario (nm_usuario, ds_email, sg_usuario, ds_senha_hash)
                VALUES (%s, %s, %s, %s)
                RETURNING id_usuario
                ''',
                (dados.nm_usuario, dados.ds_email, dados.sg_usuario, hash_senha(dados.senha)),
            )
            id_usuario = cur.fetchone()[0]
            nm_usuario, sg_usuario = dados.nm_usuario, dados.sg_usuario

            cur.execute(
                'INSERT INTO public.tb_carteira (id_usuario, nm_carteira) VALUES (%s, %s)',
                (id_usuario, 'Carteira Principal'),
            )

    conn.commit()
    _seta_cookie(response, id_usuario)
    return UsuarioResponse(nm_usuario=nm_usuario, ds_email=dados.ds_email, sg_usuario=sg_usuario)


@router.post('/login', response_model=UsuarioResponse)
def login(dados: LoginRequest, response: Response, conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id_usuario, nm_usuario, sg_usuario, ds_senha_hash FROM public.tb_usuario WHERE ds_email = %s AND fl_ativo',
            (dados.ds_email,),
        )
        row = cur.fetchone()

    credenciais_invalidas = HTTPException(status.HTTP_401_UNAUTHORIZED, 'credenciais invalidas')

    if row is None or row[3] is None:
        raise credenciais_invalidas

    id_usuario, nm_usuario, sg_usuario, senha_hash = row
    if not verifica_senha(dados.senha, senha_hash):
        raise credenciais_invalidas

    _seta_cookie(response, id_usuario)
    return UsuarioResponse(nm_usuario=nm_usuario, ds_email=dados.ds_email, sg_usuario=sg_usuario)


@router.post('/logout')
def logout(response: Response):
    response.delete_cookie(COOKIE_NOME)
    return {'ok': True}


@router.get('/me', response_model=UsuarioResponse)
def me(usuario=Depends(get_current_user)):
    return UsuarioResponse(**usuario)
