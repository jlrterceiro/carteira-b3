"use client";
import { useEffect, useState } from "react";
import { api } from "./lib/api";
import Ganhos from "./components/Ganhos";
import FiltroCorretora, { Corretora } from "./components/FiltroCorretora";
import MenuUsuario from "./components/MenuUsuario";
import Perfil from "./components/Perfil";
import Posicao from "./components/Posicao";
import Rentabilidade from "./components/Rentabilidade";

type Usuario = { nm_usuario: string; ds_email: string; sg_usuario: string };
// "Perfil" nao e aba: abre pelo menu do usuario (canto superior direito)
const ABAS = ["Posição", "Ganhos", "Rentabilidade"] as const;
type Aba = (typeof ABAS)[number] | "Perfil";

function Login({ onOk }: { onOk: (u: Usuario) => void }) {
  const [cadastro, setCadastro] = useState(false);
  const [f, setF] = useState({ nm_usuario: "", sg_usuario: "", ds_email: "", senha: "" });
  const [erro, setErro] = useState("");
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF({ ...f, [k]: e.target.value });

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setErro("");
    try {
      if (cadastro) await api("/auth/cadastro", { method: "POST", body: JSON.stringify(f) });
      else await api("/auth/login", { method: "POST", body: JSON.stringify({ ds_email: f.ds_email, senha: f.senha }) });
      onOk(await api<Usuario>("/auth/me"));
    } catch (err) {
      setErro((err as Error).message);
    }
  }

  return (
    <form className="col card" onSubmit={enviar}>
      <h1>{cadastro ? "Criar conta" : "Entrar"}</h1>
      {cadastro && <input placeholder="Nome" value={f.nm_usuario} onChange={set("nm_usuario")} required />}
      {cadastro && <input placeholder="Usuário (sigla)" value={f.sg_usuario} onChange={set("sg_usuario")} required />}
      <input type="email" placeholder="E-mail" value={f.ds_email} onChange={set("ds_email")} required />
      <input type="password" placeholder="Senha" value={f.senha} onChange={set("senha")} required />
      {erro && <p className="err">{erro}</p>}
      <button className="primary">{cadastro ? "Cadastrar" : "Entrar"}</button>
      <button type="button" onClick={() => setCadastro(!cadastro)}>
        {cadastro ? "Já tenho conta" : "Criar conta"}
      </button>
      {cadastro && <p className="muted">Se o e-mail já existir sem senha, a conta é reivindicada.</p>}
    </form>
  );
}

export default function Home() {
  const [user, setUser] = useState<Usuario | null | undefined>(undefined);
  const [aba, setAba] = useState<Aba>("Posição");
  const [corretoras, setCorretoras] = useState<Corretora[]>([]);
  const [corretora, setCorretora] = useState<number | null>(null);

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

  return (
    <div className="app">
      <aside className="side">
        <h1 className="brand">Minha Carteira</h1>
        <nav>
          {ABAS.map((a) => (
            <button key={a} className={a === aba ? "on" : ""} onClick={() => setAba(a)}>{a}</button>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          {aba !== "Perfil" && <FiltroCorretora corretoras={corretoras} valor={corretora} onChange={escolheCorretora} />}
          <MenuUsuario
            nome={user.nm_usuario}
            email={user.ds_email}
            onPerfil={() => setAba("Perfil")}
            onSair={async () => { await api("/auth/logout", { method: "POST" }); setUser(null); setAba("Posição"); setCorretoras([]); setCorretora(null); }}
          />
        </header>
        <main className="content">
          {/* key = corretora: trocar o filtro remonta a tela e refaz as buscas do zero */}
          {aba === "Posição" && <Posicao key={corretora ?? "todas"} idCorretora={corretora} />}
          {aba === "Ganhos" && <Ganhos key={corretora ?? "todas"} idCorretora={corretora} />}
          {aba === "Rentabilidade" && <Rentabilidade key={corretora ?? "todas"} idCorretora={corretora} />}
          {aba === "Perfil" && <Perfil />}
        </main>
      </div>
    </div>
  );
}
