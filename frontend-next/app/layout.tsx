import type { Metadata } from "next";
import "./globals.css";

const TEMA_INICIAL = `try{var t=localStorage.getItem("tema");if(t!=="claro"&&t!=="escuro")t=matchMedia("(prefers-color-scheme: dark)").matches?"escuro":"claro";document.documentElement.dataset.tema=t;if(localStorage.getItem("menu")==="fechado")document.documentElement.dataset.menu="fechado"}catch(e){}`;

export const metadata: Metadata = { title: "Minha Carteira" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <head>
        {/* aplica o tema salvo (ou o do sistema, na 1a visita) antes da primeira pintura: sem piscar claro->escuro */}
        <script dangerouslySetInnerHTML={{ __html: TEMA_INICIAL }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
