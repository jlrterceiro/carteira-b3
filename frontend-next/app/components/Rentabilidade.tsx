"use client";
import { Fragment, useEffect, useState } from "react";
import { api, cor, pct, pctInteiro, PERIODOS, periodoParams } from "../lib/api";
import LineChart, { Serie } from "./LineChart";

type Resp = {
  metodo?: string;
  diaria: { dt_dia: string; rentabilidade_pct: number }[];
  mensal: { periodo: string; rentabilidade_pct: number }[];
  anual: { periodo: string; rentabilidade_pct: number }[];
  total_pct: number | null;
};

type SerieMes = { periodo: string; rentabilidade_pct: number }[];
const MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
const pctBR = (v: number) => `${v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;

// Uma linha por ano: 12 meses, rentabilidade do ano e acumulada (juros compostos desde o primeiro ano ate o fim
// daquele ano). Mais recente em cima. Mes sem dado (antes do inicio / ainda nao aconteceu) fica "—".
function Matriz({ mensal, anual }: { mensal: SerieMes; anual: SerieMes }) {
  const porMes = new Map(mensal.map((m) => [m.periodo, m.rentabilidade_pct]));
  const crescente = [...anual].sort((a, b) => a.periodo.localeCompare(b.periodo));
  const linhas = crescente
    .reduce<{ ano: string; meses: (number | null)[]; anoPct: number; fator: number }[]>((out, a) => {
      const fator = (out.length ? out[out.length - 1].fator : 1) * (1 + a.rentabilidade_pct / 100);
      out.push({
        ano: a.periodo,
        meses: MESES.map((_, i) => porMes.get(`${a.periodo}-${String(i + 1).padStart(2, "0")}`) ?? null),
        anoPct: a.rentabilidade_pct,
        fator,
      });
      return out;
    }, [])
    .map((l) => ({ ...l, acum: (l.fator - 1) * 100 }))
    .reverse();
  const celula = (v: number | null) =>
    v == null ? <td className="muted">—</td> : <td className={cor(v)}>{pctBR(v)}</td>;
  return (
    <div className="card scroll">
      <h3>Rentabilidade por mês</h3>
      <table className="matriz">
        <thead>
          <tr>
            <th>Ano</th>
            {MESES.map((m) => <th key={m}>{m}</th>)}
            <th className="sep">Ano</th>
            <th>Acumulada</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map((l) => (
            <tr key={l.ano}>
              <td>{l.ano}</td>
              {l.meses.map((v, i) => <Fragment key={i}>{celula(v)}</Fragment>)}
              <td className={`sep strong ${cor(l.anoPct)}`}>{pctBR(l.anoPct)}</td>
              <td className={`strong ${cor(l.acum)}`}>{pctBR(l.acum)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const BENCH = [
  { chave: "cdi", campo: "cdi_pct", nome: "CDI", cor: "#d97706" },
  { chave: "ibov", campo: "ibov_pct", nome: "Ibovespa", cor: "#7c3aed" },
] as const;

type Metodo = "receber" | "status_invest";
const METODOS: { id: Metodo; rotulo: string; descricao: string }[] = [
  { id: "receber", rotulo: "TWR (proventos a receber)",
    descricao: "TWR em que o dividendo conta na data ex e fica na carteira, sem render, só até o dia do pagamento; nesse dia sai da conta (você saca ou reinveste, e o reinvestimento reaparece como compra). Datas de pagamento sem aviso na CVM ou na B3 são estimadas pela mediana da própria empresa." },
  { id: "status_invest", rotulo: "Status Invest",
    descricao: "Carteira com o caixa dos proventos: o dividendo conta na data de pagamento e fica na carteira para sempre, sem render. Reproduz o cálculo do Status Invest com folga de ~1 ponto. Datas de pagamento sem aviso na CVM ou na B3 são estimadas pela mediana da própria empresa." },
];

// TWR (receber | status_invest): grafico e total seguem o periodo; a matriz usa o historico inteiro.
function TwrView({ metodo, periodo, corr }: { metodo: Metodo; periodo: string; corr: string | undefined }) {
  const [res, setRes] = useState<{ key: string; dados?: Resp; erro?: string } | null>(null);
  useEffect(() => {
    api<Resp>("/carteira/rentabilidade", { params: { ...periodoParams(PERIODOS[periodo]), id_corretora: corr, metodo } })
      .then((dados) => setRes({ key: periodo, dados }))
      .catch((e) => setRes({ key: periodo, erro: e.message }));
  }, [periodo, corr, metodo]);

  // a matriz mensal sempre usa o historico inteiro: so faz sentido com meses completos, entao nao segue o filtro
  const [completo, setCompleto] = useState<Resp | null>(null);
  useEffect(() => {
    api<Resp>("/carteira/rentabilidade", { params: { id_corretora: corr, metodo } }).then(setCompleto).catch(() => setCompleto(null));
  }, [corr, metodo]);

  const atual = res?.key === periodo ? res : null;
  const dados = atual?.dados ?? null;
  const erro = atual?.erro ?? "";

  // CDI e Ibovespa acumulados a partir do fechamento anterior ao 1o ponto da carteira (mesma base do TWR)
  type Bench = { dt_dia: string; ibov_pct: number | null; cdi_pct: number | null };
  const [bench, setBench] = useState<{ de: string; ate: string; linhas: Bench[] } | null>(null);
  const de = dados?.diaria[0]?.dt_dia, ate = dados?.diaria[dados.diaria.length - 1]?.dt_dia;
  useEffect(() => {
    if (!de || !ate) return;
    api<Bench[]>("/carteira/benchmarks", { params: { de, ate } })
      .then((linhas) => setBench({ de, ate, linhas }))
      .catch(() => setBench(null));
  }, [de, ate]);
  const [mostra, setMostra] = useState<{ cdi: boolean; ibov: boolean }>({ cdi: true, ibov: true });

  const pontos = (dados?.diaria ?? []).reduce<{ x: string; y: number; f: number }[]>((out, d) => {
    const f = (out.length ? out[out.length - 1].f : 1) * (1 + d.rentabilidade_pct / 100);
    out.push({ x: d.dt_dia, y: (f - 1) * 100, f });
    return out;
  }, []);

  if (erro) return <p className="err">{erro}</p>;
  if (!dados) return <p className="muted">Carregando…</p>;
  const benchAtual = bench && bench.de === de && bench.ate === ate ? bench : null;
  const series: Serie[] = [{ nome: "Carteira", cor: "var(--accent)", pontos: pontos.map((p) => ({ x: p.x, y: p.y })) }];
  for (const b of BENCH) {
    if (!mostra[b.chave] || !benchAtual) continue;
    const pts = benchAtual.linhas.filter((l) => l[b.campo] != null).map((l) => ({ x: l.dt_dia, y: l[b.campo] as number }));
    if (pts.length) series.push({ nome: b.nome, cor: b.cor, pontos: pts });
  }

  // equivalentes compostos do retorno do periodo: (1+T)^(dias de referencia / dias do periodo) - 1.
  // O 1o ponto da serie e o retorno do proprio dia, entao o periodo cobre (ultimo - primeiro + 1) dias corridos.
  const diaria = dados.diaria;
  const dias = diaria.length
    ? Math.round((Date.parse(diaria[diaria.length - 1].dt_dia) - Date.parse(diaria[0].dt_dia)) / 864e5) + 1
    : 0;
  const equiv = (ref: number, minDias: number) =>
    dados.total_pct == null || dias < minDias ? null : (Math.pow(1 + dados.total_pct / 100, ref / dias) - 1) * 100;
  const aoMes = equiv(365.25 / 12, 30);
  const aoAno = equiv(365, 60);   // anualizar menos de ~2 meses exagera (13 dias de -2% virariam -49% a.a.)
  return (
    <>
      <div className="card">
        <div className={`big ${cor(dados.total_pct)}`}>{pct(dados.total_pct)}</div>
        <p className="muted">rentabilidade do período (juros compostos)</p>
        <p className="rent-equiv">
          <span>Mensalizada: <b className={cor(aoMes)}>{aoMes == null ? "—" : `${pct(aoMes)} a.m.`}</b></span>
          <span>Anualizada: <b className={cor(aoAno)}>{aoAno == null ? "—" : `${pct(aoAno)} a.a.`}</b></span>
          <span className="muted">equivalente composto em {dias} dias{aoAno == null ? " (curto demais para anualizar)" : ""}</span>
        </p>
        <div className="legenda">
          <span><i style={{ background: "var(--accent)" }} />Carteira <b className={cor(dados.total_pct)}>{pct(dados.total_pct)}</b></span>
          {BENCH.map((b) => {
            const linhas = benchAtual?.linhas ?? [];
            const ult = [...linhas].reverse().find((l) => l[b.campo] != null)?.[b.campo] ?? null;
            return (
              <label key={b.chave}>
                <input type="checkbox" checked={mostra[b.chave]} onChange={(e) => setMostra({ ...mostra, [b.chave]: e.target.checked })} />
                <i style={{ background: b.cor }} />{b.nome} <b>{ult == null ? "—" : pct(ult)}</b>
              </label>
            );
          })}
        </div>
        <LineChart series={series} formato={(v) => pct(v)} formatoEixo={pctInteiro} />
      </div>
      {completo && <Matriz mensal={completo.mensal} anual={completo.anual} />}
    </>
  );
}

export default function Rentabilidade({ idCorretora }: { idCorretora: number | null }) {
  const corr = idCorretora == null ? undefined : String(idCorretora);
  const [periodo, setPeriodo] = useState("Total");
  const [metodo, setMetodo] = useState<Metodo>(() => {
    try {
      const salvo = localStorage.getItem("rent_metodo") as Metodo | null;
      if (salvo && METODOS.some((m) => m.id === salvo)) return salvo;
    } catch { /* sem localStorage: usa o padrao */ }
    return "receber";
  });
  const escolhe = (m: Metodo) => {
    setMetodo(m);
    try { localStorage.setItem("rent_metodo", m); } catch { /* ok */ }
  };
  const atual = METODOS.find((m) => m.id === metodo)!;

  return (
    <>
      <div className="rent-controles">
        <label className="filtro-corretora">
          <span className="muted">Método</span>
          <select value={metodo} onChange={(e) => escolhe(e.target.value as Metodo)}>
            {METODOS.map((m) => <option key={m.id} value={m.id}>{m.rotulo}</option>)}
          </select>
        </label>
        <div className="chips">
          {Object.keys(PERIODOS).map((p) => (
            <button key={p} className={p === periodo ? "on" : ""} onClick={() => setPeriodo(p)}>{p}</button>
          ))}
        </div>
      </div>
      <p className="muted rent-descricao">{atual.descricao}</p>
      <TwrView key={metodo} metodo={metodo} periodo={periodo} corr={corr} />
    </>
  );
}
