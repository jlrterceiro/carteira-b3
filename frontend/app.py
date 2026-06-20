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


def tela_posicao():
    resp = get_sessao().get(f'{API_BASE_URL}/carteira/posicao')
    if resp.status_code != 200:
        st.error('Não foi possível carregar a posição.')
        return

    linhas = resp.json()
    if not linhas:
        st.info('Você ainda não tem nenhuma posição. Importe suas operações pra começar.')
        return

    df = pd.DataFrame(linhas)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.metric('Valor total em carteira', f"R$ {df['vl_posicao'].sum():,.2f}")


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
    st.dataframe(df, use_container_width=True, hide_index=True)

    total = df['ganho_total'].sum()
    investido = df['valor_investido'].sum()
    col1, col2, col3 = st.columns(3)
    col1.metric('Ganho total', f'R$ {total:,.2f}')
    col2.metric('Valor investido', f'R$ {investido:,.2f}')
    col3.metric('Ganho % sobre investido', f'{100 * total / investido:.2f}%')


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
        st.metric('Rentabilidade do período (juros compostos)', f"{dados['total_pct']:.2f}%")

    col_mensal, col_anual = st.columns(2)
    with col_mensal:
        st.subheader('Por mês')
        df_mensal = pd.DataFrame(dados['mensal']).rename(
            columns={'periodo': 'Mês', 'rentabilidade_pct': 'Rentabilidade (%)'}
        )
        st.dataframe(df_mensal, use_container_width=True, hide_index=True)
    with col_anual:
        st.subheader('Por ano')
        df_anual = pd.DataFrame(dados['anual']).rename(
            columns={'periodo': 'Ano', 'rentabilidade_pct': 'Rentabilidade (%)'}
        )
        st.dataframe(df_anual, use_container_width=True, hide_index=True)


def tela_principal():
    usuario = usuario_logado()
    with st.sidebar:
        st.write(f"Logado como **{usuario['nm_usuario']}**")
        st.caption(usuario['ds_email'])
        if st.button('Sair'):
            get_sessao().post(f'{API_BASE_URL}/auth/logout')
            st.session_state.clear()
            st.rerun()

    st.title('Minha Carteira')
    aba_posicao, aba_ganhos, aba_rentabilidade = st.tabs(['Posição atual', 'Ganhos', 'Rentabilidade'])
    with aba_posicao:
        tela_posicao()
    with aba_ganhos:
        tela_ganhos()
    with aba_rentabilidade:
        tela_rentabilidade()


if usuario_logado():
    tela_principal()
else:
    tela_login()
