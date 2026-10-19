import os

import psycopg2

_AQUI = os.path.dirname(os.path.abspath(__file__))


def load_dotenv():
    candidatos = [
        os.getenv('ENV_FILE'),
        os.path.join(_AQUI, '.env'),
        os.path.join(_AQUI, '..', '.env'),
        os.path.join(_AQUI, '..', '..', '.env'),
    ]
    path = next((p for p in candidatos if p and os.path.exists(p)), None)
    if path is None:
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            os.environ.setdefault(key.strip(), value.strip())


load_dotenv()


def get_conn():
    dsn = os.getenv('DATABASE_URL')
    if dsn:
        return psycopg2.connect(dsn)
    return psycopg2.connect(
        dbname=os.getenv('PGDATABASE', 'investimentos'),
        user=os.getenv('PGUSER', 'terceiro'),
        password=os.environ['PGPASSWORD'],
        host=os.getenv('PGHOST', 'localhost'),
        port=os.getenv('PGPORT', '5432'),
    )
