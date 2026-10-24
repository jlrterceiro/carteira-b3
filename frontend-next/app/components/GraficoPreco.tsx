"use client";
import { useState } from "react";
import { dataBR } from "../lib/api";

export type PontoPreco = { x: string; y: number };

// passo "redondo" (1, 2, 2,5, 5 x 10^k) pra ~5 linhas de grade
function passoRedondo(faixa: number) {
  if (faixa <= 0) return 1;
  const bruto = faixa / 5;
  const pot = Math.pow(10, Math.floor(Math.log10(bruto)));
  const f = bruto / pot;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * pot;
}

// Linha de preco (uma serie so) com area suave, grade horizontal, 5 datas no eixo x e tooltip em caixa preta como os outros graficos.
export default function GraficoPreco({ pontos, formato, cor = "var(--accent)" }: {
  pontos: PontoPreco[];
  formato: (v: number) => string;
  cor?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (pontos.length < 2) return <p className="muted">Sem dados suficientes.</p>;

  const W = 900, H = 320, P = { l: 64, r: 16, t: 16, b: 28 };
  const ys = pontos.map((p) => p.y);
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const passo = passoRedondo(hi - lo);
  const min = Math.floor(lo / passo) * passo;
  const max = Math.max(min + passo, Math.ceil(hi / passo) * passo);
  const ticks = Array.from({ length: Math.round((max - min) / passo) + 1 }, (_, i) => min + i * passo);
  const X = (i: number) => P.l + (i / (pontos.length - 1)) * (W - P.l - P.r);
  const Y = (v: number) => P.t + (1 - (v - min) / (max - min)) * (H - P.t - P.b);
  const linha = pontos.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join("");
  const area = `${linha}L${X(pontos.length - 1).toFixed(1)},${Y(min).toFixed(1)}L${X(0).toFixed(1)},${Y(min).toFixed(1)}Z`;
  const dias = (Date.parse(pontos[pontos.length - 1].x) - Date.parse(pontos[0].x)) / 864e5;
  // ate 2 anos: dd/mm/aa; mais que isso: mm/aaaa
  const rotulo = (iso: string) => (dias > 730 ? `${iso.slice(5, 7)}/${iso.slice(0, 4)}` : `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(2, 4)}`);
  const idxX = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * (pontos.length - 1)));
  const casas = passo < 1 ? 2 : 0;
  const eixo = (v: number) => v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
  const direita = hover != null && X(hover) > W / 2;
  const id = `g${pontos.length}${Math.round(hi * 100)}`;

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
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={cor} stopOpacity={0.25} />
          <stop offset="100%" stopColor={cor} stopOpacity={0.02} />
        </linearGradient>
      </defs>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={P.l} x2={W - P.r} y1={Y(t)} y2={Y(t)} className="grid" />
          <text x={P.l - 8} y={Y(t) + 4} textAnchor="end" className="tick">{eixo(t)}</text>
        </g>
      ))}
      {idxX.map((i, k) => (
        <text key={k} x={X(i)} y={H - 8} textAnchor={k === 0 ? "start" : k === idxX.length - 1 ? "end" : "middle"} className="tick">{rotulo(pontos[i].x)}</text>
      ))}
      <path d={area} fill={`url(#${id})`} />
      <path d={linha} className="line" style={{ stroke: cor }} />
      {hover != null && (() => {
        const p = pontos[hover];
        const valor = formato(p.y);
        const data = dataBR(p.x);
        const larg = Math.max(data.length * 7.5 + 24, valor.length * 7.5 + 24);
        const bx = direita ? X(hover) - 12 - larg : X(hover) + 12;
        return (
          <g>
            <line x1={X(hover)} x2={X(hover)} y1={P.t} y2={H - P.b} className="cursor" />
            <circle cx={X(hover)} cy={Y(p.y)} r={4} style={{ fill: cor }} />
            <rect className="tipbox" x={bx} y={P.t + 4} width={larg} height={54} rx={6} fillOpacity={0.72} />
            <text x={bx + 12} y={P.t + 24} fill="#fff" fontSize={12} fontWeight={600}>{data}</text>
            <text x={bx + 12} y={P.t + 46} fill="#fff" fontSize={13}>{valor}</text>
          </g>
        );
      })()}
    </svg>
  );
}
