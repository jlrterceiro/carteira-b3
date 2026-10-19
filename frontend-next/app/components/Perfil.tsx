"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, brl } from "../lib/api";

type Recalculo = { rodando: boolean; pendente: boolean; inicio: string | null; fim: string | null; erro: string | null };
type PerfilDados = {
  nm_usuario: string; sg_usuario: string; ds_email: string;
  importacao: { total_operacoes: number; primeira: string | null; ultima: string | null; sugestao_inicio: string | null };
  recalculo: Recalculo;
};
type Amostra = { dt: string; tipo: string; ticker: string; quantidade: number; preco: number; valor: number; corretora: string };
type Previa = {
  linhas: number; novas: number; ja_importadas: number; ativo_desconhecido: number; tipo_ignorado: number;
  periodo_novas: [string, string] | null; valor_comprado_novas: number; valor_vendido_novas: number;
  tickers_desconhecidos: { ticker: string; linhas: number }[]; tipos_ignorados: { tipo: string; linhas: number }[];
  corretoras_novas: string[]; amostra_novas: Amostra[]; inseridas?: number; recalculo_iniciado?: boolean;
};

const dataBR = (iso: string | null) => (iso ? iso.split("-").reverse().join("/") : "—");

export default function Perfil() {
  const [p, setP] = useState<PerfilDados | null>(null);
  const [erro, setErro] = useState("");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [previa, setPrevia] = useState<Previa | null>(null);
  const [resultado, setResultado] = useState<Previa | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [recalc, setRecalc] = useState<Recalculo | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const carrega = useCallback(
    () => api<PerfilDados>("/perfil").then((d) => { setP(d); setRecalc(d.recalculo); }).catch((e) => setErro(e.message)),
    [],
  );
  useEffect(() => { carrega(); }, [carrega]);

  // enquanto o servidor recalcula a carteira (~1 min), acompanha o andamento
  useEffect(() => {
    if (!recalc?.rodando) return;
    const t = setInterval(async () => {
      try {
        const r = await api<Recalculo>("/perfil/recalculo");
        setRecalc(r);
        if (!r.rodando) carrega();
      } catch { /* tenta de novo no proximo tick */ }
    }, 3000);
    return () => clearInterval(t);
  }, [recalc?.rodando, carrega]);

  const envio = (f: File) => {
    const fd = new FormData();
    fd.append("arquivo", f);
    return fd;
  };

  async function escolheArquivo(f: File | null) {
    setArquivo(f); setPrevia(null); setResultado(null); setErro("");
    if (!f) return;
    setOcupado(true);
    try {
      setPrevia(await api<Previa>("/perfil/importacao/previa", { method: "POST", body: envio(f) }));
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setOcupado(false);
    }
  }

  async function importar() {
    if (!arquivo) return;
    setOcupado(true); setErro("");
    try {
      const r = await api<Previa>("/perfil/importacao", { method: "POST", body: envio(arquivo) });
      setResultado(r); setPrevia(null); setArquivo(null);
      if (inputRef.current) inputRef.current.value = "";
      const rc = await api<Recalculo>("/perfil/recalculo");
      setRecalc(rc);
      await carrega();
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setOcupado(false);
    }
  }

  if (!p) return erro ? <p className="err">{erro}</p> : <p className="muted">Carregando…</p>;
  const imp = p.importacao;

  return (
    <>
      <div className="card">
        <h2 style={{ margin: "0 0 4px" }}>{p.nm_usuario}</h2>
        <p className="muted" style={{ margin: 0 }}>
          {p.sg_usuario} · {p.ds_email}
        </p>
      </div>

      <div className="card">
        <h2 style={{ margin: "0 0 8px" }}>Importar operações da B3</h2>
        <p style={{ margin: "0 0 4px" }}>
          {imp.ultima ? (
            <>
              Última operação importada: <b>{dataBR(imp.ultima)}</b> ({imp.total_operacoes} operações desde {dataBR(imp.primeira)}).
            </>
          ) : (
            "Você ainda não importou nenhuma operação."
          )}
        </p>
        <p className="muted" style={{ margin: "0 0 12px" }}>
          Na <b>Área do Investidor da B3</b>, baixe o <b>Extrato de Negociação</b>
          {imp.sugestao_inicio ? <> a partir de <b>{dataBR(imp.sugestao_inicio)}</b> (uns dias antes da última, por segurança)</> : null}
          {" "}e envie o arquivo .xlsx aqui. Operações que já existem são ignoradas, então não tem problema repetir datas.
        </p>

        <input ref={inputRef} type="file" accept=".xlsx" disabled={ocupado}
          onChange={(e) => escolheArquivo(e.target.files?.[0] ?? null)} />
        {ocupado && <p className="muted">Processando…</p>}
        {erro && <p className="err">{erro}</p>}

        {previa && (
          <div style={{ marginTop: 16 }}>
            <p style={{ margin: "0 0 4px" }}>
              <b>{previa.novas}</b> {previa.novas === 1 ? "operação nova" : "operações novas"}
              {previa.periodo_novas && <> (de {dataBR(previa.periodo_novas[0])} a {dataBR(previa.periodo_novas[1])})</>}
              {" · "}<span className="muted">{previa.ja_importadas} já estavam importadas</span>
            </p>
            {previa.novas > 0 && (
              <p className="muted" style={{ margin: "0 0 8px" }}>
                Comprado {brl(previa.valor_comprado_novas)} · vendido {brl(previa.valor_vendido_novas)}
              </p>
            )}
            {previa.ativo_desconhecido > 0 && (
              <p className="err" style={{ margin: "0 0 4px" }}>
                {previa.ativo_desconhecido} linha(s) não serão importadas — o sistema só acompanha ações e não reconhece:{" "}
                {previa.tickers_desconhecidos.map((t) => t.ticker).join(", ")} (FII, ETF, BDR ou ticker fora do cadastro).
              </p>
            )}
            {previa.tipo_ignorado > 0 && (
              <p className="muted" style={{ margin: "0 0 4px" }}>
                {previa.tipo_ignorado} linha(s) ignoradas por tipo de movimentação ({previa.tipos_ignorados.map((t) => t.tipo || "vazio").join(", ")}) — só compra e venda são importadas.
              </p>
            )}
            {previa.corretoras_novas.length > 0 && (
              <p className="muted" style={{ margin: "0 0 4px" }}>Corretora nova no sistema: {previa.corretoras_novas.join(", ")}.</p>
            )}
            {previa.amostra_novas.length > 0 && (
              <div className="scroll" style={{ margin: "8px 0" }}>
                <table>
                  <thead><tr><th>Data</th><th style={{ textAlign: "left" }}>Tipo</th><th style={{ textAlign: "left" }}>Ticker</th><th>Qtd</th><th>Preço</th><th>Valor</th></tr></thead>
                  <tbody>
                    {previa.amostra_novas.map((o, i) => (
                      <tr key={i}>
                        <td>{dataBR(o.dt)}</td><td style={{ textAlign: "left" }}>{o.tipo}</td><td style={{ textAlign: "left" }}>{o.ticker}</td>
                        <td>{o.quantidade}</td><td>{brl(o.preco)}</td><td>{brl(o.valor)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {previa.novas > previa.amostra_novas.length && (
                  <p className="muted">… e mais {previa.novas - previa.amostra_novas.length}.</p>
                )}
              </div>
            )}
            <button className="primary" disabled={ocupado || previa.novas === 0} onClick={importar}>
              {previa.novas === 0 ? "Nada novo para importar" : `Importar ${previa.novas} ${previa.novas === 1 ? "operação" : "operações"}`}
            </button>
          </div>
        )}

        {resultado && (
          <p style={{ marginTop: 16 }}>
            ✓ <b>{resultado.inseridas}</b> {resultado.inseridas === 1 ? "operação importada" : "operações importadas"}.
          </p>
        )}
        {recalc?.rodando && (
          <p className="muted">⏳ Recalculando posição, ganhos e rentabilidade (leva cerca de 1 minuto). Você pode navegar; os números mudam quando terminar.</p>
        )}
        {recalc && !recalc.rodando && recalc.fim && resultado && !recalc.erro && (
          <p className="pos">✓ Carteira recalculada. Veja as abas Posição, Ganhos e Rentabilidade.</p>
        )}
        {recalc?.erro && <p className="err">Erro no recálculo: {recalc.erro}</p>}
      </div>
    </>
  );
}
