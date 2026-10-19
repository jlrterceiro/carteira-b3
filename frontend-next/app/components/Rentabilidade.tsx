"use client";
import { Fragment, useEffect, useState } from "react";
import { api, cor, pct, PERIODOS, periodoParams } from "../lib/api";
import LineChart from "./LineChart";

type Resp = {
  diaria: { dt_dia: string; rentabilidade_pct: number }[];
  mensal: { periodo: string; rentabilidade_pct: number }[];
  anual: { periodo: string; rentabilidade_pct: number }[];
  total_pct: number | null;
};

type Serie = { periodo: string; rentabilidade_pct: number }[];
const MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
const pctBR = (v: number) => `${v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;

// Uma linha por ano: 12 meses, rentabilidade do ano e acumulada (juros compostos desde o primeiro ano ate o fim
// daquele ano). Mais recente em cima. Mes sem dado (antes do inicio / ainda nao aconteceu) fica "—".
function Matriz({ mensal, anual }: { mensal: Serie; anual: Serie }) {
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

export default function Rentabilidade({ idCorretora }: { idCorretora: number | null }) {
  const corr = idCorretora == null ? undefined : String(idCorretora);
  const [periodo, setPeriodo] = useState("1 ano");
  const [res, setRes] = useState<{ key: string; dados?: Resp; erro?: string } | null>(null);

  useEffect(() => {
    api<Resp>("/carteira/rentabilidade", { params: { ...periodoParams(PERIODOS[periodo]), id_corretora: corr } })
      .then((dados) => setRes({ key: periodo, dados }))
      .catch((e) => setRes({ key: periodo, erro: e.message }));
  }, [periodo, corr]);

  // a matriz mensal sempre usa o historico inteiro: so faz sentido com meses completos, entao nao segue o filtro
  const [completo, setCompleto] = useState<Resp | null>(null);
  useEffect(() => {
    api<Resp>("/carteira/rentabilidade", { params: { id_corretora: corr } }).then(setCompleto).catch(() => setCompleto(null));
  }, [corr]);

  const atual = res?.key === periodo ? res : null;
  const dados = atual?.dados ?? null;
  const erro = atual?.erro ?? "";

  const pontos = (dados?.diaria ?? []).reduce<{ x: string; y: number; f: number }[]>((out, d) => {
    const f = (out.length ? out[out.length - 1].f : 1) * (1 + d.rentabilidade_pct / 100);
    out.push({ x: d.dt_dia, y: (f - 1) * 100, f });
    return out;
  }, []);

  return (
    <>
      <div className="chips right">
        {Object.keys(PERIODOS).map((p) => (
          <button key={p} className={p === periodo ? "on" : ""} onClick={() => setPeriodo(p)}>{p}</button>
        ))}
      </div>
      {erro && <p className="err">{erro}</p>}
      {!dados ? <p className="muted">Carregando…</p> : (
        <>
          <div className="card">
            <div className={`big ${cor(dados.total_pct)}`}>{pct(dados.total_pct)}</div>
            <p className="muted">rentabilidade do período (juros compostos)</p>
            <LineChart pontos={pontos} formato={(v) => pct(v)} />
          </div>
          {completo && <Matriz mensal={completo.mensal} anual={completo.anual} />}
        </>
      )}
    </>
  );
}
