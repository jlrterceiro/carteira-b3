# Scraper — rastreador de carteira de investimentos

Projeto pessoal multi-usuário: cada usuário tem sua carteira de investimentos B3, importada
via extrato de negociação. Hoje tem 3 usuários (`jlrterceiro`, `mario.eulalio`, `ediesley`),
cada um com uma carteira chamada `Carteira Aposentadoria` (nomes podem repetir entre usuários
— a unicidade é por `id_usuario`). Corretoras cadastradas: NU INVESTIMENTOS S.A. - CTVM e
XP INVESTIMENTOS CCTVM S/A.

Banco Postgres local `investimentos`, usuário `terceiro`, host `localhost`, porta `5432`.
Credenciais ficam em `.env` na raiz do projeto (não commitado em lugar nenhum, é só local) —
`db_lib.py` carrega esse arquivo automaticamente antes de conectar. Pra rodar SQL direto:
`PGPASSWORD=<senha> psql -h localhost -U terceiro -d investimentos -f arquivo.sql` (senha
está no `.env`).

## Estrutura de pastas

Projeto pensado pra eventualmente virar multi-usuário "de verdade" (API + frontend, talvez
profissional) — por isso a separação:

- `db_lib.py` (raiz) — `get_conn()` + carregamento do `.env`. Compartilhado por `scrape/` e
  `backend/`; cada script faz `sys.path.insert(0, ...)` pra subir até a raiz e importar.
- `scrape/` — tudo que busca dado de fonte externa (yfinance, dadosdemercado.com.br) ou de
  arquivo (planilha de negociação) e grava no banco. `scrape/scraper_lib.py` tem só os
  helpers de scraping HTML (`get_html`, `parse_tickers`, `normalize_ticker`, `BASE`) — não
  tem `get_conn` mais, isso é responsabilidade do `db_lib.py`. `scrape/importados/` guarda as
  planilhas já importadas.
- `backend/` — schema (`backend/schema/*.sql`), funções de cálculo (`backend/functions/*.sql`),
  testes de regressão (`backend/tests/test_validacoes.sql`), geradores de relatório PDF/Excel
  (`backend/relatorios/*.py`) e a API (`backend/api/`, ver seção própria abaixo).
- `frontend/` — `app.py`, dashboard Streamlit (ver seção própria abaixo).

Se trocar a fonte de dados de cotação/balanço/etc no futuro, só precisa trocar o scraper
correspondente em `scrape/` — nada em `backend/` referencia yfinance ou dadosdemercado.com.br
diretamente, só lê das tabelas.

## Schema (public, 26 tabelas)

- `tb_usuario` → `tb_carteira` → `tb_operacao` (compra/venda/transferência/dividendo/etc, ver `tb_tipo_operacao`)
- `tb_emissor` → `tb_ativo` (ticker, classe ON/PN/UNIT) → `tb_cotacao` (histórico de preços diário)
- `tb_evento_corporativo` (SPLIT/GRUP, com `vl_fator`) por `id_ativo`
- `tb_provento` (valor bruto por ação por `id_ativo`+`dt_ex`, raw do yfinance) +
  `vl_unitario_ajustado` (corrigido por `fn_popula_provento_ajustado`, ver seção de splits abaixo)
- `tb_posicao_diaria` — snapshot diário (carteira, corretora, ativo), recalculado do zero por `fn_popula_posicao_diaria`
- `tb_provento_recebido` — proventos cruzados com a posição na data-com, uma linha só por evento real (não preenche dia a dia)
- `tb_rentabilidade_ativo_diaria` — ganho/base em R$ por (carteira, corretora, ativo, dia de pregão)
- `tb_rentabilidade_diaria` — rollup de `tb_rentabilidade_ativo_diaria` via `GROUPING SETS` sobre usuário/carteira/corretora (8 combinações por dia, `NULL` = "todos" naquela dimensão)
- `tb_balanco_patrimonial` — balanço (só ações), 14 métricas curadas, TRIMESTRAL via dados abertos da CVM (ver seção própria abaixo)
- `tb_balanco_conta` — auxiliar/raw: TODAS as contas do plano de contas da CVM pro balanço, sem curadoria, usada por `popula_balanco.py` pra montar `tb_balanco_patrimonial` (ver seção própria abaixo)
- `tb_balanco_patrimonial_old_yfinance` — histórica/descontinuada, balanço via yfinance, não recebe mais atualização (ver seção própria abaixo)
- `tb_dre` — DRE (só ações), 15 métricas curadas, TRIMESTRAL via dados abertos da CVM (ver seção própria abaixo)
- `tb_dre_conta` — auxiliar/raw: TODAS as contas do plano de contas da CVM, sem curadoria, usada por `popula_dre.py` pra montar `tb_dre` (ver seção própria abaixo)
- `tb_dre_old_yfinance` — histórica/descontinuada, DRE via yfinance, não recebe mais atualização (ver seção própria abaixo)
- `tb_dfc` — demonstração de fluxo de caixa (só ações), 5 métricas curadas, TRIMESTRAL via dados abertos da CVM (ver seção própria abaixo)
- `tb_dfc_conta` — auxiliar/raw: TODAS as contas do plano de contas da CVM pro fluxo de caixa, sem curadoria, usada por `popula_dfc.py` pra montar `tb_dfc` (ver seção própria abaixo)
- `tb_valor_mercado` — snapshot de valor de mercado por dia de raspagem (`fast_info.marketCap` do yfinance), histórico se constrói rodando o scraper periodicamente
- `tb_ticker_historico` / `tb_corretora_historico` — mapeiam nomes antigos pra ids atuais (tickers trocados, corretoras renomeadas/fundidas)

Volume em 2026-06-21: ~400 ativos, ~1100 operações, ~750 eventos corporativos, ~1,70M
cotações, ~229k linhas de posição diária, ~10,9k proventos brutos, ~20k linhas de balanço
(CVM, TRIMESTRAL — inclui 1T/2T/3T via ITR e 4T via DFP), ~25k linhas de DRE (CVM,
~20k TRIMESTRAL incluindo 4T derivado por subtração + ~5k ANUAL via DFP), ~25k linhas de DFC
(mesma mistura TRIMESTRAL/ANUAL da DRE).

## Scripts Python (`scrape/`)

- `scraper_lib.py` — helpers de scraping HTML (`get_html`, `parse_tickers`, `normalize_ticker`, `BASE`)
- `scraper_emissores.py`, `scraper_ativos.py` — raspam dadosdemercado.com.br (`/acoes`) via regex em HTML
- `scraper_cotacoes.py <TICKER opcional>` — histórico completo de preços via yfinance (`TICKER.SA`), substitui tudo (`DELETE` + reinsere)
- `scraper_eventos_corporativos.py <TICKER opcional>` — splits/grupamentos via `yfinance` (`t.splits`)
- `scraper_proventos.py <TICKER opcional>` — dividendos/JCP/rendimento via `yfinance` (`t.dividends`), valor bruto raw (sem distinguir tipo)
- `scraper_balanco_patrimonial.py <TICKER opcional>` — raspagem crua do balanço via dados abertos da CVM, só ações, popula só `tb_balanco_conta` (ver seção própria abaixo). `popula_balanco.py <TICKER opcional>` — curadoria local (lê `tb_balanco_conta`, sem rede) que popula `tb_balanco_patrimonial`, mesmo padrão de separação do DRE. `scraper_qt_acoes.py <TICKER opcional>` — só atualiza `qt_acoes` em `tb_balanco_patrimonial` via yfinance (`Ordinary Shares Number`), `UPDATE`-only (nunca `INSERT`, a linha já existe via `popula_balanco.py`) — ver seção própria abaixo pro motivo. `scraper_balanco_patrimonial_old_yfinance.py` — histórico/descontinuado, não roda mais.
- `scraper_dre.py <TICKER opcional>` — raspagem crua da DRE via dados abertos da CVM, só ações, popula só `tb_dre_conta` (ver seção própria abaixo). `popula_dre.py <TICKER opcional>` — curadoria local (lê `tb_dre_conta`, sem rede) que popula `tb_dre`; separado do scraper de propósito, pra corrigir bug de casamento sem precisar rebaixar nada da CVM. `scraper_dre_old_yfinance.py` — histórico/descontinuado, não roda mais (ver seção própria abaixo).
- `scraper_dfc.py <TICKER opcional>` — raspagem crua do fluxo de caixa via dados abertos da CVM, só ações, popula só `tb_dfc_conta` (ver seção própria abaixo). `popula_dfc.py <TICKER opcional>` — curadoria local (lê `tb_dfc_conta`, sem rede) que popula `tb_dfc`, mesmo padrão de separação da DRE/balanço.
- `scraper_valor_mercado.py <TICKER opcional>` — valor de mercado via yfinance (`fast_info.marketCap`), só ações, um snapshot por dia de execução.
- `import_operacoes.py <arquivo.xlsx> <sg_usuario>` — importa export de negociação da B3 pra carteira `Carteira Aposentadoria` do usuário informado, dedup por (ativo, tipo, data, qtd, preço) contando ocorrências já existentes. Planilhas já importadas ficam em `scrape/importados/`.

## Geradores de relatório (`backend/relatorios/`)

- `gerar_relatorio_pdf.py <sg_usuario> <nome> <caminho.pdf>` — relatório de ganhos completo (igual `fn_ganho_total`) em PDF.
- `gerar_relatorio_ncav.py` — top 20 ações por desconto de NCAV (ver seção própria abaixo), em PDF e Excel.

## API (`backend/api/`)

FastAPI fininho sobre as funções SQL existentes — autenticação por JWT em cookie `httpOnly`
(`JWT_SECRET` no `.env`, validade 7 dias, sem refresh token ainda). Subir com
`uvicorn backend.api.main:app --reload` a partir da raiz do projeto; `/docs` tem o Swagger.

- `security.py` — hash/verificação de senha (`bcrypt`), cria/decodifica token (`pyjwt`).
- `deps.py` — `get_current_user` (lê o cookie, decodifica o JWT, busca o usuário em
  `tb_usuario` por `id_usuario` do token) e `get_db`. **Todo endpoint protegido usa o
  `sg_usuario` do usuário autenticado pra filtrar as funções SQL — nunca um parâmetro vindo
  do cliente.**
- `auth.py` — `POST /auth/cadastro` (cria usuário + carteira default "Carteira Principal";
  se o e-mail já existir em `tb_usuario` sem `ds_senha_hash`, "reivindica" a conta em vez de
  criar outra — é assim que os 3 usuários que já existiam sem senha entram no sistema),
  `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.
- `carteira.py` — `GET /carteira/posicao` (`fn_posicao_atual`), `GET /carteira/ganhos`
  (`fn_ganho_total`), ambos protegidos.

`tb_usuario.ds_senha_hash` é nullable de propósito — usuário cadastrado antes da API (direto
no banco) não tem senha até passar pelo fluxo de reivindicação em `/auth/cadastro`.

Sem recuperação de senha, verificação de e-mail ou revogação de token ainda — endpoints de
escrita (importar operação, rodar scraper) também não estão expostos, só leitura por agora.

## Frontend (`frontend/app.py`)

Dashboard Streamlit, consome só a API (`backend/api/`) via HTTP — nunca acessa o banco
direto. Roda com `streamlit run frontend/app.py` (precisa da API rodando em paralelo,
`http://localhost:8000` por padrão — ver `API_BASE_URL` no topo do arquivo). Guarda a sessão
HTTP (com o cookie do JWT) em `st.session_state`, que persiste entre os reruns do Streamlit
pra a mesma sessão de navegador — login fica "lembrado" enquanto a aba estiver aberta.

Telas: login/cadastro (cadastro reaproveita o fluxo de "reivindicar" conta do `/auth/cadastro`
— tem um aviso na tela sobre isso pra quem já tem conta criada direto no banco) e, depois de
logado, abas de Posição atual, Ganhos e Rentabilidade.

A aba Rentabilidade usa `GET /carteira/rentabilidade?inicio=&fim=` (ambos opcionais — sem
`inicio` é "desde o início"), que devolve a série diária do `tb_rentabilidade_diaria` do
usuário (rollup `id_carteira IS NULL AND id_corretora IS NULL`) mais o agregado por mês/ano/
total já calculado em SQL via juros compostos (`EXP(SUM(LN(1+pct/100)))-1`, igual o resto do
projeto — NUNCA somar percentual direto). O frontend recalcula a curva acumulada localmente
em cima da série diária pra plotar o gráfico (mesma fórmula, só que ponto a ponto); o valor
final dessa curva sempre bate com `total_pct` vindo da API.

## Pipeline de recálculo

Depois de importar operação nova ou rodar qualquer scraper, rodar:

```sql
SELECT fn_rebuild_tudo();
```

Isso chama, na ordem certa: `fn_popula_provento_ajustado` → `fn_popula_posicao_diaria` →
`fn_popula_provento_recebido` → `fn_popula_rentabilidade_ativo_diaria` →
`fn_popula_rentabilidade_diaria`. A ordem importa (cada uma depende da anterior) — usar essa
função em vez de rodar as 5 manualmente. `tb_balanco_patrimonial`/`tb_valor_mercado` não
entram nesse pipeline (não dependem de nada, são só raspagem direta).

`backend/tests/test_validacoes.sql` tem alguns testes de regressão (conferidos contra fontes
oficiais) — rodar depois de qualquer mudança nas funções de cálculo.

## Splits/grupamentos retroativos (cuidado nisso)

yfinance reescreve o histórico de **preço de cotação** e de **valor de provento por ação**
retroativamente pra refletir splits/grupamentos que aconteceram DEPOIS daquela data (assim o
gráfico/histórico fica contínuo). Isso quebra qualquer comparação direta entre um preço
nominal histórico (`tb_operacao.vl_preco_unitario`, `tb_provento.vl_unitario`, ambos raw) e
uma cotação/provento do yfinance pra mesma data, se houve split depois.

`fn_fator_acumulado(id_ativo, dt_referencia)` calcula o produto dos fatores de
`tb_evento_corporativo` ocorridos DEPOIS da data — usado em dois lugares, em direções opostas:
- **Rentabilidade diária**: preço de compra/venda (raw) é DIVIDIDO pelo fator antes de comparar com `tb_cotacao` (já ajustada).
- **Provento**: valor por ação do yfinance (já ajustado pra baixo) é MULTIPLICADO pelo fator pra recuperar o valor real pago na época, gravado em `tb_provento.vl_unitario_ajustado`.

yfinance também tem **eventos de split duplicados** às vezes (mesmo fator, poucos dias de
diferença — bug deles, confirmado contra fontes oficiais várias vezes, e que volta toda vez
que o scraper roda de novo porque a fonte continua reportando os dois). Por isso
`scraper_eventos_corporativos.py` chama `remove_duplicados()` no final de toda execução,
removendo automaticamente a data mais recente de cada par (mesmo `id_ativo`+`vl_fator`, até 14
dias de diferença). `test_validacoes.sql` confere que não sobra nenhum par desses.

yfinance também rate-limita/bloqueia depois de raspagens pesadas (centenas de tickers) — se
um scraper começar a retornar tudo vazio/"possibly delisted" pra tickers que sabidamente
existem, é isso, não bug: esperar alguns minutos e tentar de novo.

## Same-day COMPRA/VENDA: tie-break

Quando uma planilha de negociação lista VENDA antes de COMPRA no mesmo dia/ativo/carteira/
corretora, isso pode gerar quantidade negativa transitória e inflar o ganho calculado (venda
contra custo médio zero). Conta de pessoa física no fracionário não vende a descoberto, então
a compra teve que ter vindo primeiro na vida real — `fn_extrato_ativo`, `fn_ganho_realizado_venda`
e `fn_popula_posicao_diaria` desempatam por isso: evento corporativo antes de operação, e
dentro de operação, COMPRA antes de VENDA no mesmo dia (`ORDER BY dt, (fator IS NULL), (tipo = 'VENDA'), seq`).

## Funções/queries SQL (`backend/functions/`)

Todas as funções de cálculo (`fn_extrato_ativo`, `fn_ganho_realizado_venda`,
`fn_popula_posicao_diaria`) seguem o mesmo padrão: para cada grupo
(carteira, corretora, ativo), percorrem COMPRA/VENDA + eventos corporativos em ordem
cronológica (ver tie-break acima), mantendo:
- quantidade corrente
- preço médio ponderado (recalculado em COMPRA, dividido por `vl_fator` em SPLIT/GRUP, inalterado em VENDA)

Ao criar uma nova função de extrato/ganho, replicar esse mesmo loop para manter os números
consistentes entre as funções.

- `fn_extrato_ativo(ticker, usuario?)` — extrato evento a evento de um ativo, em ordem
  cronológica única (todas as corretoras misturadas), com ganho realizado por venda e total no fim.
- `fn_ganho_realizado_venda(dt_inicio?, dt_fim?, carteira?, corretora?, usuario?)` — ganho de
  capital realizado agregado por ativo, com filtro de período opcional.
- `fn_extrato_provento(dt_inicio?, dt_fim?, carteira?, corretora?, usuario?)` — extrato de
  proventos linha a linha (uma por ativo+data ex), lendo de `tb_provento_recebido`.
- `fn_provento_recebido(dt_inicio?, dt_fim?, carteira?, corretora?, usuario?)` — proventos
  totais por ativo, mesmos filtros.
- `fn_ganho_total(dt_inicio?, dt_fim?, carteira?, corretora?, usuario?)` — por ativo:
  `ganho_realizado_vendas`, `proventos`, `ganho_nao_realizado`, `ganho_total`,
  `valor_investido` (total histórico comprado, não filtra por período) e `ganho_pct_total`.
  Combina as três funções acima + posição atual x cotação mais recente.
- `fn_posicao_atual(usuario?)` / `fn_posicao_acoes(usuario?)` — posição atual usando
  `tb_posicao_diaria` (já considera eventos corporativos). Praticamente equivalentes hoje;
  existem dois nomes por causa de uma versão antiga de `fn_posicao_acoes` que calculava
  direto de `tb_operacao` sem ajuste de split (estava errada, foi corrigida).
- `fn_popula_posicao_diaria()` / `fn_popula_provento_ajustado()` / `fn_popula_provento_recebido()` /
  `fn_popula_rentabilidade_ativo_diaria()` / `fn_popula_rentabilidade_diaria()` — populam as
  tabelas derivadas, chamadas em ordem por `fn_rebuild_tudo()`.

## Rentabilidade diária (TWR)

`tb_rentabilidade_ativo_diaria` guarda, por (carteira, corretora, ativo, dia de pregão),
`vl_base` (capital exposto no dia) e `vl_ganho` (ganho em R$, incluindo provento do dia). A
fórmula usa o fechamento de ontem como referência (não a abertura de hoje) pra capturar
também o retorno overnight — isso é necessário pra capturar o efeito de ex-dividendo
corretamente (o preço cai no ex, o provento compensa, ambos no mesmo dia).

Pra rentabilidade composta de um período: `EXP(SUM(LN(1 + rentabilidade_pct/100))) - 1`
sobre as linhas de `tb_rentabilidade_diaria` filtradas (NÃO somar os percentuais — isso dá
resultado errado).

**Não trata `TRANSF`** (transferência entre carteira/corretora) — só `fn_popula_posicao_diaria`
trata isso hoje. Se uma transferência acontecer, o dia da transferência vai calcular
base/ganho errado nessa tabela. Pendente.

CDI, SELIC, Ibovespa e S&P 500 não fazem parte do banco — quando pedido, busco sob demanda
(BCB SGS API pra CDI/SELIC, yfinance `^BVSP`/`^GSPC` pros índices).

## Análise fundamentalista (NCAV / net-net)

`backend/relatorios/gerar_relatorio_ncav.py` calcula, por ação, NCAV = Ativo Circulante −
Passivo Total (só pra quem tem Patrimônio Líquido > 0 e Ativo Circulante > Passivo Total) e
ordena por Valor de Mercado / NCAV ascendente — valores menores indicam desconto tipo Graham
"net-net" (mercado paga menos que o ativo circulante líquido da empresa). Não confundir com
ordenar pelo inverso (NCAV/VM maior) achando que é o mesmo: dá o mesmo ranking, só muda a
direção de leitura do número.

## Balanço patrimonial

Mesma migração da DRE, mesmo motivo: troca de yfinance pra dados abertos da CVM
(`dados.cvm.gov.br`), pipeline em duas etapas (`scraper_balanco_patrimonial.py` cru →
`tb_balanco_conta`, `popula_balanco.py` curadoria local sem rede → `tb_balanco_patrimonial`).
`tb_balanco_patrimonial_old_yfinance` fica como histórico, não recebe mais atualização.

A CVM publica ativo (`BPA`) e passivo (`BPP`) em arquivos separados (diferente da DRE, que é
um arquivo só) — `scraper_balanco_patrimonial.py` junta os dois pelo mesmo
(`dt_referencia`, `tp_periodo`) antes de gravar em `tb_balanco_conta`; `cd_conta` começando
com `'1'` é do ativo, com `'2'` é do passivo, então cabem na mesma tabela sem coluna extra.
Balanço é foto (`DT_FIM_EXERC`), não fluxo como a DRE — não tem o problema de
trimestre-isolado-vs-acumulado, só o filtro padrão `ORDEM_EXERC='ÚLTIMO'` (ignora o
comparativo do ano anterior). Mesmo fallback consolidado→individual da DRE pras empresas sem
subsidiária pra consolidar (Sanepar, Comgás, bancos estaduais pequenos).

**4T via DFP**: não existe "4º ITR" — a CVM só publica o balanço de 31/12 depois do
encerramento do exercício, via DFP (anual). Diferente da DRE/DFC (fluxo, precisa de
subtração pra isolar o trimestre), o balanço é foto — o BPA/BPP do DFP em 31/12 JÁ É o "4T",
sem nenhuma transformação. `scraper_balanco_patrimonial.py` simplesmente busca tanto ITR
quanto DFP (`for tipo in ('itr', 'dfp')`) e grava tudo com `tp_periodo='TRIMESTRAL'` direto —
`popula_balanco.py` não precisou de nenhuma mudança, processa o 31/12 vindo do DFP exatamente
igual a qualquer outro trimestre vindo do ITR.

Mesmo achado de perfil da DRE: bancos "de depósito" (BBAS3, BPAC3 etc. — não BRBI11, banco de
investimento, que segue o plano padrão) têm plano de contas diferente pro ativo/passivo, sem
o conceito de circulante/não circulante (`cd_conta='1.01'` é "Ativo Circulante" pro padrão,
"Caixa e Equivalentes de Caixa" pro banco — mesmo código, conceito totalmente diferente).
`vl_ativo_total` (`'1'`) e `vl_passivo_total` (`'2'`) são estáveis nos dois perfis; todo o
resto é casado por texto de `ds_conta` normalizado em `popula_balanco.py`.
`vl_ativo_circulante`/`vl_passivo_circulante`/`vl_capital_giro` ficam `NULL` pro perfil banco
— não é dado faltando, o conceito não existe nesse plano de contas. Achado um perfil a mais
que a DRE não tinha: seguradoras (BBSE3) seguem o plano padrão (têm Ativo/Passivo Circulante
normal) mas genuinamente não têm linha de "Empréstimos e Financiamentos" — `vl_divida_total`
fica `NULL` só pra esse caso, também não é bug.

`vl_patrimonio_liquido_total`/`vl_patrimonio_liquido`/`vl_participacao_nao_controladores`
seguem o mesmo padrão da DRE (`vl_lucro_liquido_total`/`vl_lucro_liquido`) — "Patrimônio
Líquido Consolidado" inclui participação de não controladores, confirmado em EVEN3 (total
2.305.504 − participação 377.994 = 1.927.510, bate exato com o "Stockholders Equity" do
yfinance, que só contava a parte dos controladores sem deixar isso explícito). A frase de
não-controladores no `ds_conta` varia por empresa ("Participação dos Acionistas Não
Controladores" como irmã das reservas em algumas, "Patrimônio Líquido Atribuído aos Não
Controladores" como filho direto em outras) — `popula_balanco.py` casa só por "não
controlador", que cobre as duas variações.

`vl_caixa`: caixa + aplicações financeiras de curto prazo (`1.01.01` + `1.01.02`) pro perfil
padrão; só o caixa estreito (`1.01`) pro perfil banco — o "Ativos Financeiros" bancário
(`1.02`) inclui carteira de crédito/empréstimos a clientes, não é caixa.

**Bug encontrado e corrigido (validando contra o yfinance)**: 25 empresas (confirmado em
LOGG3) escondem um valor de "Títulos e Valores Mobiliários" dentro de "Outros Ativos
Circulantes" (`1.01.08`) em vez da linha padrão de Aplicações Financeiras (`1.01.02`) —
economicamente é a mesma coisa (título/aplicação de curto prazo), mas `vl_caixa` ficava até
~90% menor que o real pra essas empresas, já que só somava `1.01.01`+`1.01.02`. Corrigido
somando também o que casar com "títulos e valores mobiliários" dentro de `1.01.08`
especificamente — restrito a esse ramo de propósito, porque o mesmo texto também aparece
dentro de `1.01.01`/`1.01.02` (já contado, duplicaria) e de `1.01.03` "Contas a Receber" (não
é caixa, é recebível). Confirmado em LOGG3 1T26: `7.405 + 43.036 + 339.582 = 390.023` mil,
bate exato com o yfinance.

`vl_divida_total` pro perfil padrão soma "Empréstimos e Financiamentos" circulante e não
circulante (`2.01.04` + `2.02.01`, restringindo a busca por prefixo de `cd_conta` — o mesmo
texto existe nos dois níveis com a mesma profundidade, sem restringir o casamento por texto
empataria e podia pegar a conta errada). Pro perfil banco usa "Passivos Financeiros ao Custo
Amortizado" (`2.02`) inteiro — inclui depósito de cliente, mesmo problema já aceito pro "Total
Debt" do yfinance nesse setor (decisão anterior do usuário foi manter o número "imperfeito"
em vez de nulificar; mantido aqui pela mesma razão, só que agora com uma base mais completa
de passivos financeiros da CVM em vez do número opaco do yfinance). `vl_divida_liquida`
SEMPRE calculada como `vl_divida_total - vl_caixa`.

**Limitação conhecida, aceita de propósito (validando contra o yfinance)**: `vl_divida_total`
pro perfil padrão fica ~5-10% menor que o yfinance em várias empresas (confirmado em ITSA4:
gap de R$940mi bate exato com "Passivos de Arrendamentos" em `2.01.05.02.05`+`2.02.02.02.04` —
posições fora do ramo `2.01.04`/`2.02.01` que a curadoria já soma). Diferente do achado do
`vl_caixa` acima (frase única, posição única, fácil de generalizar), o texto de arrendamento
mercantil tem **112 variações diferentes** espalhadas por posições inconsistentes entre
empresas (incluindo erros de digitação na própria base, ex: "arrendamento merncatil") — mesma
categoria de instabilidade já aceita pro capex do DFC (ver seção própria). Decisão tomada:
manter como está, sem tentar casar por texto — o risco de pegar conta errada numa empresa
qualquer supera o ganho de fechar esse gap em algumas.

`vl_valor_patrimonial_tangivel` calculado como `vl_patrimonio_liquido - "Intangível"` (texto)
— a CVM não tem uma linha pronta de "tangible book value" como o yfinance tinha.

`qt_acoes` CONTINUA vindo do yfinance (`scraper_qt_acoes.py`, só esse campo, `UPDATE`-only) —
o arquivo `composicao_capital` da CVM (equivalente à contagem de ações) tem erro de escala
(1000x menor) em pelo menos VALE3 e ITSA4, mas bate certo em PETR4 e EVEN3; sem como validar
algoritmicamente quais empresas são afetadas sem outra fonte, optou-se por não usar esse
arquivo. Trade-off aceito: yfinance só cobre os últimos ~4-5 trimestres (ao contrário da CVM,
que cobre desde 2011), então `qt_acoes` fica `NULL` pra períodos mais antigos — não afeta o
trimestre mais recente, que é o que importa pra cálculo de valor por ação hoje.

## Demonstração de fluxo de caixa (DFC)

Mesma fonte (CVM) e mesmo pipeline em duas etapas da DRE/balanço
(`scraper_dfc.py` cru → `tb_dfc_conta`, `popula_dfc.py` curadoria local sem rede → `tb_dfc`).
A CVM publica ativo/passivo do fluxo de caixa em arquivos próprios: `DFC_MI` (Método
Indireto, usado por quase toda empresa) com fallback pra `DFC_MD` (Método Direto, poucas
empresas — ex: HAGA4) — mesma estrutura de `cd_conta` nos dois métodos, então o mesmo código
de extração serve pra ambos. Mesmo fallback consolidado→individual da DRE/balanço.

**Diferença importante em relação à DRE**: a CVM só publica o fluxo de caixa acumulado desde
o início do ano fiscal (nunca o trimestre isolado, mesmo a partir do 2º trimestre — diferente
da DRE, que publica os dois). `tb_dfc_conta` guarda o valor exatamente como vem (acumulado);
`popula_dfc.py` isola o trimestre por subtração dentro do mesmo ano civil (1T fica como está,
já que YTD do 1T é o próprio 1T; 2T = YTD 2T − YTD 1T; 3T = YTD 3T − YTD 2T) — assim
`tp_periodo='TRIMESTRAL'` continua significando "só aquele trimestre" em toda a base, igual
DRE/balanço.

**4T via DFP**: não existe "4º ITR" — a CVM só publica o ano inteiro depois do encerramento
do exercício, via DFP (anual), arquivo `dfp_cia_aberta_<ano>.zip` (mesmos nomes de CSV do
ITR, mesmo parser — só troca o `tipo` do download). `scraper_dfc.py` grava o DFP em
`tb_dfc_conta` com `tp_periodo='ANUAL'` (sempre o ano inteiro acumulado, igual o YTD do ITR,
sem filtro de isolamento — `carrega_ano` só pula o filtro de ~95 dias quando `tipo!='itr'`).
`popula_dfc.py` trata o ANUAL como "mais um período do ano" dentro de `isola_trimestres()`:
grava o total anual como está (`tp_periodo='ANUAL'`, valor isolado por si só) E, quando o
período imediatamente anterior é especificamente o 3T (mês 9), deriva o 4T isolado por
subtração do acumulado de 9 meses (`tp_periodo='TRIMESTRAL'`) — mesma lógica do 2T/3T, só que
subtraindo do acumulado anual em vez do trimestre anterior. Se faltar o 3T daquele ano (ITR
não entregue, falha de raspagem), o ANUAL fica como está, sem isolar — subtrair do período
errado geraria um 4T silenciosamente errado.

**Curadoria mais simples que DRE/balanço**: a posição por `cd_conta` (`6.01` a `6.05`) é
estável em todos os perfis testados, incluindo banco (BBAS3) e seguradora (BBSE3, só com o
nome de `6.01` mudando pra "Caixa Líquido Atividades Seguradora/Resseguradora") — não
precisou de detecção de perfil nem casamento por texto pros 5 totais, diferente da
DRE/balanço.

`vl_caixa_operacional + vl_caixa_investimento + vl_caixa_financiamento + vl_variacao_cambial`
soma exatamente `vl_variacao_caixa` (identidade contábil) em 99,8% das linhas — usado como
checagem de consistência na validação. Os ~0,2% que não batem são erro da própria fonte CVM,
não da curadoria: confirmado em AXIA3 (3T22), onde o módulo bate exato mas o **sinal** de
`6.05` vem invertido já no dado bruto (`6.01+6.02+6.03+6.04` = +3.921.783, `6.05` reportado
= −3.921.783) — mesma categoria de anomalia pontual já documentada pra CMIG4 (DRE)/MRVE3
(LPA), não dá pra "corrigir" de forma confiável sem arriscar mascarar um erro real em outro
lugar.

Capex (aquisição de imobilizado/intangível, sub-conta de `6.02`) ficou **fora** da curadoria
de propósito — testado em EVEN3/VALE3/KLBN3, a posição e o texto variam bem mais que o resto
do plano de contas (KLBN3 chega a ter capex florestal numa sub-conta separada da de
imobilizado/intangível) — quem precisar de capex de uma empresa específica consulta
`tb_dfc_conta` direto, calculando free cash flow manualmente a partir daí.

## Demonstração de resultado (DRE)

Fonte trocada de yfinance pra dados abertos da CVM (`dados.cvm.gov.br`) depois de achar que
`vl_resultado_financeiro` vindo do `Net Interest Income` do yfinance estava sistematicamente
errado (sinal E magnitude, confirmado contra o ITR oficial da Even em 3 trimestres
diferentes). `tb_dre_old_yfinance` fica como histórico, não recebe mais atualização;
`scraper_dre_old_yfinance.py` não roda mais.

Pipeline em duas etapas, de propósito separadas (raspar a CVM é lento — baixar+parsear ~16
anos de ITR pra todo o mercado; casar conta-por-texto é rápido — só leitura local; separar
evita ter que rebaixar tudo de novo só pra corrigir um bug de casamento):
- `scraper_dre.py <TICKER opcional>` — baixa os ZIPs anuais da CVM
  (`itr_cia_aberta_<ano>.zip`, `..._DRE_con_<ano>.csv`/`..._DRE_ind_<ano>.csv`, cache em
  `scrape/cvm_cache/`), filtra `ORDEM_EXERC='ÚLTIMO'` e o intervalo trimestre-isolado (ver
  abaixo), aplica a escala (`ESCALA_MOEDA` — 'MIL'/'MILHAO'/'UNIDADE', exceto contas de LPA
  3.99.\* que a CVM sempre reporta em reais absolutos) e grava **todas** as contas em
  `tb_dre_conta`, sem curadoria nenhuma. É por CNPJ/emissor (não por ticker) — o resultado é
  replicado pra todos os `id_ativo` daquele emissor (ON/PN/etc compartilham a mesma DRE).
- `popula_dre.py <TICKER opcional>` — lê `tb_dre_conta` (sem rede), detecta o perfil contábil
  e casa cada coluna de `tb_dre` por texto de `ds_conta` (normalizado: minúsculo + sem
  acento), grava em `tb_dre`. Roda de novo é rápido — é só essa etapa que precisa mudar pra
  corrigir um bug de casamento.

Cobertura: 378 de 384 ações. Os 6 que faltam não são bug — 5 são tickers antigos sem
`id_emissor` vinculado (BIDI3/BIDI11, CIEL3, ENBR3, CEPE6 — tickers trocados/descontinuados,
ver `tb_ticker_historico`) e PPLA11 não tem CNPJ em `tb_emissor`.

**Formato CVM é long/EAV, não wide**: uma linha por (empresa, período, conta do plano de
contas) — `CNPJ_CIA;DT_REFER;VERSAO;...;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA`. Duas
armadilhas no filtro:
- `ORDEM_EXERC` repete cada conta pro período comparativo do ano anterior
  (`'PENÚLTIMO'`) — só usar `'ÚLTIMO'`.
- A partir do 2º trimestre, a CVM reporta TANTO o trimestre isolado (`DT_INI_EXERC` = início
  daquele trimestre) QUANTO o acumulado desde janeiro (`DT_INI_EXERC` = 1º de janeiro) pro
  mesmo `DT_REFER` — sem filtrar por isso, pegaria o acumulado por engano (confirmado errado
  em EVEN3 3T25: peguei R$1.435.896 quando o trimestre isolado real era R$528.822).
  `scraper_dre.py` mantém só o intervalo ≤ ~95 dias (trimestre isolado); no 1º trimestre os
  dois coincidem, não tem ambiguidade.

**Consolidado (`_con`) é a fonte preferida** (mesma escolha do resto do projeto — lucro
atribuível aos controladores etc.), com fallback pra individual (`_ind`) nos períodos que
faltarem no consolidado: empresa sem subsidiária pra consolidar (Sanepar, Comgás, bancos
estaduais pequenos como Banese/BNB/Banco da Amazônia) simplesmente não publica `_con`. Nesse
caso não existe a linha "Atribuído a Sócios da Empresa Controladora" — `vl_lucro_liquido`
cai pra `vl_lucro_liquido_total` (sem split de minoritários, porque não tem).

**Casamento por texto, não por `cd_conta` fixo**: o plano de contas da CVM é padronizado
(CPC 26) pra maioria das empresas — `cd_conta` 3.01 a 3.11 com texto idêntico letra por
letra — MAS bancos "de depósito" de verdade (BBAS3, BPAC3; não BRBI11, que é banco de
investimento e segue o plano padrão) usam um plano de "Intermediação Financeira" diferente,
e a posição numérica do resultado final varia até entre bancos (3.11 no BBAS3, 3.09 no
BPAC3) — mapear por posição fixa não generaliza nem dentro do "perfil banco". Por isso
`popula_dre.py` casa por frase-âncora no texto de `ds_conta` normalizado pra tudo a partir de
3.05 (`acha()`); só as posições 3.01-3.04 (receita/custo/lucro bruto/despesas operacionais)
são estruturalmente estáveis nos dois perfis e usadas por `cd_conta` direto.

**Bug encontrado e corrigido (empate de profundidade no `acha()`)**: o desempate original
escolhia a conta de `cd_conta` mais BAIXO entre candidatos no mesmo nível de profundidade —
quebrou em BBAS3, que repete o texto "Atribuído aos Sócios da Empresa Controladora" em DOIS
níveis da hierarquia (`3.09.01`, intermediário "antes das Participações Estatutárias", com
valor zerado — só um campo estrutural do formulário, sem dado real — E `3.11.01`, o final de
fato, com o valor real). O desempate por `cd_conta` mais baixo pegava o `3.09.01` zerado,
gerando `vl_lucro_liquido=0` mesmo com `vl_lucro_liquido_total` preenchido. Corrigido pra
desempatar pelo `cd_conta` mais ALTO entre empates (mais "final"/downstream na demonstração)
— afetou 827 linhas em 144 tickers diferentes depois de reprocessar a base inteira. Mesma
correção replicada em `popula_balanco.py` (`chave_ordenacao_conta()`, idêntica nos dois
arquivos) por precaução, embora nenhuma duplicata real tenha aparecido lá além do caso já
tratado (`emprestimos e financiamentos` em `2.01.04`/`2.02.01`, já restrito por prefixo de
`cd_conta` antes de chamar `acha()`). `popula_dfc.py` não usa casamento por texto, não é
afetado por essa classe de bug.

**Bug encontrado e corrigido (precisão de `tb_dre_conta.vl_conta`)**: a coluna era
`NUMERIC(20,2)` (2 casas decimais) — suficiente pra contas monetárias grandes, mas o LPA
(`3.99.*`) é um valor pequeno com 4 casas decimais relevantes (ex: R$0,3934/ação). Com só 2
casas, o valor era arredondado silenciosamente na raspagem (R$0,3934 virava R$0,39, erro de
~1% sem nenhum aviso) — achado comparando a curadoria contra um valor de LPA já validado
manualmente pra ITSA4. Corrigido pra `NUMERIC(20,4)`; precisou reraspar `tb_dre_conta` por
completo (não só reprocessar a curadoria) já que o valor já tinha sido truncado na escrita
original. `tb_balanco_conta`/`tb_dfc_conta` não têm esse problema — nenhuma das duas
demonstrações guarda valor por ação.

**Bug encontrado e corrigido (`vl_impostos`/`vl_lucro_antes_impostos` em 25 bancos)**: a CVM
tem DUAS formas de reportar o efeito fiscal na DRE, e qual delas aparece **varia por período
pra a mesma empresa** (não é por empresa) — confirmado em BBAS3/BBDC4/ITUB4/BPAC3 e mais 21
bancos, todos alternando entre as duas ao longo dos ~16 anos de histórico:
- Combinada: uma única conta de grupo "Imposto de Renda e Contribuição Social sobre o Lucro".
- Dividida: duas contas de grupo separadas, "Provisão para IR e Contribuição Social"
  (corrente) + "IR Diferido" — sem nenhuma linha combinada. A busca antiga
  (`acha(contas, 'imposto de renda')`) não casava com nenhuma das duas (o texto usa a sigla
  "IR", não "imposto de renda" por extenso) e caía pra uma sub-conta-filha chamada "Provisão
  para imposto de renda" que existe DUPLICADA dentro de cada uma das duas contas de grupo
  (corrente e diferido) — pegava só um pedaço do efeito fiscal total, não o total. Corrigido
  restringindo a busca a contas de grupo (`nivel_superior()`, exclui sub-contas de detalhe) e
  somando as duas linhas quando a combinada não existir. Mesmo achado afetou
  `vl_lucro_antes_impostos`: nesses períodos divididos a conta se chama "Resultado Antes
  Tributação/Participações" (sem a palavra "tributos"), que a busca antiga não cobria —
  generalizada pra casar qualquer "resultado antes..." que não seja a conta intermediária
  "Resultado Antes do Resultado Financeiro e dos Tributos" (única outra variação que existe
  no projeto inteiro).

**Bug encontrado e corrigido (split controlador/não-controlador zerado, achado validando
contra o yfinance)**: variante do bug do `acha()` acima, mas sem empate de profundidade — a
CVM as vezes preenche `3.11.01`/`3.11.02` ("Atribuído aos Sócios da Empresa
Controladora"/"Não Controladores") com **0 e 0**, mesmo com `3.11` (o total) tendo um valor
real — confirmado em CAMB3, CGRA4, VSTE3, RECV3 e mais 137 ações (1001 linhas no total).
Diferente do fallback já existente (`vl_lucro_liquido is None` → usa o total, pra empresa que
nem tem a linha de split) — aqui a conta EXISTE e tem valor explícito 0, então o fallback
antigo não disparava. Corrigido: quando `vl_lucro_liquido=0` E
`vl_participacao_nao_controladores=0` E o total é diferente de zero, assume que não há
participação minoritária real (formulário só não foi preenchido) e usa o total também.
Sem esse fix, o bug se propagava pro 4T derivado: como `vl_lucro_liquido` de 1T/2T/3T vinha
zerado, a subtração (`Anual − 1T − 2T − 3T`) ficava `Anual − 0 − 0 − 0`, dando o total do ano
inteiro em vez do 4T isolado (confirmado em RECV3 2025: 4T mostrava R$638mi — o ANUAL — em
vez dos R$50,7mi corretos). Balanço não tem essa classe de bug (`vl_patrimonio_liquido`/
`vl_participacao_nao_controladores`: 0 ocorrências do mesmo padrão).

**Bug encontrado e corrigido (overflow na estimativa de LPA do 4T)**: a estimativa de LPA do
4T (`lucro_líquido_4T × lpa_3T ÷ lucro_líquido_3T`, ver acima) explode quando
`lucro_líquido_3T` é próximo de zero — confirmado em SOND5 (2012-09-30: lucro 3T = −R$12 mil,
lpa 3T = −614 → estimativa do 4T ≈ 5,2 milhões, estourando `NUMERIC(10,4)` e quebrando o
`INSERT`). Corrigida aplicando a mesma guarda `LIMITE_LPA` (≥10.000 em módulo → `NULL`) já
usada em `extrai_lpa()`, agora também no valor derivado.

Duas decisões de modelagem:
- `vl_receitas_financeiras`/`vl_despesas_financeiras` são confiáveis (reconciliam exatamente
  com `vl_resultado_financeiro`, testado em EVEN3: 35.160 − 11.036 = 24.124) — diferente do
  yfinance, onde `Interest Income`/`Interest Expense` não reconstruíam o `Net Interest
  Income`. Ficam `NULL` pro perfil banco — esse desmembramento não existe lá, já vem embutido
  dentro de "Intermediação Financeira" sem separação explícita; `vl_resultado_financeiro`
  recebe o mesmo valor de `vl_lucro_bruto` nesse perfil (pra um banco, resultado da
  intermediação financeira *é* o resultado financeiro).
- `vl_ebitda`/`vl_ebit` saíram da curadoria (existiam na versão yfinance) — não existem como
  conta na CVM, são métrica voluntária. `vl_lucro_liquido_total` ("Lucro/Prejuízo Consolidado
  do Período") e `vl_lucro_liquido` ("Atribuído aos Sócios da Empresa Controladora") seguem
  distintos quando há subsidiária não 100%-controlada; `vl_participacao_nao_controladores`
  reconcilia os dois, fica `NULL` quando não aplicável.

Bancos não têm o bloco de resultado financeiro separado entre despesas operacionais e
tributos — `vl_resultado_operacional` e `vl_lucro_antes_impostos` saem iguais pra esse
perfil, esperado, não é bug.

`vl_lpa_basico`/`vl_lpa_diluido`: empresas têm 1 a 3 classes de ação (ON / ON+PN /
ON+PNA+PNB) — a posição das contas-filhas de LPA básico/diluído (3.99.01.\*/3.99.02.\*) NÃO é
estável entre empresas (SHUL4 lista PN antes de ON) — `popula_dre.py` casa pelo texto da
classe (`tb_ativo.sg_classe`) contra `ds_conta`, nunca por posição. Descarta (vira `NULL`)
qualquer valor com módulo ≥ 10.000 — a CVM ocasionalmente reporta LPA com erro grosseiro de
carga (confirmado em MRVE3 2017-06-30: R$614 milhões/ação, e em AMAR3 2021-12-31: R$ −27,44
QUATRILHÕES/ação — esse último estourava a coluna `NUMERIC(20,4)` na hora do `INSERT`, então
o limiar (`LIMITE_LPA`) teve que ser replicado em `scraper_dre.py` também, não só em
`popula_dre.py` — sem isso o scraper quebrava antes da curadoria ter a chance de filtrar),
mesmo limiar usado pelo scraper antigo pro mesmo tipo de problema.

**4T via DFP**: não existe "4º ITR" — a CVM só publica o trimestral (1T/2T/3T) via ITR; o
resultado do ano inteiro só sai depois do encerramento do exercício, via DFP (anual), mesmo
nome de arquivo/CSV do ITR (só troca `itr_cia_aberta_<ano>.zip` por
`dfp_cia_aberta_<ano>.zip`). `scraper_dre.py` busca os dois (`for tipo, tp_periodo in
(('itr', 'TRIMESTRAL'), ('dfp', 'ANUAL'))`) e grava o DFP em `tb_dre_conta` com
`tp_periodo='ANUAL'` — sem o filtro de isolamento de trimestre (só faz sentido pro ITR, onde
existe a ambiguidade trimestre-isolado-vs-acumulado; o DFP é sempre o ano inteiro, sem
ambiguidade). `popula_dre.py` deriva o 4T isolado por subtração na curadoria
(`deriva_quarto_trimestre()`): `Anual − 1T − 2T − 3T`, coluna a coluna, só quando os 4
períodos do mesmo ano civil estão disponíveis. O total anual em si (`tp_periodo='ANUAL'`)
fica gravado também, sem nenhuma subtração — útil por si só (ex: "qual foi o lucro líquido do
ano inteiro").

`vl_lpa_basico`/`vl_lpa_diluido` NÃO entram na subtração — LPA é ponderado pela quantidade de
ações em circulação em cada trimestre, não soma linearmente como um valor monetário
("Anual − 1T − 2T − 3T" daria um número sem sentido matemático, não só impreciso, se a
empresa emitiu/recomprou ações no meio do ano). Em vez disso, **estima** o LPA do 4T usando a
quantidade de ações IMPLÍCITA no 3T (`lucro_líquido_3T / lpa_3T`) como proxy pra "ações em
circulação no 4T" — assume que essa quantidade não muda muito entre 3T e 4T (emissões/
recompras corporativas costumam ser graduais, não um salto abrupto isolado no último
trimestre). Validado contra `qt_acoes` (yfinance) em ITSA4: a série de ações implícitas é
suave e plausível (~10,3 bilhões em 2024, subindo gradualmente pra ~11,2 bilhões em 2026,
bate com o real) e o LPA derivado do 4T fica exatamente entre o 3T e o 1T seguinte nos dois
anos testados. Usa o 3T como referência (não o anual) por ser o período mais próximo no
tempo do 4T que está sendo estimado.

Fica `NULL` quando a divisão não é confiável — `lpa_3T=0` ou `lucro_líquido_3T=0` (a CVM
reporta LPA trimestral como exatamente `0,0000`, não faltando, em ~38% dos terceiros
trimestres da base; confirmado em ABCB4 2020-2025, todos os anos: a conta `3.99.01`/`3.99.02`
em si vem zerada na fonte, sem nenhuma sub-conta de classe — não é bug de extração, é
ausência de disclosure trimestral de LPA por parte de algumas empresas, mais comum em bancos)
— cobertura do LPA derivado no 4T fica em ~54% da base por causa disso, bem abaixo do ~95%
do 1T/2T/3T (que conta um `0,0000` reportado como "presente", mesmo sem ser informação
realmente útil).

`tb_dre_conta` é a tabela auxiliar/raw — guarda TODAS as contas de TODOS os períodos, sem
curadoria, serve de auditoria e de fonte pra qualquer métrica que a curadoria de `tb_dre` não
cobrir. `cd_conta` só serve pra navegar a hierarquia (achar contas-filhas), não é chave de
identificação estável entre empresas.

## Fontes de dados externas

- dadosdemercado.com.br — scraping HTML (sem API), lista de tickers e detalhe de emissor
- yfinance — cotações, splits/grupamentos, proventos, balanço patrimonial, valor de mercado (DRE saiu de yfinance, ver seção própria)
- dados.cvm.gov.br — dados abertos da CVM, DRE (ITR trimestral), ver seção própria
- planilhas `negociacao-*.xlsx` — exportadas manualmente da B3 e importadas via `import_operacoes.py`, arquivadas em `scrape/importados/` depois de importadas
