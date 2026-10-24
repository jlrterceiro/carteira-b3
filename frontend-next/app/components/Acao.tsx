"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, brl, cor, dataBR, pct } from "../lib/api";
import { brlCompacto, num2, pctSimples } from "../lib/formato";
import BarChart, { Barra } from "./BarChart";
import BuscaAcao from "./BuscaAcao";
import Dica from "./Dica";
import GraficoPreco, { PontoPreco } from "./GraficoPreco";

type Indicador = { chave: string; rotulo: string; valor: number | null; tipo: "x" | "pct" | "brl"; dica: string };
type Resumo = {
  ticker: string; classe: string | null; nome: string; nome_ativo: string;
  cadastro: { emissor: string | null; cnpj: string | null; site: string | null; ativo: boolean; inicio_negociacao: string | null; primeira_cotacao: string | null; fim_negociacao: string | null; setor: string | null; subsetor: string | null; segmento: string | null };
  irmaos: { ticker: string; classe: string | null; ativo: boolean }[];
  cotacao: { preco: number | null; anterior: number | null; data: string | null; fonte: string | null; variacao_dia: number | null; valorizacao?: Record<string, number | null> };
  faixas: Record<string, { min: number | null; max: number | null }>;
  valor_mercado: number | null; acoes: number | null;
  capital: { data: string; total: number | null; ordinarias: number | null; preferenciais: number | null; tesouraria: number | null } | null;
  proventos_12m: number | null; dividend_yield: number | null;
  indicadores: { grupo: string; itens: Indicador[] }[]; financeira: boolean;
  retornos: { periodo: string; acao: number | null; ibov: number | null; cdi: number | null }[];
  insiders: { compras: number; vendas: number; operacoes: number; ultima: string | null; sem_valor: number } | null;
  eventos: { data: string; fator: number }[];
  demonstracoes: { ultimo_trimestre: string | null; ultimo_balanco: string | null; ttm_completo: boolean };
};
type Provento = { dt_ex: string; tipo: string | null; bruto: number; liquido: number | null; dt_com: string | null; dt_pagamento: string | null; pagamento_estimado: boolean };
type Proventos = {
  proventos: Provento[];
  por_ano: { ano: number; bruto: number; liquido: number; eventos: number; payout: number | null }[];
  payout: { atual: number; ano_atual: number; menor: number; ano_menor: number; maior: number; ano_maior: number } | null;
};
type Periodo = {
  data: string; receita: number | null; lucro_bruto: number | null; ebit: number | null; resultado_financeiro: number | null; lucro_liquido_total: number | null;
  lucro_liquido: number | null; lpa: number | null; ativo_total: number | null; patrimonio_liquido: number | null; divida_total: number | null;
  divida_liquida: number | null; caixa: number | null; caixa_operacional: number | null; caixa_investimento: number | null; caixa_financiamento: number | null;
};
type Posicao = { sg_ticker: string; quantidade: number; preco_medio: number; preco_atual: number };

const PERIODOS_COTACAO = [["1m", "1 mês"], ["6m", "6 meses"], ["1a", "1 ano"], ["5a", "5 anos"], ["10a", "10 anos"], ["max", "Máx"]] as const;
// o preco do grafico e SEMPRE ajustado por desdobramentos, grupamentos e bonificacoes; a escolha e so quanto aos dividendos (ajustado = retorno total)
const SERIES = [
  { id: "total", rotulo: "Ajustada por dividendos", dica: "Preço ajustado por desdobramentos, grupamentos e bonificações e também pelos dividendos e JCP pagos (como se fossem reinvestidos): mostra o retorno total. Os preços antigos ficam menores que os negociados na época; o último é o preço de hoje." },
  { id: "ajustada", rotulo: "Sem ajuste por dividendos", dica: "Preço ajustado só por desdobramentos, grupamentos e bonificações, sem descontar os dividendos e JCP pagos: a queda do preço no dia ex aparece no gráfico." },
] as const;
const rotuloPeriodo = (iso: string, anual: boolean) => (anual ? iso.slice(0, 4) : `${Math.ceil(Number(iso.slice(5, 7)) / 3)}T${iso.slice(2, 4)}`);

function Valor({ ind }: { ind: Indicador }) {
  if (ind.valor == null) return <>—</>;
  return <>{ind.tipo === "pct" ? pctSimples(ind.valor) : ind.tipo === "brl" ? brl(ind.valor) : num2(ind.valor)}</>;
}

function Tile({ rotulo, dica, children, classe }: { rotulo: string; dica?: string; children: React.ReactNode; classe?: string }) {
  return (
    <div className="tile">
      <div className="tile-rotulo">{rotulo}{dica && <Dica texto={dica} />}</div>
      <div className={`tile-valor ${classe ?? ""}`}>{children}</div>
    </div>
  );
}

export default function Acao({ ticker }: { ticker: string }) {
  const [res, setRes] = useState<{ ticker: string; dados?: Resumo; erro?: string } | null>(null);
  const [posicao, setPosicao] = useState<Posicao | null>(null);
  const [logo, setLogo] = useState<number | null>(null);
  useEffect(() => {
    api<Resumo>(`/acoes/${encodeURIComponent(ticker)}`)
      .then((dados) => setRes({ ticker, dados }))
      .catch((e) => setRes({ ticker, erro: e.message }));
    api<Posicao[]>("/carteira/posicao").then((r) => setPosicao(r.find((l) => l.sg_ticker === ticker) ?? null)).catch(() => setPosicao(null));
    api<Record<string, number | null>>("/acoes/logos", { params: { tickers: ticker } }).then((r) => setLogo(r[ticker] ?? null)).catch(() => setLogo(null));
  }, [ticker]);

  // cotacao
  const [periodo, setPeriodo] = useState("1a");
  const [serie, setSerie] = useState<(typeof SERIES)[number]["id"]>("total");
  const [graf, setGraf] = useState<{ key: string; pontos?: PontoPreco[]; erro?: string } | null>(null);
  const keyGraf = `${ticker}|${periodo}|${serie}`;
  useEffect(() => {
    api<{ pontos: PontoPreco[] }>(`/acoes/${encodeURIComponent(ticker)}/cotacoes`, { params: { periodo, serie } })
      .then((r) => setGraf({ key: keyGraf, pontos: r.pontos }))
      .catch((e) => setGraf((ant) => ({ key: keyGraf, pontos: ant?.pontos, erro: e.message })));
  }, [ticker, periodo, serie, keyGraf]);

  // proventos
  const [prov, setProv] = useState<Proventos | null>(null);
  const [todosProv, setTodosProv] = useState(false);
  useEffect(() => {
    api<Proventos>(`/acoes/${encodeURIComponent(ticker)}/proventos`).then(setProv).catch(() => setProv(null));
  }, [ticker]);

  // resultados
  const [tipoRes, setTipoRes] = useState<"trimestral" | "anual">("trimestral");
  const [resultados, setResultados] = useState<{ tipo: string; periodos: Periodo[] } | null>(null);
  useEffect(() => {
    api<{ periodos: Periodo[] }>(`/acoes/${encodeURIComponent(ticker)}/resultados`, { params: { periodo: tipoRes, n: tipoRes === "anual" ? "10" : "12" } })
      .then((r) => setResultados({ tipo: tipoRes, periodos: r.periodos }))
      .catch(() => setResultados(null));
  }, [ticker, tipoRes]);

  const d = res?.ticker === ticker ? res.dados ?? null : null;
  if (res?.ticker === ticker && res.erro) return <p className="err">{res.erro === "ticker desconhecido" ? `Ticker ${ticker} não encontrado.` : res.erro}</p>;
  if (!d) return <p className="muted">Carregando…</p>;

  const c = d.cotacao;
  const fx = d.faixas;
  const anual = resultados?.tipo === "anual";
  const periodos = resultados?.periodos ?? [];
  const cronologico = [...periodos].reverse();
  const barrasRec: Barra[] = cronologico.map((p) => ({ rotulo: rotuloPeriodo(p.data, !!anual), titulo: rotuloPeriodo(p.data, !!anual), valor: p.receita ?? 0 }));
  const barrasLucro: Barra[] = cronologico.map((p) => ({ rotulo: rotuloPeriodo(p.data, !!anual), titulo: rotuloPeriodo(p.data, !!anual), valor: p.lucro_liquido ?? 0 }));
  const barrasProv: Barra[] = (prov?.por_ano ?? []).slice(-15).map((a) => ({
    rotulo: String(a.ano), titulo: String(a.ano), valor: a.bruto,
    extra: [{ nome: "Líquido", valor: brl(a.liquido) }, { nome: "Eventos", valor: String(a.eventos) }, ...(a.payout != null ? [{ nome: "Payout", valor: pctSimples(a.payout) }] : [])],
  }));
  const listaProv = prov ? (todosProv ? prov.proventos : prov.proventos.slice(0, 12)) : [];
  const grafAtual = graf?.key === keyGraf ? graf : null;
  const pontos = (grafAtual ?? graf)?.pontos ?? [];
  const serieAtual = SERIES.find((s) => s.id === serie)!;

  return (
    <>
      <div className="card">
        <div className="acao-topo">
          <div className="acao-id">
            {logo && <img className="acao-logo" src={`https://statusinvest.com.br/img/company/avatar/${logo}.jpg`} alt="" />}
            <div>
              <div className="acao-titulo">
                <h2 style={{ margin: 0 }}>{d.ticker} <span className="muted" style={{ fontWeight: 400 }}>· {d.nome}</span></h2>
                {d.irmaos.some((i) => i.ticker !== d.ticker) && (
                  <div className="chips" style={{ margin: 0 }}>
                    {d.irmaos.filter((i) => i.ticker !== d.ticker).map((i) => (
                      <Link key={i.ticker} href={`/acoes/${i.ticker}`}><button type="button" title={i.classe ?? ""}>{i.ticker}</button></Link>
                    ))}
                  </div>
                )}
              </div>
              <p className="muted" style={{ margin: "8px 0 0" }}>
                {[d.cadastro.setor, d.cadastro.subsetor, d.cadastro.segmento].filter(Boolean).join(" · ") || "Setor não informado"}
                {!d.cadastro.ativo && " · fora de negociação"}
              </p>
            </div>
          </div>
          <div className="acao-preco">
            <div className="muted">Valor atual{c.fonte === "INTRADIA" ? " (intradia)" : ""}</div>
            <div className="big">{brl(c.preco)}</div>
            <div className={cor(c.variacao_dia)}>{pct(c.variacao_dia)} <span className="muted">no dia{c.data ? ` · ${dataBR(c.data)}` : ""}</span></div>
          </div>
        </div>
        {posicao && (
          <p className="acao-carteira">
            <b>Na sua carteira:</b> {posicao.quantidade.toLocaleString("pt-BR")} ações · preço médio {brl(posicao.preco_medio)}
            {posicao.preco_medio > 0 && <> · <b className={cor(posicao.preco_atual - posicao.preco_medio)}>{pct((posicao.preco_atual / posicao.preco_medio - 1) * 100)}</b> sobre o preço médio</>}
          </p>
        )}
        <div className="tiles topo">
          <Tile rotulo="Mín. e máx. 52 semanas">{brl(fx["52 semanas"]?.min)} – {brl(fx["52 semanas"]?.max)}</Tile>
          <Tile rotulo="Mín. e máx. do mês">{brl(fx["mês"]?.min)} – {brl(fx["mês"]?.max)}</Tile>
          <Tile rotulo="Dividend yield (12m)" dica="Proventos por ação pagos nos últimos 12 meses (bruto, ajustado por desdobramentos) ÷ preço atual.">
            {pctSimples(d.dividend_yield)}<div className="muted tile-sub">{d.proventos_12m != null ? `${brl(d.proventos_12m)} por ação` : ""}</div>
          </Tile>
          <Tile rotulo="Valorização (12m)" dica="Variação do preço (ajustado por desdobramentos, sem proventos) em relação ao fechamento de 12 meses atrás." classe={cor(c.valorizacao?.["12 meses"])}>
            {pct(c.valorizacao?.["12 meses"])}<div className="muted tile-sub">mês {pct(c.valorizacao?.["mês"])} · ano {pct(c.valorizacao?.["ano"])}</div>
          </Tile>
          <Tile rotulo="Valor de mercado" dica="Ações em circulação (CVM, corrigidas por eventos) × preço, ON e PN cada uma pelo seu preço. Não inclui ações em tesouraria.">
            {d.valor_mercado != null ? brlCompacto(d.valor_mercado) : "—"}<div className="muted tile-sub">{d.acoes != null ? `${(d.acoes / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 0 })} mi de ações` : ""}</div>
          </Tile>
        </div>
      </div>

      <div className="card">
        <div className="acao-cab">
          <h3 style={{ margin: 0 }}>Cotação de {d.ticker}</h3>
          <div className="acao-controles">
            <label className="filtro-corretora">
              <select value={serie} onChange={(e) => setSerie(e.target.value as typeof serie)}>
                {SERIES.map((s) => <option key={s.id} value={s.id}>{s.rotulo}</option>)}
              </select>
              <Dica texto={serieAtual.dica} />
            </label>
            <div className="chips">
              {PERIODOS_COTACAO.map(([id, rot]) => <button key={id} className={id === periodo ? "on" : ""} onClick={() => setPeriodo(id)}>{rot}</button>)}
            </div>
          </div>
        </div>
        <div className={!grafAtual && pontos.length ? "recarregando" : undefined}>
          {graf?.erro && !pontos.length ? <p className="err">{graf.erro}</p> : pontos.length ? <GraficoPreco pontos={pontos} formato={brl} /> : <p className="muted">Carregando…</p>}
        </div>
      </div>

      <div className="card scroll">
        <h3>Rentabilidade<Dica texto="Retorno total (com proventos reinvestidos) da ação contra o Ibovespa e o CDI, até o último pregão. O Ibovespa e o CDI só existem no banco desde 2018." /></h3>
        <table>
          <thead><tr><th className="esq">Período</th>{d.retornos.map((r) => <th key={r.periodo}>{r.periodo}</th>)}</tr></thead>
          <tbody>
            {([["acao", d.ticker], ["ibov", "Ibovespa"], ["cdi", "CDI"]] as const).map(([k, nome]) => (
              <tr key={k}>
                <td className="esq"><b>{nome}</b></td>
                {d.retornos.map((r) => <td key={r.periodo} className={cor(r[k])}>{r[k] == null ? <span className="muted">—</span> : pct(r[k])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Indicadores<Dica texto="Calculados só com dados da CVM e da B3 que temos no banco. Passe o mouse no “?” de cada um para ver a fórmula. Não existem EV/EBITDA nem margem EBITDA: a depreciação não está na base." /></h3>
        {d.financeira && <p className="muted">Banco ou outra instituição financeira: dívida, EBIT, margem bruta e ROIC não se aplicam (o plano de contas não separa circulante, e a “dívida” incluiria os depósitos de clientes).</p>}
        {!d.demonstracoes.ttm_completo && <p className="muted">Sem os 4 últimos trimestres seguidos na base: os indicadores que dependem de lucro e receita ficam vazios.</p>}
        {d.demonstracoes.ultimo_balanco && <p className="muted" style={{ marginTop: 0 }}>Balanço de {dataBR(d.demonstracoes.ultimo_balanco)} · resultado dos 4 trimestres até {dataBR(d.demonstracoes.ultimo_trimestre ?? d.demonstracoes.ultimo_balanco)}.</p>}
        {d.indicadores.map((g) => (
          <div key={g.grupo}>
            <h4 className="ind-grupo">{g.grupo}</h4>
            <div className="tiles">
              {g.itens.map((i) => <Tile key={i.chave} rotulo={i.rotulo} dica={i.dica}><Valor ind={i} /></Tile>)}
            </div>
          </div>
        ))}
      </div>

      <div className="card">
        <h3>Dividendos<Dica texto="Valor bruto por ação pago em cada ano, na base de hoje (dividido pelos desdobramentos posteriores). O payout do ano é o total pago por ação ÷ o lucro por ação daquele ano." /></h3>
        {!prov ? <p className="muted">Carregando…</p> : (
          <>
            <BarChart barras={barrasProv} formato={brl} formatoEixo={(v) => v.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} nomeValor="Bruto por ação" vazio="Sem proventos registrados." />
            {prov.payout && (
              <div className="tiles">
                <Tile rotulo={`Payout atual (${prov.payout.ano_atual})`} dica="Proventos do ano por ação ÷ lucro por ação do ano.">{pctSimples(prov.payout.atual)}</Tile>
                <Tile rotulo={`Menor payout (${prov.payout.ano_menor})`}>{pctSimples(prov.payout.menor)}</Tile>
                <Tile rotulo={`Maior payout (${prov.payout.ano_maior})`}>{pctSimples(prov.payout.maior)}</Tile>
              </div>
            )}
            <div className="scroll">
              <table>
                <thead><tr><th className="esq">Tipo</th><th className="esq">Data com</th><th className="esq">Data ex</th><th className="esq">Pagamento</th><th>Bruto</th><th>Líquido</th></tr></thead>
                <tbody>
                  {listaProv.map((p, i) => (
                    <tr key={`${p.dt_ex}${p.tipo}${i}`}>
                      <td className="esq">{p.tipo ?? "—"}</td>
                      <td className="esq">{p.dt_com ? dataBR(p.dt_com) : <span className="muted">—</span>}</td>
                      <td className="esq">{dataBR(p.dt_ex)}</td>
                      <td className="esq">{p.dt_pagamento ? dataBR(p.dt_pagamento) : <span className="muted">—</span>}{p.dt_pagamento && p.pagamento_estimado && <span className="muted" title="data estimada (mediana da empresa)"> ~</span>}</td>
                      <td>{p.bruto.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 6 })}</td>
                      <td>{p.liquido == null ? "—" : p.liquido.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 6 })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {prov.proventos.length > 12 && <p><button onClick={() => setTodosProv(!todosProv)}>{todosProv ? "Mostrar menos" : `Mostrar todos (${prov.proventos.length})`}</button></p>}
          </>
        )}
      </div>

      <div className="card">
        <div className="acao-cab">
          <h3 style={{ margin: 0 }}>Resultados<Dica texto="DRE, balanço e fluxo de caixa dos dados abertos da CVM. Trimestral = trimestre isolado (o 4º é o anual menos os três primeiros). Valores em R$." /></h3>
          <div className="chips">
            <button className={tipoRes === "trimestral" ? "on" : ""} onClick={() => setTipoRes("trimestral")}>Trimestral</button>
            <button className={tipoRes === "anual" ? "on" : ""} onClick={() => setTipoRes("anual")}>Anual</button>
          </div>
        </div>
        {!resultados ? <p className="muted">Carregando…</p> : periodos.length === 0 ? <p className="muted">Sem demonstrações na base para este papel.</p> : (
          <>
            <div className="grid2">
              <div><h4 className="ind-grupo">Receita</h4><BarChart barras={barrasRec} formato={brlCompacto} formatoEixo={brlCompacto} nomeValor="Receita" vazio="Sem dados." /></div>
              <div><h4 className="ind-grupo">Lucro líquido (controladores)</h4><BarChart barras={barrasLucro} formato={brlCompacto} formatoEixo={brlCompacto} nomeValor="Lucro líquido" vazio="Sem dados." /></div>
            </div>
            <div className="scroll">
              <table className="resultados">
                <thead><tr><th className="esq">R$</th>{periodos.map((p) => <th key={p.data} title={dataBR(p.data)}>{rotuloPeriodo(p.data, !!anual)}</th>)}</tr></thead>
                <tbody>
                  {([
                    ["DRE", null], ["Receita", "receita"], ["Lucro bruto", "lucro_bruto"], ["EBIT", "ebit"], ["Resultado financeiro", "resultado_financeiro"],
                    ["Lucro líquido (controladores)", "lucro_liquido"], ["LPA", "lpa"],
                    ["Balanço", null], ["Ativo total", "ativo_total"], ["Patrimônio líquido", "patrimonio_liquido"], ["Dívida bruta", "divida_total"], ["Dívida líquida", "divida_liquida"], ["Caixa", "caixa"],
                    ["Fluxo de caixa", null], ["Operacional", "caixa_operacional"], ["Investimento", "caixa_investimento"], ["Financiamento", "caixa_financiamento"],
                  ] as const).map(([rot, campo]) => campo == null ? (
                    <tr key={rot} className="grupo"><td className="esq" colSpan={periodos.length + 1}>{rot}</td></tr>
                  ) : (
                    <tr key={rot}>
                      <td className="esq">{rot}</td>
                      {periodos.map((p) => {
                        const v = p[campo];
                        return <td key={p.data} className={campo === "lpa" ? cor(v) : cor(["lucro_liquido", "ebit", "resultado_financeiro", "caixa_operacional", "caixa_investimento", "caixa_financiamento"].includes(campo) ? v : null)} title={v == null ? "" : campo === "lpa" ? brl(v) : brl(v)}>{v == null ? <span className="muted">—</span> : campo === "lpa" ? brl(v) : brlCompacto(v)}</td>;
                      })}
                    </tr>
                  ))}
                  <tr className="grupo"><td className="esq" colSpan={periodos.length + 1}>Margens</td></tr>
                  {([["Margem bruta", "lucro_bruto"], ["Margem EBIT", "ebit"], ["Margem líquida (consolidada)", "lucro_liquido_total"]] as const).map(([rot, campo]) => (
                    <tr key={rot}>
                      <td className="esq">{rot}</td>
                      {periodos.map((p) => <td key={p.data}>{p.receita && p[campo] != null ? pctSimples((p[campo]! / p.receita) * 100) : <span className="muted">—</span>}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      <div className="grid2">
        <div className="card">
          <h3>Insiders<Dica texto="Compra e venda à vista de ações e units por administradores, conselheiros, controladores e pessoas ligadas, nos últimos 12 meses (competência do formulário). Dados abertos da CVM." /></h3>
          {d.insiders && d.insiders.operacoes > 0 ? (
            <>
              <div className="tiles">
                <Tile rotulo="Compras" classe="pos">{brlCompacto(d.insiders.compras)}</Tile>
                <Tile rotulo="Vendas" classe="neg">{brlCompacto(-d.insiders.vendas)}</Tile>
                <Tile rotulo="Líquido" classe={cor(d.insiders.compras - d.insiders.vendas)}>{brlCompacto(d.insiders.compras - d.insiders.vendas)}</Tile>
              </div>
              <p className="muted">{d.insiders.operacoes} operações{d.insiders.ultima ? ` · última em ${dataBR(d.insiders.ultima)}` : ""}.{d.insiders.sem_valor > 0 ? ` Mais ${d.insiders.sem_valor} sem valor informado no formulário.` : ""}</p>
            </>
          ) : <p className="muted">Sem compras ou vendas à vista de insiders com valor informado nos últimos 12 meses.{d.insiders && d.insiders.sem_valor > 0 ? ` (${d.insiders.sem_valor} operações sem valor no formulário.)` : ""}</p>}
          <p><Link className="rank-link" href={`/insiders/${d.ticker}`}>Ver todas as operações e os formulários →</Link></p>
        </div>

        <div className="card">
          <h3>Eventos corporativos<Dica texto="Desdobramentos, grupamentos e bonificações. O fator multiplica a quantidade de ações: 2 = cada ação vira duas; 0,1 = dez ações viram uma." /></h3>
          {d.eventos.length === 0 ? <p className="muted">Nenhum desdobramento, grupamento ou bonificação registrado.</p> : (
            <table>
              <thead><tr><th className="esq">Data</th><th className="esq">Tipo</th><th>Fator</th></tr></thead>
              <tbody>
                {d.eventos.map((e) => (
                  <tr key={e.data + e.fator}>
                    <td className="esq">{dataBR(e.data)}</td>
                    <td className="esq">{e.fator > 1 ? "Desdobramento / bonificação" : "Grupamento"}</td>
                    <td>{e.fator.toLocaleString("pt-BR", { maximumFractionDigits: 6 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Sobre a empresa</h3>
        <div className="tiles sobre">
          <Tile rotulo="Empresa">{d.nome}</Tile>
          <Tile rotulo="CNPJ">{d.cadastro.cnpj ?? "—"}</Tile>
          <Tile rotulo="Setor">{d.cadastro.setor ?? "—"}</Tile>
          <Tile rotulo="Subsetor">{d.cadastro.subsetor ?? "—"}</Tile>
          <Tile rotulo="Segmento">{d.cadastro.segmento ?? "—"}</Tile>
          <Tile rotulo="Classe">{d.classe ?? "—"}</Tile>
          {d.cadastro.inicio_negociacao ? <Tile rotulo="Início de negociação">{dataBR(d.cadastro.inicio_negociacao)}</Tile> : <Tile rotulo="Primeiro pregão na base" dica="O cadastro da B3 não informa o início da negociação deste papel; esta é a data da cotação mais antiga que temos (COTAHIST, desde 1994).">{d.cadastro.primeira_cotacao ? dataBR(d.cadastro.primeira_cotacao) : "—"}</Tile>}
          <Tile rotulo="Site">{d.cadastro.site ? <a className="rank-link" href={d.cadastro.site} target="_blank" rel="noreferrer">{d.cadastro.site.replace(/^https?:\/\//, "")}</a> : "—"}</Tile>
        </div>
        {d.capital && (
          <>
            <h4 className="ind-grupo">Ações (composição do capital em {dataBR(d.capital.data)})</h4>
            <div className="tiles">
              <Tile rotulo="Total">{d.capital.total?.toLocaleString("pt-BR") ?? "—"}</Tile>
              <Tile rotulo="Ordinárias (ON)">{d.capital.ordinarias?.toLocaleString("pt-BR") ?? "—"}</Tile>
              <Tile rotulo="Preferenciais (PN)">{d.capital.preferenciais?.toLocaleString("pt-BR") ?? "—"}</Tile>
              <Tile rotulo="Em tesouraria">{d.capital.tesouraria?.toLocaleString("pt-BR") ?? "—"}</Tile>
            </div>
          </>
        )}
      </div>
    </>
  );
}

// Entrada de Ações: busca com autocomplete e atalhos das acoes em carteira
export function AcaoBusca() {
  const [meus, setMeus] = useState<string[]>([]);
  useEffect(() => {
    api<{ sg_ticker: string }[]>("/carteira/posicao").then((r) => setMeus(r.map((l) => l.sg_ticker))).catch(() => setMeus([]));
  }, []);
  return (
    <div className="card">
      <h3>Ações</h3>
      <p className="muted">Cotação, indicadores, proventos, resultados e insiders de qualquer ação da B3, com dados da B3 e da CVM.</p>
      <label className="filtro-corretora">
        <span className="muted">Ação</span>
        <BuscaAcao placeholder="Ticker ou nome (ex.: PETR4, Petrobras)" destino={(t) => `/acoes/${t}`} />
      </label>
      {meus.length > 0 && (
        <>
          <p className="muted">Suas ações:</p>
          <div className="chips">{meus.map((t) => <Link key={t} href={`/acoes/${t}`}><button type="button">{t}</button></Link>)}</div>
        </>
      )}
    </div>
  );
}
