import os

import psycopg2


def load_dotenv():
    path = os.path.join(os.path.dirname(__file__), '.env')
    if not os.path.exists(path):
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
