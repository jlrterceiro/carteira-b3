# Airflow estavel mais recente (3.3.2, 2026-09-17) + o que os scripts de scrape/ precisam.
FROM apache/airflow:3.3.2

USER root
# pdftotext (poppler) e usado por prototipo_eventos_cvm / scraper_pagamentos_cvm pra ler os PDFs da CVM
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

USER airflow
COPY requirements.txt /tmp/requirements.txt
# constraints do proprio Airflow pra nao quebrar as dependencias dele
RUN PY=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
       --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-${PY}.txt"
