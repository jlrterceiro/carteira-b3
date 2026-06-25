from datetime import date, timedelta

import altair as alt
import pandas as pd
import requests
import streamlit as st

API_BASE_URL = 'http://localhost:8000'

PERIODOS = {
    'Últimos 30 dias': timedelta(days=30),
    '6 meses': timedelta(days=182),
    '1 ano': timedelta(days=365),
    '2 anos': timedelta(days=2 * 365),
    '5 anos': timedelta(days=5 * 365),
    '10 anos': timedelta(days=10 * 365),
    'Total': None,
    'Personalizado': 'custom',
}

st.set_page_config(page_title='Minha Carteira', layout='wide')


def fmt_num(valor, decimais=2):
    if pd.isna(valor):
        return ''
    texto = f'{valor:,.{decimais}f}'
    return texto.translate(str.maketrans({',': '.', '.': ','}))


def fmt_brl(valor, decimais=2):
    if pd.isna(valor):
        return ''
    return f'R$ {fmt_num(valor, decimais)}'


def fmt_pct(valor, decimais=2):
    if pd.isna(valor):
        return ''
    return f'{fmt_num(valor, decimais)}%'


def cor_variacao(valor):
    if pd.isna(valor) or valor == 0:
        return ''
    return 'color: green' if valor > 0 else 'color: red'


def get_sessao():
    if 'sessao' not in st.session_state:
        st.session_state.sessao = requests.Session()
    return st.session_state.sessao


def usuario_logado():
    return st.session_state.get('usuario')


def tela_login():
    st.title('Minha Carteira')
    aba_login, aba_cadastro = st.tabs(['Entrar', 'Cadastrar'])

    with aba_login:
        with st.form('form_login'):
            ds_email = st.text_input('E-mail')
            senha = st.text_input('Senha', type='password')
            enviado = st.form_submit_button('Entrar')

        if enviado:
            resp = get_sessao().post(
                f'{API_BASE_URL}/auth/login',
                json={'ds_email': ds_email, 'senha': senha},
            )
            if resp.status_code == 200:
                st.session_state.usuario = resp.json()
                st.rerun()
            else:
                st.error('E-mail ou senha incorretos.')

    with aba_cadastro:
        st.caption(
            'Se o seu e-mail já tiver sido cadastrado por outra via (ex: importação direta '
            'da carteira), esse formulário só define a senha pra você acessar — não cria uma '
            'conta nova nem duplica dados.'
        )
        with st.form('form_cadastro'):
            nm_usuario = st.text_input('Nome completo')
            ds_email_cad = st.text_input('E-mail', key='email_cadastro')
            sg_usuario = st.text_input('Nome de usuário (sem espaço)')
            senha_cad = st.text_input('Senha', type='password', key='senha_cadastro')
            enviado_cad = st.form_submit_button('Cadastrar')

        if enviado_cad:
            resp = get_sessao().post(
                f'{API_BASE_URL}/auth/cadastro',
                json={
                    'nm_usuario': nm_usuario,
                    'ds_email': ds_email_cad,
                    'sg_usuario': sg_usuario,
                    'senha': senha_cad,
                },
            )
            if resp.status_code == 200:
                st.session_state.usuario = resp.json()
                st.rerun()
            elif resp.status_code == 409:
                st.error(resp.json().get('detail', 'E-mail ou usuário já em uso.'))
            else:
                st.error('Não foi possível cadastrar. Confira os campos.')


def tabela_patrimonio_html(df, variacao_total, variacao_total_pct, valor_total, cor_total):
    linhas_html = []
    for _, row in df.iterrows():
        sinal = 'pos' if row['ganho_capital_pct'] > 0 else ('neg' if row['ganho_capital_pct'] < 0 else '')
        linhas_html.append(f'''
        <tr>
            <td class="esquerda" data-sort="{row['sg_ticker']}">{row['sg_ticker']}</td>
            <td data-sort="{row['quantidade']}">{fmt_num(row['quantidade'], 0)}</td>
            <td data-sort="{row['preco_medio']}">{fmt_brl(row['preco_medio'])}</td>
            <td data-sort="{row['preco_atual']}">{fmt_brl(row['preco_atual'])}</td>
            <td data-sort="{row['ganho_capital_pct']}">
                <div class="variacao">
                    <span class="{sinal}">{fmt_brl(row['ganho_capital'])}</span>
                    <span class="{sinal}">{fmt_pct(row['ganho_capital_pct'])}</span>
                </div>
            </td>
            <td data-sort="{row['vl_posicao']}">{fmt_brl(row['vl_posicao'])}</td>
            <td data-sort="{row['peso_carteira_pct']}">{fmt_pct(row['peso_carteira_pct'])}</td>
        </tr>''')

    return f'''
    <style>
        body {{ margin: 4px; font-family: "Source Sans Pro", sans-serif; }}
        .borda {{ border: 1px solid #ddd; border-radius: 20px; overflow: hidden; padding: 16px; }}
        .scroll-wrap {{ overflow-x: auto; }}
        table {{ width: 100%; min-width: 700px; border-collapse: collapse; font-size: 13px; table-layout: fixed; }}
        th, td {{ padding: 6px; text-align: right; border-bottom: 1px solid #eee; border-right: 1px solid #eee;
                  overflow: hidden; text-overflow: ellipsis; }}
        th:last-child, td:last-child {{ border-right: none; }}
        th.esquerda, td.esquerda {{ text-align: left; }}
        th {{ cursor: pointer; background: #f8f9fb; color: #000000; text-transform: uppercase;
              font-weight: bold; user-select: none; position: sticky; top: 0; }}
        th:hover {{ background: #eef0f4; }}
        tbody tr:nth-child(even) {{ background: #f9f7f2; }}
        .totais td {{ border-bottom: 2px solid #ddd; border-right: none; background: #ffffff; }}
        .totais .rotulo {{ color: #000000; font-size: 11px; font-weight: bold; text-transform: uppercase; }}
        .totais .valor {{ font-weight: normal; white-space: nowrap; }}
        .seta {{ margin-left: 4px; }}
        .variacao {{ display: flex; justify-content: space-between; gap: 4px; white-space: nowrap; }}
        .pos {{ color: green; }}
        .neg {{ color: red; }}
    </style>
    <div class="borda">
    <div class="scroll-wrap">
    <table id="tbl-patrimonio">
        <colgroup>
            <col style="width: 11%">
            <col style="width: 13%">
            <col style="width: 13%">
            <col style="width: 13%">
            <col style="width: 20%">
            <col style="width: 17%">
            <col style="width: 13%">
        </colgroup>
        <thead>
            <tr class="totais">
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td>
                    <div class="rotulo">Variação total</div>
                    <div class="valor variacao" style="{cor_total}">
                        <span>{fmt_brl(variacao_total)}</span>
                        <span>{fmt_pct(variacao_total_pct)}</span>
                    </div>
                </td>
                <td>
                    <div class="rotulo">Patrimônio total</div>
                    <div class="valor">{fmt_brl(valor_total)}</div>
                </td>
                <td></td>
            </tr>
            <tr>
                <th class="esquerda" data-col="0" data-type="text">TICKER<span class="seta"></span></th>
                <th data-col="1" data-type="num">QUANTIDADE<span class="seta"></span></th>
                <th data-col="2" data-type="num">PREÇO MÉDIO<span class="seta"></span></th>
                <th data-col="3" data-type="num">PREÇO ATUAL<span class="seta"></span></th>
                <th data-col="4" data-type="num">VARIAÇÃO<span class="seta"></span></th>
                <th data-col="5" data-type="num">PATRIMÔNIO ATUAL<span class="seta"></span></th>
                <th data-col="6" data-type="num">% DA CARTEIRA<span class="seta"></span></th>
            </tr>
        </thead>
        <tbody>{"".join(linhas_html)}</tbody>
    </table>
    </div>
    </div>
    <script>
        const dir = {{}};
        document.querySelectorAll('#tbl-patrimonio th').forEach(th => {{
            th.addEventListener('click', () => {{
                const col = parseInt(th.dataset.col);
                const tipo = th.dataset.type;
                dir[col] = !dir[col];
                const tbody = document.querySelector('#tbl-patrimonio tbody');
                const linhas = Array.from(tbody.querySelectorAll('tr'));
                linhas.sort((a, b) => {{
                    const av = a.children[col].dataset.sort;
                    const bv = b.children[col].dataset.sort;
                    const cmp = tipo === 'num' ? (parseFloat(av) - parseFloat(bv)) : av.localeCompare(bv);
                    return dir[col] ? cmp : -cmp;
                }});
                linhas.forEach(linha => tbody.appendChild(linha));
                document.querySelectorAll('#tbl-patrimonio th .seta').forEach(s => s.textContent = '');
                th.querySelector('.seta').textContent = dir[col] ? '▲' : '▼';
            }});
        }});
    </script>
    '''


def tabela_ganhos_html(df, ganho_total, ganho_total_pct, investido_total):
    cor_total = cor_variacao(ganho_total)
    linhas_html = []
    for _, row in df.iterrows():
        cores = {
            'realizado': cor_variacao(row['ganho_realizado_vendas']),
            'nao_realizado': cor_variacao(row['ganho_nao_realizado']),
            'total': cor_variacao(row['ganho_total']),
            'total_pct': cor_variacao(row['ganho_pct_total']),
        }
        linhas_html.append(f'''
        <tr>
            <td class="esquerda" data-sort="{row['sg_ticker']}">{row['sg_ticker']}</td>
            <td data-sort="{row['ganho_realizado_vendas']}" style="{cores['realizado']}">{fmt_brl(row['ganho_realizado_vendas'])}</td>
            <td data-sort="{row['proventos']}">{fmt_brl(row['proventos'])}</td>
            <td data-sort="{row['ganho_nao_realizado']}" style="{cores['nao_realizado']}">{fmt_brl(row['ganho_nao_realizado'])}</td>
            <td data-sort="{row['ganho_total']}" style="{cores['total']}">{fmt_brl(row['ganho_total'])}</td>
            <td data-sort="{row['valor_investido']}">{fmt_brl(row['valor_investido'])}</td>
            <td data-sort="{row['ganho_pct_total']}" style="{cores['total_pct']}">{fmt_pct(row['ganho_pct_total'])}</td>
        </tr>''')

    return f'''
    <style>
        body {{ margin: 4px; font-family: "Source Sans Pro", sans-serif; }}
        .borda {{ border: 1px solid #ddd; border-radius: 20px; overflow: hidden; padding: 16px; }}
        .scroll-wrap {{ overflow-x: auto; }}
        table {{ width: 100%; min-width: 800px; border-collapse: collapse; font-size: 13px; table-layout: fixed; }}
        th, td {{ padding: 6px; text-align: right; border-bottom: 1px solid #eee; border-right: 1px solid #eee;
                  overflow: hidden; text-overflow: ellipsis; }}
        th:last-child, td:last-child {{ border-right: none; }}
        th.esquerda, td.esquerda {{ text-align: left; }}
        th {{ cursor: pointer; background: #f8f9fb; color: #000000; text-transform: uppercase;
              font-weight: bold; user-select: none; position: sticky; top: 0; }}
        th:hover {{ background: #eef0f4; }}
        tbody tr:nth-child(even) {{ background: #f9f7f2; }}
        .totais td {{ border-bottom: 2px solid #ddd; border-right: none; background: #ffffff; }}
        .totais .rotulo {{ color: #000000; font-size: 11px; font-weight: bold; text-transform: uppercase; }}
        .totais .valor {{ font-weight: normal; white-space: nowrap; }}
        .seta {{ margin-left: 4px; }}
        .variacao {{ display: flex; justify-content: space-between; gap: 4px; white-space: nowrap; }}
        .pos {{ color: green; }}
        .neg {{ color: red; }}
    </style>
    <div class="borda">
    <div class="scroll-wrap">
    <table id="tbl-ganhos">
        <colgroup>
            <col style="width: 9%">
            <col style="width: 13%">
            <col style="width: 11%">
            <col style="width: 13%">
            <col style="width: 22%">
            <col style="width: 16%">
            <col style="width: 16%">
        </colgroup>
        <thead>
            <tr class="totais">
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td>
                    <div class="rotulo">Ganho total</div>
                    <div class="valor variacao" style="{cor_total}">
                        <span>{fmt_brl(ganho_total)}</span>
                        <span>{fmt_pct(ganho_total_pct)}</span>
                    </div>
                </td>
                <td>
                    <div class="rotulo">Valor investido</div>
                    <div class="valor">{fmt_brl(investido_total)}</div>
                </td>
                <td></td>
            </tr>
            <tr>
                <th class="esquerda" data-col="0" data-type="text">TICKER<span class="seta"></span></th>
                <th data-col="1" data-type="num">GANHO REALIZADO (VENDAS)<span class="seta"></span></th>
                <th data-col="2" data-type="num">PROVENTOS<span class="seta"></span></th>
                <th data-col="3" data-type="num">GANHO NÃO REALIZADO<span class="seta"></span></th>
                <th data-col="4" data-type="num">GANHO TOTAL<span class="seta"></span></th>
                <th data-col="5" data-type="num">VALOR INVESTIDO<span class="seta"></span></th>
                <th data-col="6" data-type="num">GANHO TOTAL (%)<span class="seta"></span></th>
            </tr>
        </thead>
        <tbody>{"".join(linhas_html)}</tbody>
    </table>
    </div>
    </div>
    <script>
        const dir = {{}};
        document.querySelectorAll('#tbl-ganhos th').forEach(th => {{
            th.addEventListener('click', () => {{
                const col = parseInt(th.dataset.col);
                const tipo = th.dataset.type;
                dir[col] = !dir[col];
                const tbody = document.querySelector('#tbl-ganhos tbody');
                const linhas = Array.from(tbody.querySelectorAll('tr'));
                linhas.sort((a, b) => {{
                    const av = a.children[col].dataset.sort;
                    const bv = b.children[col].dataset.sort;
                    const cmp = tipo === 'num' ? (parseFloat(av) - parseFloat(bv)) : av.localeCompare(bv);
                    return dir[col] ? cmp : -cmp;
                }});
                linhas.forEach(linha => tbody.appendChild(linha));
                document.querySelectorAll('#tbl-ganhos th .seta').forEach(s => s.textContent = '');
                th.querySelector('.seta').textContent = dir[col] ? '▲' : '▼';
            }});
        }});
    </script>
    '''


def tela_posicao():
    resp = get_sessao().get(f'{API_BASE_URL}/carteira/posicao')
    if resp.status_code != 200:
        st.error('Não foi possível carregar o patrimônio.')
        return

    linhas = resp.json()
    if not linhas:
        st.info('Você ainda não tem nenhuma posição. Importe suas operações pra começar.')
        return

    df = pd.DataFrame(linhas).sort_values('vl_posicao', ascending=False)
    valor_total = df['vl_posicao'].sum()
    df['peso_carteira_pct'] = 100 * df['vl_posicao'] / valor_total

    custo_total = (df['quantidade'] * df['preco_medio']).sum()
    variacao_total = df['ganho_capital'].sum()
    variacao_total_pct = 100 * variacao_total / custo_total

    cor_total = cor_variacao(variacao_total)

    altura = 136 + 40 * len(df)
    html = tabela_patrimonio_html(df, variacao_total, variacao_total_pct, valor_total, cor_total)
    st.components.v1.html(html, height=altura, scrolling=False)


def tela_ganhos():
    resp = get_sessao().get(f'{API_BASE_URL}/carteira/ganhos')
    if resp.status_code != 200:
        st.error('Não foi possível carregar os ganhos.')
        return

    linhas = resp.json()
    if not linhas:
        st.info('Sem dados de ganho ainda.')
        return

    df = pd.DataFrame(linhas).sort_values('ganho_pct_total', ascending=False)
    total = df['ganho_total'].sum()
    investido = df['valor_investido'].sum()
    total_pct = 100 * total / investido

    altura = 136 + 40 * len(df)
    html = tabela_ganhos_html(df, total, total_pct, investido)
    st.components.v1.html(html, height=altura, scrolling=False)


def tela_rentabilidade():
    escolha = st.radio('Período', list(PERIODOS.keys()), horizontal=True, index=2)

    hoje = date.today()
    if escolha == 'Total':
        inicio, fim = None, hoje
    elif escolha == 'Personalizado':
        col1, col2 = st.columns(2)
        inicio = col1.date_input('De', value=hoje - timedelta(days=365))
        fim = col2.date_input('Até', value=hoje)
    else:
        inicio, fim = hoje - PERIODOS[escolha], hoje

    params = {'fim': fim.isoformat()}
    if inicio:
        params['inicio'] = inicio.isoformat()

    resp = get_sessao().get(f'{API_BASE_URL}/carteira/rentabilidade', params=params)
    if resp.status_code != 200:
        st.error('Não foi possível carregar a rentabilidade.')
        return

    dados = resp.json()
    if not dados['diaria']:
        st.info('Sem dados de rentabilidade nesse período.')
        return

    df_diaria = pd.DataFrame(dados['diaria'])
    df_diaria['dt_dia'] = pd.to_datetime(df_diaria['dt_dia'])
    df_diaria['cumulativo_pct'] = (
        (1 + df_diaria['rentabilidade_pct'] / 100).cumprod() - 1
    ) * 100

    st.line_chart(df_diaria.set_index('dt_dia')['cumulativo_pct'])

    if dados['total_pct'] is not None:
        st.metric('Rentabilidade do período (juros compostos)', fmt_pct(dados['total_pct']))

    col_mensal, col_anual = st.columns(2)
    with col_mensal:
        st.subheader('Por mês')
        df_mensal = pd.DataFrame(dados['mensal']).rename(
            columns={'periodo': 'MÊS', 'rentabilidade_pct': 'RENTABILIDADE (%)'}
        )
        estilo_mensal = df_mensal.style.format({'RENTABILIDADE (%)': fmt_pct})
        estilo_mensal = estilo_mensal.map(cor_variacao, subset=['RENTABILIDADE (%)'])
        st.dataframe(estilo_mensal, use_container_width=True, hide_index=True)
    with col_anual:
        st.subheader('Por ano')
        df_anual = pd.DataFrame(dados['anual']).rename(
            columns={'periodo': 'ANO', 'rentabilidade_pct': 'RENTABILIDADE (%)'}
        )
        estilo_anual = df_anual.style.format({'RENTABILIDADE (%)': fmt_pct})
        estilo_anual = estilo_anual.map(cor_variacao, subset=['RENTABILIDADE (%)'])
        st.dataframe(estilo_anual, use_container_width=True, hide_index=True)


TELAS = {
    'Patrimônio': tela_posicao,
    'Ganhos': tela_ganhos,
    'Rentabilidade': tela_rentabilidade,
}

TIPOS_COTACAO = {
    'Sem ajuste (nominal na época)': 'vl_fechamento_nominal',
    'Ajustada apenas por eventos corporativos': 'vl_fechamento',
    'Ajustada por eventos corporativos e dividendos': 'vl_fechamento_ajustado',
}


def tela_acoes():
    st.title('Ações')

    if 'acoes_lista_tickers' not in st.session_state:
        resp = requests.get(f'{API_BASE_URL}/acoes/lista')
        st.session_state.acoes_lista_tickers = resp.json() if resp.status_code == 200 else []

    tickers = st.session_state.acoes_lista_tickers
    if not tickers:
        st.error('Não foi possível carregar a lista de ações.')
        return

    # le o ticker da URL (?ticker=PETR4) pra permitir link direto pra uma acao -- Streamlit
    # nao tem rota de caminho dinamico tipo /acoes/petr4 (precisaria de proxy/servidor
    # proprio na frente), query param e o equivalente real dentro do framework.
    ticker_url = st.query_params.get('ticker', '').upper()
    index_inicial = tickers.index(ticker_url) if ticker_url in tickers else 0

    ticker = st.selectbox('Ação', tickers, index=index_inicial)
    if st.query_params.get('ticker') != ticker:
        st.query_params['ticker'] = ticker

    opcoes_cotacao = list(TIPOS_COTACAO.keys())
    tipo_cotacao = st.selectbox(
        'Cotação', opcoes_cotacao,
        index=opcoes_cotacao.index('Ajustada por eventos corporativos e dividendos'),
    )
    campo = TIPOS_COTACAO[tipo_cotacao]

    escolha = st.radio('Período', list(PERIODOS.keys()), horizontal=True, index=2, key='acoes_periodo')
    hoje = date.today()
    if escolha == 'Total':
        inicio, fim = None, hoje
    elif escolha == 'Personalizado':
        col1, col2 = st.columns(2)
        inicio = col1.date_input('De', value=hoje - timedelta(days=365), key='acoes_de')
        fim = col2.date_input('Até', value=hoje, key='acoes_ate')
    else:
        inicio, fim = hoje - PERIODOS[escolha], hoje

    params = {'ticker': ticker, 'fim': fim.isoformat()}
    if inicio:
        params['inicio'] = inicio.isoformat()

    resp = requests.get(f'{API_BASE_URL}/acoes/cotacao', params=params)
    if resp.status_code != 200:
        st.error('Não foi possível carregar a cotação.')
        return

    dados = resp.json()
    if not dados:
        st.info('Sem cotações nesse período.')
        return

    df = pd.DataFrame(dados)
    df['dt_cotacao'] = pd.to_datetime(df['dt_cotacao'])

    # altair sem .interactive() de proposito -- st.line_chart (vega-lite) deixa zoom/pan
    # ligado por padrao e nao tem opcao pra desligar; aqui o grafico so muda pelos
    # controles (acao/cotacao/periodo), nunca por zoom/pan do mouse. O unico mouse-gesto
    # permitido e arrastar pra selecionar um intervalo (brush) e ver a rentabilidade entre
    # os dois pontos -- isso nao reescala o grafico, so marca a regiao e devolve o intervalo
    # pro Python via on_select/selection_mode.
    brush = alt.selection_interval(encodings=['x'], name='selecao')
    grafico = alt.Chart(df).mark_line().encode(
        x=alt.X('dt_cotacao:T', title=None),
        y=alt.Y(f'{campo}:Q', title=None),
    ).add_params(brush)

    evento = st.altair_chart(
        grafico, use_container_width=True,
        on_select='rerun', key=f'grafico_cotacao_{ticker}_{campo}',
    )

    intervalo = (evento.get('selection') or {}).get('selecao') if evento else None
    limites = (intervalo or {}).get('dt_cotacao')
    if limites:
        # o vega devolve o intervalo em milissegundos desde epoch -- sem unit='ms',
        # pd.to_datetime interpreta como nanosegundos e o filtro abaixo fica vazio
        # silenciosamente (sem erro nenhum).
        ts_inicio, ts_fim = sorted(limites)
        sub = df[
            (df['dt_cotacao'] >= pd.to_datetime(ts_inicio, unit='ms')) &
            (df['dt_cotacao'] <= pd.to_datetime(ts_fim, unit='ms'))
        ]
        if len(sub) >= 2:
            valor_inicial = sub.iloc[0][campo]
            valor_final = sub.iloc[-1][campo]
            pct = (valor_final / valor_inicial - 1) * 100
            dt_ini = sub.iloc[0]['dt_cotacao'].strftime('%d/%m/%Y')
            dt_fim = sub.iloc[-1]['dt_cotacao'].strftime('%d/%m/%Y')
            st.metric(f'Variação de {dt_ini} até {dt_fim}', f'{pct:.2f}%')
    else:
        st.caption('Arraste sobre o gráfico pra selecionar um intervalo e ver a variação entre as duas datas.')


def tela_principal():
    usuario = usuario_logado()
    with st.sidebar:
        st.write(f"Logado como **{usuario['nm_usuario']}**")
        st.caption(usuario['ds_email'])
        if st.button('Sair'):
            get_sessao().post(f'{API_BASE_URL}/auth/logout')
            st.session_state.clear()
            st.rerun()
        st.divider()
        secao = st.radio('Menu', list(TELAS.keys()), label_visibility='collapsed')

    st.title('Minha Carteira')
    TELAS[secao]()


with st.sidebar:
    _area_default = 'Ações' if st.query_params.get('ticker') else 'Carteira'
    area = st.radio(
        'Área', ['Carteira', 'Ações'], horizontal=True,
        index=['Carteira', 'Ações'].index(_area_default),
        label_visibility='collapsed',
    )
    st.divider()

if area == 'Ações':
    tela_acoes()
elif usuario_logado():
    tela_principal()
else:
    tela_login()
