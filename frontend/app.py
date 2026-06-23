from datetime import date, timedelta

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


COLUNAS_GANHOS = {
    'sg_ticker': 'TICKER',
    'ganho_realizado_vendas': 'GANHO REALIZADO (VENDAS)',
    'proventos': 'PROVENTOS',
    'ganho_nao_realizado': 'GANHO NÃO REALIZADO',
    'ganho_total': 'GANHO TOTAL',
    'valor_investido': 'VALOR INVESTIDO',
    'ganho_pct_total': 'GANHO TOTAL (%)',
}


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
        body {{ margin: 0; font-family: "Source Sans Pro", sans-serif; }}
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
        .totais td {{ border-bottom: 2px solid #ddd; background: #ffffff; }}
        .totais .rotulo {{ color: rgba(49,51,63,0.6); font-size: 11px; font-weight: normal; text-transform: none; }}
        .totais .valor {{ font-weight: 600; white-space: nowrap; }}
        .seta {{ margin-left: 4px; }}
        .variacao {{ display: flex; justify-content: space-between; gap: 4px; white-space: nowrap; }}
        .pos {{ color: green; }}
        .neg {{ color: red; }}
    </style>
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
                    <div class="valor" style="{cor_total}">{fmt_brl(variacao_total)}   {fmt_pct(variacao_total_pct)}</div>
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

    altura = 86 + 40 * len(df)
    html = tabela_patrimonio_html(df, variacao_total, variacao_total_pct, valor_total, cor_total)
    st.components.v1.html(html, height=altura, scrolling=True)


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

    df_exibicao = df.drop(columns='id_ativo').rename(columns=COLUNAS_GANHOS)
    colunas_variacao = ['GANHO REALIZADO (VENDAS)', 'GANHO NÃO REALIZADO', 'GANHO TOTAL', 'GANHO TOTAL (%)']
    estilo = df_exibicao.style.format({
        'GANHO REALIZADO (VENDAS)': fmt_brl,
        'PROVENTOS': fmt_brl,
        'GANHO NÃO REALIZADO': fmt_brl,
        'GANHO TOTAL': fmt_brl,
        'VALOR INVESTIDO': fmt_brl,
        'GANHO TOTAL (%)': fmt_pct,
    })
    estilo = estilo.map(cor_variacao, subset=colunas_variacao)
    st.dataframe(estilo, use_container_width=True, hide_index=True)

    col1, col2, col3 = st.columns(3)
    col1.metric('Ganho total', fmt_brl(total))
    col2.metric('Valor investido', fmt_brl(investido))
    col3.metric('Ganho % sobre investido', fmt_pct(100 * total / investido))


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


if usuario_logado():
    tela_principal()
else:
    tela_login()
