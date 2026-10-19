"use client";
import { useState } from "react";

export type Ponto = { x: string; y: number; destaque?: boolean };

export default function LineChart({
  pontos,
  formato,
}: {
  pontos: Ponto[];
  formato: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (pontos.length < 2) return <p className="muted">Sem dados suficientes.</p>;

  const W = 900, H = 320, P = { l: 64, r: 16, t: 16, b: 28 };
  const ys = pontos.map((p) => p.y);
  let min = Math.min(...ys), max = Math.max(...ys);
  if (min === max) { min -= 1; max += 1; }
  const X = (i: number) => P.l + (i / (pontos.length - 1)) * (W - P.l - P.r);
  const Y = (v: number) => P.t + (1 - (v - min) / (max - min)) * (H - P.t - P.b);
  const d = pontos.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join("");
  const ticks = [0, 1, 2, 3, 4].map((i) => min + ((max - min) * i) / 4);
  const h = hover != null ? pontos[hover] : null;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="chart"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const px = ((e.clientX - r.left) / r.width) * W;
        const i = Math.round(((px - P.l) / (W - P.l - P.r)) * (pontos.length - 1));
        setHover(Math.max(0, Math.min(pontos.length - 1, i)));
      }}
    >
      {ticks.map((t) => (
        <g key={t}>
          <line x1={P.l} x2={W - P.r} y1={Y(t)} y2={Y(t)} className="grid" />
          <text x={P.l - 8} y={Y(t) + 4} textAnchor="end" className="tick">{formato(t)}</text>
        </g>
      ))}
      <text x={P.l} y={H - 8} className="tick">{pontos[0].x}</text>
      <text x={W - P.r} y={H - 8} textAnchor="end" className="tick">{pontos[pontos.length - 1].x}</text>
      <path d={d} className="line" />
      {h && hover != null && (
        <g>
          <line x1={X(hover)} x2={X(hover)} y1={P.t} y2={H - P.b} className="cursor" />
          <circle cx={X(hover)} cy={Y(h.y)} r={4} className="dot" />
          <text x={X(hover) > W / 2 ? X(hover) - 8 : X(hover) + 8} y={P.t + 12}
            textAnchor={X(hover) > W / 2 ? "end" : "start"} className="tip">
            {h.x} · {formato(h.y)}
          </text>
        </g>
      )}
    </svg>
  );
}
