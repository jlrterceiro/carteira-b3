"use client";
import { useState } from "react";

export type Barra = { rotulo: string; titulo: string; valor: number; extra?: { nome: string; valor: string }[] };

// passo "redondo" (1, 2, 2,5, 5 x 10^k) pra ~5 linhas de grade
function passoRedondo(max: number) {
  if (max <= 0) return 1;
  const bruto = max / 5;
  const pot = Math.pow(10, Math.floor(Math.log10(bruto)));
  const f = bruto / pot;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * pot;
}

// Colunas verticais (valor >= 0): uma barra por periodo, grade horizontal, tooltip em caixa preta como o do grafico de linhas.
export default function BarChart({
  barras,
  formato,
  formatoEixo,
  cor = "#059669",
  nomeValor = "Líquido",
}: {
  barras: Barra[];
  formato: (v: number) => string;
  formatoEixo: (v: number) => string;
  cor?: string;
  nomeValor?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (!barras.length) return <p className="muted">Sem proventos no período.</p>;

  const W = 900, H = 320, P = { l: 72, r: 16, t: 16, b: 32 };
  const maxV = Math.max(...barras.map((b) => b.valor), 0);
  const passo = passoRedondo(maxV);
  const topo = Math.max(passo, Math.ceil(maxV / passo) * passo);
  const ticks = Array.from({ length: Math.round(topo / passo) + 1 }, (_, i) => i * passo);
  const larg = (W - P.l - P.r) / barras.length;
  const X = (i: number) => P.l + i * larg;
  const Y = (v: number) => P.t + (1 - v / topo) * (H - P.t - P.b);
  const cada = Math.ceil(barras.length / 14);      // no maximo ~14 rotulos no eixo x
  const bw = Math.min(larg * 0.7, 56);

  const h = hover != null ? barras[hover] : null;
  const direita = hover != null && X(hover) + larg / 2 > W / 2;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="chart"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const px = ((e.clientX - r.left) / r.width) * W;
        const i = Math.floor((px - P.l) / larg);
        setHover(i >= 0 && i < barras.length ? i : null);
      }}
    >
      {ticks.map((t) => (
        <g key={t}>
          <line x1={P.l} x2={W - P.r} y1={Y(t)} y2={Y(t)} className={t === 0 ? "grid zero" : "grid"} />
          <text x={P.l - 8} y={Y(t) + 4} textAnchor="end" className="tick">{formatoEixo(t)}</text>
        </g>
      ))}
      {barras.map((b, i) => (
        <g key={i}>
          {b.valor > 0 && (
            <rect x={X(i) + (larg - bw) / 2} y={Y(b.valor)} width={bw} height={Y(0) - Y(b.valor)} rx={2}
              fill={cor} fillOpacity={hover === i ? 1 : 0.85} />
          )}
          {i % cada === 0 && (
            <text x={X(i) + larg / 2} y={H - 10} textAnchor="middle" className="tick">{b.rotulo}</text>
          )}
        </g>
      ))}
      {h && hover != null && (() => {
        const linhas = [{ nome: nomeValor, valor: formato(h.valor), cor }, ...(h.extra ?? []).map((x) => ({ ...x, cor: "" }))];
        const largNome = Math.max(...linhas.map((l) => l.nome.length)) * 7;
        const largValor = Math.max(...linhas.map((l) => l.valor.length)) * 7;
        const caixa = Math.max(h.titulo.length * 7.5 + 24, 29 + largNome + 24 + largValor + 14);
        const alt = 14 + 20 * (linhas.length + 1);
        const cx = X(hover) + larg / 2;
        const bx = direita ? cx - larg / 2 - 8 - caixa : cx + larg / 2 + 8;
        return (
          <g>
            <rect x={X(hover)} y={P.t} width={larg} height={H - P.t - P.b} fill="#000" fillOpacity={0.05} />
            <rect x={bx} y={P.t + 4} width={caixa} height={alt} rx={6} fill="#000" fillOpacity={0.72} />
            <text x={bx + 12} y={P.t + 26} fill="#fff" fontSize={12} fontWeight={600}>{h.titulo}</text>
            {linhas.map((l, i) => {
              const y = P.t + 26 + 20 * (i + 1);
              return (
                <g key={l.nome}>
                  {l.cor && <circle cx={bx + 17} cy={y - 4} r={5} fill={l.cor} />}
                  <text x={bx + 29} y={y} fill="#fff" fontSize={12}>{l.nome}</text>
                  <text x={bx + caixa - 14} y={y} fill="#fff" fontSize={12} textAnchor="end">{l.valor}</text>
                </g>
              );
            })}
          </g>
        );
      })()}
    </svg>
  );
}
