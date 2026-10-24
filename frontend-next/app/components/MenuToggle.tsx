"use client";
import { useSyncExternalStore } from "react";

// Esconde/mostra o menu lateral. O estado vive em data-menu no <html> (o script do layout aplica o valor salvo antes da 1a pintura);
// aqui so se le e se troca, igual ao botao de tema.
function assina(cb: () => void) {
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-menu"] });
  return () => obs.disconnect();
}
const fechado = () => document.documentElement.dataset.menu === "fechado";

export default function MenuToggle() {
  const esconde = useSyncExternalStore(assina, fechado, () => false);
  const troca = () => {
    if (esconde) delete document.documentElement.dataset.menu;
    else document.documentElement.dataset.menu = "fechado";
    try { localStorage.setItem("menu", esconde ? "aberto" : "fechado"); } catch { /* sem localStorage: vale so nesta visita */ }
  };
  return (
    <button type="button" className="menu-btn" onClick={troca} aria-expanded={!esconde} aria-label={esconde ? "Mostrar o menu lateral" : "Esconder o menu lateral"} title={esconde ? "Mostrar o menu" : "Esconder o menu (mais espaço para a tela)"}>
      <span aria-hidden>{esconde ? "☰" : "«"}</span>
    </button>
  );
}
