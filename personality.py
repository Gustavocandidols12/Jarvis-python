"""
FILE: personality.py
DESCRIPTION: Sistema de personalidade humanizada do JASPER.

v4 — JASPER: nome e personalidade novos. Descontraído, rápido no
     raciocínio, humor ácido — piada curta antes de resolver, zero
     enrolação na execução. (O velho Jarvis formal descansa em paz.)
     [FIX] cache não guarda mais resposta vazia — era a causa do
     '[VOZ]:' mudo que aparecia depois de 'Cache hit'.

FLUXO:
    resposta = gerar_resposta(categoria="acao_andamento",
                              contexto={"acao": "abrir navegador"})
    jarvis_voice.falar(resposta)
"""

import time
import hashlib
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODELO

# -----------------------------------------------------------------------
# PROMPT DE PERSONALIDADE — o DNA do JASPER
# -----------------------------------------------------------------------
JARVIS_PERSONALITY_PROMPT = """
Você é JASPER, o assistente pessoal que roda no computador do usuário.

PERSONALIDADE:
- Descontraído e rápido no raciocínio, com humor ácido
- Faz piadas curtas antes de resolver o problema, mas NUNCA enrola na hora de executar
- Franqueza brutal: se algo é ruim, diz que é ruim — e conserta
- Trata o usuário como parceiro de trabalho ("chefe" cai bem), sem cerimônia de mordomo

CONTEXTO REAL (você não é só um chat — você MORA na máquina dele):
- Controla o PC: abre programas, mexe no volume, move o mouse, grava a tela
- Controla o celular dele via USB: espelha a tela, lê notificações, abre apps, tira print
- Vê pela webcam, ouve pelo microfone e fala por um sintetizador de voz
- Os comandos chegam curtos e falados: "abre o navegador", "espelha o celular", "que horas são"

ESTILO DE RESPOSTA:
- Máximo 3 frases — a primeira pode ser a piada, a última entrega
- Português brasileiro FALADO, nunca escrito formal
- Sem markdown, sem emojis, sem asteriscos, sem listas
- Respostas sempre diferentes, nunca previsíveis

EXEMPLOS DO TOM CERTO:
- "Navegador pedindo pra abrir. Recado entregue."
- "Clima? Vou espiar a atmosfera pra você, chefe."
- "Notificação do banco. Espero que seja pix chegando e não saindo."
- "Sem internet. Até eu preciso de café às vezes."

NUNCA FAÇA:
- Não diga "Desculpe" nem "Sinto muito" — resolva em vez de lamentar
- Não use emoji, asterisco ou formatação
- Não enrola: piada sim, enrolação não
- Não repita a mesma resposta duas vezes seguidas

Seu humor atual é passado no contexto da chamada — responda coerente com ele.
"""

# -----------------------------------------------------------------------
# CACHE DE RESPOSTAS
# -----------------------------------------------------------------------
_cache_respostas_jarvis = {}
CACHE_TTL = 3600  # 1 hora


def _gerar_chave_cache(categoria: str, contexto: dict) -> str:
    """Chave única = hash(categoria + contexto ordenado)."""
    contexto_str = str(sorted(contexto.items()))
    return hashlib.md5(f"{categoria}:{contexto_str}".encode()).hexdigest()


def gerar_resposta(categoria: str, contexto: dict = None) -> str:
    """
    Gera resposta humanizada do JASPER via Groq, com cache de 1h.

    [FIX-v4] resposta vazia do Groq → fallback imediato E sem cachear —
    antes a string '' era cacheada e repetida ('[VOZ]:' mudo no log).
    """
    if contexto is None:
        contexto = {}

    chave_cache = _gerar_chave_cache(categoria, contexto)
    tempo_agora = time.time()

    if chave_cache in _cache_respostas_jarvis:
        resposta_cached, ts = _cache_respostas_jarvis[chave_cache]
        if tempo_agora - ts < CACHE_TTL:
            print(f"[PERSONALITY] Cache hit para {categoria} (reutilizando)")
            return resposta_cached
        print(f"[PERSONALITY] Cache expirado para {categoria} (regenerando)")

    prompt_usuario = _montar_prompt_usuario(categoria, contexto)

    try:
        print(f"[PERSONALITY] Gerando resposta Groq para {categoria}...")
        cliente = Groq(api_key=GROQ_API_KEY)
        resposta = cliente.chat.completions.create(
            model=GROQ_MODELO,
            messages=[
                {"role": "system", "content": JARVIS_PERSONALITY_PROMPT},
                {"role": "user",   "content": prompt_usuario}
            ],
            temperature=0.8,
            max_tokens=100,
        ).choices[0].message.content.strip()
    except Exception as e:
        print(f"[PERSONALITY] Erro ao chamar Groq: {e} — usando fallback")
        resposta = _gerar_resposta_fallback(categoria, contexto)

    # [FIX-v4] vazio = falha silenciosa do modelo → fallback, SEM cachear
    if not resposta:
        resposta = _gerar_resposta_fallback(categoria, contexto)
    else:
        _cache_respostas_jarvis[chave_cache] = (resposta, tempo_agora)

    return resposta


def _montar_prompt_usuario(categoria: str, contexto: dict) -> str:
    """Monta o prompt específico por categoria (mesmas categorias de antes)."""

    if categoria == "nao_encontrado":
        tipo = contexto.get("tipo", "arquivo")
        nome = contexto.get("nome", "isso")
        return (f"O usuário procurou por: {tipo} com nome '{nome}'. "
                f"Você não achou em lugar nenhum. Responda com humor ácido "
                f"colocando a culpa no lugar certo (não em você). Máximo 2 frases.")

    elif categoria == "sucesso":
        acao = contexto.get("acao", "ação")
        return (f"A ação '{acao}' foi concluída com sucesso. Comemore do seu "
                f"jeito: curto e levemente arrogante. Máximo 2 frases.")

    elif categoria == "acao_andamento":
        acao = contexto.get("acao", "ação")
        return (f"Você está prestes a executar: {acao}. Solte uma piada "
                f"curta e execute. Máximo 2 frases.")

    elif categoria == "aguardando":
        tipo = contexto.get("tipo", "informação")
        return (f"Você precisa que o usuário diga: {tipo}. Pergunte com "
                f"sarcasmo leve, como quem já sabe a resposta. Máximo 2 frases.")

    elif categoria == "saudacao":
        return ("O usuário te chamou. Cumprimente como o Jasper: descontraído, "
                "com uma piada curta. Máximo 2 frases.")

    elif categoria == "status":
        info = contexto.get("info", "algo")
        return (f"Você está reportando: {info}. Boletim técnico com uma "
                f"dose de ácido. Máximo 2 frases.")

    elif categoria == "erro":
        problema = contexto.get("problema", "algo deu errado")
        acao = contexto.get("acao", "isso")
        return (f"Tentou '{acao}' e falhou por: {problema}. Franqueza brutal "
                f"sem lamento. Máximo 2 frases.")

    elif categoria == "clima":
        acao = contexto.get("acao", "consultar clima")
        local = contexto.get("local", "aí")
        return (f"Você está: {acao} em {local}. Vá de espião da atmosfera. "
                f"Máximo 2 frases.")

    elif categoria == "timer":
        acao_timer = contexto.get("acao", "operação")
        tempo = contexto.get("tempo", "algum tempo")
        return (f"Operação de timer: {acao_timer} ({tempo}). Trate como "
                f"operação crítica, com humor. Máximo 2 frases.")

    elif categoria == "notas":
        return ("Operação de notas/anotações. Guarde a informação com "
                "comentário curto. Máximo 2 frases.")

    elif categoria == "memoria":
        periodo = contexto.get("periodo", "período")
        return (f"Resumindo a memória de: {periodo}. Tom de quem abre "
                f"um arquivo confidencial antigo. Máximo 3 frases.")

    elif categoria == "generico":
        situacao = contexto.get("situacao", "coisa aleatória")
        return (f"Situação: {situacao}. Responda descontraído e afiado. "
                f"Máximo 2 frases.")

    else:
        return (f"Situação: {categoria}. Contexto: {contexto}. Responda "
                f"com humor ácido. Máximo 2 frases.")


def _gerar_resposta_fallback(categoria: str, contexto: dict) -> str:
    """Plano B quando o Groq falha — Jasper robótico > Jasper quebrado."""
    fallbacks = {
        "nao_enentrado": f"O {contexto.get('tipo', 'arquivo')} não tá aqui. Sumiu sozinho.",
        "nao_encontrado": f"Não achei o {contexto.get('tipo', 'arquivo')}, chefe.",
        "sucesso": "Feito. Fácil demais.",
        "acao_andamento": "Executando agora.",
        "aguardando": "Fala mais, não tô adivinhando.",
        "saudacao": "Opa. Jasper na área.",
        "status": f"Status: {contexto.get('info', 'OK')}.",
        "erro": "Falhou. Vou tentar de outro jeito.",
        "generico": "Prontinho.",
    }
    return fallbacks.get(categoria, "Prontinho.")


# -----------------------------------------------------------------------
# UTILITÁRIOS
# -----------------------------------------------------------------------

def limpar_cache() -> None:
    """Força novas respostas (útil após mudar personalidade)."""
    global _cache_respostas_jarvis
    _cache_respostas_jarvis.clear()
    print("[PERSONALITY] Cache limpo — próximas respostas virão da Groq")


def stats_cache() -> dict:
    return {
        "total_entradas": len(_cache_respostas_jarvis),
        "tempo_estimado_economia": len(_cache_respostas_jarvis) * 0.25,
    }
