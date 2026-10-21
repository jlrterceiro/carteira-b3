"use client";
import { useEffect, useState } from "react";
import { api, brl, cor, pct } from "../lib/api";
import { useSort } from "../lib/sort";

type Linha = {
  sg_ticker: string; quantidade: number; preco_medio: number; preco_atual: number;
  vl_posicao: number; ganho_capital: number; ganho_capital_pct: number; peso: number;
  var_dia_pct: number | null; ganho_dia: number | null; data_cotacao: string | null;
  dh_cotacao: string | null; ds_fonte: string | null;
};

const num = (v: unknown) => Number(v);
const numN = (v: unknown) => (v == null ? null : Number(v));

export default function Posicao({ idCorretora, dataRef }: { idCorretora: number | null; dataRef: string | null }) {
  const [linhas, setLinhas] = useState<Linha[] | null>(null);
  const [logos, setLogos] = useState<Record<string, number | null>>({});
  const [erro, setErro] = useState("");
  const { ordenadas, Th } = useSort(linhas ?? [], "vl_posicao");

  useEffect(() => {
    const busca = () => api<Linha[]>("/carteira/posicao", { params: { id_corretora: idCorretora == null ? undefined : String(idCorretora), data_ref: dataRef ?? undefined } })
      .then((r) => {
        const tot = r.reduce((a, l) => a + num(l.vl_posicao), 0);
        const ls = r
          .map((l) => ({ ...l, peso: tot ? (100 * num(l.vl_posicao)) / tot : 0, quantidade: num(l.quantidade), preco_medio: num(l.preco_medio),
            preco_atual: num(l.preco_atual), vl_posicao: num(l.vl_posicao),
            ganho_capital: num(l.ganho_capital), ganho_capital_pct: num(l.ganho_capital_pct),
            var_dia_pct: numN(l.var_dia_pct), ganho_dia: numN(l.ganho_dia),
            dh_cotacao: l.dh_cotacao ?? null, ds_fonte: l.ds_fonte ?? null }))
          .sort((a, b) => b.vl_posicao - a.vl_posicao);
        setLinhas(ls);
        if (ls.length)
          api<Record<string, number | null>>("/acoes/logos", {
            params: { tickers: ls.map((l) => l.sg_ticker).join(",") },
          }).then(setLogos).catch(() => {});
      })
      .catch((e) => setErro(e.message));
    busca();
    // durante o pregao a cotacao muda a cada ~5 min (coleta intradia): refaz a busca no mesmo ritmo
    const t = dataRef ? null : setInterval(busca, 5 * 60 * 1000);   // snapshot de uma data passada nao muda
    return () => { if (t) clearInterval(t); };
  }, [idCorretora, dataRef]);

  if (erro) return <p className="err">{erro}</p>;
  if (!linhas) return <p className="muted">Carregando…</p>;
  if (!linhas.length) return <p className="muted">Nenhuma posição ainda.</p>;

  const total = linhas.reduce((s, l) => s + l.vl_posicao, 0);
  const custo = linhas.reduce((s, l) => s + l.quantidade * l.preco_medio, 0);
  const ganho = linhas.reduce((s, l) => s + l.ganho_capital, 0);
  const ganhoDia = linhas.reduce((s, l) => s + (l.ganho_dia ?? 0), 0);
  const baseDia = total - ganhoDia;     // valor da carteira no fechamento anterior
  const intradia = linhas.find((l) => l.ds_fonte === "INTRADIA" && l.dh_cotacao);
  const dtCotacao = linhas.map((l) => l.data_cotacao).filter(Boolean).sort().pop();
  const hora = intradia?.dh_cotacao ? new Date(intradia.dh_cotacao).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : null;

  return (
    <div className="card scroll">
      <div className="big">{brl(total)}</div>
      <p className={cor(ganho)}>{brl(ganho)} ({pct(custo ? (100 * ganho) / custo : null)}) <span className="muted">no total</span></p>
      <p className={cor(ganhoDia)}>
        {brl(ganhoDia)} ({pct(baseDia ? (100 * ganhoDia) / baseDia : null)}) <span className="muted">{dataRef ? "no dia" : "hoje"}</span>
        {intradia
          ? <span className="muted"> · cotação das {hora} (atraso de ~15 min)</span>
          : dtCotacao && <span className="muted"> · fechamento de {dtCotacao.split("-").reverse().join("/")}</span>}
      </p>
      <table>
        <thead><tr>
          <Th c="sg_ticker">Ativo</Th><Th c="quantidade">Qtd</Th><Th c="preco_medio">PM</Th><Th c="preco_atual">Atual</Th>
          <Th c="var_dia_pct">{dataRef ? "Dia %" : "Hoje %"}</Th><Th c="ganho_dia">{dataRef ? "Dia R$" : "Hoje R$"}</Th>
          <Th c="vl_posicao">Posição</Th><Th c="peso">Peso</Th><Th c="ganho_capital">Ganho</Th><Th c="ganho_capital_pct">%</Th>
        </tr></thead>
        <tbody>
          {ordenadas.map((l) => (
            <tr key={l.sg_ticker}>
              <td><span className="tk">
                {logos[l.sg_ticker] && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={`https://statusinvest.com.br/img/company/avatar/${logos[l.sg_ticker]}.jpg`} alt="" />
                )}
                {l.sg_ticker}</span></td>
              <td>{l.quantidade.toLocaleString("pt-BR")}</td>
              <td>{brl(l.preco_medio)}</td>
              <td>{brl(l.preco_atual)}</td>
              <td className={cor(l.var_dia_pct)}>{l.var_dia_pct == null ? "—" : pct(l.var_dia_pct)}</td>
              <td className={cor(l.ganho_dia)}>{l.ganho_dia == null ? "—" : brl(l.ganho_dia)}</td>
              <td>{brl(l.vl_posicao)}</td>
              <td>{pct(l.peso).replace("+", "")}</td>
              <td className={cor(l.ganho_capital)}>{brl(l.ganho_capital)}</td>
              <td className={cor(l.ganho_capital_pct)}>{pct(l.ganho_capital_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
