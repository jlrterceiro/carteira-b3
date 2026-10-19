import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

import db  # noqa: F401  (carrega o .env antes de ler JWT_SECRET)

JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = 'HS256'
JWT_EXPIRACAO = timedelta(days=7)


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verifica_senha(senha: str, senha_hash: str) -> bool:
    return bcrypt.checkpw(senha.encode('utf-8'), senha_hash.encode('utf-8'))


def cria_token(id_usuario: int) -> str:
    payload = {
        'id_usuario': id_usuario,
        'exp': datetime.now(timezone.utc) + JWT_EXPIRACAO,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decodifica_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload.get('id_usuario')
