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


COLUNAS_POSICAO = {
    'sg_ticker': 'Ticker',
    'quantidade': 'Quantidade',
    'preco_medio': 'Preço Médio',
    'preco_atual': 'Preço Atual',
    'vl_posicao': 'Valor em Carteira',
}

COLUNAS_GANHOS = {
    'sg_ticker': 'Ticker',
    'ganho_realizado_vendas': 'Ganho Realizado (Vendas)',
    'proventos': 'Proventos',
    'ganho_nao_realizado': 'Ganho Não Realizado',
    'ganho_total': 'Ganho Total',
    'valor_investido': 'Valor Investido',
    'ganho_pct_total': 'Ganho Total (%)',
}


def tela_posicao():
    resp = get_sessao().get(f'{API_BASE_URL}/carteira/posicao')
    if resp.status_code != 200:
        st.error('Não foi possível carregar o patrimônio.')
        return

    linhas = resp.json()
    if not linhas:
        st.info('Você ainda não tem nenhuma posição. Importe suas operações pra começar.')
        return

    df = pd.DataFrame(linhas).sort_values('ganho_capital_pct', ascending=False)
    valor_total = df['vl_posicao'].sum()
    df['peso_carteira_pct'] = 100 * df['vl_posicao'] / valor_total
    df['variacao'] = [
        f'{fmt_brl(nominal)} ({fmt_pct(pct)})'
        for nominal, pct in zip(df['ganho_capital'], df['ganho_capital_pct'])
    ]

    df_exibicao = df.drop(columns=['nm_ativo', 'data_cotacao', 'ganho_capital', 'ganho_capital_pct']).rename(
        columns={**COLUNAS_POSICAO, 'peso_carteira_pct': '% da Carteira', 'variacao': 'Variação'}
    )
    estilo = df_exibicao.style.format({
        'Quantidade': fmt_num,
        'Preço Médio': fmt_brl,
        'Preço Atual': fmt_brl,
        'Valor em Carteira': fmt_brl,
        '% da Carteira': fmt_pct,
    })
    st.dataframe(estilo, use_container_width=True, hide_index=True)
    st.metric('Valor total em carteira', fmt_brl(valor_total))


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
    estilo = df_exibicao.style.format({
        'Ganho Realizado (Vendas)': fmt_brl,
        'Proventos': fmt_brl,
        'Ganho Não Realizado': fmt_brl,
        'Ganho Total': fmt_brl,
        'Valor Investido': fmt_brl,
        'Ganho Total (%)': fmt_pct,
    })
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
            columns={'periodo': 'Mês', 'rentabilidade_pct': 'Rentabilidade (%)'}
        )
        st.dataframe(
            df_mensal.style.format({'Rentabilidade (%)': fmt_pct}),
            use_container_width=True,
            hide_index=True,
        )
    with col_anual:
        st.subheader('Por ano')
        df_anual = pd.DataFrame(dados['anual']).rename(
            columns={'periodo': 'Ano', 'rentabilidade_pct': 'Rentabilidade (%)'}
        )
        st.dataframe(
            df_anual.style.format({'Rentabilidade (%)': fmt_pct}),
            use_container_width=True,
            hide_index=True,
        )


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
