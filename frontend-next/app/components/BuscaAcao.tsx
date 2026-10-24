"use client";
import { useEffect, useId, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "../lib/api";

type Sugestao = { ticker: string; nome: string | null; classe: string | null; ativo: boolean };

// Campo de busca de ação com autocomplete: aceita ticker ou nome da empresa (sem acento, em qualquer parte do nome) e vai sugerindo
// enquanto digita. Setas ↑↓ navegam, Enter escolhe, Esc fecha. Ao escolher, abre a página de insiders daquela ação.
export default function BuscaAcao({ placeholder = "Ticker ou nome da empresa", destino = (t: string) => `/insiders/${t}` }: {
  placeholder?: string;
  destino?: (ticker: string) => string;
}) {
  const router = useRouter();
  const id = useId();
  const raiz = useRef<HTMLDivElement>(null);
  const ultima = useRef(0);                      // ignora resposta atrasada de uma digitação anterior
  const [q, setQ] = useState("");
  const [sug, setSug] = useState<Sugestao[]>([]);
  const [resultadoPara, setResultadoPara] = useState("");   // texto a que `sug` responde (pra distinguir "buscando" de "nenhuma")
  const [aberto, setAberto] = useState(false);
  const [ativo, setAtivo] = useState(-1);

  useEffect(() => {
    const termo = q.trim();
    const numero = ++ultima.current;
    const t = setTimeout(() => {
      if (!termo) { setSug([]); setResultadoPara(""); return; }
      api<Sugestao[]>("/acoes/busca", { params: { q: termo } })
        .then((r) => { if (numero === ultima.current) { setSug(r); setResultadoPara(termo); setAtivo(-1); } })
        .catch(() => { if (numero === ultima.current) { setSug([]); setResultadoPara(termo); } });
    }, 150);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => { if (raiz.current && !raiz.current.contains(e.target as Node)) setAberto(false); };
    document.addEventListener("mousedown", fora);
    return () => document.removeEventListener("mousedown", fora);
  }, [aberto]);

  const vai = (ticker: string) => {
    setAberto(false);
    setQ("");
    router.push(destino(ticker.toUpperCase()));
  };

  const teclas = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setAberto(true); setAtivo((a) => Math.min(sug.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setAtivo((a) => Math.max(-1, a - 1)); }
    else if (e.key === "Escape") { setAberto(false); }
    else if (e.key === "Enter") {
      e.preventDefault();
      const escolhida = sug[ativo >= 0 ? ativo : 0];
      if (escolhida) vai(escolhida.ticker);
      else if (q.trim()) vai(q.trim());          // ticker digitado que a busca não conhece: tenta mesmo assim
    }
  };

  return (
    <div className="busca" ref={raiz}>
      <input
        role="combobox"
        aria-expanded={aberto && sug.length > 0}
        aria-controls={`${id}-lista`}
        aria-activedescendant={ativo >= 0 ? `${id}-${ativo}` : undefined}
        aria-autocomplete="list"
        autoComplete="off"
        value={q}
        placeholder={placeholder}
        onChange={(e) => { setQ(e.target.value); setAberto(true); }}
        onFocus={() => setAberto(true)}
        onKeyDown={teclas}
      />
      {aberto && q.trim() !== "" && (
        <ul className="busca-lista" id={`${id}-lista`} role="listbox">
          {resultadoPara !== q.trim() && sug.length === 0 && <li className="busca-vazio muted">Buscando…</li>}
          {resultadoPara === q.trim() && sug.length === 0 && <li className="busca-vazio muted">Nenhuma ação encontrada</li>}
          {sug.map((s, i) => (
            <li
              key={s.ticker}
              id={`${id}-${i}`}
              role="option"
              aria-selected={i === ativo}
              className={`busca-item${i === ativo ? " on" : ""}`}
              onMouseEnter={() => setAtivo(i)}
              onMouseDown={(e) => { e.preventDefault(); vai(s.ticker); }}
            >
              <b>{s.ticker}</b>
              <span className="muted">{s.nome ?? ""}{s.classe ? ` · ${s.classe}` : ""}{s.ativo ? "" : " · fora de negociação"}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
