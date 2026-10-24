"use client";
import { useState } from "react";
import { dataBR } from "../lib/api";

export type Ponto = { x: string; y: number };
// A 1a serie define o eixo x; as demais sao alinhadas por data (vao sem dado herda o ultimo valor, antes do 1o dado fica sem linha).
export type Serie = { nome: string; cor: string; pontos: Ponto[] };

export default function LineChart({
  series,
  formato,
  formatoEixo,
}: {
  series: Serie[];
  formato: (v: number) => string;
  formatoEixo?: (v: number) => string;      // rotulos da esquerda (padrao: o mesmo de `formato`)
}) {
  const [hover, setHover] = useState<number | null>(null);
  const base = series[0]?.pontos ?? [];
  if (base.length < 2) return <p className="muted">Sem dados suficientes.</p>;

  const xs = base.map((p) => p.x);
  // y de cada serie em cada x (null = ainda sem dado)
  const valores: (number | null)[][] = series.map((s) => {
    const porX = new Map(s.pontos.map((p) => [p.x, p.y]));
    const ordenados = [...s.pontos].sort((a, b) => a.x.localeCompare(b.x));
    let j = 0, ult: number | null = null;
    return xs.map((x) => {
      if (porX.has(x)) { ult = porX.get(x)!; while (j < ordenados.length && ordenados[j].x <= x) j++; return ult; }
      while (j < ordenados.length && ordenados[j].x <= x) { ult = ordenados[j].y; j++; }
      return ult;
    });
  });

  const W = 900, H = 320, P = { l: 64, r: 16, t: 16, b: 28 };
  const todos = valores.flat().filter((v): v is number => v != null);
  // uma linha a cada 20 (pontos em %), sempre com o 0 no eixo; abaixo de 0 tambem (-20, -40...)
  let passo = 20;
  while ((Math.max(0, ...todos) - Math.min(0, ...todos)) / passo > 14) passo *= 2;
  const min = Math.floor(Math.min(0, ...todos) / passo) * passo;
  let max = Math.ceil(Math.max(0, ...todos) / passo) * passo;
  if (max === min) max = min + passo;
  const X = (i: number) => P.l + (i / (xs.length - 1)) * (W - P.l - P.r);
  const Y = (v: number) => P.t + (1 - (v - min) / (max - min)) * (H - P.t - P.b);
  const caminho = (vs: (number | null)[]) =>
    vs.map((v, i) => (v == null ? "" : `${vs.slice(0, i).some((u) => u != null) ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`)).join("");
  const ticks = Array.from({ length: Math.round((max - min) / passo) + 1 }, (_, i) => min + i * passo);
  const direita = hover != null && X(hover) > W / 2;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="chart"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const px = ((e.clientX - r.left) / r.width) * W;
        const i = Math.round(((px - P.l) / (W - P.l - P.r)) * (xs.length - 1));
        setHover(Math.max(0, Math.min(xs.length - 1, i)));
      }}
    >
      {ticks.map((t) => (
        <g key={t}>
          <line x1={P.l} x2={W - P.r} y1={Y(t)} y2={Y(t)} className={t === 0 ? "grid zero" : "grid"} />
          <text x={P.l - 8} y={Y(t) + 4} textAnchor="end" className="tick">{(formatoEixo ?? formato)(t)}</text>
        </g>
      ))}
      <text x={P.l} y={H - 8} className="tick">{dataBR(xs[0])}</text>
      <text x={W - P.r} y={H - 8} textAnchor="end" className="tick">{dataBR(xs[xs.length - 1])}</text>
      {series.map((s, k) => (
        <path key={s.nome} d={caminho(valores[k])} className="line" style={{ stroke: s.cor }} />
      ))}
      {hover != null && (
        <g>
          <line x1={X(hover)} x2={X(hover)} y1={P.t} y2={H - P.b} className="cursor" />
          {series.map((s, k) => valores[k][hover] != null && (
            <circle key={s.nome} cx={X(hover)} cy={Y(valores[k][hover]!)} r={4} style={{ fill: s.cor }} />
          ))}
          {(() => {
            // caixa preta com a data e o valor de cada linha; a bolinha na cor da linha vem antes do nome
            const linhas = series
              .map((s, k) => ({ nome: s.nome, cor: s.cor, v: valores[k][hover] }))
              .filter((l): l is { nome: string; cor: string; v: number } => l.v != null)
              .map((l) => ({ ...l, valor: formato(l.v) }));
            const data = dataBR(xs[hover]);
            // nome alinhado a esquerda (depois da bolinha) e o valor a direita, em colunas
            const largNome = Math.max(...linhas.map((l) => l.nome.length)) * 7;
            const largValor = Math.max(...linhas.map((l) => l.valor.length)) * 7;
            const larg = Math.max(data.length * 7.5 + 24, 29 + largNome + 24 + largValor + 14);
            const alt = 14 + 20 * (linhas.length + 1);
            const bx = direita ? X(hover) - 12 - larg : X(hover) + 12;
            return (
              <g className="tip-caixa">
                <rect className="tipbox" x={bx} y={P.t + 4} width={larg} height={alt} rx={6} fillOpacity={0.72} />
                <text x={bx + 12} y={P.t + 4 + 22} fill="#fff" fontSize={12} fontWeight={600}>{data}</text>
                {linhas.map((l, i) => {
                  const y = P.t + 4 + 22 + 20 * (i + 1);
                  return (
                    <g key={l.nome}>
                      <circle cx={bx + 17} cy={y - 4} r={5} style={{ fill: l.cor }} />
                      <text x={bx + 29} y={y} fill="#fff" fontSize={12}>{l.nome}</text>
                      <text x={bx + larg - 14} y={y} fill="#fff" fontSize={12} textAnchor="end">{l.valor}</text>
                    </g>
                  );
                })}
              </g>
            );
          })()}
        </g>
      )}
    </svg>
  );
}
