"""
Rotina diaria dos dados (equivale ao scrape/atualiza_diario.py, mas com cada etapa visivel, com retry e historico):
cotacoes (COTAHIST) -> benchmarks (Ibovespa e CDI) -> negocios -> eventos da B3 -> reconstrucao diaria dos eventos -> proventos -> datas de pagamento
(CVM e B3) -> fn_rebuild_tudo(). Cada etapa e uma tarefa; se uma falha, as seguintes nao rodam e da pra reexecutar so dali.
Dias de semana as 20h (Brasilia), depois do COTAHIST do dia. Feriado: a etapa de cotacoes nao acha dado novo e segue.
"""
from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PROJ = '/opt/projeto'


def etapa(task_id, script, *args):
    return BashOperator(task_id=task_id, cwd=PROJ, bash_command=' '.join(['python', f'scrape/{script}', *args]))


with DAG(
    dag_id='atualiza_diario',
    description='Cotacoes, negocios, eventos, proventos, datas de pagamento e recalculo da carteira',
    schedule='0 20 * * 1-5',
    start_date=pendulum.datetime(2026, 10, 19, tz='America/Sao_Paulo'),
    catchup=False,
    max_active_runs=1,
    default_args={'retries': 2, 'retry_delay': timedelta(minutes=10)},
    tags=['dados', 'diario'],
) as dag:
    cotacoes = etapa('cotacoes_cotahist', 'scraper_cotacoes_b3.py')
    benchmarks = etapa('benchmarks', 'scraper_benchmarks.py')
    negocios = etapa('negocios_b3', 'scraper_negocios_b3.py')
    eventos = etapa('eventos_b3', 'scraper_eventos_corporativos_b3.py')
    reconstroi = etapa('reconstroi_eventos', 'reconstroi_eventos.py', '--diario', '--aplica')
    proventos = etapa('proventos_b3', 'scraper_proventos.py')
    pagamentos_cvm = etapa('pagamentos_cvm', 'scraper_pagamentos_cvm.py', '--aplica')
    pagamentos_b3 = etapa('pagamentos_b3', 'scraper_pagamentos_b3.py')
    rebuild = etapa('rebuild_tudo', 'rebuild_tudo.py')

    cotacoes >> benchmarks >> negocios >> eventos >> reconstroi >> proventos >> pagamentos_cvm >> pagamentos_b3 >> rebuild
