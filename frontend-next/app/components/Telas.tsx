"use client";
import Ganhos from "./Ganhos";
import Insiders from "./Insiders";
import InsidersBusca from "./InsidersBusca";
import Posicao from "./Posicao";
import Proventos from "./Proventos";
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
export function ProventosTela() {
  const c = useCorretora();
  const d = useDataRef();
  return <Proventos key={`${c ?? "todas"}|${d ?? "hoje"}`} idCorretora={c} dataRef={d} />;
}
export function InsidersTela({ ticker }: { ticker: string }) {
  const d = useDataRef();
  return <Insiders key={`${ticker}|${d ?? "hoje"}`} ticker={ticker} dataRef={d} />;
}
export function InsidersBuscaTela() {
  const c = useCorretora();
  const d = useDataRef();
  return <InsidersBusca key={`${c ?? "todas"}|${d ?? "hoje"}`} idCorretora={c} dataRef={d} />;
}
