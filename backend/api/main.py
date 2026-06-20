import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import auth
import carteira

app = FastAPI(title='Scraper API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:8501', 'http://localhost:3000'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth.router)
app.include_router(carteira.router)


@app.get('/')
def raiz():
    return {'status': 'ok'}
