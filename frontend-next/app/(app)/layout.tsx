import Casca from "../components/Casca";

// O app inteiro depende do login (cookie), entao nenhuma rota e "instantanea" no sentido do cache components.
export const instant = false;

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <Casca>{children}</Casca>;
}
