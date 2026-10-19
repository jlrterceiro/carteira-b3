"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import FiltroCorretora, { Corretora } from "./FiltroCorretora";
import Login from "./Login";
import MenuUsuario from "./MenuUsuario";
import { ProvedorCorretora, Usuario } from "../lib/sessao";

// Cada tela e uma rota (/posicao, /ganhos, /rentabilidade); o Perfil abre pelo menu do usuario (/perfil).
const ABAS = [
  { href: "/posicao", rotulo: "Posição" },
  { href: "/ganhos", rotulo: "Ganhos" },
  { href: "/rentabilidade", rotulo: "Rentabilidade" },
];

// Casca do app logado: barra lateral, barra do topo e filtro de corretora. Sem login mostra a tela de entrada NA MESMA
// URL (link direto pra /rentabilidade pede login e, entrando, ja cai nela).
export default function Casca({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Usuario | null | undefined>(undefined);
  const [corretoras, setCorretoras] = useState<Corretora[]>([]);
  const [corretora, setCorretora] = useState<number | null>(null);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    api<Usuario>("/auth/me").then(setUser).catch(() => setUser(null));
  }, []);

  // corretoras do usuario (alimentam o filtro); a escolha fica lembrada neste navegador
  const logado = !!user;
  useEffect(() => {
    if (!logado) return;
    api<Corretora[]>("/carteira/corretoras")
      .then((lista) => {
        setCorretoras(lista);
        try {
          const salvo = Number(localStorage.getItem("corretora"));
          if (salvo && lista.some((c) => c.id_corretora === salvo)) setCorretora(salvo);
        } catch { /* sem localStorage: segue sem lembrar */ }
      })
      .catch(() => setCorretoras([]));
  }, [logado]);

  const escolheCorretora = (v: number | null) => {
    setCorretora(v);
    try { if (v == null) localStorage.removeItem("corretora"); else localStorage.setItem("corretora", String(v)); } catch { /* ok */ }
  };

  if (user === undefined) return <div className="wrap muted">Carregando…</div>;

  if (!user) {
    return (
      <div className="wrap">
        <header className="top"><h1>Minha Carteira</h1></header>
        <Login onOk={setUser} />
      </div>
    );
  }

  const noPerfil = pathname === "/perfil";
  return (
    <div className="app">
      <aside className="side">
        <h1 className="brand">Minha Carteira</h1>
        <nav>
          {ABAS.map((a) => (
            <Link key={a.href} href={a.href} className={pathname === a.href ? "on" : ""}>{a.rotulo}</Link>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          {!noPerfil && <FiltroCorretora corretoras={corretoras} valor={corretora} onChange={escolheCorretora} />}
          <MenuUsuario
            nome={user.nm_usuario}
            email={user.ds_email}
            onPerfil={() => router.push("/perfil")}
            onSair={async () => {
              await api("/auth/logout", { method: "POST" });
              setUser(null); setCorretoras([]); setCorretora(null);
              router.push("/posicao");
            }}
          />
        </header>
        <main className="content">
          <ProvedorCorretora value={corretora}>{children}</ProvedorCorretora>
        </main>
      </div>
    </div>
  );
}
