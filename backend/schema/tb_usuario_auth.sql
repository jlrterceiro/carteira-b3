-- Adiciona coluna de senha pra autenticacao via API. Nullable de proposito: os 3 usuarios
-- existentes (jlrterceiro, mario.eulalio, ediesley) nao tem senha ainda -- ficam NULL ate
-- "reivindicarem" a propria conta via POST /auth/cadastro com o mesmo e-mail.

ALTER TABLE public.tb_usuario ADD COLUMN ds_senha_hash TEXT;
