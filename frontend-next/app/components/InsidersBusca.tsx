"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, brl, cor } from "../lib/api";
import { brlCompacto } from "../lib/formato";
import BuscaAcao from "./BuscaAcao";
import Dica, { DICAS } from "./Dica";

type Linha = {
  ticker: string; nome: string | null; compras_valor: number; vendas_valor: number; liquido_valor: number;
  valor: number; valor_mercado: number | null; percentual: number | null; saldo_inicial: number | null; pct_posicao: number | null;
};
type LinhaCarteira = {
  ticker: string; nome: string | null; compras_valor: number; vendas_valor: number; liquido_valor: number;
  valor_mercado: number | null; percentual: number | null; saldo_inicial: number | null; pct_posicao: number | null;
};
type Ranking = { inicio: string; fim: string; meses: number; n: number; ordenar: string; sem_valor_mercado: number; compradores: Linha[]; vendedores: Linha[]; carteira: LinhaCarteira[] };


const GRUPOS: { id: string; rotulo: string; dica: string }[] = [
  { id: "todos", rotulo: "Todos", dica: "administradores e controladores" },
  { id: "administracao", rotulo: "Administração", dica: "conselho de administração, diretoria, conselho fiscal e órgãos estatutários" },
  { id: "controlador", rotulo: "Controladores", dica: "controlador e vinculados" },
];

// % do valor de mercado: 2 casas, 3 quando e muito pequeno
const pctVM = (v: number | null) =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${v.toLocaleString("pt-BR", { minimumFractionDigits: Math.abs(v) < 0.1 ? 3 : 2, maximumFractionDigits: Math.abs(v) < 0.1 ? 3 : 2 })}%`;

const JANELAS: { rotulo: string; meses: number }[] = [
  { rotulo: "1 mês", meses: 1 }, { rotulo: "3 meses", meses: 3 }, { rotulo: "6 meses", meses: 6 },
  { rotulo: "1 ano", meses: 12 }, { rotulo: "2 anos", meses: 24 }, { rotulo: "5 anos", meses: 60 }, { rotulo: "Tudo", meses: 600 },
];

const OPCOES_N = [10, 20, 30, 40, 50];
const MINIMOS_VM = [
  { valor: 0, rotulo: "Sem mínimo" }, { valor: 50e6, rotulo: "R$ 50 mi" }, { valor: 100e6, rotulo: "R$ 100 mi" }, { valor: 200e6, rotulo: "R$ 200 mi" },
  { valor: 500e6, rotulo: "R$ 500 mi" }, { valor: 1e9, rotulo: "R$ 1 bi" }, { valor: 5e9, rotulo: "R$ 5 bi" },
];

type Coluna = "compras" | "vendas" | "liquido";

// `destaque` = a coluna em R$ que define a ordem da lista (negrito); as tres aparecem sempre
function Tabela({ titulo, linhas, classe, destaque, destaquePct, ordenaPor, n, onN }: { titulo: string; linhas: Linha[]; classe: "pos" | "neg"; destaque: Coluna; destaquePct: "vm" | "posicao" | null; ordenaPor: Coluna | "vm" | "posicao"; n: number; onN: (n: number) => void }) {
  const forte = (c: Coluna | "vm" | "posicao" | "vmEpoca") => (c === destaque || c === destaquePct || (c === "vmEpoca" && destaquePct === "vm") ? " forte" : "");
  // seta so na coluna que de fato ordena a lista; o negrito marca tambem a coluna de que o percentual depende
  const seta = (c: Coluna | "vm" | "posicao") => (c === ordenaPor ? <span className="seta-ordem" title="lista ordenada por esta coluna" aria-label="ordenado por esta coluna"> ▼</span> : null);
  return (
    <div className="card scroll">
      <h3 className={classe}>{titulo}</h3>
      {linhas.length === 0 ? <p className="muted">Nenhuma empresa no período.</p> : (
        <table>
          <thead><tr><th className="esq">#</th><th className="esq">Ação</th><th className="esq">Empresa</th><th className={forte("compras").trim()}>Compras (R$){seta("compras")}</th><th className={forte("vendas").trim()}>Vendas (R$){seta("vendas")}</th><th className={forte("liquido").trim()}>Líquido (R$){seta("liquido")}</th><th className={forte("vm").trim()}>% do VM{seta("vm")}<Dica texto={DICAS.vm} /></th><th className={forte("posicao").trim()}>% da posição{seta("posicao")}<Dica texto={DICAS.posicao} /></th><th className={forte("vmEpoca").trim()}>VM na época<Dica texto={DICAS.vmEpoca} /></th></tr></thead>
          <tbody>
            {linhas.map((l, i) => (
              <tr key={l.ticker}>
                <td className="esq muted">{i + 1}</td>
                <td className="esq"><Link className="rank-link" href={`/insiders/${l.ticker}`}><b>{l.ticker}</b></Link></td>
                <td className="esq">{l.nome ?? "—"}</td>
                <td className={(l.compras_valor ? "pos" : "muted") + forte("compras")} title={brl(l.compras_valor)}>{l.compras_valor ? brlCompacto(l.compras_valor) : "—"}</td>
                <td className={(l.vendas_valor ? "neg" : "muted") + forte("vendas")} title={brl(l.vendas_valor)}>{l.vendas_valor ? brlCompacto(-l.vendas_valor) : "—"}</td>
                <td className={cor(l.liquido_valor) + forte("liquido")} title={brl(l.liquido_valor)}>{brlCompacto(l.liquido_valor)}</td>
                <td className={classe + forte("vm")}>{pctVM(l.percentual)}</td>
                <td className={classe + forte("posicao")} title={l.saldo_inicial == null ? "sem saldo inicial no formulário" : `posição no começo do período: ${l.saldo_inicial.toLocaleString("pt-BR")} ações`}>{pctVM(l.pct_posicao)}</td>
                <td className={"muted" + forte("vmEpoca")} title={l.valor_mercado == null ? "sem quantidade de ações no cadastro" : brl(l.valor_mercado)}>{l.valor_mercado == null ? "—" : brlCompacto(l.valor_mercado)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="rodape-n">
        <label>
          <span className="muted">Mostrar</span>
          <select value={n} onChange={(e) => onN(Number(e.target.value))}>
            {OPCOES_N.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
          <span className="muted">empresas</span>
        </label>
      </div>
    </div>
  );
}

// Resumo das empresas da carteira: o que os insiders compraram e venderam delas no periodo
function TabelaCarteira({ linhas }: { linhas: LinhaCarteira[] }) {
  return (
    <div className="card scroll">
      <h3>Insiders nas empresas da sua carteira</h3>
      {linhas.length === 0 ? <p className="muted">Você não tem ações em carteira.</p> : (
        <table>
          <thead><tr>
            <th className="esq">Ação</th><th className="esq">Empresa</th><th>Compras (R$)</th><th>Vendas (R$)</th><th>Líquido (R$)</th>
            <th>% do VM<Dica texto={DICAS.vm} /></th>
            <th>% da posição<Dica texto={DICAS.posicao} /></th>
          </tr></thead>
          <tbody>
            {linhas.map((l) => {
              const sem = l.compras_valor === 0 && l.vendas_valor === 0;
              return (
                <tr key={l.ticker}>
                  <td className="esq"><Link className="rank-link" href={`/insiders/${l.ticker}`}><b>{l.ticker}</b></Link></td>
                  <td className="esq">{l.nome ?? "—"}</td>
                  <td className={sem ? "muted" : "pos"} title={brl(l.compras_valor)}>{sem ? "—" : brlCompacto(l.compras_valor)}</td>
                  <td className={sem ? "muted" : "neg"} title={brl(l.vendas_valor)}>{sem ? "—" : brlCompacto(-l.vendas_valor)}</td>
                  <td className={sem ? "muted" : cor(l.liquido_valor)} title={brl(l.liquido_valor)}>{sem ? "—" : brlCompacto(l.liquido_valor)}</td>
                  <td className={sem ? "muted" : cor(l.liquido_valor)}>{sem ? "—" : pctVM(l.percentual)}</td>
                  <td className={sem ? "muted" : cor(l.liquido_valor)} title={l.saldo_inicial == null ? "sem saldo inicial no formulário" : `posição no começo do período: ${l.saldo_inicial.toLocaleString("pt-BR")} ações`}>{sem ? "—" : pctVM(l.pct_posicao)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

// Entrada da area de Insiders: busca com autocomplete, ranking das empresas com maior compra e venda liquida (periodo e quantidade
// ajustaveis) e atalhos pras acoes em carteira.
export default function InsidersBusca({ idCorretora, dataRef }: { idCorretora: number | null; dataRef: string | null }) {
  const [meus, setMeus] = useState<string[] | null>(null);
  const [janela, setJanela] = useState("6 meses");
  const [grupo, setGrupo] = useState("todos");
  const [ordenar, setOrdenar] = useState("valor");
  const [medida, setMedida] = useState("bruto");
  const [semBlocos, setSemBlocos] = useState(false);       // padrao: operacoes em bloco ENTRAM; o checkbox as exclui
  const [comSuspeitos, setComSuspeitos] = useState(false);
  const [vmMin, setVmMin] = useState(200_000_000);          // valor de mercado minimo (R$) das empresas nas listas de compras/vendas
  const [nC, setNC] = useState(10);                       // quantas empresas em cada lista (compras e vendas escolhem separado)
  const [nV, setNV] = useState(10);
  const n = Math.max(nC, nV);                          // a API devolve as duas listas com o maior; cada tabela corta o seu pedaco
  const [res, setRes] = useState<{ key: string; dados?: Ranking; erro?: string } | null>(null);
  const meses = JANELAS.find((j) => j.rotulo === janela)!.meses;
  const key = `${meses}|${n}|${grupo}|${ordenar}|${medida}|${semBlocos}|${comSuspeitos}|${vmMin}|${(meus ?? []).join(",")}|${dataRef ?? ""}`;

  useEffect(() => {
    api<{ sg_ticker: string }[]>("/carteira/posicao", { params: { id_corretora: idCorretora == null ? undefined : String(idCorretora) } })
      .then((r) => setMeus(r.map((l) => l.sg_ticker)))
      .catch(() => setMeus([]));
  }, [idCorretora]);

  useEffect(() => {
    if (meus === null) return;     // espera saber as acoes da carteira (o resumo vem junto do ranking)
    const t = setTimeout(() => {
      api<Ranking>("/insiders/ranking/liquido", { params: { meses: String(meses), n: String(n), grupo, ordenar, medida, com_blocos: String(!semBlocos), com_suspeitos: String(comSuspeitos), vm_min: String(vmMin), tickers: meus.join(","), data_ref: dataRef ?? undefined } })
        .then((dados) => setRes({ key, dados }))
        .catch((e) => setRes((ant) => ({ key, dados: ant?.dados, erro: e.message })));
    }, 250);
    return () => clearTimeout(t);
  }, [meses, n, grupo, ordenar, medida, semBlocos, comSuspeitos, vmMin, meus, dataRef, key]);

  // mantem o resultado anterior na tela enquanto o novo carrega (esmaecido): esconder as tabelas encolhe a pagina e joga a rolagem pro topo
  const atual = res;
  const carregando = res?.key !== key;

  return (
    <>
      <div className="card">
        <h3>Insiders<Dica texto={DICAS.geral} /></h3>
        <p className="muted">O que administradores, conselheiros, controladores e pessoas ligadas compraram e venderam das ações da própria empresa, com o link do formulário na CVM.</p>
        <label className="filtro-corretora">
          <span className="muted">Ação</span>
          <BuscaAcao placeholder="Ticker ou nome (ex.: CAMB3, Cambuci)" />
        </label>
      </div>

      <div className="rent-controles">
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
        <label><input type="checkbox" checked={semBlocos} onChange={(e) => setSemBlocos(e.target.checked)} /> Excluir vendas em bloco e ofertas<Dica texto={DICAS.bloco} /></label>
        <label><input type="checkbox" checked={comSuspeitos} onChange={(e) => setComSuspeitos(e.target.checked)} /> Incluir dados suspeitos<Dica texto={DICAS.suspeito} /></label>
        <label>
          <span>Valor de mercado mínimo</span>
          <select value={vmMin} onChange={(e) => setVmMin(Number(e.target.value))}>
            {MINIMOS_VM.map((m) => <option key={m.valor} value={m.valor}>{m.rotulo}</option>)}
          </select>
          <Dica texto={DICAS.vmMin} />
        </label>
      </p>

      {atual?.erro && <p className="err">{atual.erro}</p>}
      {!atual && <p className="muted">Carregando…</p>}
      <div className={carregando && atual?.dados ? "recarregando" : undefined}>
      {atual?.dados && <TabelaCarteira linhas={atual.dados.carteira} />}
      </div>

      <div className="rent-controles">
        <div className="chips">
          <span className="muted" style={{ alignSelf: "center", marginRight: 4 }}>Ordenar por</span>
          <button className={ordenar === "valor" ? "on" : ""} onClick={() => setOrdenar("valor")}>Valor (R$)</button>
          <button className={ordenar === "percentual" ? "on" : ""} onClick={() => setOrdenar("percentual")}>% do valor de mercado</button>
          <button className={ordenar === "posicao" ? "on" : ""} onClick={() => setOrdenar("posicao")}>% da posição do grupo</button>
          <span style={{ alignSelf: "center" }}><Dica texto={DICAS.ordenar} /></span>
        </div>
        <div className="chips">
          <span className="muted" style={{ alignSelf: "center", marginRight: 4 }}>Medida</span>
          <button title="maiores compras e maiores vendas à vista, cada lista pelo seu total (uma não anula a outra)" className={medida === "bruto" ? "on" : ""} onClick={() => setMedida("bruto")}>Compras e vendas</button>
          <button title="compras menos vendas" className={medida === "liquido" ? "on" : ""} onClick={() => setMedida("liquido")}>Líquido</button>
          <span style={{ alignSelf: "center" }}><Dica texto={DICAS.medida} /></span>
        </div>
      </div>

      {atual?.dados && (
        <div className={carregando ? "recarregando" : undefined}>
          <Tabela titulo={`${medida === "bruto" ? "Maiores compras" : "Maiores compras líquidas"} (${Math.min(nC, atual.dados.compradores.length)})`} linhas={atual.dados.compradores.slice(0, nC)} classe="pos" destaque={medida === "bruto" ? "compras" : "liquido"} destaquePct={ordenar === "percentual" ? "vm" : ordenar === "posicao" ? "posicao" : null} ordenaPor={ordenar === "percentual" ? "vm" : ordenar === "posicao" ? "posicao" : medida === "bruto" ? "compras" : "liquido"} n={nC} onN={setNC} />
          <Tabela titulo={`${medida === "bruto" ? "Maiores vendas" : "Maiores vendas líquidas"} (${Math.min(nV, atual.dados.vendedores.length)})`} linhas={atual.dados.vendedores.slice(0, nV)} classe="neg" destaque={medida === "bruto" ? "vendas" : "liquido"} destaquePct={ordenar === "percentual" ? "vm" : ordenar === "posicao" ? "posicao" : null} ordenaPor={ordenar === "percentual" ? "vm" : ordenar === "posicao" ? "posicao" : medida === "bruto" ? "vendas" : "liquido"} n={nV} onN={setNV} />
        </div>
      )}
    </>
  );
}
