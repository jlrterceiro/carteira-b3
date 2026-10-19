import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // pagina inicial: logado ou nao, cai na Posicao (sem login a propria rota mostra a tela de entrada)
  async redirects() {
    return [{ source: "/", destination: "/posicao", permanent: false }];
  },
  cacheComponents: true,
  partialPrefetching: true,
};

export default nextConfig;
