"use client";
import { useEffect, useState } from "react";
import { api, brl, cor, dataBR } from "../lib/api";
import BuscaAcao from "./BuscaAcao";
import Dica, { DICAS } from "./Dica";

type Mes = { mes: string; compras_qtd: number; compras_valor: number; vendas_qtd: number; vendas_valor: number; link: string | null; liquido_pct: number | null; saldo_inicial: number | null; liquido_pct_posicao: number | null };
type Cargo = { cargo: string; liquido_qtd: number; liquido_valor: number };
type Operacao = {
  dt: string; cargo: string | null; empresa: string | null; tipo_empresa: string | null; movimentacao: string; operacao: string;
  ativo: string | null; caracteristica: string | null; intermediario: string | null; qtd: number | null; preco: number | null;
  volume: number | null; descricao: string | null; link: string | null; bloco: boolean; suspeito: boolean; pct_mercado: number | null;
};
type Resp = {
  ticker: string; emissor: string; nome: string; inicio: string | null; fim: string;
  resumo: { compras_qtd: number; compras_valor: number; vendas_qtd: number; vendas_valor: number; liquido_qtd: number; liquido_valor: number; liquido_percentual: number | null; saldo_inicial: number | null; liquido_pct_posicao: number | null };
  valor_mercado: number | null;
  mensal: Mes[]; por_cargo: Cargo[]; operacoes: Operacao[]; operacoes_truncadas: boolean;
};

const JANELAS: { rotulo: string; meses: number | null }[] = [
  { rotulo: "6 meses", meses: 6 }, { rotulo: "1 ano", meses: 12 }, { rotulo: "2 anos", meses: 24 },
  { rotulo: "5 anos", meses: 60 }, { rotulo: "Tudo", meses: null },
];
const GRUPOS: { id: string; rotulo: string; dica: string }[] = [
  { id: "todos", rotulo: "Todos", dica: "administradores e controladores" },
  { id: "administracao", rotulo: "Administração", dica: "conselho de administração, diretoria, conselho fiscal e órgãos estatutários" },
  { id: "controlador", rotulo: "Controladores", dica: "controlador e vinculados" },
];
const MOSTRA_INICIAL = 100;
const qtd = (v: number | null) => (v == null ? "—" : v.toLocaleString("pt-BR", { maximumFractionDigits: 0 }));
const pctVM = (v: number | null) =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${v.toLocaleString("pt-BR", { minimumFractionDigits: Math.abs(v) < 0.1 ? 3 : 2, maximumFractionDigits: Math.abs(v) < 0.1 ? 3 : 2 })}%`;
const mesBR = (m: string) => `${m.slice(5, 7)}/${m.slice(0, 4)}`;
const brl4 = (v: number | null) => (v == null ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const Doc = ({ href }: { href: string | null }) =>
  href ? <a href={href} target="_blank" rel="noreferrer">Abrir</a> : <span className="muted">—</span>;

export default function Insiders({ ticker, dataRef }: { ticker: string; dataRef: string | null }) {
  const [janela, setJanela] = useState("1 ano");
  const [grupo, setGrupo] = useState("todos");
  const [semBlocos, setSemBlocos] = useState(false);       // padrao: operacoes em bloco ENTRAM nas contas; o checkbox as exclui
  const [comSuspeitos, setComSuspeitos] = useState(false);
  const [soNegocios, setSoNegocios] = useState(true);
  const [mostraTudo, setMostraTudo] = useState(false);
  const [res, setRes] = useState<{ key: string; dados?: Resp; erro?: string } | null>(null);
  const meses = JANELAS.find((j) => j.rotulo === janela)!.meses;
  const key = `${ticker}|${janela}|${grupo}|${semBlocos}|${comSuspeitos}|${dataRef ?? ""}`;

  useEffect(() => {
    api<Resp>(`/insiders/${encodeURIComponent(ticker)}`, { params: { meses: meses == null ? undefined : String(meses), grupo, com_blocos: String(!semBlocos), com_suspeitos: String(comSuspeitos), data_ref: dataRef ?? undefined } })
      .then((dados) => setRes({ key, dados }))
      .catch((e) => setRes((ant) => ({ key, dados: ant?.dados, erro: e.message })));
  }, [ticker, meses, grupo, semBlocos, comSuspeitos, dataRef, key]);

  // mantem o resultado anterior (da mesma acao) na tela enquanto o novo carrega: esconder encolhe a pagina e joga a rolagem pro topo
  const atual = res && res.key.startsWith(`${ticker}|`) ? res : null;
  const carregando = res?.key !== key;
  const d = atual?.dados ?? null;
  const operacoes = (d?.operacoes ?? []).filter((o) => !soNegocios || o.movimentacao === "Compra à vista" || o.movimentacao === "Venda à vista");
  const visiveis = mostraTudo ? operacoes : operacoes.slice(0, MOSTRA_INICIAL);

  return (
    <>
      <div className="rent-controles">
        <label className="filtro-corretora">
          <span className="muted">Ação</span>
          <BuscaAcao placeholder={`${ticker} — buscar outra ação`} />
        </label>
        <div className="chips">
          {GRUPOS.map((g) => (
            <button key={g.id} title={g.dica} className={g.id === grupo ? "on" : ""} onClick={() => setGrupo(g.id)}>{g.rotulo}</button>
          ))}
          <span style={{ alignSelf: "center" }}><Dica texto={DICAS.grupo} /></span>
        </div>
        <div className="chips">
          {JANELAS.map((j) => (
            <button key={j.rotulo} className={j.rotulo === janela ? "on" : ""} onClick={() => setJanela(j.rotulo)}>{j.rotulo}</button>
          ))}
        </div>
      </div>

      <p className="muted opcoes">
        <label><input type="checkbox" checked={semBlocos} onChange={(e) => setSemBlocos(e.target.checked)} /> Excluir vendas em bloco e ofertas das contas<Dica texto={DICAS.bloco} /></label>
        <label><input type="checkbox" checked={comSuspeitos} onChange={(e) => setComSuspeitos(e.target.checked)} /> Incluir dados suspeitos<Dica texto={DICAS.suspeito} /></label>
      </p>

      {atual?.erro && <p className="err">{atual.erro === "ticker desconhecido" ? `Ticker ${ticker} não encontrado.` : atual.erro}</p>}
      {!atual && <p className="muted">Carregando…</p>}

      {d && (
        <div className={carregando ? "recarregando" : undefined}>
          <div className="card">
            <h3 style={{ margin: 0 }}>{d.ticker} · {d.nome}</h3>
            <div className={`big ${cor(d.resumo.liquido_valor)}`}>{brl(d.resumo.liquido_valor)}</div>
            <p className="muted">
              compra líquida dos insiders no período
              {d.resumo.liquido_percentual != null && d.valor_mercado != null && <> = <b className={cor(d.resumo.liquido_valor)}>{pctVM(d.resumo.liquido_percentual)}</b> do valor de mercado da época das operações (hoje a empresa vale {brl(d.valor_mercado)})</>}
              {d.resumo.liquido_pct_posicao != null && <>{" · "}<b className={cor(d.resumo.liquido_qtd)}>{pctVM(d.resumo.liquido_pct_posicao)}</b> da posição que o grupo tinha no começo do período ({qtd(d.resumo.saldo_inicial ?? 0)} ações)</>}
              {" · "}compras {brl(d.resumo.compras_valor)} ({qtd(d.resumo.compras_qtd)} ações)
              {" · "}vendas {brl(d.resumo.vendas_valor)} ({qtd(d.resumo.vendas_qtd)} ações)
            </p>
            {d.por_cargo.length > 0 && (
              <p className="muted">
                Por grupo:{" "}
                {d.por_cargo.map((c, i) => (
                  <span key={c.cargo}>{i > 0 && " · "}{(c.cargo === "—" ? "Cargo não informado" : c.cargo).replace(" ou Vinculado", "")} <b className={cor(c.liquido_valor)}>{brl(c.liquido_valor)}</b></span>
                ))}
              </p>
            )}
          </div>

          <div className="card scroll">
            <h3>Por mês<Dica texto={DICAS.geral} /></h3>
            {d.mensal.length === 0 ? <p className="muted">Sem compras ou vendas de ações por insiders no período.</p> : (
              <table>
                <thead><tr>
                  <th>Mês</th><th>Compras (ações)</th><th>Vendas (ações)</th><th>Líquido (ações)</th><th>Líquido (R$)</th><th>% do VM<Dica texto={DICAS.vm} /></th><th>% da posição<Dica texto={DICAS.posicao} /></th><th>Preço médio de compra</th><th>Formulário</th>
                </tr></thead>
                <tbody>
                  {d.mensal.map((m) => {
                    const liqQ = m.compras_qtd - m.vendas_qtd, liqV = m.compras_valor - m.vendas_valor;
                    return (
                      <tr key={m.mes}>
                        <td>{mesBR(m.mes)}</td>
                        <td>{qtd(m.compras_qtd)}</td>
                        <td>{qtd(m.vendas_qtd)}</td>
                        <td className={cor(liqQ)}>{qtd(liqQ)}</td>
                        <td className={cor(liqV)}>{brl(liqV)}</td>
                        <td className={cor(liqV)}>{pctVM(m.liquido_pct)}</td>
                        <td className={cor(liqQ)} title={m.saldo_inicial == null ? "sem saldo inicial no formulário" : `posição no começo do mês: ${qtd(m.saldo_inicial)} ações`}>{pctVM(m.liquido_pct_posicao)}</td>
                        <td>{m.compras_qtd > 0 ? brl4(m.compras_valor / m.compras_qtd) : "—"}</td>
                        <td><Doc href={m.link} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          <div className="card scroll">
            <h3>Operações</h3>
            <label className="muted" style={{ display: "inline-flex", gap: 6, alignItems: "center", marginBottom: 8 }}>
              <input type="checkbox" checked={soNegocios} onChange={(e) => { setSoNegocios(e.target.checked); setMostraTudo(false); }} />
              só compras e vendas à vista
            </label>
            {operacoes.length === 0 ? <p className="muted">Nenhuma operação no período.</p> : (
              <table>
                <thead><tr>
                  <th className="esq">Data</th><th className="esq">Quem</th><th className="esq">Operação</th><th className="esq">Ativo</th><th>Quantidade</th><th>Preço</th><th>Volume</th><th className="esq">Corretora</th><th>Formulário</th>
                </tr></thead>
                <tbody>
                  {visiveis.map((o, i) => (
                    <tr key={i}>
                      <td className="esq">{dataBR(o.dt)}</td>
                      <td className="esq" title={o.empresa ?? ""}>{(o.cargo ?? "Cargo não informado").replace(" ou Vinculado", "")}{o.tipo_empresa && o.tipo_empresa !== "Companhia" ? ` (${o.tipo_empresa.toLowerCase()})` : ""}</td>
                      <td className={`esq ${o.operacao === "Crédito" ? "pos" : "neg"}`} title={o.descricao ?? ""}>{o.movimentacao}{o.bloco && <span className="tag tag-bloco" title="operação grande demais para pregão normal (≥ 25% do volume do dia e ≥ R$ 5 mi, ou ≥ 2% da empresa)"> bloco</span>}{o.suspeito && <span className="tag tag-susp" title="preço do formulário muito fora do preço do dia, ou maior que a empresa inteira"> suspeito</span>}</td>
                      <td className="esq">{[o.ativo, o.caracteristica].filter(Boolean).join(" ")}</td>
                      <td>{qtd(o.qtd)}</td>
                      <td>{o.preco == null ? "—" : brl4(o.preco)}</td>
                      <td>{o.volume == null ? "—" : brl(o.volume)}</td>
                      <td className="esq">{o.intermediario ?? "—"}</td>
                      <td><Doc href={o.link} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {operacoes.length > MOSTRA_INICIAL && !mostraTudo && (
              <p><button onClick={() => setMostraTudo(true)}>Mostrar todas ({operacoes.length})</button></p>
            )}
            {d.operacoes_truncadas && <p className="muted">Mostrando as 2.000 operações mais recentes do período.</p>}
          </div>
        </div>
      )}
    </>
  );
}
