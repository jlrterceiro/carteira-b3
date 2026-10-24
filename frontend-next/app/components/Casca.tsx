"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import FiltroCorretora, { Corretora } from "./FiltroCorretora";
import Login from "./Login";
import MenuUsuario from "./MenuUsuario";
import { dataBR } from "../lib/api";
import { ProvedorCorretora, ProvedorDataRef, Usuario } from "../lib/sessao";

// Cada tela e uma rota (/posicao, /ganhos, /rentabilidade); o Perfil abre pelo menu do usuario (/perfil).
const ABAS = [
  { href: "/posicao", rotulo: "Posição" },
  { href: "/ganhos", rotulo: "Ganhos" },
  { href: "/proventos", rotulo: "Proventos" },
  { href: "/insiders", rotulo: "Insiders" },
  { href: "/rentabilidade", rotulo: "Rentabilidade" },
];

const hojeISO = () => new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);

// Casca do app logado: barra lateral, barra do topo e filtro de corretora. Sem login mostra a tela de entrada NA MESMA
// URL (link direto pra /rentabilidade pede login e, entrando, ja cai nela).
export default function Casca({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Usuario | null | undefined>(undefined);
  const [corretoras, setCorretoras] = useState<Corretora[]>([]);
  const [corretora, setCorretora] = useState<number | null>(null);
  // data de referencia (snapshot): vale pra todas as telas; fica so nesta aba do navegador
  const [hoje] = useState(hojeISO);
  const [dataRef, setDataRef] = useState<string | null>(() => {
    try { const v = sessionStorage.getItem("data_ref"); return v && v < hoje ? v : null; } catch { return null; }
  });
  const escolheData = (v: string | null) => {
    const d = v && v < hoje ? v : null;       // hoje (ou depois) = sem snapshot
    setDataRef(d);
    try { if (d) sessionStorage.setItem("data_ref", d); else sessionStorage.removeItem("data_ref"); } catch { /* ok */ }
  };
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
            <Link key={a.href} href={a.href} className={pathname === a.href || pathname.startsWith(`${a.href}/`) ? "on" : ""}>{a.rotulo}</Link>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          {!noPerfil && (
            <label className="filtro-corretora">
              <span className="muted">Data</span>
              <input type="date" value={dataRef ?? ""} max={hoje} onChange={(e) => escolheData(e.target.value || null)} />
              {dataRef && <button type="button" onClick={() => escolheData(null)}>Hoje</button>}
            </label>
          )}
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
          {!noPerfil && dataRef && (
            <p className="snapshot-aviso">
              Visão em <b>{dataBR(dataRef)}</b>: todas as telas mostram a carteira como estava nesse dia (operações, proventos e cotações até ele).{" "}
              <button type="button" onClick={() => escolheData(null)}>Voltar para hoje</button>
            </p>
          )}
          <ProvedorCorretora value={corretora}>
            <ProvedorDataRef value={noPerfil ? null : dataRef}>{children}</ProvedorDataRef>
          </ProvedorCorretora>
        </main>
      </div>
    </div>
  );
}
