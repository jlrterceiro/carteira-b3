"use client";
import { useSyncExternalStore } from "react";

type Tema = "claro" | "escuro";

// o tema vive no atributo data-tema do <html> (o script do layout poe antes da primeira pintura); aqui so se le e se troca
function assina(cb: () => void) {
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-tema"] });
  return () => obs.disconnect();
}
const atual = (): Tema => (document.documentElement.dataset.tema === "escuro" ? "escuro" : "claro");

export default function TemaToggle() {
  const tema = useSyncExternalStore(assina, atual, () => "claro" as Tema);
  const troca = () => {
    const novo: Tema = tema === "escuro" ? "claro" : "escuro";
    document.documentElement.dataset.tema = novo;
    try { localStorage.setItem("tema", novo); } catch { /* sem localStorage: vale so nesta visita */ }
  };
  return (
    <button type="button" className="tema-btn" onClick={troca} title={tema === "escuro" ? "Mudar para o tema claro" : "Mudar para o tema escuro"} aria-label="Alternar tema claro e escuro">
      <span className="tema-icone" aria-hidden>{tema === "escuro" ? "☀" : "☾"}</span>
      {tema === "escuro" ? "Claro" : "Escuro"}
    </button>
  );
}
