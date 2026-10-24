// "R$ 744,1 mi" / "R$ 8,97 bi" (o valor exato fica no title da celula)
export const brlCompacto = (v: number) =>
  `${v < 0 ? "-" : ""}R$ ${Math.abs(v).toLocaleString("pt-BR", { notation: "compact", maximumFractionDigits: 1 })}`;

// numero com 2 casas ("5,67"); "—" quando nao ha valor
export const num2 = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// "6,25%" (sem sinal +); "—" quando nao ha valor
export const pctSimples = (v: number | null | undefined) => (v == null ? "—" : `${num2(v)}%`);
