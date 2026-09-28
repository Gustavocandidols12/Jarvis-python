"""
FILE: image_gen.py
DESCRIPTION: Geração de imagens do JASPER via Pollinations.ai.

             API pública e gratuita (sem chave, sem cadastro): um GET
             devolve a imagem pronta. Fila pública = geração demora
             10-60s — o brain.py avisa o usuário antes de chamar.

             Fluxo:
               1. pedido do usuário → Groq enriquece (traduz p/ inglês +
                  termos de qualidade). Groq falhou → usa o pedido cru.
               2. GET em image.pollinations.ai/prompt/<prompt>
               3. salva em ~/ImagesIA/imagem_YYYYMMDD_HHMMSS.jpg
               4. abre no visualizador padrão (xdg-open)

             IMPORTA ZERO módulos do projeto (padrão orbs.py) — sem
             risco de import circular. Retorna strings prontas para o
             brain.py falar (padrão phone.py).

SEM EXPRESSÕES REGULARES: limpeza de texto via strip/replace (a pedido).
"""
import os
import subprocess
import datetime

import requests
from urllib.parse import quote          # URL-encode (não é regex)

try:
    from config import GROQ_API_KEY, GROQ_MODELO
except ImportError:
    GROQ_API_KEY = ""
    GROQ_MODELO  = "openai/gpt-oss-20b"

# -----------------------------------------------------------------------
# CONFIGURAÇÃO
# -----------------------------------------------------------------------
API_URL         = "https://image.pollinations.ai/prompt/"
LARGURA         = 1024
ALTURA          = 1024
TIMEOUT_GERACAO = 90      # seg — fila grátis é lenta mesmo
TIMEOUT_GROQ    = 12
PASTA_IMAGENS   = os.path.join(os.path.expanduser("~"), "ImagesIA")

# [SEM-REGEX] prompt de instruções enviado junto do pedido do usuário
PROMPT_INSTRUCOES = (
    "Converta o pedido abaixo em UM prompt de geração de imagem, em inglês. "
    "Traduza fielmente o conteúdo pedido e acrescente termos de qualidade: "
    "highly detailed, professional lighting, beautiful composition, 4k. "
    "A imagem NÃO deve conter texto legível. "
    "Responda APENAS o prompt final em uma linha, sem aspas, sem explicação, "
    "sem prefixo. Pedido: "
)


def _enriquecer_prompt(pedido: str) -> str:
    """
    Groq traduz + melhora o pedido (Stable Diffusion entende inglês
    muito melhor). Falhou/vazio → devolve o pedido cru. Nunca lança.
    """
    if not GROQ_API_KEY:
        return pedido
    try:
        from groq import Groq
        cliente = Groq(api_key=GROQ_API_KEY)
        resp = cliente.chat.completions.create(
            model=GROQ_MODELO,
            messages=[{"role": "user",
                       "content": PROMPT_INSTRUCOES + pedido}],
            temperature=0.3,
            max_tokens=90,
        ).choices[0].message.content.strip()

        # [SEM-REGEX] limpeza de bordas com charset, não regex
        resp = resp.strip(" \t\n\r\"'`.,;-:")
        if resp and len(resp) > 10:
            print(f"[IMG] Prompt enriquecido: {resp[:80]}...")
            return resp
    except Exception as e:
        print(f"[IMG] Groq falhou no enriquecimento ({e}) — usando pedido cru")
    return pedido


def gerar_imagem(pedido: str) -> str:
    """
    Gera a imagem e retorna string pronta para o brain.py falar.
    BLOQUEANTE (10-60s) — o brain.py chama em thread separada.
    """
    pedido = (pedido or "").strip()
    if not pedido:
        return "Me diz o que devo criar, chefe."

    # 1) enriquece (tradução + qualidade)
    prompt_final = _enriquecer_prompt(pedido)

    # 2) gera via Pollinations (a URL inteira É o prompt)
    url = (f"{API_URL}{quote(prompt_final)}"
           f"?width={LARGURA}&height={ALTURA}&nologo=true")
    print(f"[IMG] Gerando imagem (~10-60s)...")
    try:
        resp = requests.get(url, timeout=TIMEOUT_GERACAO)
    except requests.exceptions.Timeout:
        return "A fila da imagem tá lenta demais hoje, chefe. Tenta de novo."
    except requests.exceptions.ConnectionError:
        return "Sem internet, sem imagem. A mágica precisa de rede."

    if resp.status_code != 200 or len(resp.content) < 2000:
        print(f"[IMG] Resposta inesperada: HTTP {resp.status_code}, "
              f"{len(resp.content)} bytes")
        return "A API de imagem não colaborou agora. Tenta de novo em instantes."

    # 3) salva com nome de data (mesmo padrão do screenshot do phone.py)
    os.makedirs(PASTA_IMAGENS, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(PASTA_IMAGENS, f"imagem_{timestamp}.jpg")
    with open(caminho, "wb") as f:
        f.write(resp.content)
    print(f"[IMG] Salva em: {caminho}")

    # 4) abre no visualizador
    try:
        subprocess.Popen(["xdg-open", caminho])
    except Exception as e:
        print(f"[IMG] Não abri o visualizador: {e}")

    return f"Imagem pronta e aberta, chefe. Salvei em {PASTA_IMAGENS}."
