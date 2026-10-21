"use client";
import Ganhos from "./Ganhos";
import Posicao from "./Posicao";
import Rentabilidade from "./Rentabilidade";
import { useCorretora, useDataRef } from "../lib/sessao";

// key = corretora + data: trocar o filtro remonta a tela e refaz as buscas do zero
export function PosicaoTela() {
  const c = useCorretora();
  const d = useDataRef();
  return <Posicao key={`${c ?? "todas"}|${d ?? "hoje"}`} idCorretora={c} dataRef={d} />;
}
export function GanhosTela() {
  const c = useCorretora();
  const d = useDataRef();
  return <Ganhos key={`${c ?? "todas"}|${d ?? "hoje"}`} idCorretora={c} dataRef={d} />;
}
export function RentabilidadeTela() {
  const c = useCorretora();
  const d = useDataRef();
  return <Rentabilidade key={`${c ?? "todas"}|${d ?? "hoje"}`} idCorretora={c} dataRef={d} />;
}
