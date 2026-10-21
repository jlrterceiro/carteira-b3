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
  `backend/relatorios/`; cada script faz `sys.path.insert(0, ...)` pra subir até a raiz e
  importar. A API (`backend/api/`) NÃO usa mais: tem o próprio `backend/api/db.py` (mesma lógica,
  procura o `.env` em `ENV_FILE`, `backend/api/`, `backend/` ou raiz) — a API e o frontend são
  independentes, cada um com seu `requirements.txt` (`backend/requirements.txt`,
  `frontend/requirements.txt`).
- `scrape/` — tudo que busca dado de fonte externa (B3, CVM; yfinance ainda em migração) ou de
  arquivo (planilha de negociação) e grava no banco. `scrape/importados/` guarda as planilhas
  já importadas.
- `backend/` — schema (`backend/schema/*.sql`), funções de cálculo (`backend/functions/*.sql`),
  testes de regressão (`backend/tests/test_validacoes.sql`), geradores de relatório PDF/Excel
  (`backend/relatorios/*.py`) e a API (`backend/api/`, ver seção própria abaixo).
- `frontend/` — `app.py`, dashboard Streamlit (ver seção própria abaixo).

Se trocar a fonte de dados de cotação/balanço/etc no futuro, só precisa trocar o scraper
correspondente em `scrape/` — nada em `backend/` referencia a fonte externa diretamente, só lê
das tabelas.

**Direção do projeto (decisão do usuário, 2026-10-18)**: só fontes oficiais — B3 e CVM. Sai
yfinance e dadosdemercado.com.br; Status Invest fica só pros logos dos tickers (usado pela
API); BCB aceito só pra CDI/SELIC e índices (Ibovespa). Escopo é só AÇÕES: FII e BDR foram
removidos do banco (backup no schema `bkp_fii_bdr`, 18 ativos). Já migrado: cadastro
(`scraper_cadastro_b3.py`), cotações (COTAHIST completo, 1994+, `scraper_cotacoes_b3.py`),
proventos e eventos corporativos (B3), balanço/DRE/DFC (CVM). Os scrapers de cotação e de
eventos do yfinance foram apagados (2026-10-18). Falta só: `qt_acoes`/valor de mercado
(`scraper_qt_acoes.py`/`scraper_valor_mercado.py`, ainda yfinance) e CDI/índices via BCB.
Backup do histórico de cotações do yfinance (pré-migração) no schema `bkp_cotacao`
(`tb_cotacao_pre_full`); eventos antigos de `ds_origem='yfinance'` continuam na tabela (sem scraper pra
renová-los) até o `scraper_eventos_cvm.py` confirmá-los (viram `ds_origem='CVM'`).

## Schema (public, 36 tabelas)

- `tb_usuario` → `tb_carteira` → `tb_operacao` (compra/venda/transferência/dividendo/etc, ver `tb_tipo_operacao`)
- `tb_emissor` → `tb_ativo` (ticker, classe ON/PN/UNIT) → `tb_cotacao_bruta` (preço REAL do dia, COTAHIST, nunca ajustado) → `tb_cotacao_ajustada` (derivada, ver "Cotações")
- `tb_evento_corporativo` (SPLIT/GRUP, com `vl_fator`) por `id_ativo`
- `tb_provento` (valor bruto por ação, por `id_ativo`+`dt_ex`+`ds_tipo_provento` — raw da B3
  pra ações, yfinance ainda pra FII/BDR, ver seção própria) + `vl_unitario_liquido`/
  `vl_imposto_unitario` (IRRF de 15% pra JCP) + `vl_unitario_ajustado` (corrigido por
  `fn_popula_provento_ajustado`, ver seção de splits abaixo e seção de proventos)
- `tb_posicao_diaria` — snapshot diário (carteira, corretora, ativo), recalculado do zero por `fn_popula_posicao_diaria`
- `tb_provento_recebido` — proventos cruzados com a posição na data-com, uma linha só por evento real (não preenche dia a dia)
- `tb_provento_pagamento` — data de PAGAMENTO de cada provento (persistente, só upsert; real da B3 ou estimada), `tb_provento_recebido_tipo` (derivada: recebido por tipo + data de pagamento) e `tb_rentabilidade_caixa_diaria` (derivada: caixa de proventos por dia) — ver "Rentabilidade: métodos"
- `tb_rentabilidade_ativo_diaria` — ganho/base em R$ por (carteira, corretora, ativo, dia de pregão)
- `tb_rentabilidade_diaria` — rollup de `tb_rentabilidade_ativo_diaria` via `GROUPING SETS` sobre usuário/carteira/corretora (8 combinações por dia, `NULL` = "todos" naquela dimensão)
- `tb_balanco_patrimonial` — balanço (só ações), 14 métricas curadas, TRIMESTRAL via dados abertos da CVM (ver seção própria abaixo)
- `tb_balanco_conta` — auxiliar/raw: TODAS as contas do plano de contas da CVM pro balanço, sem curadoria, usada por `popula_balanco.py` pra montar `tb_balanco_patrimonial` (ver seção própria abaixo)
- `tb_dre` — DRE (só ações), 15 métricas curadas, TRIMESTRAL via dados abertos da CVM (ver seção própria abaixo)
- `tb_dre_conta` — auxiliar/raw: TODAS as contas do plano de contas da CVM, sem curadoria, usada por `popula_dre.py` pra montar `tb_dre` (ver seção própria abaixo)
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

- `scraper_cadastro_b3.py [--dry-run]` — cadastro de emissores (`tb_emissor`) e ações (`tb_ativo`) direto da B3
  (`GetInitialCompanies` + `GetDetail`, mesma API de proventos/eventos), substitui os antigos
  scrapers do dadosdemercado (apagados). Ver seção "Cadastro (B3)" abaixo.
- `scraper_cotacoes_b3.py <TICKER opcional> [--full|--novos]` — cotações do COTAHIST da B3 (única fonte de
  cotação). Grava o preço REAL em `tb_cotacao_bruta`, sem ajustar nada. Padrão: incremental (só dias depois da
  última cotação de cada ativo). `--full` substitui o histórico inteiro (1994+). `--novos` faz a carga completa
  só dos ativos que ainda não têm nenhuma cotação (cadastro novo). Ver "Cotações (COTAHIST)" e "Cotação real ×
  ajustada" abaixo.
- `scraper_negocios_b3.py [DATA... | --desde DATA]` — coletor do arquivo diário de negócios consolidados da B3
  (`tb_negocio_diario`, com a oscilação oficial), só ações do cadastro, 3 rodadas de retry.
- `reconstroi_eventos.py [--aplica] [--diario]` — reconstrói `tb_evento_corporativo` (S1 oscilação + S2 opções + S3
  preço, ver "Eventos corporativos: reconstrução"). Apoio: `eventos_por_oscilacao.py`, `eventos_por_opcoes.py`,
  `compara_eventos_opcoes.py`. `scraper_eventos_cvm.py [--aplica]` — carga ÚNICA do passado via avisos da CVM
  (com PDF); `prototipo_eventos_cvm.py` é a versão só-leitura.
- `atualiza_diario.py` — rotina diária completa, só dados estruturados (cotações → benchmarks → negócios → eventos B3 →
  reconstroi `--diario` → proventos → `fn_rebuild_tudo()`).
- `scraper_pagamentos_b3.py [SG_EMISSOR]` — data de pagamento dos proventos (`GetListedSupplementCompany.cashDividends.paymentDate`),
  só upsert em `tb_provento_pagamento`; roda na rotina diária depois de `scraper_proventos.py`.
- `scraper_pagamentos_cvm.py [--aplica] [--ano-ini 2022] [SG_EMISSOR]` — data de pagamento REAL dos proventos de 2022 em diante, lida do formulário
  "Relatório Proventos" (categoria do IPE da CVM, PDF estruturado: data-com + valor bruto + data de pagamento por ISIN);
  só grava onde hoje há estimativa, nunca sobrescreve a da B3. Roda na rotina diária antes do da B3.
- `descobre_trocas_ticker.py [--aplica]` — emenda séries de tickers renomeados só com o COTAHIST.
- `scraper_proventos.py <TICKER opcional>` — dividendos/JCP/rendimento via `yfinance` (`t.dividends`), valor bruto raw (sem distinguir tipo)
- `scraper_balanco_patrimonial.py <TICKER opcional>` — raspagem crua do balanço via dados abertos da CVM, só ações, popula só `tb_balanco_conta` (ver seção própria abaixo). `popula_balanco.py <TICKER opcional>` — curadoria local (lê `tb_balanco_conta`, sem rede) que popula `tb_balanco_patrimonial`, mesmo padrão de separação do DRE. `scraper_qt_acoes.py <TICKER opcional>` — só atualiza `qt_acoes` em `tb_balanco_patrimonial` via yfinance (`Ordinary Shares Number`), `UPDATE`-only (nunca `INSERT`, a linha já existe via `popula_balanco.py`) — ver seção própria abaixo pro motivo.
- `scraper_dre.py <TICKER opcional>` — raspagem crua da DRE via dados abertos da CVM, só ações, popula só `tb_dre_conta` (ver seção própria abaixo). `popula_dre.py <TICKER opcional>` — curadoria local (lê `tb_dre_conta`, sem rede) que popula `tb_dre`; separado do scraper de propósito, pra corrigir bug de casamento sem precisar rebaixar nada da CVM.
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

- `db.py` — `get_conn()` + carregamento do `.env`, próprio da API (não depende de nada fora de `backend/`).
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
  (`fn_ganho_total`), `GET /carteira/rentabilidade?inicio=&fim=&metodo=acoes|receber|status_invest` (padrão `acoes`, o cálculo antigo, pro
  Streamlit não mudar), todos protegidos e todos com `id_corretora`
  opcional (sem ele = todas as corretoras do usuário); `GET /carteira/corretoras` lista as corretoras em que o
  usuário já operou (alimenta o filtro da tela). O filtro vem SEMPRE junto do usuário autenticado: id de
  corretora alheia só devolve vazio. Rentabilidade por corretora lê as linhas `(id_usuario, id_carteira NULL,
  id_corretora X)` de `tb_rentabilidade_diaria`, que o GROUPING SETS já gerava; `fn_posicao_atual(usuario,
  id_corretora)` ganhou o 2º parâmetro (assinatura trocada com `DROP`, senão a chamada de 1 argumento fica
  ambígua); `fn_ganho_total` já aceitava corretora. Soma por corretora = total (conferido nos 3 usuários).

**Variação do dia e cotação intradia na Posição (2026-10-19)**: `fn_posicao_atual` devolve também `preco_anterior`, `var_dia_pct`,
`ganho_dia` (quantidade × (atual − fechamento anterior)), `dh_cotacao` e `ds_fonte`; a tela tem "Hoje %"/"Hoje R$", o total do dia
e refaz a busca a cada 5 min. O preço atual vem SÓ de `vw_cotacao_atual` (também usada por `fn_ganho_total`, pra Posição e
Ganhos concordarem): **durante o pregão vale a coleta intradia, quando o COTAHIST do dia sai completo passa a valer ele**
(regra: intradia só se `tb_cotacao_intradia.dt_pregao` > último pregão do COTAHIST do ativo; atual/anterior = último negócio /
fechamento do último pregão; senão último e penúltimo pregão do COTAHIST). `scrape/scraper_cotacao_intradia.py [--loop] [--todos]`
lê `cotacao.b3.com.br/mds/api/v1/instrumentQuotation/<TICKER>` (endpoint do próprio site da B3, atraso ~15 min, preço real:
`curPrc`, `opngPric`, `minPric`, `maxPric`, `prcFlcn`=variação % do dia, `Msg.dtTm`), só dos ativos com posição aberta, só grava
se a data da cotação for hoje, upsert em `tb_cotacao_intradia` (uma linha por ativo, sem histórico). `--loop` roda a cada 5 min
em dia útil de 9h50 a 18h40; precisa ficar de pé (hoje é manual: `python3 scrape/scraper_cotacao_intradia.py --loop`).
Rentabilidade/ganho realizado e as derivadas NÃO usam o intradia (continuam fechamento do COTAHIST, via `fn_rebuild_tudo`).

**Benchmarks no gráfico de Rentabilidade (2026-10-21)**: `tb_benchmark_diario` (IBOV e CDI, desde 2018) via `scrape/scraper_benchmarks.py`
(só upsert, incremental). IBOV = fechamento diário do arquivo de índices da B3 (`www.b3.com.br/pesquisapregao/download?filelist=IR<aammdd>.zip`,
zip dentro de zip com o XML BVBG.087.01; vazio em dia sem pregão; baixar UM por vez e com a conexão reaproveitada — em paralelo a B3/Cloudflare
derruba as conexões). É índice de RETORNO TOTAL (a metodologia da B3 reinveste os proventos; bruto×líquido de IR não verificado). CDI = BCB SGS 12
(% a.d.; o BCB resolve pra IPv6 e pendura, o script força IPv4; o SGS 7 do Ibovespa parou em 2019). `GET /carteira/benchmarks?de=&ate=` devolve
IBOV e CDI acumulados nos pregões a partir do fechamento ANTERIOR a `de` (mesma base do TWR); a tela passa a data do 1º ponto da carteira.
O coletor roda na rotina diária (logo depois das cotações, no `atualiza_diario.py` e na DAG; incremental: só os pregões que faltam). O gráfico (`LineChart`) é multi-série (Carteira azul, CDI verde `#059669`, Ibovespa rosa `#db2777`, com caixas de seleção; S&P 500 ficou de fora por falta de fonte aberta acessível: o FRED, com chave gratuita, é a opção), eixo esquerdo sem casas decimais, datas dd/mm/aaaa e
tooltip em caixa preta translúcida com bolinha na cor de cada linha.

**Coleta intradia: armadilha do `Msg.dtTm` (2026-10-21)**: nas respostas de `cotacao.b3.com.br` o `Msg.dtTm` é a hora da REQUISIÇÃO, não a do
negócio — fora do pregão ele devolve o último preço (inclusive do after-market, que difere do fechamento oficial) com a hora de agora, e a
coleta gravava isso como "de hoje" (Posição mostrava um dia falso negativo). Agora o `scraper_cotacao_intradia.py` usa
`DailyFluctuationHistory/<TICKER>` (data do pregão em `TradgFlr.date`, horário real da última barra, só até 18:00). Antes do pregão abrir nada é
gravado e a Posição mostra o último dia fechado.

**Carteira só no nível do usuário (decisão de 2026-10-18)**: a funcionalidade de várias carteiras por usuário foi
descartada por ser complexa demais. Some da API e da interface (nem seletor, nem menção no Perfil; o upload usa a
carteira do usuário sem perguntar). A tabela `tb_carteira` e o `id_carteira` continuam existindo POR DENTRO (as
funções `fn_*`, `tb_operacao` e as derivadas ainda se apoiam nelas): cada usuário tem uma só, criada no
cadastro, e `importacao.carteira_do_usuario()` devolve a primeira. Remover de vez do schema é um refactor grande,
não feito.
- `acoes.py` — hoje só `GET /acoes/logos?tickers=A,B` (usado pela tabela de Posição; sem `get_current_user`, dado
  público). **`/acoes/lista` e `/acoes/cotacao` foram REMOVIDOS em 2026-10-18** a pedido do usuário, que vai
  refazer a funcionalidade de Ações depois (eram abertos, lendo `tb_cotacao_ajustada`, com
  `vl_fechamento_nominal`/`vl_fechamento`/`vl_fechamento_ajustado` — as colunas continuam na tabela). O
  `/acoes/logos` resolve ticker → `parentId` do Status Invest (logo da empresa,
  busca externa feita pela API, com fallback ON/prefixo de 4 letras) — o frontend nunca chama
  serviço externo direto, só a API; a imagem do logo em si ainda é carregada pelo navegador.

- `perfil.py` + `importacao.py` — **perfil do usuário e upload do extrato de negociação da B3** (xlsx da Área do
  Investidor), todos protegidos: `GET /perfil` (dados, carteiras e situação da importação: última operação e a
  data sugerida pra baixar o próximo extrato, 7 dias antes), `POST /perfil/importacao/previa` (lê a planilha e
  diz o que entraria, SEM gravar), `POST /perfil/importacao` (grava só as novas, numa transação, e dispara o
  recálculo) e `GET /perfil/recalculo` (andamento). Mesma regra do `scrape/import_operacoes.py` (só COMPRA/VENDA,
  fracionário perde o "F", duplicata = contagem de ocorrências (ativo, tipo, data, qtd, preço) já gravadas na
  carteira — reimportar período sobreposto é seguro); a CLI continua existindo e é independente (a API não
  importa nada de `scrape/`). Validações do arquivo: ≤5 MB, só .xlsx (magic `PK`), total descompactado ≤60 MB,
  ≤20.000 linhas, cabeçalho exato de 9 colunas, data/quantidade/preço conferidos, `pg_advisory_xact_lock` por
  usuário contra duplo clique. Ticker que não está em `tb_ativo` (FII/ETF/BDR — o escopo é só ação) vira
  `ativo_desconhecido` e NÃO é importado, avisado na prévia. Corretora nova é criada com o nome da planilha (≤120
  caracteres); a comparação com as existentes (e com `tb_corretora_historico`) ignora caixa, espaços duplos e ponto
  final, porque a B3 grafa 'S/A' num extrato e 'S/A.' em outro (a XP chegou a ficar duplicada, ids 2 e 5; unidas em
  2026-10-18, com alias em `tb_corretora_historico`). O recálculo (`fn_rebuild_tudo()`, ~70 s, refaz as derivadas de TODOS os usuários) roda em thread
  depois do upload; estado em memória, vale só pra processo único (uvicorn sem `--workers`); upload durante o
  recálculo marca "pendente" e roda de novo. Limitação: enquanto roda, as derivadas estão em transação e as
  leituras esperam. Dependências novas em `backend/requirements.txt`: `openpyxl`, `python-multipart`.

`tb_usuario.ds_senha_hash` é nullable de propósito — usuário cadastrado antes da API (direto
no banco) não tem senha até passar pelo fluxo de reivindicação em `/auth/cadastro`.

Sem recuperação de senha, verificação de e-mail ou revogação de token ainda — endpoints de
escrita (importar operação, rodar scraper) também não estão expostos, só leitura por agora.

## Frontend (`frontend/app.py`)

Dashboard Streamlit, consome só a API (`backend/api/`) via HTTP — nunca acessa o banco
direto. Roda com `streamlit run frontend/app.py` (precisa da API rodando em paralelo,
`http://localhost:8000` por padrão — configurável pela variável de ambiente `API_BASE_URL`). Guarda a sessão
HTTP (com o cookie do JWT) em `st.session_state`, que persiste entre os reruns do Streamlit
pra a mesma sessão de navegador — login fica "lembrado" enquanto a aba estiver aberta.

Duas áreas, selecionadas por um radio no topo da sidebar (`area`, fora do gate de login):
**Carteira** (login obrigatório) — login/cadastro (cadastro reaproveita o fluxo de
"reivindicar" conta do `/auth/cadastro` — tem um aviso na tela sobre isso pra quem já tem
conta criada direto no banco) e, depois de logado, abas de Posição atual, Ganhos e
Rentabilidade. **Ações** — informação pública sobre ativos individuais, sem precisar logar
(é uma parte aberta do site, dados de mercado não são por usuário); pensada pra crescer aos
poucos. Primeiro incremento: gráfico de cotação de uma ação escolhida (`st.selectbox`, lista
de `GET /acoes/lista`), com select de 3 opções de ajuste e o mesmo seletor de período
(`PERIODOS`) já usado na aba Rentabilidade — `GET /acoes/cotacao?ticker=&inicio=&fim=`, lê
direto de `tb_cotacao_ajustada`:
- "Sem ajuste (nominal na época)" (`vl_fechamento_nominal`) — preço real como negociou
  naquele dia, coluna da própria `tb_cotacao_ajustada` (cópia de `tb_cotacao_bruta.vl_fechamento`,
  o que o COTAHIST informou). Desde 2026-10-18 o real é a fonte e o ajustado é que é derivado (ver
  "Cotações").
- "Ajustada apenas por eventos corporativos" (`vl_fechamento`)
- "Ajustada por eventos corporativos e dividendos" (`vl_fechamento_ajustado`)

**Link direto pra uma ação**: `?ticker=PETR4` na URL (`st.query_params`) seleciona a ação e
já abre na área Ações, mesmo sem estar logado — usado como o equivalente real de uma "página
por ação" dentro do Streamlit, que **não tem rota de caminho dinâmico** tipo `/acoes/petr4`
(precisaria de proxy/servidor próprio na frente; fora de escopo por agora).

**Seleção de intervalo no gráfico** (`alt.selection_interval`, sem `.interactive()` — não
afeta zoom/escala, que continua desligado): arrastar o mouse sobre o gráfico marca um
intervalo e mostra, numa caixa centralizada acima do gráfico (altura sempre reservada, "—"
quando não há seleção, pra não pular o layout), a variação simples e a anualizada (juros
compostos sobre os dias do intervalo, nunca regra de três) entre o primeiro e o último ponto
selecionados — atualiza em tempo real durante o próprio arrasto (Streamlit dispara reruns
contínuos enquanto o brush do Vega-Lite muda, não só no `mouseup`). A seleção é lida de
`st.session_state[chart_key]` **antes** de montar o gráfico (o valor já reflete a interação
que disparou aquele rerun) — `chart_key` inclui ação+cotação+período de propósito, pra trocar
qualquer um desses controles começar com uma seleção limpa em vez de carregar um intervalo de
datas que não existe mais no novo eixo x. Limpar a seleção é por **duplo clique** no gráfico
(padrão do Vega-Lite) — `clear='click'` parecia a escolha óbvia, mas **quebra o próprio
arrasto**: todo `mouseup` que termina um drag também dispara um `click` nativo do DOM (sem
limiar de movimento, mousedown+mouseup no mesmo elemento já conta como click), e o Vega não
distingue os dois — a seleção era criada e imediatamente limpa pelo mesmo gesto.

A aba Rentabilidade usa `GET /carteira/rentabilidade?inicio=&fim=` (ambos opcionais — sem
`inicio` é "desde o início"), que devolve a série diária do `tb_rentabilidade_diaria` do
usuário (rollup `id_carteira IS NULL AND id_corretora IS NULL`) mais o agregado por mês/ano/
total já calculado em SQL via juros compostos (`EXP(SUM(LN(1+pct/100)))-1`, igual o resto do
projeto — NUNCA somar percentual direto). O frontend recalcula a curva acumulada localmente
em cima da série diária pra plotar o gráfico (mesma fórmula, só que ponto a ponto); o valor
final dessa curva sempre bate com `total_pct` vindo da API.

## Frontend oficial (`frontend-next/`)

**É a interface oficial desde 2026-10-18** (decisão do usuário); o Streamlit (`frontend/`) fica como
estava e não recebe funcionalidade nova. Next.js (App Router, TypeScript, sem libs de UI/gráfico — o gráfico é
um SVG próprio em `app/components/LineChart.tsx`): login/cadastro, Posição, Ganhos e Rentabilidade (barra lateral `aside.side` colada na
borda esquerda da TELA, altura toda, com o título "Minha Carteira" no topo e os botões em coluna; conteúdo ocupa o
resto da largura, menu do usuário no canto superior direito; filtros de período da Rentabilidade ancorados à
direita, `.chips.right`; em tela estreita a barra vira uma faixa horizontal no topo) e **Perfil**,
que NÃO é aba: abre pelo menu do usuário (nome + seta no canto superior direito,
`app/components/MenuUsuario.tsx`, com Perfil e Sair; fecha ao clicar fora ou com Esc). `app/components/Perfil.tsx`:
dados do usuário, última operação importada, data sugerida pro próximo extrato da B3 e upload do .xlsx com prévia
antes de gravar e acompanhamento do recálculo.
**A tela de Ações foi removida do Next em 2026-10-18** (componente `Acoes.tsx`, aba e link `?ticker=`), junto
com os endpoints do backend, a pedido do usuário, que vai refazê-la; sem ela, todo o app exige login. O
Streamlit (`frontend/`) NÃO foi alterado: a área Ações dele chama `/acoes/lista` e `/acoes/cotacao` e agora falha.
**Rotas (2026-10-19)**: cada tela tem URL própria — `/posicao`, `/ganhos`, `/rentabilidade` e `/perfil` (grupo de rotas `app/(app)/`);
`/` redireciona (307, `redirects()` em `next.config.ts`) pra `/posicao`. O layout `(app)/layout.tsx` é fino (server, `instant = false`
porque tudo depende do cookie de login) e renderiza `components/Casca.tsx` (cliente: sessão, barra lateral com `Link` e realce por
`usePathname`, topbar, filtro de corretora, tela de login NA MESMA URL quando não logado — link direto pede login e depois cai na
própria tela). A corretora escolhida vai por contexto (`lib/sessao.tsx`, `useCorretora`) e `components/Telas.tsx` remonta cada tela
com `key={corretora}`. Next 16 (`cacheComponents`): `instant` não pode ficar em componente cliente, por isso as páginas são server
components finos; leia `node_modules/next/dist/docs/` antes de mexer (AGENTS.md).
**Filtro de corretora** (`FiltroCorretora.tsx`, na barra do topo, à esquerda do menu do usuário): um seletor
só, compartilhado por Posição, Ganhos e Rentabilidade (some no Perfil); `page.tsx` guarda a escolha em
`localStorage` e passa `key={corretora}` às telas, que remontam e refazem as buscas ao trocar. Corretoras
vêm de `GET /carteira/corretoras`.
**Rentabilidade**: filtros de período (30 dias … Total) controlam o gráfico e o total do topo; abaixo, a matriz
"Rentabilidade por mês" (`Matriz` em `Rentabilidade.tsx`) tem uma linha por ano (mais recente em cima), 12
colunas Jan–Dez, "Ano" e "Acumulada" (juros compostos desde o primeiro ano até o fim daquele ano). A matriz SEMPRE
usa o histórico inteiro (`GET /carteira/rentabilidade` sem `inicio`, segunda chamada) e não segue o filtro, porque só
faz sentido com meses completos; mês sem dado fica "—". Valores conferidos contra o cálculo direto em SQL
(`EXP(SUM(LN(1+pct/100)))-1` sobre `tb_rentabilidade_diaria`).
O helper `api()` não força `Content-Type: json` quando o corpo é `FormData` (o navegador precisa definir o
boundary do upload). Consome só a API, com cookie
(`credentials: 'include'`); URL da API em `NEXT_PUBLIC_API_BASE_URL` (padrão
`http://localhost:8000`). Rodar: `cd frontend-next && npm run dev` (porta 3000, já liberada no
CORS da API). Ainda não tem a aba "Rent. por Ação" (só existe no Streamlit).

## Cadastro (B3)

`scraper_cadastro_b3.py` pagina `GetInitialCompanies` (~3,5k empresas, a maioria emissor de
dívida — `type='7'` é descartado sem chamar o detalhe) e chama `GetDetail` pro resto
(`codeCVM`), que devolve `otherCodes` (ticker + ISIN), setor B3 (`industryClassification`,
usa "." onde o dadosdemercado usava ",") e site. Casa com `tb_emissor` por **CNPJ** (a B3
devolve o CNPJ como número, sem zeros à esquerda — `BBAS` vem `191` — por isso `zfill(14)`).
Nunca recria nem renomeia linha existente (preserva `id_emissor`/`id_ativo`): pra emissor
existente só preenche `ds_site`/`info` quando estiverem vazios.

Quais tickers entram: ISIN tipo `ACN` (ação, classe pelo par de letras 10-11: `OR`=ON,
`P?`=PN) ou, só pra ticker terminado em `11`, ISIN `CDA` (maioria das units), `UNT` (BPAC11)
ou `TRV` (PSVM11) → classe UNIT. Sufixo `9x` (97/98/99) é direito/recibo, descartado. Debênture,
BDR, FII, ETF ficam de fora por não terem ISIN `ACN`/unit.

**Papéis B3 × CVM (decisão do usuário, 2026-10-18)**: B3 é a autoridade pro que NEGOCIA (tickers,
ISIN, classe, listagem, cotações, eventos, proventos); a CVM (`cad_cia_aberta.csv`, baixado pro cache
`scrape/cvm_cache/`) é a autoridade pra ENTIDADE JURÍDICA (CNPJ, razão social, situação, setor) — e é
o CNPJ que liga o dado financeiro. A comparação B3×banco é pela **raiz do CNPJ** (8 primeiros dígitos):
a mesma empresa pode ter estabelecimentos diferentes em cada fonte (TUPY: B3 `/0003-00` filial, CVM
`/0001-49` matriz) e isso NÃO é divergência — o CNPJ gravado fica o da CVM e o da B3 vai pra
`info.cnpj_b3` só como rastreio. Raiz diferente = outra pessoa jurídica e aparece como divergência. O
scraper também avisa quando um emissor com ticker ainda listado tem o CNPJ cancelado/suspenso na CVM.

**CNPJ que muda (`info.cnpjs_anteriores`)**: caso BRST — a CVM cancelou a holding Brisanet
Participações (`19.796.586/0001-70`) em 2024-12-04 e a Brisanet Serviços de Telecomunicações
(`04.601.397/0001-28`) assumiu a listagem em 2024-12-05 (BRIT3 → BRST3). `tb_emissor.nr_cnpj` guarda o
CNPJ ATUAL e `info.cnpjs_anteriores = [{"cnpj": "...", "ate": "2024-09-30"}]` os antigos com o último
`DT_REFER` que vale pra eles; `scrape/cnpj_emissor.py` expande isso e os scrapers de DRE/balanço/DFC
leem o CNPJ antigo até `ate` e o novo depois (BRST passou de 19 pra 27 períodos de DRE, 2020-12 →
2026-03; o 4T24 derivado bate com o trimestre publicado). Os scrapers só fazem upsert, nunca apagam,
então ler dois CNPJs em sequência é seguro. `scraper_insider.py`/`scraper_recompra.py` ainda NÃO usam
`cnpjs_anteriores` (pendente).

`fl_ativo` é sincronizado com o que a B3 lista hoje (quem saiu fica `false` e ganha
`dt_fim_negociacao` = último pregão que temos; nada é apagado, o histórico segue valendo).
`--dry-run` imprime tudo sem gravar. Divergências que ele só reporta (revisar à mão): BRST e
TUPY (CNPJ do banco difere do da B3 — TUPY é só matriz×filial), TRAD/FICT (sigla do banco ≠
código B3, ECOM/FASA — por isso o scraper de eventos dava resposta vazia pra esses) e PPLA
(sem CNPJ no banco, B3 usa outro código, VSUI).

Ativos novos (cadastro novo): a data ex dos proventos usa `tb_cotacao_bruta` (só as datas de
pregão). Ordem: `scraper_cotacoes_b3.py --novos` → eventos corporativos → `scraper_proventos.py` →
`fn_rebuild_tudo()`. A circularidade de antes (ajuste de dividendo gravado na cotação) acabou: o
ajustado é derivado e recalculado pelo rebuild.

## Cotações (COTAHIST)

Histórico completo (1998+ na prática) vem do COTAHIST anual da B3 (`COTAHIST_A<ano>.ZIP`, cache em
`scrape/cotahist_cache/`, o do ano corrente é rebaixado a cada execução). Só linhas `tpmerc='010'`
(mercado à vista, sem o fracionário `…F`). `vl_fechamento` = preço bruto ÷ produto dos eventos
corporativos POSTERIORES (`ajusta_por_split`, mesma definição de `fn_fator_acumulado`);
`vl_fechamento_ajustado` ainda desconta os proventos (retorno total).

**Validado contra o yfinance antigo (trocado em 2026-10-18)**: patrimônio de uma carteira bate no
centavo em 3 de 4 datas testadas; a diferença (CGRA4 em 30/12/2024, +1,5%) era o yfinance
ajustando a bonificação DUAS vezes (CMIG4 2024 também: 12,69 ÷ 1,3 = 9,76 certo, yfinance dava
7,51 = ÷1,69). Ou seja, a série nova é a correta.

**`FATCOT` e moeda**: até ~2005 muitos papéis são cotados POR LOTE de 1.000 ações (também 100, 10.000,
100.000, 1.000.000 — campo `FATCOT`, posições 211-217): o preço unitário é o do arquivo ÷ FATCOT
(`parse_linha` faz isso; ignorar gerava saltos ×1000/×20 em BRKM6, CEGR3...). Linhas de 1994 antes do
Plano Real vêm em CR$ (`MODREF` ≠ `R$`) e são descartadas. Os arquivos de 1994-1997 usam códigos antigos
de 3 letras (`ACE 3`, `PET 4`); a recodificação foi em 16/03/1998 (por isso toda série "nossa" começava
nessa data) e o ISIN NÃO mudou nela.

**`--full` apaga antes de reinserir** (por ativo): a primeira versão só sobrescrevia, e sobravam
linhas do yfinance onde o COTAHIST não cobre (FICT3 tinha 6.560 linhas desde 2000, o COTAHIST só
420 desde 2024). Depois de corrigir, o banco passou de 1,79M pra 1,18M cotações (603.563 linhas
removidas, 303 ativos): 74% eram dias SEM negócio (o yfinance preenchia todo pregão com o último
preço; o COTAHIST só tem dia com negócio — logo `tb_cotacao_bruta` NÃO tem linha pra dia sem negócio) e o
resto, histórico de PREDECESSORA que o Yahoo emendava sob o ticker novo (TASA4 ← FJTA4 antes de
2019, ITUB3 antes de 2009, SANB3/4 antes de 2007, CYRE3/CAMB3/CSUD3…). Nenhum dia de posição aberta de
usuário perdeu cotação, e patrimônio/ganho/rentabilidade ficaram idênticos ao centavo. Backups:
`bkp_cotacao.tb_cotacao_pre_full` (yfinance puro) e `tb_cotacao_pos_merge` (antes do apagar).
Ticker renomeado só mantém histórico se estiver em `tb_ticker_historico`.

**Descoberta de trocas de ticker só com o COTAHIST** (`scrape/descobre_trocas_ticker.py [--aplica]`):
indexa todas as séries (código, ISIN) e monta, pra cada ativo, a cadeia de predecessoras. Tipos de
ligação: `ISIN` (mesmo ISIN, outro código — certo; é a recodificação de 1998 e renomeações que mantêm o
ISIN) e por PREÇO quando o ISIN mudou (ele carrega as 4 letras do emissor, BRFJTAACNPR2 → BRTASAACNPR4):
série antiga termina colada (≤10 dias) no início da nova, mesma classe e fechamento contínuo —
`PRECO-A` exige nome de pregão ou prefixo de código parecido (FORJA TAURUS ~ TAURUS ARMAS, ITAUBANCO ~
ITAUUNIBANCO) e `PRECO-B` aceita candidato ÚNICO com gap ≤5d e razão 0,9–1,12 (TRNA11 → TAEE11, nome
muda por completo). `PRECO-fraco` NUNCA é aplicado e para a cadeia: só por preço dá falso positivo
(PETR4 casaria com CEMIG, ABEV3 com Vicunha Têxtil, BRKM6 com a Transbrasil). Resultado:
TASA4 ← FJTA4 ← FJT 4 (1994+), ITUB3 ← ITAU3 ← ITA 3, PETR4 ← PET 4, VALE3 ← VAL 3...
`tb_ticker_historico` ganhou `cd_isin` e a chave virou (`sg_ticker_antigo`, `cd_isin`): o mesmo código
antigo pode ter ISINs diferentes (FJT 4 tem dois) e código é reaproveitado por empresas diferentes;
`cd_isin` NULL = vale pro código todo (ligações manuais antigas). Backup antes: `bkp_cotacao.tb_cotacao_pre_chain`.

**Proventos antigos em escala de lote**: a B3 informa provento anterior a ~2005 por LOTE de 1.000 ações
(CMIG4 1998-03-16: 202,94 em base de hoje contra preço ~R$4). Com a série agora indo até 1994, aplicar
isso no ajuste de retorno total fazia o fator explodir (10³⁵) ou ficar negativo e estourar
`NUMERIC(20,8)` (47 ativos falharam no `--full`, o rollback manteve as linhas antigas deles). Trava em
`ajusta_total_return`: provento ≥ 50% do preço da véspera é descartado (e o scraper imprime quantos —
CMIG4: 29, de 1998 a 2007). Consequência: `vl_fechamento_ajustado` antes de ~2007 subestima os
dividendos; `vl_fechamento` (só eventos) não é afetado.

**Resultado da emenda (2026-10-18)**: `tb_cotacao_bruta` = 1,33M linhas, 440 ativos, de 1994-07-04 a
2026-10-16 (TASA4 7.859 pregões desde 1994, ITUB3/PETR4/VALE3/BBAS3 desde 1994, VIVT3 desde 1998).
Saltos "limpos" (×2, ×3, ×10…) sem evento por perto caíram de 2.495 (110 tickers) pra 187 (65 tickers,
quase todos ilíquidos). Patrimônio/ganho/rentabilidade dos usuários idênticos ao centavo.
**Pendência — eventos antigos que a B3 não lista**: 283 saltos PERSISTENTES (nível novo se mantém 10
pregões, volume >0, sem evento a 7 dias) em 136 tickers, 100 deles até 2007 — BBDC4 em 2004-12 (×0,33),
2005-11 (×0,5), 2007-03 (×0,5), ITUB4 em 1999 e 2011, etc. Os eventos de yfinance que restam (393)
cobrem só ~2008+. Efeito: `vl_fechamento` antes do salto fica na base errada (degrau). Caminho
previsto: inferir o fator do próprio salto (F ≈ preço da véspera ÷ preço do dia), aceitar só quando cai
a ≤6% de um valor "redondo" (2, 3, 4, 5, 10…, 1/k) e gravar com `ds_origem='COTAHIST'` (reversível);
bonificação pequena (10–30%) é indistinguível de oscilação normal e fica de fora.
Download do COTAHIST ficou robusto (4 tentativas, arquivo `.part`, cache do ano corrente só vale no
mesmo dia).

**Eventos corporativos: auditoria e protótipo CVM (2026-10-18)** — `backend/tests/auditoria_eventos.sql`
confronta cada evento com o salto do preço bruto (`vl_fechamento × fn_fator_acumulado`): dos 974 eventos
líquidos, 426 confirmados, 37 contraditos, 11 divergentes, 196 pequenos demais (<~22%) e 304 sem preço.
B3 erra ~6% dos conclusivos e yfinance ~17%. A API de eventos da B3 é PARCIAL (Bradesco: 10 linhas em 25
anos, nenhuma bonificação de 2004-2021; Itaú 2011: só a perna do grupamento ×0,01, sem o desdobramento
×100 simultâneo → preços de ITUB3/ITUB4 antes de 2011 ficaram 100× acima). A CVM TEM todos: os avisos/atas
do IPE (`ipe_cia_aberta_<ano>.zip`, de 2003 em diante) descrevem cada evento no `Assunto` e, no PDF
anexo (`Link_Download`, `pdftotext`), o fator e a data-base. `scrape/prototipo_eventos_cvm.py TICKER... [--pdf]`
(SÓ LEITURA, não grava) cruza CVM × COTAHIST: fator e dia ex vêm do aviso ("a partir de 26.3.2013 as ações
passarão a ser negociadas ex-bonificação", ou "Data-base: ... final do dia 20.5.2013" → ex = pregão
seguinte) e o preço bruto só confirma; pernas que se anulam (grupamento 100:1 + desdobramento 1:100) =
NEUTRO. Amostra de 12 papéis (113 episódios): reproduziu 44 eventos do banco na MESMA data, achou 6
faltando (BBDC4: grupamento 2004, desdobramento 2004-12 ×3, bonificações 2005-11 ×2, 2007-03 ×2, 2010-07
×1,1; ITSA4: 2025-02 ×1,05), acusou o erro do ITUB 2011 e deixou 60 episódios "sem dado". Limites: IPE só
existe a partir de 2003 (1994-2002 fica com B3 + preço); a redação do aviso varia por empresa (recall de
data/fator ~50% nos episódios pós-2003); fator inferido só pelo preço NÃO é confiável pra valor não
redondo (TASA4: preço sugeriu ×0,1, o certo é 1:11 = 0,0909). Pendência: virar `scraper_eventos_cvm.py`
(origem 'CVM'), melhorar o extrator e decidir o que fazer com os eventos de yfinance não verificáveis.

**`tb_ticker_historico` (ticker antigo → ativo atual)**: pra datas ANTES de `dt_alteracao` o
ativo é a série do ticker ANTIGO, e as linhas do ticker novo nesse período são descartadas.
Caso real: AESB3 → AURE3 (incorporação, 2024-07-01) — as compras de 2022 foram a ~R$10,8 (preço
do AESB3), e o AURE3 tinha série própria (~R$14,5) que negociava em paralelo; misturar as duas
alternava os preços dia a dia. Mesma lógica vale pra CPLE6 → CPLE3 e TRPL4 → ISAE4.

**Eventos que a B3 não lista**: `backend/tests/saltos_sem_evento.sql` lista saltos diários grandes
na série já ajustada, sem evento num raio de 7 dias (rodar depois de atualizar cotações; revisar à
mão — papel ilíquido/em recuperação e crash de mercado, como PETR4 em 09/03/2020, geram ruído).
Pendência conhecida: antes de ~2005 o COTAHIST cota alguns papéis por lote de 1.000 ações
(`FATCOT`, ignorado em `parse_linha`), gerando saltos ×20/×1000 em tickers antigos (BRKM6, CEGR3)
— sem efeito na carteira atual.

## Cotação real × ajustada (redesenho de 2026-10-18)

`tb_cotacao` deixou de existir (backup em `bkp_cotacao.tb_cotacao_pre_bruta`). Antes ela guardava o preço
JÁ AJUSTADO pelos eventos da época da raspagem e o real era recalculado na leitura
(`vl_fechamento × fn_fator_acumulado`) — o contrário do certo: corrigir um evento obrigava a regerar a
cotação do ativo, e no modo incremental um split NOVO só ajustava as linhas novas, deixando as antigas
sem o ajuste. Agora a fonte é o real e o ajustado é derivado, no mesmo padrão das demais tabelas derivadas:

- `tb_cotacao_bruta` — preço REAL do dia, como o COTAHIST informou (÷ `FATCOT`, só R$). Única que os
  scrapers de cotação gravam (`scraper_cotacoes_b3.py`, sem nenhuma lógica de ajuste). Evento novo ou
  corrigido não exige mexer aqui.
- `tb_cotacao_ajustada` — derivada, recalculada do zero por `fn_popula_cotacao_ajustada()` (~15 s, chamada por
  `fn_rebuild_tudo()`; nunca gravar na mão). Mesmas colunas que a antiga `tb_cotacao`: OHLC e `vl_fechamento`
  ajustados por eventos (real ÷ `fn_fator_acumulado`), `vl_fechamento_ajustado` (retorno total, desconta
  proventos) e `vl_fechamento_nominal` (o real). Provento vira fator `(P − v)/P` com P = fechamento do pregão
  anterior ao ex já ajustado por evento e v = valor real ÷ `fn_fator_acumulado(dt_ex)`; trava de 50%
  (provento ≥ 50% do preço = escala de lote, descartado). Soma de logaritmos em janela, provento ordenado
  ANTES do pregão do mesmo dia (só conta pra dias estritamente anteriores ao ex).
- Quem lê cotação ajustada usa `tb_cotacao_ajustada`; quem só precisa de data de pregão ou do real usa
  `tb_cotacao_bruta`. O nome antigo some de propósito: leitor esquecido falha na hora em vez de ler errado.

Validação da troca: nos 25 ativos regerados no dia (128.266 linhas, 1994+) a derivada bate com a tabela antiga
em até 6e-10; nos outros 40 só o retorno total diferia, porque os proventos tinham sido reraspados depois.

**Bug do fuso em `fn_popula_posicao_diaria` (achado na troca, corrigido)**: o banco roda em
`America/Fortaleza`, que teve horário de verão nos anos 90. `generate_series(date, CURRENT_DATE, '1 day')`
promove a `timestamptz` e uma série que COMEÇA antes de ~2000 anda 1 h fora e perde o último dia. A posição
terminava em ontem e `fn_posicao_atual` (que filtra `MAX(dt_posicao)`) a descartava. Atingia qualquer posição
com evento corporativo antigo legítimo: CAMB3 do jlrterceiro (780 ações) e PETR4 do mario (250) sumiam do
patrimônio, e o evento espúrio de BBAS3 1996 escondia BBAS3/GOAU3/GOAU4 do mario e do ediesley. Corrigido com
`generate_series(...::timestamp, ...)`. **Os números de referência antigos (patrimônio 88.845,59 do
jlrterceiro) estavam errados por isso.** Referência certa em 2026-10-18: patrimônio jlrterceiro 95.615,99 /
mario.eulalio 45.428,69 / ediesley 5.110,40; ganho total 115.611,80 / 24.692,09 / 2.210,02; rentabilidade
composta 139,04% / 107,61% / 26,75% — **estes três números de rentabilidade estavam errados** por outro bug (unidade
da quantidade, ver "Rentabilidade diária (TWR)"); os corretos são 159,54% / 108,92% / 54,88%.

## Eventos corporativos: reconstrução só com fontes oficiais (2026-10-18)

Regra de ouro: o **preço bruto do COTAHIST** é o único árbitro que DESMENTE um evento. Ajuste do strike das
opções e oscilação da B3 CONFIRMAM e DATAM, mas a ausência deles não prova nada (a B3 às vezes troca o código
da série em vez de ajustar; EGIE3 2018, EQTL3 2019, NATU3 2019, WEGE3 2018 e PETR4 2000 são eventos reais que
as opções não mostravam). Evento certo ⇒ série ajustada contínua na data; espúrio ⇒ a série ajustada pula por
F; mal datado ⇒ pulo compensatório perto. Pernas que se anulam no mesmo dia (grupamento + desdobramento,
líquido ≈ 1) NUNCA são removidas.

Fontes, da mais à menos exata:
- **S1** `tb_negocio_diario` (arquivo `TradeInformationConsolidatedFile` do `arquivos.b3.com.br`, coletor
  `scraper_negocios_b3.py`, só de 2025-06-11 em diante — a B3 serve ~16 meses). `OscnPctg` é a oscilação contra
  o fechamento anterior JÁ AJUSTADO (evento e provento líquido de IRRF): `F_total = (1+osc)·P_ant/P`,
  `F_total = F_evento × F_div`, `F_div = P/(P − provento líquido)`. Dá fator e dia exatos por ticker
  (`eventos_por_oscilacao.py`). Hoje 95 eventos; 7 dias sem arquivo são lacunas reais de publicação.
- **S2** strike das opções (`eventos_por_opcoes.py`, de 1994): a B3 ajusta o `PREEXE` na data ex; várias séries
  da mesma raiz mudando na mesma razão (multiplicativo, ≥4 séries, 80% consistentes) = fator do evento. Só vale
  pra papel com opções (157 raízes). Provento em dinheiro é aditivo e o filtro descarta.
- **S3** preço bruto: desmente (ou reposiciona, se achar o salto compensatório) evento grande (|ln F| ≥ 0,15);
  pra evento pequeno (< 0,4) o reposicionamento por preço só vira "ambíguo".
- **B3 API de eventos** (`scraper_eventos_corporativos_b3.py`) e **CVM** (abaixo) completam o resto.

`reconstroi_eventos.py [--aplica] [--diario]` junta tudo: ADD / REPLACE / FIX_DATA / REMOVE, backup em
`bkp_eventos.tb_evento_corporativo_pre_recon` (`..._pre_diario_<data>` no modo diário), removidos/trocados em
`tb_evento_rejeitado` (os scrapers consultam pra não reinserir). Origens novas em `ds_origem`: `B3-OSC`,
`B3-OPCOES`, `B3-PRECO`, `CVM`. Fonte exata (S1/S2) manda na data: evento do banco com o fator certo a 1-3 dias
de distância é movido. Evento pequeno (< ~28%) só entra com 2ª evidência (aviso no índice IPE da CVM), senão
vira ambíguo. Rodada de 2026-10-18: 29 removidos (ITUB3/4 2011 ×0,01, ABEV3 2013 ×5, AMER3 2024 ×0,01, VALE3
1997, GGBR4/GOAU3/GOAU4/UNIP6/USIM5 de 1999-2000, OIBR 2013, BEES, etc. — preço bruto contínuo), 7 datas
corrigidas (INEP4, USIM3, CEBR5, VIVR3, MWET3, LREN3, SLCE3), 1 fator trocado (OIBR4 2012 ×1,0341), 6 adições
(BBDC4 2010-07-14 ×1,1, TOKY3, IFCM3, RVEE3, VIVR3, OIBR3). Auditoria por origem após a rodada: B3 280
confirmados / 17 errados (~6%), yfinance 146 / 30 (~17%) — os errados do yfinance foram os removidos.
**42 ambíguos ficam parados** (ajustes de 3% a 17%, provavelmente proventos extraordinários; KLBN 2025-12 ×1,05
no arquivo contra bonificação ×1,01 em 12-18 no banco; DOHL4 ×1,25 e PATI3/4 ×1,31 por preço).

**Carga CVM aplicada em 2026-10-18** (435 ativos, relatório em `/tmp/eventos_cvm.csv`, backup em
`bkp_eventos.tb_evento_corporativo_pre_cvm`): 125 eventos do yfinance confirmados pelo aviso (só `ds_origem` →
`CVM`), 8 adicionados (BBDC4 2004-03-22 ×0,0001 / 2005-11-23 ×2 / 2007-03-26 ×2, AXIA6 2007, CMIG3 2013 ×1,30765,
CTAX3 2016 ×0,01, FRIO3 2015 ×1/3, MGEL4 2004 ×0,001) e 1 trocado (INEP4 2005-08-29 ×0,1 → ×0,0001; o preço real
pulou ~9.773×). Os 9 foram conferidos de forma independente contra o preço real do COTAHIST (salto = 1/F). Não
aplicados: 37 "REVISAR" (aviso e banco divergem sem prova) e 2 falhas (GFSA3 e OSXB3: `ValueError` de log de preço
0, a corrigir). A auditoria de preço passou de 426 confirmados / 37 contraditos para 443 / 3; restam 13
não-confirmados (SHUL4 2008, VALE3 1996, BBDC3 2004, BGIP3 1997, CTSA3 2020, DOHL4 2020, GSHP3 2019, PATI3/4 2021,
RCSL3 2023, TASA3 2011, TELB4 2011, VIVR3 2026), todos anteriores às operações dos usuários ou em ativos que eles não
têm: patrimônio e ganhos ficaram idênticos.

**Os 13 eventos que a auditoria de preço não confirmava, resolvidos (2026-10-18)** com avisos da CVM, API de
eventos da B3 (`GetListedSupplementCompany`, inclusive entradas que o scraper descarta) e preço real. Backup:
`bkp_eventos.tb_evento_corporativo_pre_13`.
- Certos como estavam (6): SHUL4 2008 ×1,24434 (aviso: 2.506.241 bonificadas sobre 10.257.144 = 1,244343, ex
  14/04), VALE3 1996 ×0,1 (B3: grupamento 10:1; o preço pré-abr/1996 vem em escala de lote ~10× menor),
  BGIP3 1997 ×2,5 (B3, preço de 0,0002 é só ruído), CTSA3 2020 ×2,8321 (B3 e CVM: bonificação de 183,2101627%),
  GSHP3 2019 ×2 (B3: bonificação 100%; a queda maior no preço é a subscrição de capital) e PATI3 2021-08-04 (B3).
- Corrigidos: BBDC3 2004-12-14 ×2 → ×3 e BBDC4 2004-12-14 ×3 (faltava): aviso do Bradesco, "desdobramento em
  200%" = 2 novas por 1; TELB4 2011-01-24 ×0,1 → ×0,0001 (preço saltou 9.546×, TELB3 já tinha ×0,0001); TASA3
  2011-07-07 ×1,381 → ×1,22611 e TASA4 ×1,22611 (faltava): reestruturação Polimetal, 1.000 ações viram ~1.226
  (0,4593 × 1,9331 × 29/21), não só o desdobramento 1:29 + grupamento 21:1 (= 1,381). A bonificação de 2011-05-02
  (×1,1) estava certa, o ×1,38095 que o parser leu nela era o evento de julho.
- Removidos (4, em `tb_evento_rejeitado`): DOHL4 2020-05-04 e PATI4 2021-07-01 (duplicatas do yfinance mal
  datadas; os reais são 2020-07-30 e 2021-08-04), RCSL3 2023-05-02 (a queda de 50% foi aumento de capital; o
  grupamento real é 2023-07-10) e VIVR3 2026-02-24 ×2,0597 (B3 ajustou a referência mas não há aviso de
  bonificação/desdobramento e o preço não agiu como tal; provável direito de subscrição; confiança média).
**Limitação**: o modelo não tem direito de subscrição (aumento de capital com preço de emissão baixo): a queda de
preço no ex-direito aparece como degrau que nenhum evento explica (GSHP3 2019, RCSL3 2023, VIVR3 2026).
`reconstroi_eventos.py` agora consulta `tb_evento_rejeitado` e não reintroduz evento já rejeitado. A auditoria de
preço ficou em 447 confirmados / 1 contradito / 6 divergentes (todos os 7 não-confirmados têm base oficial).

**Carga única do passado × rotina diária (decisão do usuário)**: `scraper_eventos_cvm.py` lê avisos/atas do IPE
da CVM (inclusive PDF/anexo) a partir do protótipo `prototipo_eventos_cvm.py` e serve SÓ pra melhorar o
histórico; só CRIA/TROCA evento quando aviso e salto de preço concordam, confirma (`ds_origem='CVM'`) os do
yfinance que o aviso bate, e NUNCA move a data do banco pela do texto: a data extraída do PDF erra 2-4 dias
(BBDC4 2013: texto 28/3, opções e preço 26/3). A rotina diária (`atualiza_diario.py`) não usa PDF: cotações →
negócios da B3 → eventos da API → `reconstroi_eventos.py --diario --aplica` (só S1, últimos 15 dias) →
proventos → `fn_rebuild_tudo()`.

## Orquestração (Airflow, `orquestracao/`)

Airflow 3.3.2 (estável mais recente em 2026-10-19) via Docker Compose, **dentro do mesmo repositório** (as DAGs chamam os
scripts de `scrape/` e leem o `.env` da raiz; o projeto inteiro é montado em `/opt/projeto`; dá pra separar depois). LocalExecutor
(uma máquina: sem Redis/Celery), `network_mode: host` (o Postgres da carteira é `localhost:5432` e os scripts usam
`PGHOST=localhost`), metadados do Airflow em outro Postgres (container, porta 5433), UI/API em `http://localhost:8080`.
`orquestracao/.env` (segredos, gerado, fora do git; `.env.example` mostra as chaves) e `Dockerfile` (poppler-utils pro `pdftotext`
+ `requirements.txt` dos scripts). Subir: `cd orquestracao && docker compose up -d --build`; login `admin` + `AIRFLOW_ADMIN_PASSWORD`
do `.env`. Instalado e testado em 2026-10-19 (Docker 29.9.1 / Compose 5.6 via repo oficial da Docker no Fedora 44; o usuário
precisa estar no grupo `docker`). DAGs (nascem PAUSADAS; as duas foram ligadas em 2026-10-19): `atualiza_diario` (dias úteis 20h, uma tarefa por etapa, retry 2× a cada 10 min,
termina em `scrape/rebuild_tudo.py`; o `scrape/atualiza_diario.py` segue existindo como CLI manual) e `cotacao_intradia`
(`*/5 10-18 * * 1-5`, SUBSTITUIU o `scraper_cotacao_intradia.py --loop`, que foi desligado); o Airflow foi DESLIGADO em 2026-10-21 a pedido
do usuário (`docker compose stop`; religar com `docker compose up -d`) — enquanto parado, a coleta intradia e a DAG diária não rodam, use `scrape/atualiza_diario.py`. Pendente: alerta de falha (e-mail/Telegram), checagem
de "COTAHIST do dia chegou" e feriados.

## Pipeline de recálculo

Depois de importar operação nova ou rodar qualquer scraper, rodar:

```sql
SELECT fn_rebuild_tudo();
```

Isso chama, na ordem certa: `fn_popula_provento_ajustado` → `fn_popula_cotacao_ajustada` →
`fn_popula_posicao_diaria` →
`fn_popula_provento_recebido` → `fn_popula_rentabilidade_ativo_diaria` →
`fn_popula_rentabilidade_diaria`. As funções `fn_popula_*` limpam a tabela com `DELETE FROM`, **não `TRUNCATE`** (decisão de 2026-10-18): `TRUNCATE` pede
lock exclusivo e entrava em deadlock com qualquer tela lendo a posição durante o recálculo (leitor segura a
posição e espera a cotação, o rebuild segura a cotação e espera a posição) — abortava o rebuild disparado pelo
upload e a carteira ficava desatualizada (achado quando o patrimônio do app não bateu com o da B3). Com `DELETE`
o leitor vê o dado antigo, consistente, até o commit. Testado com 79 rodadas de leitura simultânea: 0 erros. A
thread do upload (`perfil.py`) ainda tenta de novo até 3 vezes em caso de `DeadlockDetected`. O rebuild leva ~90 s.
A ordem importa (cada uma depende da anterior) — usar essa
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
- **Rentabilidade diária**: preço de compra/venda (raw) é DIVIDIDO pelo fator antes de comparar com `tb_cotacao_ajustada.vl_fechamento` (já ajustada por eventos).
- **Provento (`ds_origem='yfinance'`, hoje só FII/BDR)**: valor por ação do yfinance (já
  ajustado pra baixo) é MULTIPLICADO pelo fator pra recuperar o valor real pago na época,
  gravado em `tb_provento.vl_unitario_ajustado`. **Provento (`ds_origem='B3'`, ações)**: a B3
  já reporta o valor real da época direto, sem reescrita retroativa — `vl_unitario_ajustado`
  não precisa de fator nenhum (= `vl_unitario`); quem precisar comparar contra a cotação de
  HOJE precisa DIVIDIR pelo fator (mesma direção da rentabilidade diária) — ver seção de
  proventos pra detalhe completo.

yfinance também tem **eventos de split duplicados** às vezes (mesmo fator, poucos dias de
diferença — bug deles, confirmado contra fontes oficiais várias vezes, e que volta toda vez
que o scraper roda de novo porque a fonte continua reportando os dois). Por isso
`scraper_eventos_corporativos.py` (yfinance, APAGADO em 2026-10-18; mantido aqui só como contexto dos 393 eventos antigos) chamava `remove_duplicados()` no final de toda execução,
removendo automaticamente a data mais recente de cada par (mesmo `id_ativo`+`vl_fator`, até 14
dias de diferença). `test_validacoes.sql` confere que não sobra nenhum par desses.

**`scraper_eventos_corporativos_b3.py` (complementar, não substitui o de yfinance)**: yfinance
joga desdobramento e bonificação no mesmo balaio (`SPLIT`, só pelo sinal do fator) — a B3
distingue os dois de verdade (`GetListedSupplementCompany`, ver seção de proventos pra detalhe
da API). Mas o endpoint da B3 pra isso **não é o histórico completo** (confirmado contra a UI
renderizada de verdade, não só a API — PETR4/VALE3/BBAS3 têm cada um 3-4 eventos no nosso banco,
vindos do yfinance, que simplesmente não aparecem na resposta da B3), então esse scraper só
SUBSTITUI/ADICIONA eventos nos pontos (ativo+data, tolerância de 14 dias, mesma janela do
`remove_duplicados`) onde a B3 tem dado — nunca um `DELETE` geral como fizemos pra proventos.
`tb_evento_corporativo.ds_origem` (`'B3'` ou `'yfinance'`, coluna nova) marca a procedência de
cada linha.

`factor` da B3 tem DUAS convenções diferentes pro mesmo campo, dependendo do `label`:
- `GRUPAMENTO`: `factor` já É o multiplicador direto, mesma semântica de `vl_fator` (confirmado
  exato: CEMIG 2007, `factor=0,002` bate com nosso `vl_fator=0.002`).
- `DESDOBRAMENTO`/`BONIFICACAO`: `factor` vem em PERCENTUAL, precisa `1 + factor/100` pra virar
  multiplicador (confirmado exato: PETR4 2008, `factor=100` → 2,0, bate com o split 2:1 conhecido;
  CEMIG 2024, `factor=30` → 1,3, bate com o `SPLIT` que o yfinance já tinha gravado pra essa data
  — só que com o tipo errado, era bonificação, não desdobramento).

Match de classe (ON/PN) é pelas posições 10-11 do ISIN (`isinCode`/`assetIssued`, igual a lógica
de proventos) — `classe_do_isin()`. UNIT não tem esse padrão de ISIN (usa "CDA" em vez de "ACN"
+ classe) — cai num fallback simples (atribui ao ativo classe UNIT do emissor, se existir).
Eventos simultâneos do mesmo tipo na mesma data pro mesmo ativo (confirmado em BBAS3 1996: 3
bonificações de 20%/30%/50% no mesmo dia) são agregados por PRODUTO dos multiplicadores antes
de gravar, não um sobrescrevendo o outro — efeito cumulativo correto. **Mas só dentro do MESMO
ISIN**: a B3 repete o mesmo evento uma vez por ISIN da classe (BBAS3 tem 3 ISINs de ON, COCE5 2
de PN), e multiplicar entre ISINs elevava o fator à potência do nº de ISINs (BBAS3 2024:
bonificação 2,0 virava 8,0; grupamento 0,001 virava 1e-9 → `round(,6)` = 0 → cotação `NaN` e
rentabilidade absurda, BBAS3 chegou a +14.663%). Entre ISINs da mesma classe usa-se o valor de
um só. Desdobramento+grupamento no mesmo dia são eventos de TIPO diferente (VIVT3 2025: ×80 e
×0,025 = 2,0 líquido, bate com o salto real do COTAHIST) e a limpeza é em duas fases (apaga os
eventos B3 antigos do ativo + yfinance a até 14 dias de um evento B3, e só depois grava) pra um
evento B3 nunca apagar o irmão recém-gravado. O mesmo evento listado sob ISINs com
`lastDatePrior` diferentes (HOOT4/FESA4/EUCA3 1987-89) fica só com a data mais antiga.

Eventos anteriores ao início da nossa `tb_cotacao_bruta` (raspagem não cobre essa época) usam
fallback de `+1 dia corrido` em vez de tentar achar o próximo pregão (que acharia um pregão
real, mas anos depois da data certa, se não tiver cotação por perto) — impreciso, mas não
absurdo, e sem efeito prático já que não há nada no sistema pra comparar contra essa época
mesmo.

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

**Método (análise de 2026-10-18)**: TWR com valorização diária, encadeado geometricamente. Ganho do dia por ativo =
posição mantida × (fechamento − fechamento anterior) + vendido × (preço de venda − fechamento anterior) + comprado ×
(fechamento − preço de compra) + proventos líquidos na data ex; base = capital exposto (posição de ontem + compras
do dia). Retorno agregado = Σganho ÷ Σbase (média ponderada pelo capital). Aproximação conhecida: o dia inteiro pesa
igual pra quem comprou/vendeu no pregão (Dietz com peso 1), erro de segunda ordem. É TWR só da carteira de AÇÕES: não
modela caixa (no método `acoes`; os métodos `gips`/`status_invest` incluem o caixa dos proventos, ver "Rentabilidade:
métodos"), nem custos/IR (as operações não trazem taxa; `vl_taxa`/`vl_ir` são todos 0). XIRR foi feito e REMOVIDO em
2026-10-19 (decisão do usuário: ficam só TWR e Status Invest); benchmarks (CDI/Ibovespa) ainda não.

**Bug de unidade (corrigido em 2026-10-18)**: `tb_cotacao_ajustada` traz preço ajustado por TODO evento posterior,
mas `tb_posicao_diaria`/`tb_operacao` guardam quantidade e preço nominais da época; só o preço de compra/venda era
convertido (÷ `fn_fator_acumulado`), a quantidade não. O retorno de cada ativo saía certo (ganho e base escalam
juntos) mas o PESO dele na carteira ficava errado em todo dia anterior a um split/grupamento posterior (IRBR3 30×,
CASH3 10×, MGLU3 ~9,5×, SLCE3 0,4×). Ex.: ediesley em 15/02/2022 tinha R$ 326 de capital real e a base somava R$ 769
(IRBR3, posição de R$ 12,76, entrava com R$ 382,80). Agora a quantidade é multiplicada pelo mesmo fator
(posição de D−1 × `fn_fator_acumulado(ativo, D−1)`; compras/vendas do dia × `fn_fator_acumulado(ativo, D)`).
Validado contra um cálculo independente em valores NOMINAIS (sem série ajustada, evento tratado só no dia em que
ocorre): diferença máxima de 3e-8 p.p. em todos os dias dos 3 usuários. Efeito no acumulado: jlrterceiro 139,10% →
159,54%, mario 107,61% → 108,92%, ediesley 26,25% → 54,88% (2022: 4,48% → 30,16%). A conferência "ao centavo" da
migração do yfinance comparava o código com ele mesmo e não podia ver isso. Teste de regressão em
`test_validacoes.sql` (base = quantidade nominal × preço nominal da véspera; pegou 4.048 linhas na versão antiga).
`fn_popula_rentabilidade_acao_diaria` (por ação) NÃO tinha o defeito (um ativo só: o erro cancela).

**Pendente — dia sem negócio** (efeito medido, ainda NÃO corrigido): `tb_cotacao_*` só tem dias COM negócio do ativo
(COTAHIST), então um ativo sem negócio no dia fica fora do numerador E do denominador. Com calendário de pregão e
preço carregado o acumulado muda −0,43 p.p. (jlrterceiro) e +0,49 (ediesley). O yfinance preenchia todos os dias.
Também pendente: `LN(1 + pct/100)` na API quebra se algum dia der ≤ −100% (nunca ocorreu; pior dia é −8,3%).

**Comparação com o Status Invest** (jlrterceiro, ano a ano: 3,40 / 64 / −7,19 / 42,12 em 2022–2025): nenhuma variante
reproduz (TWR com dividendos 8,22 / 70,75 / −8,43 / 54,72; só preço −1,31 / 56,36 / −16,67 / 31,26; Dietz −8,50 /
70,81 / −8,29 / 51,84). Hipóteses não confirmadas: a carteira dele inclui FII/BDR (os extratos têm DEVA11, NUBR33...),
dividendo por data de pagamento, ou outra fórmula. Proventos conferidos contra o extrato de Movimentação da B3
(abr–out/2026): MTRE3, LOGG3, RECV3, EVEN3 e BRBI11 batem ao centavo; os demais diferem só por calendário (data ex ×
pagamento). Proventos de 2025 (R$ 25,6 mil, ~23 p.p. do retorno do jlrterceiro) ainda NÃO validados: falta o extrato
de Movimentação de 2025.

## Rentabilidade: métodos (2026-10-19)

A tela de Rentabilidade tem um seletor de método (dropdown "Método", igual ao de corretora; `Rentabilidade.tsx`;
escolha lembrada em `localStorage`, padrão TWR; período padrão "Total"). O card do gráfico mostra também a rentabilidade
MENSALIZADA e ANUALIZADA do período, equivalentes compostos `(1+T)^(ref/dias) − 1` (ref = 365,25/12 ou 365; dias corridos do
primeiro ao último ponto; mensal só com ≥ 30 dias, anual só com ≥ 60, senão "—"). Os dois são TWR diário encadeado, mudando só o tratamento do dividendo:

| Método (API) | Dividendo conta em | Depois |
|---|---|---|
| **TWR (proventos a receber)** (`receber`, 1º e padrão) | data ex | fica na carteira, sem render, só até o dia do PAGAMENTO; aí sai (saque ou reinvestimento, que reaparece como compra) |
| **Status Invest** (`status_invest`) | data de PAGAMENTO | fica na carteira como caixa, sem render, pra sempre |
| **Só ações** (`acoes`, só API, usado pelo Streamlit) | data ex | SAI da carteira (o cálculo antigo; mede a escolha das ações sem caixa) |

Cálculo: `receber = ganho / (base + vl_receber_ini)`; `status_invest = (ganho − prov_ex + prov_pgto) / (base + caixa_pgto_ini)`;
`vl_receber_ini` = proventos com ex < dia e pagamento > dia (a receber no início do dia), `caixa_pgto_ini` = soma acumulada dos
pagos até o início do dia (`tb_rentabilidade_caixa_diaria`, por usuário e corretora; NULL = todas). O caixa que não rende é
um LIMITE INFERIOR do efeito. A hipótese de que o Status Invest funciona assim NÃO foi confirmada na documentação dele; vem do
encaixe numérico. Resultados em 2026-10-19 (datas de pagamento reais da CVM/B3 + estimadas pela mediana da empresa),
jlrterceiro 2022 / 23 / 24 / 25 (Status Invest real: 3,40 / 64,00 / −7,19 / 42,12): `status_invest` 4,52 / 64,48 / −7,88 / 41,83;
`receber` 8,26 / 68,71 / −8,34 / 53,62. Acumulado jlrterceiro / mario / ediesley: `receber` 155,66 / 106,82 / 54,81;
`status_invest` 125,38 / 96,29 / 58,25; `acoes` 159,54 / 108,92 / 54,88.

**Data de pagamento**: a B3 só informa os últimos ~12 meses (`GetListedSupplementCompany`, `cashDividends`:
`label`, `lastDatePrior`=data-com, `paymentDate`); conferido contra o extrato de Movimentação: 35 de 35 batem.
`tb_provento_pagamento` é persistente (o scraper de proventos apaga e regrava `tb_provento`, ela não) e acumula a
data real com o tempo; evento sem data real recebe ESTIMATIVA (`fl_estimado=true`): data-com + mediana do atraso
observado da MESMA EMPRESA e tipo (≥ 1 observação), senão da mesma empresa em qualquer tipo, senão 1 ano (365 dias) — regra do
usuário —, nunca antes do ex. A B3 usa 31/12/9999 pra "a definir": ignorado (vira estimativa). Segunda fonte (2026-10-19): formulários "Relatório Proventos" da CVM (`scraper_pagamentos_cvm.py`), de 2022 em diante,
casados por emissor (CNPJ) + data-com + valor bruto por ação (ou data única); contra as 602 datas que a B3 também tem, 96% batem
(as divergências são JCP com várias parcelas/datas "a definir" e erros da própria B3, ex.: 9999-12-31). Formulários de 2022 misturam
dia/mês e mês/dia: só aceita quando uma leitura é a única válida depois da data-com. Hoje ~2,5 mil reais e ~11,5 mil estimadas
(antes de 2022 tudo é estimado, então os anos antigos são aproximados). Casamento: `(tipo, data-com)`, procurando a data-com até 5
dias antes do pregão anterior ao ex. Pagamento em dia sem pregão entra no 1º dia da série ≥ a data.

Testes em `test_validacoes.sql`: proventos por tipo somam o recebido; pagamento ≥ ex; caixa acumulado = total de proventos recebidos.

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
(A antiga `tb_balanco_patrimonial_old_yfinance` e o scraper dela foram apagados em 2026-10-18.)

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

**Bug encontrado e corrigido (`vl_caixa` de seguradora, achado validando contra o
yfinance)**: `detecta_perfil()` agora detecta um terceiro perfil, `'seguradora'` (marcador:
presença de "Passivos do contrato de seguro/resseguro" em qualquer posição do plano de
contas — só 3 ativos têm esse texto, BBAS3/HAPV3/PSSA3; BBAS3 já cai em `'banco'` antes desse
check). Mantém o plano padrão pra `vl_ativo_circulante`/`vl_divida_total`/etc, mas
`vl_caixa` usa só `1.01.01` ("Caixa e Equivalentes de Caixa"), sem somar `1.01.02`
("Aplicações Financeiras") — pra esse perfil, essa conta é majoritariamente float de reservas
técnicas/provisões de sinistro, não caixa livre. Confirmado em PSSA3 (minha soma de
`1.01.01+1.01.02` ficava 554% maior que o yfinance, que conta só `1.01.01`; com o fix bate
exato, `1.993.244.000`) e HAPV3 (`8.330.387.000`, também exato — plano de saúde usa
contabilidade de seguro também, mesmo marcador detecta os dois).

Testado também CXSE3, SAUD3 e BBSE3 (outras seguradoras/participações do setor) pra confirmar
que o marcador não generalizou demais: CXSE3 e SAUD3 já batiam com a fórmula padrão
(`1.01.01+1.01.02`) antes do fix — pra elas, diferente de PSSA3, o yfinance CONTA as
aplicações financeiras como caixa (SAUD3: `524.928.000` bate exato; CXSE3: `1,109bi` vs
`1,076bi` yfinance, só 3% de diferença) — corretamente não caem no perfil `'seguradora'`
(não têm o marcador "contrato de seguro/resseguro" no texto). BBSE3 diverge muito (minha
`Caixa e Equivalentes de Caixa`, direto da CVM, é `6.072.474.000`; o yfinance mostra
`3.603.000`, ~1685x menor) mas não é bug meu — confirmado que não é erro de escala (ativo
total bate exato nos dois, `19.619.021.000`) e R$6bi de caixa é plausível num ativo total de
R$19,6bi; R$3,6 milhões não é. Mesma categoria de erro do próprio yfinance já documentada pra
CMIG4/ITSA4.

**Limitação conhecida, aceita de propósito (perfil seguradora, `vl_divida_total`)**: PSSA3
continua com gap de ~85% contra o yfinance (R$126,4mi vs R$820,8mi) mesmo depois do fix do
`vl_caixa` acima — "Empréstimos e Financiamentos" é genuinamente zero na CVM pra esse perfil
(confirmado em `2.01.04`/`2.02.01`, ambos zero), e nenhuma outra conta soma exatamente
R$820,8mi (testado contra "Passivos financeiros", "Passivos de contratos de seguros" e
combinações — nenhuma bate). Diferente do achado do `vl_caixa` (uma conta especifica e
exata), aqui não há candidato identificável — decisão tomada: manter como está em vez de
arriscar uma soma especulativa sem fonte confirmada.

`vl_patrimonio_liquido_total`/`vl_patrimonio_liquido`/`vl_participacao_nao_controladores`
seguem o mesmo padrão da DRE (`vl_lucro_liquido_total`/`vl_lucro_liquido`) — "Patrimônio
Líquido Consolidado" inclui participação de não controladores, confirmado em EVEN3 (total
2.305.504 − participação 377.994 = 1.927.510, bate exato com o "Stockholders Equity" do
yfinance, que só contava a parte dos controladores sem deixar isso explícito). A frase de
não-controladores no `ds_conta` varia por empresa ("Participação dos Acionistas Não
Controladores" como irmã das reservas em algumas, "Patrimônio Líquido Atribuído aos Não
Controladores" como filho direto em outras) — `popula_balanco.py` casa só por "não
controlador", que cobre as duas variações.

**Bug encontrado e corrigido (`vl_passivo_total` incluindo patrimônio líquido, achado
montando um relatório de screening/NCAV)**: a conta `'2' - Passivo Total` da própria CVM
segue a identidade contábil brasileira `2 = 2.01 (circulante) + 2.02 (não circulante) + 2.03
(patrimônio líquido)` — ou seja, JÁ inclui o patrimônio líquido, e por isso
`por_codigo(contas, '2')` sempre dava exatamente igual a `vl_ativo_total` (confirmado em
ITSA4/PETR4/B3SA3/CSAN3/ABEV3/USIM5/BBDC4 e mais, diferença sempre zero) — inútil pra qualquer
fórmula que precise só do passivo exigível (ex: NCAV de Graham, `Ativo Circulante − Passivo
Total`, que ficava sempre fortemente negativo pra toda a base). O pipeline antigo via
yfinance já mapeava esse campo pra `Total Liabilities Net Minority Interest` (passivo SEM
patrimônio líquido) — a migração pra CVM perdeu essa semântica usando a conta `'2'` literal
por engano. Corrigido derivando por subtração (`vl_ativo_total − vl_patrimonio_liquido_total`)
em vez de casar/somar `2.01`/`2.02` por texto (que tem semântica diferente por perfil
banco/seguradora, mesmo `cd_conta`, `ds_conta` diferente — arriscaria reintroduzir esse tipo
de bug). Confirmado exato nos 3 perfis (padrão, banco, seguradora): ITSA4
(19.545.000.000 = 5.339.000.000+14.206.000.000, soma de `2.01`+`2.02` direto), PETR4, B3SA3,
BBAS3, PSSA3 — identidade `vl_ativo_total = vl_passivo_total + vl_patrimonio_liquido_total`
bate exata em todos.

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

**Bug encontrado e corrigido (`vl_divida_total` faltando arrendamento mercantil, achado
validando contra o yfinance)**: pro perfil padrão, `vl_divida_total` ficava ~5-10% menor que
o yfinance em várias empresas (confirmado em ITSA4: gap de R$940mi bate exato com "Passivos
de Arrendamentos" em `2.01.05.02.05`+`2.02.02.02.04` — posições fora do ramo
`2.01.04`/`2.02.01` que a curadoria já soma). O texto de arrendamento mercantil tem **112
variações diferentes** espalhadas por posições inconsistentes entre empresas (incluindo erros
de digitação na própria base, ex: "arrendamento merncatil") — mesma categoria de instabilidade
já aceita pro capex do DFC (ver seção própria), arriscado demais generalizar pra todas.
Corrigido com `passivo_arrendamento_fora_emprestimos()`: restrito só à família de texto
"passivo(s) de arrendamento(s)" (contém "passivo" E "arrendamento", em qualquer ordem/posição
relativa — cobre "passivo de arrendamento", "passivos de arrendamentos", "passivo por
arrendamento" etc., 87 ativos afetados), só em contas-folha (sem filhos, pra não somar
conta-pai e filha juntas) fora de `2.01.04`/`2.02.01` (pra não duplicar o que já é somado
ali). Confirmado em ITSA4 (12.161.000.000, bate exato com o yfinance) e PFRM3
(1.599.043.000, bate exato). **Limitação residual aceita**: as outras ~111 variações de texto
("arrendamento mercantil", "arrendamentos a pagar" etc., sem a palavra "passivo") continuam de
fora — confirmado em SOND6 e NORD3, que usam essas frases e continuam com gap; risco de pegar
conta errada generalizando mais que isso ainda supera o ganho.

**Bug encontrado e corrigido (`vl_divida_total` com "Empréstimos e Financiamentos" escondido
fora da posição padrão, achado validando os ~380 ativos inteiros contra o yfinance, não só
amostra)**: mesma categoria do bug de arrendamento acima, mas pra divida principal — em
algumas empresas a conta de dívida de verdade mora dentro da árvore de "Outros Passivos"
(`2.01.05.02.x`/`2.02.02.02.x`, mesmas posições do arrendamento) em vez de `2.01.04`/`2.02.01`,
que ficam genuinamente zerados. Confirmado exato em ALOS3 (`2.01.05.02.05`+`2.02.02.02.07` =
258.964.000+5.556.680.000 = 5.815.644.000, somado ao arrendamento já capturado dá
6.029.867.000, bate exato com o yfinance) e ~99% em FHER3/WDCN3 (dentro de margem de
arredondamento). Corrigido com `emprestimos_fora_posicao_padrao()`: restrito à frase composta
"emprestimo(s)" E "financiamento(s)" juntos no mesmo texto (família limpa, 10 ações: ALOS3,
FHER3, IRBR3, MRVE3, PEAB3/4, SHOW3, TELB3/4, WDCN3) — não generaliza pra variantes de uma
palavra só ("Encargos sobre empréstimos", "Compromissos de empréstimos", "Debêntures"
isoladas, todas com significado contábil diferente), mesma restrição a contas-folha e exclusão
de `2.01.04`/`2.02.01` do fix de arrendamento.

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
diferentes). A antiga `tb_dre_old_yfinance` e o scraper dela foram apagados em 2026-10-18.

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

**Bug encontrado e corrigido (split controlador/não-controlador invertido, achado validando
contra o yfinance, 6ª rodada com 20 ações novas)**: variante do bug acima — em vez das duas
sub-contas zeradas, `3.11.01` ("Atribuído aos Controladores") vem **0** e `3.11.02` ("Não
Controladores") vem com **praticamente o total inteiro** (tolerância de 1%, por causa de
arredondamento na própria CVM — ex: EUCA3/EUCA4 1T de todo ano desde 2019: total `95.960.000`
vs não controladores `95.964.000`). Achado em 55 linhas/~17 ações (EUCA3/EUCA4, VSTE3, AMAR3,
OPCT3, RNEW3/RNEW4, AGRO3, PATI3/PATI4, LUXM4, VLID3, VIVT3, OSXB3, GGPS3, CMIG3/CMIG4) —
sinal de que os rótulos das duas sub-contas vieram trocados na própria fonte pra esses
períodos específicos. Corrigido com o mesmo fallback (usa o total). 4 linhas residuais em
CMIG3/CMIG4 (2022-06-30, 2022-09-30) não se encaixam no padrão (não controladores não bate
nem com zero nem com o total) — mesma categoria de anomalia pontual de CMIG4 já documentada,
deixadas como estão.

**Limitação conhecida, aceita de propósito (anomalia pontual na própria fonte CVM)**:
confirmado em VITT3 2025-06-30, `3.11.01 + 3.11.02` (−23.010.000 + −131.000 = −23.141.000)
não reconcilia com `3.11` (−21.183.000, diferença de R$1,96mi) — diferente do bug acima (que
era 0 e 0), aqui as duas sub-contas têm valor real, só não somam o total corretamente; erro
da própria CVM nesse trimestre específico, não da curadoria. `vl_lucro_liquido` usa o valor
que a CVM reporta explicitamente em "Atribuído aos Sócios da Empresa Controladora"
(−23.010.000) — correto por usar o texto literal da fonte primária, mesmo que o yfinance
mostre um número diferente (ele deriva por subtração, `Total − Não Controladores`, que dá
outro resultado quando a fonte não reconcilia). Mesma categoria de anomalia pontual já
documentada pra CMIG4 (DRE)/MRVE3 (LPA)/AXIA3 (DFC, ver seção própria) — não dá pra
"corrigir" sem arriscar mascarar um erro real em outro lugar. Mais dois casos achados na
validação completa contra o yfinance: TFCO4 1T26 (`3.11.01`=0, `3.11.02`=−142.000, não soma
com o total de 34.401.000) e BOBR4 (`3.11.01`=20.635.000, `3.11.02`=0, total=27.188.000, gap
de R$6,55mi) — nenhum dos dois se encaixa nos 3 fallbacks já implementados (nem zerados nem
≈total nem sinal trocado), mesma decisão: usar o valor literal de "Atribuído aos Controladores"
sem forçar ajuste especulativo.

**Bug encontrado e corrigido (split controlador/não-controlador com sinal trocado, achado
validando contra o yfinance, 7ª rodada com 20 ações novas)**: terceira variante da família de
bugs de split — sem participação de não-controladores (0 ou ausente), "Atribuído aos
Controladores" vem com o MESMO valor em módulo do total, mas com o **sinal trocado** já na
própria CVM. Confirmado em AMER3 1T26 (total=−329.000.000, controladores=+329.000.000) e
EPAR3 2023-06-30 (total=13.363.000, controladores=−13.363.000). Corrigido com o mesmo
fallback (usa o total), restrito a tolerância de 1% de diferença de módulo — existem mais 17
linhas na base com sinal trocado e participação de não-controladores zerada/ausente (AZUL3,
BDLL3/4, CTAX3, NEXP3 e outras), mas nessas a magnitude diverge bastante entre `vl_lucro_liquido`
e o total (não é só o sinal trocado) — ficam de fora de propósito, provavelmente um problema
relacionado mas distinto (casamento de texto pegando a conta errada), sem padrão exato
identificável pra arriscar um fix especulativo.

**Bug encontrado e corrigido (overflow na estimativa de LPA do 4T)**: a estimativa de LPA do
4T (`lucro_líquido_4T × lpa_3T ÷ lucro_líquido_3T`, ver acima) explode quando
`lucro_líquido_3T` é próximo de zero — confirmado em SOND5 (2012-09-30: lucro 3T = −R$12 mil,
lpa 3T = −614 → estimativa do 4T ≈ 5,2 milhões, estourando `NUMERIC(10,4)` e quebrando o
`INSERT`). Corrigida aplicando a mesma guarda `LIMITE_LPA` (≥10.000 em módulo → `NULL`) já
usada em `extrai_lpa()`, agora também no valor derivado.

**Bug encontrado e corrigido (`vl_receita_total` zerado, achado validando contra o
yfinance)**: `por_codigo(contas, '3.01')` ficava zerado em ~25 empresas — a própria conta
`3.01` da CVM é zero pra elas, não é erro de extração, mas em pelo menos 20 dessas a receita
real existe, só está "escondida" dentro de `3.04.04` ("Outras Receitas Operacionais") em vez
de `3.01` (CXSE3: `41.891.000` "Receitas de Acesso à Rede e Uso da Marca" +
`578.796.000` "Receitas de prestação de serviços" = `620.687.000`, bate quase exato com o
yfinance, `620.529.000`). Corrigido com `receita_em_outras_operacionais()`: quando `3.01` é
zero, soma as contas-filhas de `3.04.04` cujo texto contém "receita" (cobre CXSE3/UNIP3,
posição em filha); se a soma vier zero (filha existe mas vem zerada na própria CVM — achado
em RPAD3 2025-09-30: a única filha com "receita" no nome é `0`, mas a conta-pai tem o valor
real, `243.000` — mesma categoria do bug de split controlador/não-controlador zerado
documentado acima, só que numa árvore diferente), cai pro valor da própria conta-pai (cobre
TELB3/RPAD3, posição direto na conta-pai sem filha informativa). Holdings puras (BRAP3/4,
`3.04.04` genuinamente zero, resultado vem só de `3.04.06` "Resultado de Equivalência
Patrimonial") e OSXB3 (`vl_receita_total=0` correto nalguns períodos) ficam corretamente de
fora — nenhuma conta sob `3.04.04` tem "receita" no nome pra elas. **Limitação residual
aceita**: ~16 empresas continuam com `vl_receita_total=0` onde isso é mesmo correto (holdings
sem receita operacional) ou onde a receita real está em posição ainda mais inconsistente —
BBSE3 nem usa `3.04.04` pra isso (ali é "Despesas com Publicidade e Propaganda"), não
investigado por ser caso único, mesma decisão já aceita pro `vl_divida_total`/arrendamento
acima.

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

## Proventos (dividendos/JCP)

Fonte trocada de yfinance pra B3 (`sistemaswebb3-listados.b3.com.br`, a mesma API JSON que o
site institucional da B3 usa internamente pra mostrar "Dividendos e outros eventos
corporativos") — motivada pelo bloqueio do yfinance/Yahoo Finance (anti-bot por IP, ver seção
de fontes externas) e por uma vantagem concreta: a B3 discrimina o TIPO de cada provento
(`DIVIDENDO`, `JRS CAP PROPRIO`, `RENDIMENTO`, `REST CAP DIN`), enquanto o yfinance devolvia
tudo somado num valor bruto só, sem distinguir.

`scraper_proventos.py <TICKER opcional>` itera por emissor (igual DRE/balanço/DFC — proventos
são por empresa, replicados pra todos os `id_ativo` daquele `id_emissor`), resolve o
`tradingName` da B3 a partir de qualquer ticker do emissor (`GetInitialCompanies`), busca
todos os eventos de `GetListedCashDividends` UMA vez por emissor, e distribui pra cada
`id_ativo` filtrando por `typeStock` (`ON`/`PN`/`UNT`, casado contra `tb_ativo.sg_classe`) —
confirmado que o valor por ação É o mesmo entre classes pra um mesmo evento (Lei das S.A.
exige isso), `typeStock` só existe pra permitir que cada classe tenha sua própria
`closingPricePriorExDate` (preço de fechamento anterior ao ex, que varia por classe).
`DELETE`+reinsere por `id_ativo` a cada execução (substitui tudo, como o antigo scraper de cotações yfinance)
— sem tabela `_old_yfinance` preservada (diferente da migração de DRE/balanço/DFC): mesmo
papel semântico, só fonte melhor, sem mudança de formato que justifique manter as duas.

**Só ações (`tb_tipo_ativo.sg_tipo_ativo='ACAO'`)** — FIIs/BDRs continuam em
`ds_origem='yfinance'` (dado antigo, não re-raspado), fora do escopo dessa migração.

**`dt_ex` não vem direto da API** — a B3 só devolve `lastDatePriorEx` ("última data anterior
ao ex", a data de fechamento usada como referência, não a própria data ex). `dt_ex` real é
inferido como o próximo dia de pregão depois de `lastDatePriorEx`, consultando
`tb_cotacao_bruta` (`MIN(dt_cotacao) WHERE dt_cotacao > lastDatePriorEx`) em vez de simplesmente
`+1 dia corrido` — pega o próximo dia de pregão de verdade mesmo quando `lastDatePriorEx` cai
numa sexta (ex-data cairia na segunda, não no sábado). Confirmado contra o dado antigo do
yfinance pra BBAS3/PETR4 (mesmas datas exatas).

**Paginação tem limite silencioso**: `pageSize` acima de ~120 faz a API devolver
`totalRecords`/`totalPages` nulos e `results` vazio, SEM erro — `fetch_cash_dividends` pagina
em blocos de 120 de propósito, nunca pede tudo de uma vez.

**Mais de uma linha por (ativo, data)**: a B3 lista cada evento separadamente (ex: 2
declarações de DIVIDENDO + 2 de RENDIMENTO no mesmo `dt_ex`, valores diferentes) — confirmado
que a soma de todas bate exata com o valor único que o yfinance reportava
(PETR4 17/04/2025: 0,35477261×2 + 0,01706013 + 0,02152467 = 0,74813002, yfinance tinha
0,74813000). `tb_provento` agora agrupa por (`id_ativo`, `dt_ex`, `ds_tipo_provento`)
— `uk_tb_provento_01` mudou de `(id_ativo, dt_ex)` pra incluir o tipo.

**IRRF sobre proventos** — `vl_unitario` (bruto, como a empresa declara) tem duas colunas:
`vl_unitario_liquido` e `vl_imposto_unitario`. `RENDIMENTO`/`REST CAP DIN`=0% (isentos pra
pessoa física — decisão do usuário pro `RENDIMENTO`, que apareceu até em ações sem ser FII,
provavelmente ligado a debênture participativa tipo a da Petrobras; tratado como isento por
padrão, igual rendimento de FII, na ausência de um caso conhecido que exija alíquota
diferente). `tb_provento_recebido`/`fn_ganho_total` (e a tela de Ganhos) somam o LÍQUIDO, não
o bruto — decisão do usuário, reflete o caixa real recebido na conta. FII/BDR (ainda
yfinance) não têm líquido/imposto calculado — `fn_popula_provento_recebido` cai pro bruto
nesse caso (`COALESCE(vl_unitario_liquido, vl_unitario_ajustado)`).

`JRS CAP PROPRIO` (Lei 9.249/95, art. 9º, parágrafo único, alíquota alterada pela Lei
15.270/2025): 15% até 31/12/2025, 17,5% a partir de 01/01/2026 — alíquota por DATA
(`aliquota_imposto()` em `scraper_proventos.py`, usa `dt_ex` como referência, não a data de
pagamento real que a B3 não fornece nesse endpoint — aproximação aceita, gap entre ex e
pagamento raramente cruza a virada do ano de forma relevante), calculada já na raspagem
(não depende de usuário/posição).

`DIVIDENDO` a partir de 01/01/2026 (mesma Lei 15.270/2025): IRRF de 10%, mas só quando o
total pago por uma MESMA empresa a um MESMO usuário (pessoa física, agregado entre todas as
carteiras/corretoras dele — o limiar é por CPF) num MESMO mês passa de R$50.000 — nesse caso
incide sobre o valor TOTAL do mês, não só o excedente. Tem regra de transição: dividendo
aprovado até 31/12/2025 (mesmo que pago em 2026-2028) fica isento até 2028. Diferente do JCP,
esse cálculo depende de QUANTAS AÇÕES o usuário tem — não dá pra pré-calcular por ativo/evento
em `tb_provento` (genérico, sem usuário). Por isso fica isento nesse nível (mesma base pra
todo mundo) e o cálculo real acontece em `fn_popula_provento_recebido`, que agrega por
(usuário, emissor, mês) usando `tb_posicao_diaria` pra saber a quantidade de ações de cada um
— `dt_aprovacao` (nova coluna em `tb_provento`, capturada do `dateApproval` da B3) decide a
transição; `NULL` é tratado como "não comprovadamente isento" (mais conservador). Restrito a
`dt_ex >= 2026-01-01` — dividendo histórico (sem `dt_aprovacao` preenchido) não entra na conta
mesmo que `dt_aprovacao` esteja `NULL`. Testado contra a base real (2026-06-24): a carteira
mais exposta a uma única empresa no mês fica em ~R$561 — longe do limiar, então o IRRF de
dividendo fica em R$0,00 pra todo mundo hoje, como esperado pra investidor de varejo; o
mecanismo está pronto pra quando/se isso mudar.

**`vl_unitario_ajustado` muda de sentido**: pra `ds_origem='B3'`, a B3 já reporta o valor real
da época sem nenhuma reescrita retroativa de split (diferente do yfinance, que ajustava pra
baixo refletindo splits futuros) — `fn_popula_provento_ajustado()` não multiplica mais pelo
fator pra esse caso (`vl_unitario_ajustado = vl_unitario` direto). Isso inverteu a direção do
ajuste em `gerar_relatorio_screening.py` (dividendo médio/preço atual): antes dividia
`vl_unitario` direto (já vinha na base "ações de hoje"), agora precisa DIVIDIR por
`fn_fator_acumulado` pra trazer o valor real histórico pra essa mesma base — sem isso,
subestimaria o yield de qualquer ação que fez desdobramento no período.

## Fontes de dados externas

- dadosdemercado.com.br — NÃO é mais usado (substituído pelo cadastro B3).
- B3 (`sistemaswebb3-listados.b3.com.br`) — API JSON não documentada publicamente, usada pelo
  próprio site institucional da B3; proventos (dividendos/JCP/rendimento), ver seção própria.
  Não tem o bloqueio anti-bot agressivo do Yahoo Finance.
- yfinance — (saindo, ver "Direção do projeto") cotações antigas, splits/grupamentos, balanço patrimonial, valor de mercado (DRE saiu de
  yfinance, ver seção própria; proventos também saiu, ver seção própria). Sujeito a bloqueio
  por IP da Yahoo depois de raspagens pesadas — quando bloqueado, manifesta como timeout puro
  de conexão (sem resposta HTTP, nem 429/403) na maioria das tentativas, não como erro de
  rate-limit normal de aplicação; esperar ou trocar de rede resolve.
- dados.cvm.gov.br — dados abertos da CVM, DRE/balanço/DFC (ITR trimestral + DFP anual), ver
  seções próprias. Também tem um dataset de desdobramento/grupamento/bonificação no
  Formulário de Referência (`fre_cia_aberta_capital_social_desdobramento_<ano>.csv`,
  dentro do zip `fre_cia_aberta_<ano>.zip`) mas é esparso e inconsistente entre anos
  (apareceu no zip de 2023, ausente em 2024/2025/2026, só 2 linhas no ano em que apareceu) —
  não é fonte sistemática viável pra histórico de splits, só serviria pra um caso pontual.
- planilhas `negociacao-*.xlsx` — exportadas manualmente da B3 e importadas via `import_operacoes.py`, arquivadas em `scrape/importados/` depois de importadas
