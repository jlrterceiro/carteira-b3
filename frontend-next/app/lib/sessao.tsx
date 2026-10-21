"use client";
import { createContext, useContext } from "react";

export type Usuario = { nm_usuario: string; ds_email: string; sg_usuario: string };

// Corretora escolhida no filtro da barra do topo: compartilhada por Posicao, Ganhos e Rentabilidade (cada uma e uma rota).
const CorretoraCtx = createContext<number | null>(null);
export const ProvedorCorretora = CorretoraCtx.Provider;
export const useCorretora = () => useContext(CorretoraCtx);

// Data de referencia (snapshot): todas as telas mostram a carteira como estava naquele dia (yyyy-mm-dd). null = hoje.
const DataRefCtx = createContext<string | null>(null);
export const ProvedorDataRef = DataRefCtx.Provider;
export const useDataRef = () => useContext(DataRefCtx);
