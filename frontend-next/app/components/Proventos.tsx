"use client";
import { useEffect, useState } from "react";
import { api, brl } from "../lib/api";
import BarChart, { Barra } from "./BarChart";

type Agrupar = "mes" | "trimestre" | "semestre" | "ano";
const AGRUPAR: { id: Agrupar; rotulo: string; plural: string }[] = [
  { id: "mes", rotulo: "Mês", plural: "mês" },
  { id: "trimestre", rotulo: "Trimestre", plural: "trimestre" },
  { id: "semestre", rotulo: "Semestre", plural: "semestre" },
  { id: "ano", rotulo: "Ano", plural: "ano" },
];
// janela pra tras, em meses (null = tudo)
const JANELAS: { rotulo: string; meses: number | null }[] = [
  { rotulo: "6 meses", meses: 6 },
  { rotulo: "1 ano", meses: 12 },
  { rotulo: "2 anos", meses: 24 },
  { rotulo: "5 anos", meses: 60 },
  { rotulo: "Tudo", meses: null },
];
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const MESES_LONGO = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

type Resp = {
  agrupar: Agrupar; inicio: string | null; fim: string;
  serie: { periodo: string; total: number }[];
  total: number; media: number; nao_pago: number;
};

// rotulos em pt-BR: "out/26", "3T26", "2S26", "2026" e, no tooltip, "outubro de 2026", "3º trimestre de 2026"...
function rotulos(periodo: string, agrupar: Agrupar) {
  const ano = Number(periodo.slice(0, 4)), mes = Number(periodo.slice(5, 7));
  const a2 = String(ano).slice(2);
  if (agrupar === "mes") return { rotulo: `${MESES[mes - 1]}/${a2}`, titulo: `${MESES_LONGO[mes - 1]} de ${ano}` };
  if (agrupar === "trimestre") { const t = Math.ceil(mes / 3); return { rotulo: `${t}T${a2}`, titulo: `${t}º trimestre de ${ano}` }; }
  if (agrupar === "semestre") { const s = mes <= 6 ? 1 : 2; return { rotulo: `${s}S${a2}`, titulo: `${s}º semestre de ${ano}` }; }
  return { rotulo: String(ano), titulo: String(ano) };
}

const brlInteiro = (v: number) => `R$ ${v.toLocaleString("pt-BR", { maximumFractionDigits: 0 })}`;

export default function Proventos({ idCorretora, dataRef }: { idCorretora: number | null; dataRef: string | null }) {
  const [agrupar, setAgrupar] = useState<Agrupar>("mes");
  const [janela, setJanela] = useState("1 ano");
  const [res, setRes] = useState<{ key: string; dados?: Resp; erro?: string } | null>(null);
  const meses = JANELAS.find((j) => j.rotulo === janela)!.meses;
  const key = `${agrupar}|${janela}`;

  useEffect(() => {
    api<Resp>("/carteira/proventos", {
      params: {
        agrupar,
        meses: meses == null ? undefined : String(meses),
        id_corretora: idCorretora == null ? undefined : String(idCorretora),
        data_ref: dataRef ?? undefined,
      },
    })
      .then((dados) => setRes({ key, dados }))
      .catch((e) => setRes({ key, erro: e.message }));
  }, [agrupar, meses, idCorretora, dataRef, key]);

  const atual = res?.key === key ? res : null;
  const dados = atual?.dados ?? null;
  const unidade = AGRUPAR.find((a) => a.id === agrupar)!.plural;

  const barras: Barra[] = (dados?.serie ?? []).map((b) => ({
    ...rotulos(b.periodo, agrupar),
    valor: b.total,
  }));

  return (
    <>
      <div className="rent-controles">
        <div className="chips">
          {AGRUPAR.map((a) => (
            <button key={a.id} className={a.id === agrupar ? "on" : ""} onClick={() => setAgrupar(a.id)}>{a.rotulo}</button>
          ))}
        </div>
        <div className="chips">
          {JANELAS.map((j) => (
            <button key={j.rotulo} className={j.rotulo === janela ? "on" : ""} onClick={() => setJanela(j.rotulo)}>{j.rotulo}</button>
          ))}
        </div>
      </div>
      {atual?.erro && <p className="err">{atual.erro}</p>}
      {!atual && <p className="muted">Carregando…</p>}
      {dados && (
        <div className="card">
          <div className="big">{brl(dados.total)}</div>
          <p className="muted">
            proventos líquidos no período · média de {brl(dados.media)} por {unidade}
            {dados.nao_pago > 0 && <> · {brl(dados.nao_pago)} ainda não pagos</>}
          </p>
          <BarChart barras={barras} formato={brl} formatoEixo={brlInteiro} />
          <p className="muted">Contado na data ex (a mesma da tela de Ganhos), só o valor líquido de IR.</p>
        </div>
      )}
    </>
  );
}
