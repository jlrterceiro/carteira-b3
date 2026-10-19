export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function api<T>(
  path: string,
  init?: RequestInit & { params?: Record<string, string | undefined> },
): Promise<T> {
  const url = new URL(API_BASE + path);
  for (const [k, v] of Object.entries(init?.params ?? {})) {
    if (v !== undefined) url.searchParams.set(k, v);
  }
  const resp = await fetch(url, {
    credentials: "include",
    ...init,
    // upload (FormData): o navegador define o Content-Type com o boundary; forcar JSON quebraria o envio
    headers: init?.body instanceof FormData
      ? { ...init?.headers }
      : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!resp.ok) {
    let detail = `Erro ${resp.status}`;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw Object.assign(new Error(detail), { status: resp.status });
  }
  return resp.json();
}

export const brl = (v: number | null | undefined) =>
  v == null
    ? "—"
    : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export const pct = (v: number | null | undefined) =>
  v == null
    ? "—"
    : `${v > 0 ? "+" : ""}${v.toLocaleString("pt-BR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}%`;

export const cor = (v: number | null | undefined) =>
  v == null || v === 0 ? "" : v > 0 ? "pos" : "neg";

export const isoDate = (d: Date) => d.toISOString().slice(0, 10);

export const PERIODOS: Record<string, number | null> = {
  "30 dias": 30,
  "6 meses": 182,
  "1 ano": 365,
  "2 anos": 730,
  "5 anos": 1825,
  "10 anos": 3650,
  Total: null,
};

export function periodoParams(dias: number | null) {
  const hoje = new Date();
  const inicio =
    dias == null ? undefined : isoDate(new Date(hoje.getTime() - dias * 864e5));
  return { inicio, fim: isoDate(hoje) };
}
