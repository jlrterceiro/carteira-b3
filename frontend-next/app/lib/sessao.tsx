"use client";
import { createContext, useContext } from "react";

export type Usuario = { nm_usuario: string; ds_email: string; sg_usuario: string };

// Corretora escolhida no filtro da barra do topo: compartilhada por Posicao, Ganhos e Rentabilidade (cada uma e uma rota).
const CorretoraCtx = createContext<number | null>(null);
export const ProvedorCorretora = CorretoraCtx.Provider;
export const useCorretora = () => useContext(CorretoraCtx);
