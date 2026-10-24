import { AcaoTela } from "../../../components/Telas";

export const instant = false;

export default async function Page({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await params;
  return <AcaoTela ticker={ticker.toUpperCase()} />;
}
