"""
Cotacao durante o pregao (atraso ~15 min, endpoint de cotacao da B3) -> tb_cotacao_intradia, a cada 5 minutos em dia util,
das 10h as 18h55 (Brasilia). A Posicao usa essa cotacao ate o COTAHIST do dia sair (vw_cotacao_atual).
Sem retry (a proxima rodada, 5 min depois, ja substitui) e uma execucao por vez.
"""
from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

with DAG(
    dag_id='cotacao_intradia',
    description='Cotacao intradia dos ativos em carteira (B3)',
    schedule='*/5 10-18 * * 1-5',
    start_date=pendulum.datetime(2026, 10, 19, tz='America/Sao_Paulo'),
    catchup=False,
    max_active_runs=1,
    default_args={'retries': 0, 'execution_timeout': timedelta(minutes=4)},
    tags=['dados', 'intradia'],
) as dag:
    BashOperator(task_id='coleta_intradia', cwd='/opt/projeto', bash_command='python scrape/scraper_cotacao_intradia.py')
