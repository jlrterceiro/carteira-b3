"use client";
import { useState } from "react";

// Explicacoes das telas de Insiders, num lugar so (aparecem em "?" ao lado do que explicam).
export const DICAS = {
  geral: "Compra e venda à vista de ações e units por administradores, conselheiros, controladores e pessoas ligadas à empresa, somando todas as classes (ON, PN, unit). Dados abertos da CVM; o mês é o da competência do formulário.",
  grupo: "Administração = conselho de administração, diretoria, conselho fiscal e órgãos estatutários. Controladores = controlador e pessoas ou empresas ligadas a ele. “Ou vinculado” = parentes e empresas do declarante.",
  vm: "Soma de cada operação ÷ valor de mercado da empresa NO DIA dela (ações do trimestre, corrigidas por desdobramentos, × preço do dia). A quantidade de ações vem da CVM, ajustada por escala; empresas muito pequenas ou em recuperação ainda distorcem.",
  posicao: "Ações compradas menos vendidas ÷ posição que o grupo tinha no começo do período (saldo inicial do formulário da CVM). Mostra o quanto o grupo mexeu no que já tinha.",
  vmEpoca: "Valor de mercado da empresa na época das operações (média ponderada pelo valor negociado), não o de hoje.",
  bloco: "Operação grande demais para pregão normal: ≥ 25% do volume do dia e ≥ R$ 5 mi, ou ≥ 2% da empresa de uma vez (ofertas, vendas casadas). Entra nas contas por padrão: nos dados, o que acontece com a ação depois não difere das operações normais. Marque para ver o ranking sem elas.",
  suspeito: "Preço do formulário muito fora do preço do dia, ou operação maior que a empresa inteira: provável erro de preenchimento. Fica de fora das contas por padrão.",
  vmMin: "Ignora operações feitas quando a empresa valia menos que isso (valor de mercado no dia da operação). Empresas pequenas distorcem os percentuais. Não afeta a tabela da sua carteira. Com mínimo, empresas sem quantidade de ações no cadastro também ficam de fora.",
  ordenar: "Valor (R$), % do valor de mercado da empresa ou % da posição do grupo. Empresas sem quantidade de ações no cadastro ficam fora da ordenação por %.",
  medida: "Compras e vendas: cada lista pelo seu total (uma não anula a outra; compra no mercado aberto é o sinal mais informativo). Líquido: compras menos vendas.",
};

// "?" que mostra a explicacao ao passar o mouse (ou focar com o teclado). Caixa fixa na tela, pra nao ser cortada por tabela com rolagem.
export default function Dica({ texto }: { texto: string }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const abre = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    const larg = 300;
    setPos({ x: Math.max(8, Math.min(window.innerWidth - larg - 8, r.left + r.width / 2 - larg / 2)), y: r.bottom + 8 });
  };
  return (
    <span
      className="dica"
      tabIndex={0}
      role="img"
      aria-label={texto}
      onMouseEnter={(e) => abre(e.currentTarget)}
      onMouseLeave={() => setPos(null)}
      onFocus={(e) => abre(e.currentTarget)}
      onBlur={() => setPos(null)}
    >
      ?
      {pos && <span className="dica-txt" role="tooltip" style={{ left: pos.x, top: pos.y }}>{texto}</span>}
    </span>
  );
}
