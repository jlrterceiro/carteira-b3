"use client";
import Ganhos from "./Ganhos";
import Posicao from "./Posicao";
import Rentabilidade from "./Rentabilidade";
import { useCorretora } from "../lib/sessao";

// key = corretora: trocar o filtro remonta a tela e refaz as buscas do zero
export function PosicaoTela() {
  const c = useCorretora();
  return <Posicao key={c ?? "todas"} idCorretora={c} />;
}
export function GanhosTela() {
  const c = useCorretora();
  return <Ganhos key={c ?? "todas"} idCorretora={c} />;
}
export function RentabilidadeTela() {
  const c = useCorretora();
  return <Rentabilidade key={c ?? "todas"} idCorretora={c} />;
}
