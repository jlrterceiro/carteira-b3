"use client";
import { useEffect, useState } from "react";
import { api, brl, cor, pct } from "../lib/api";
import { useSort } from "../lib/sort";

type Linha = {
  sg_ticker: string; valor_investido: number; ganho_realizado_vendas: number;
  proventos: number; ganho_nao_realizado: number; ganho_total: number; ganho_pct_total: number;
};
const CAMPOS = ["valor_investido", "ganho_realizado_vendas", "proventos",
  "ganho_nao_realizado", "ganho_total", "ganho_pct_total"] as const;

export default function Ganhos({ idCorretora }: { idCorretora: number | null }) {
  const [linhas, setLinhas] = useState<Linha[] | null>(null);
  const [erro, setErro] = useState("");
  const { ordenadas, Th } = useSort(linhas ?? [], "ganho_pct_total");

  useEffect(() => {
    api<Linha[]>("/carteira/ganhos", { params: { id_corretora: idCorretora == null ? undefined : String(idCorretora) } })
      .then((r) => setLinhas(
        r.map((l) => {
          const o = { ...l } as Record<string, unknown>;
          for (const c of CAMPOS) o[c] = Number(o[c] ?? 0);
          return o as unknown as Linha;
        }).sort((a, b) => b.ganho_pct_total - a.ganho_pct_total)))
      .catch((e) => setErro(e.message));
  }, [idCorretora]);

  if (erro) return <p className="err">{erro}</p>;
  if (!linhas) return <p className="muted">Carregando…</p>;
  if (!linhas.length) return <p className="muted">Sem dados de ganho ainda.</p>;

  const soma = (k: keyof Linha) => linhas.reduce((s, l) => s + (l[k] as number), 0);
  const investido = soma("valor_investido"), total = soma("ganho_total");

  return (
    <div className="card scroll">
      <div className={`big ${cor(total)}`}>{brl(total)}</div>
      <p className="muted">sobre {brl(investido)} investidos ({pct(investido ? (100 * total) / investido : null)})</p>
      <table>
        <thead><tr>
          <Th c="sg_ticker">Ativo</Th><Th c="valor_investido">Investido</Th><Th c="ganho_realizado_vendas">Vendas</Th>
          <Th c="proventos">Proventos</Th><Th c="ganho_nao_realizado">Não realizado</Th><Th c="ganho_total">Total</Th>
          <Th c="ganho_pct_total">%</Th>
        </tr></thead>
        <tbody>
          {ordenadas.map((l) => (
            <tr key={l.sg_ticker}>
              <td>{l.sg_ticker}</td>
              <td>{brl(l.valor_investido)}</td>
              <td className={cor(l.ganho_realizado_vendas)}>{brl(l.ganho_realizado_vendas)}</td>
              <td className={cor(l.proventos)}>{brl(l.proventos)}</td>
              <td className={cor(l.ganho_nao_realizado)}>{brl(l.ganho_nao_realizado)}</td>
              <td className={cor(l.ganho_total)}>{brl(l.ganho_total)}</td>
              <td className={cor(l.ganho_pct_total)}>{pct(l.ganho_pct_total)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot><tr><td>Total</td><td>{brl(investido)}</td><td>{brl(soma("ganho_realizado_vendas"))}</td>
          <td>{brl(soma("proventos"))}</td><td>{brl(soma("ganho_nao_realizado"))}</td>
          <td className={cor(total)}>{brl(total)}</td><td>{pct(investido ? (100 * total) / investido : null)}</td></tr></tfoot>
      </table>
    </div>
  );
}
