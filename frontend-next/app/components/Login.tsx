"use client";
import { useState } from "react";
import { api } from "../lib/api";
import type { Usuario } from "../lib/sessao";

export default function Login({ onOk }: { onOk: (u: Usuario) => void }) {
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
