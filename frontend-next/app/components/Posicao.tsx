"use client";
import { useEffect, useState } from "react";
import { api, brl, cor, pct } from "../lib/api";
import { useSort } from "../lib/sort";

type Linha = {
  sg_ticker: string; quantidade: number; preco_medio: number; preco_atual: number;
  vl_posicao: number; ganho_capital: number; ganho_capital_pct: number; peso: number;
};

const num = (v: unknown) => Number(v);

export default function Posicao({ idCorretora }: { idCorretora: number | null }) {
  const [linhas, setLinhas] = useState<Linha[] | null>(null);
  const [logos, setLogos] = useState<Record<string, number | null>>({});
  const [erro, setErro] = useState("");
  const { ordenadas, Th } = useSort(linhas ?? [], "vl_posicao");

  useEffect(() => {
    api<Linha[]>("/carteira/posicao", { params: { id_corretora: idCorretora == null ? undefined : String(idCorretora) } })
      .then((r) => {
        const tot = r.reduce((a, l) => a + num(l.vl_posicao), 0);
        const ls = r
          .map((l) => ({ ...l, peso: tot ? (100 * num(l.vl_posicao)) / tot : 0, quantidade: num(l.quantidade), preco_medio: num(l.preco_medio),
            preco_atual: num(l.preco_atual), vl_posicao: num(l.vl_posicao),
            ganho_capital: num(l.ganho_capital), ganho_capital_pct: num(l.ganho_capital_pct) }))
          .sort((a, b) => b.vl_posicao - a.vl_posicao);
        setLinhas(ls);
        if (ls.length)
          api<Record<string, number | null>>("/acoes/logos", {
            params: { tickers: ls.map((l) => l.sg_ticker).join(",") },
          }).then(setLogos).catch(() => {});
      })
      .catch((e) => setErro(e.message));
  }, [idCorretora]);

  if (erro) return <p className="err">{erro}</p>;
  if (!linhas) return <p className="muted">Carregando…</p>;
  if (!linhas.length) return <p className="muted">Nenhuma posição ainda.</p>;

  const total = linhas.reduce((s, l) => s + l.vl_posicao, 0);
  const custo = linhas.reduce((s, l) => s + l.quantidade * l.preco_medio, 0);
  const ganho = linhas.reduce((s, l) => s + l.ganho_capital, 0);

  return (
    <div className="card scroll">
      <div className="big">{brl(total)}</div>
      <p className={cor(ganho)}>{brl(ganho)} ({pct(custo ? (100 * ganho) / custo : null)})</p>
      <table>
        <thead><tr>
          <Th c="sg_ticker">Ativo</Th><Th c="quantidade">Qtd</Th><Th c="preco_medio">PM</Th><Th c="preco_atual">Atual</Th>
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
