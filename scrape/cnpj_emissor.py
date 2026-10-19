"""CNPJs de um emissor ao longo do tempo (usado pelos scrapers de dados da CVM).

Quando uma empresa muda de CNPJ (reorganizacao societaria: BRST — holding cancelada em
2024-12-04, operadora assume a listagem em 2024-12-05), o CNPJ atual fica em
tb_emissor.nr_cnpj e os anteriores em tb_emissor.info -> 'cnpjs_anteriores':
    [{"cnpj": "19.796.586/0001-70", "ate": "2024-09-30"}]
"ate" = ultimo DT_REFER (inclusive) que vale pro CNPJ antigo; depois dele vale o CNPJ atual.
"""
from datetime import date


def fetch_emissores_cnpj(conn, ticker_filter=None):
    """[(id_emissor, cnpj, dt_min_exclusivo, dt_max_inclusivo)] de todos os emissores de acao.

    Emissor sem CNPJ anterior: (id, cnpj, None, None). Com anteriores: uma linha pro CNPJ
    atual (so periodos DEPOIS do maior 'ate') e uma por CNPJ antigo (so ate o 'ate' dele).
    """
    query = '''
        SELECT DISTINCT e.id_emissor, e.nr_cnpj, e.info
        FROM public.tb_emissor e
        JOIN public.tb_ativo a ON a.id_emissor = e.id_emissor
        JOIN public.tb_tipo_ativo ta ON ta.id_tipo_ativo = a.id_tipo_ativo
        WHERE ta.sg_tipo_ativo = 'ACAO' AND e.nr_cnpj IS NOT NULL
    '''
    params = ()
    if ticker_filter:
        query += ' AND a.sg_ticker = %s'
        params = (ticker_filter,)
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    saida = []
    for id_emissor, cnpj, info in rows:
        anteriores = (info or {}).get('cnpjs_anteriores') or []
        if not anteriores:
            saida.append((id_emissor, cnpj, None, None))
            continue
        corte = max(date.fromisoformat(a['ate']) for a in anteriores)
        saida.append((id_emissor, cnpj, corte, None))
        for a in anteriores:
            saida.append((id_emissor, a['cnpj'], None, date.fromisoformat(a['ate'])))
    return saida


def periodo_valido(dt_referencia, dt_min, dt_max):
    if dt_min is not None and dt_referencia <= dt_min:
        return False
    if dt_max is not None and dt_referencia > dt_max:
        return False
    return True
