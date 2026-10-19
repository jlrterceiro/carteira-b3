"""Roda fn_rebuild_tudo() (recalcula todas as derivadas). Usado pela DAG diaria do Airflow; o atualiza_diario.py faz o mesmo inline."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db_lib import get_conn

conn = get_conn()
with conn.cursor() as cur:
    cur.execute('SELECT fn_rebuild_tudo()')
conn.commit()
conn.close()
print('fn_rebuild_tudo ok')
