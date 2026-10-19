import threading
import time
from datetime import datetime

import psycopg2.errors
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

import importacao
from db import get_conn
from deps import get_current_user, get_db

router = APIRouter(prefix='/perfil', tags=['perfil'])

# --- recalculo em segundo plano -------------------------------------------------------------------------
# fn_rebuild_tudo() refaz as tabelas derivadas de TODOS os usuarios (~70 s hoje), entao roda numa thread depois do
# upload e a tela acompanha por GET /perfil/recalculo. Estado em memoria: vale pra um processo so (uvicorn sem
# --workers). Upload durante um recalculo marca "pendente" e roda de novo ao terminar. Enquanto roda, as tabelas
# derivadas estao em transacao: leituras esperam e depois veem tudo consistente.
_lock = threading.Lock()
_estado = {'rodando': False, 'pendente': False, 'inicio': None, 'fim': None, 'erro': None}


def _roda_recalculo():
    while True:
        erro = None
        for tentativa in range(1, 4):
            conn = None
            try:
                conn = get_conn()
                with conn.cursor() as cur:
                    cur.execute('SELECT public.fn_rebuild_tudo()')
                conn.commit()
                erro = None
                break
            except psycopg2.errors.DeadlockDetected as e:   # concorrencia com outra escrita: tenta de novo
                erro = str(e)
                time.sleep(5 * tentativa)
            except Exception as e:  # noqa: BLE001
                erro = str(e)
                break
            finally:
                if conn is not None:
                    conn.close()
        with _lock:
            if _estado['pendente'] and erro is None:
                _estado['pendente'] = False
                continue
            _estado.update(rodando=False, pendente=False, fim=datetime.now().isoformat(timespec='seconds'), erro=erro)
            return


def dispara_recalculo():
    with _lock:
        if _estado['rodando']:
            _estado['pendente'] = True
            return
        _estado.update(rodando=True, pendente=False, inicio=datetime.now().isoformat(timespec='seconds'), fim=None, erro=None)
    threading.Thread(target=_roda_recalculo, daemon=True).start()


@router.get('/recalculo')
def recalculo(usuario=Depends(get_current_user)):
    with _lock:
        return dict(_estado)


# --- perfil ---------------------------------------------------------------------------------------------
@router.get('')
def perfil(usuario=Depends(get_current_user), conn=Depends(get_db)):
    """Dados do usuario logado + situacao da importacao (a partir de que dia baixar o proximo extrato)."""
    with _lock:
        estado = dict(_estado)
    return {
        'nm_usuario': usuario['nm_usuario'],
        'sg_usuario': usuario['sg_usuario'],
        'ds_email': usuario['ds_email'],
        'importacao': importacao.resumo_importacao(conn, usuario['id_usuario']),
        'recalculo': estado,
    }


def _le_upload(arquivo: UploadFile):
    dados = arquivo.file.read(importacao.MAX_BYTES + 1)
    try:
        return importacao.le_planilha(dados)
    except importacao.PlanilhaInvalida as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))


@router.post('/importacao/previa')
def previa_importacao(arquivo: UploadFile = File(...), usuario=Depends(get_current_user), conn=Depends(get_db)):
    """Le a planilha e diz o que seria importado, SEM gravar nada."""
    ops = _le_upload(arquivo)
    try:
        carteira = importacao.carteira_do_usuario(conn, usuario['id_usuario'])
    except importacao.PlanilhaInvalida as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    return importacao.previa(conn, carteira['id_carteira'], ops)


@router.post('/importacao')
def importar(arquivo: UploadFile = File(...), usuario=Depends(get_current_user), conn=Depends(get_db)):
    """Grava as operacoes novas da planilha na carteira do usuario e dispara o recalculo da carteira."""
    ops = _le_upload(arquivo)
    try:
        carteira = importacao.carteira_do_usuario(conn, usuario['id_usuario'])
    except importacao.PlanilhaInvalida as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    resultado = importacao.importa(conn, usuario['id_usuario'], carteira['id_carteira'], ops)
    if resultado['inseridas']:
        dispara_recalculo()
    return {**resultado, 'recalculo_iniciado': bool(resultado['inseridas'])}
