import { InsidersTela } from "../../../components/Telas";

export const instant = false;

export default async function Page({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await params;
  return <InsidersTela ticker={ticker.toUpperCase()} />;
}
