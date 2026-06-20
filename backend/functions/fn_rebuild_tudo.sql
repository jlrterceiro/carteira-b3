-- Roda todo o pipeline de recalculo na ordem certa. Chamar depois de qualquer
-- importacao de operacao ou atualizacao de cotacao/evento corporativo/provento.
--
-- Ordem importa: provento_ajustado depende de tb_evento_corporativo; posicao_diaria
-- depende de tb_operacao/tb_evento_corporativo; provento_recebido depende de
-- provento_ajustado + posicao_diaria; rentabilidade_ativo_diaria depende de
-- posicao_diaria + provento_recebido + tb_cotacao; rentabilidade_diaria depende de
-- rentabilidade_ativo_diaria.
--
-- NAO trata transferencias (TRANSF) na rentabilidade diaria -- so posicao_diaria
-- trata isso por enquanto.

CREATE OR REPLACE FUNCTION public.fn_rebuild_tudo()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM public.fn_popula_provento_ajustado();
    PERFORM public.fn_popula_posicao_diaria();
    PERFORM public.fn_popula_provento_recebido();
    PERFORM public.fn_popula_rentabilidade_ativo_diaria();
    PERFORM public.fn_popula_rentabilidade_diaria();
END;
$$;
