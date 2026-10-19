"use client";
import { useMemo, useState } from "react";

export function useSort<T>(linhas: T[], inicial: keyof T, dirInicial: "asc" | "desc" = "desc") {
  const [chave, setChave] = useState<keyof T>(inicial);
  const [dir, setDir] = useState(dirInicial);

  const ordenadas = useMemo(() => {
    const f = dir === "asc" ? 1 : -1;
    return [...linhas].sort((a, b) => {
      const x = a[chave], y = b[chave];
      if (typeof x === "string" && typeof y === "string") return f * x.localeCompare(y);
      return f * (Number(x) - Number(y));
    });
  }, [linhas, chave, dir]);

  function alterna(c: keyof T) {
    if (c === chave) setDir(dir === "asc" ? "desc" : "asc");
    else { setChave(c); setDir(typeof linhas[0]?.[c] === "string" ? "asc" : "desc"); }
  }

  const Th = ({ c, children }: { c: keyof T; children: React.ReactNode }) => (
    <th className="sortable" onClick={() => alterna(c)} aria-sort={c === chave ? (dir === "asc" ? "ascending" : "descending") : "none"}>
      {children}{c === chave ? (dir === "asc" ? " ▲" : " ▼") : ""}
    </th>
  );

  return { ordenadas, Th };
}
