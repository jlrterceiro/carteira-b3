"use client";
import { useEffect, useRef, useState } from "react";

type Props = {
  nome: string;
  email: string;
  onPerfil: () => void;
  onSair: () => void;
};

// Menu do usuario no canto superior direito: nome + seta; abre com Perfil e Sair.
// Fecha ao clicar fora, ao apertar Esc ou ao escolher uma opcao.
export default function MenuUsuario({ nome, email, onPerfil, onSair }: Props) {
  const [aberto, setAberto] = useState(false);
  const raiz = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => {
      if (raiz.current && !raiz.current.contains(e.target as Node)) setAberto(false);
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setAberto(false); };
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", esc);
    };
  }, [aberto]);

  const escolhe = (acao: () => void) => () => { setAberto(false); acao(); };

  return (
    <div className="user-menu" ref={raiz}>
      <button
        type="button"
        className="user-btn"
        aria-haspopup="menu"
        aria-expanded={aberto}
        onClick={() => setAberto(!aberto)}
      >
        {nome} <span className={`caret ${aberto ? "up" : ""}`} aria-hidden>▾</span>
      </button>
      {aberto && (
        <div className="menu-pop" role="menu">
          <div className="menu-info muted">{email}</div>
          <button type="button" role="menuitem" onClick={escolhe(onPerfil)}>Perfil</button>
          <button type="button" role="menuitem" onClick={escolhe(onSair)}>Sair</button>
        </div>
      )}
    </div>
  );
}
