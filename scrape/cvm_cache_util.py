"""
Cache dos zips da CVM (itr_/dfp_cia_aberta_<ano>.zip + CSVs extraidos em scrape/cvm_cache/). Os scrapers de DRE, balanco e fluxo de caixa reaproveitam
o cache pra nao rebaixar 16 anos de dados, mas o do ano corrente (ITR do ano, DFP do ano anterior, que ganha reapresentacoes) PRECISA ser renovado: sem isso
o banco parou no 1T26 meses depois do 2T26 sair. `renova_se_velho` apaga o zip e os CSVs desses anos quando passam de ~20 h (uma vez por processo).
"""
import glob
import os
import time
from datetime import date

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cvm_cache')
_verificados = set()


def renova_se_velho(tipo, ano, horas=20):
    """apaga o cache de (tipo, ano) se for do ano corrente ou do anterior e tiver mais de `horas` horas; devolve True se apagou"""
    if ano < date.today().year - 1 or (tipo, ano) in _verificados:
        return False
    _verificados.add((tipo, ano))
    zip_path = os.path.join(CACHE_DIR, f'{tipo}_cia_aberta_{ano}.zip')
    if not os.path.exists(zip_path) or time.time() - os.path.getmtime(zip_path) <= horas * 3600:
        return False
    os.remove(zip_path)
    for f in glob.glob(os.path.join(CACHE_DIR, f'{tipo}_cia_aberta_*_{ano}.csv')):
        os.remove(f)
    return True
