"use client";

export type Corretora = { id_corretora: number; nm_corretora: string };

// Filtro de corretora compartilhado pelas telas Posicao, Ganhos e Rentabilidade (fica na barra do topo).
export default function FiltroCorretora({ corretoras, valor, onChange }: {
  corretoras: Corretora[];
  valor: number | null;
  onChange: (v: number | null) => void;
}) {
  if (!corretoras.length) return null;
  return (
    <label className="filtro-corretora">
      <span className="muted">Corretora</span>
      <select value={valor ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}>
        <option value="">Todas</option>
        {corretoras.map((c) => <option key={c.id_corretora} value={c.id_corretora}>{c.nm_corretora}</option>)}
      </select>
    </label>
  );
}
