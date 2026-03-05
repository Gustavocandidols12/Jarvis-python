"""
FILE: vision.py
DESCRIPTION: Módulo de visão do JARVIS.
             Mantém o frame atual da câmera sempre atualizado (atualizado pelo main.py
             a cada iteração do loop de vídeo) e expõe a função analisar_frame(),
             que captura o frame, salva em disco e envia para a API Groq Vision.

FLUXO:
    main.py  → vision.atualizar_frame(frame)   [a cada frame, ~26x/s]
    brain.py → vision.analisar_frame(pergunta) [quando o usuário pede]

DEPENDÊNCIAS:
    pip install groq  (já instalado — mesmo cliente usado em utilities.py)

API USADA:
    Groq Vision — gratuita, mesma chave já configurada em config.py.
    Modelo: meta-llama/llama-4-scout-17b-16e-instruct (suporta imagens)
    Chave em: https://console.groq.com
"""

import os
import cv2
import base64
import datetime
import threading
import numpy as np
from groq import Groq
from config import GROQ_API_KEY
from dotenv import load_dotenv
load_dotenv()

# -----------------------------------------------------------------------
# CONFIGURAÇÕES
# -----------------------------------------------------------------------

PASTA_FRAMES       = os.path.join(os.path.expanduser("~"), "Jarvis_frames")
GROQ_VISION_MODELO = "meta-llama/llama-4-scout-17b-16e-instruct"
JPEG_QUALIDADE     = 85

PROMPT_PADRAO = (
    "Descreva o que você vê nesta imagem de forma clara e concisa, "
    "em português brasileiro, como se estivesse relatando para alguém. "
    "Máximo de 3 frases."
)

VISION_SYSTEM_PROMPT = (
    "Você é JARVIS, um assistente de IA pessoal. "
    "Descreva imagens de forma direta e concisa em português brasileiro. "
    "Sem markdown, sem bullets, sem emojis. "
    "o homem de oculos e barba é seu criador"
    "Máximo de 3 frases curtas e naturais, como se estivesse conversando."
)

# -----------------------------------------------------------------------
# ESTADO INTERNO
# -----------------------------------------------------------------------

_lock_frame  = threading.Lock()
_frame_atual = None
_groq_client = None


def _get_client() -> Groq:
    """Retorna o cliente Groq, criando uma única vez (lazy singleton)."""
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=GROQ_API_KEY)
        print("[VISION] Cliente Groq Vision inicializado.")
    return _groq_client


# -----------------------------------------------------------------------
# API PÚBLICA
# -----------------------------------------------------------------------

def atualizar_frame(frame: np.ndarray) -> None:
    """
    Chamado pelo main.py a cada iteração do loop de vídeo (~26x/s).
    Mantém uma cópia thread-safe do frame mais recente.
    """
    global _frame_atual
    with _lock_frame:
        _frame_atual = frame.copy()


def capturar_e_salvar() -> tuple[np.ndarray | None, str | None]:
    """
    Captura o frame atual e salva em disco com timestamp.
    Retorna (frame, caminho) ou (None, None) se câmera indisponível.
    """
    with _lock_frame:
        if _frame_atual is None:
            return None, None
        frame = _frame_atual.copy()

    os.makedirs(PASTA_FRAMES, exist_ok=True)
    timestamp    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho      = os.path.join(PASTA_FRAMES, f"jarvis_{timestamp}.jpg")
    cv2.imwrite(caminho, frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALIDADE])
    print(f"[VISION] Frame salvo em: {caminho}")
    return frame, caminho


def analisar_frame(pergunta: str = "") -> str:
    """
    Captura o frame atual, salva em disco e envia ao Groq Vision para análise.
    Esta função é BLOQUEANTE (~1-3s) — sempre chamada em thread separada.

    Parâmetros:
        pergunta — texto do usuário. Se vazio, usa PROMPT_PADRAO.

    Retorna:
        String pronta para ser falada pelo TTS.
    """
    frame, _ = capturar_e_salvar()
    if frame is None:
        return "Não consigo acessar a câmera agora, senhor."

    prompt = pergunta.strip() if pergunta.strip() else PROMPT_PADRAO

    sucesso, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALIDADE])
    if not sucesso:
        return "Não consegui processar a imagem da câmera, senhor."

    imagem_b64 = base64.b64encode(buffer).decode("utf-8")

    try:
        print(f"[VISION] Enviando frame ao Groq Vision... (modelo: {GROQ_VISION_MODELO})")

        cliente  = _get_client()
        resposta = cliente.chat.completions.create(
            model=GROQ_VISION_MODELO,
            messages=[
                {
                    "role": "system",
                    "content": VISION_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{imagem_b64}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.4,
            max_tokens=200,
        )

        texto = resposta.choices[0].message.content.strip()

        if not texto:
            return "Não consegui descrever a imagem, senhor."

        print(f"[VISION] Resposta: {texto[:120]}")
        return _limpar_para_tts(texto)

    except Exception as e:
        erro = str(e)
        print(f"[VISION] Erro: {type(e).__name__}: {erro}")

        if "rate_limit" in erro.lower() or "429" in erro:
            return "Limite da API de visão atingido. Tente novamente em instantes, senhor."
        if "invalid_api_key" in erro.lower() or "401" in erro:
            return "Chave da API inválida. Verifique o GROQ_API_KEY no config.py."
        if "model_not_found" in erro.lower() or "404" in erro:
            return "Modelo de visão não encontrado. Verifique o GROQ_VISION_MODELO no vision.py."
        if "connection" in erro.lower():
            return "Sem conexão com a internet, senhor."

        return "Ocorreu um erro ao analisar a imagem, senhor."


# -----------------------------------------------------------------------
# UTILITÁRIO INTERNO
# -----------------------------------------------------------------------

def _limpar_para_tts(texto: str) -> str:
    """Remove markdown e formatação que o pyttsx3 leria literalmente."""
    import re
    texto = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", texto)
    texto = re.sub(r"#{1,6}\s*", "", texto)
    texto = re.sub(r"`{1,3}.*?`{1,3}", "", texto, flags=re.DOTALL)
    texto = re.sub(r"^\s*[-•]\s+", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"\n+", " ", texto)
    texto = re.sub(r" {2,}", " ", texto)
    return texto.strip()