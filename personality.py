"""
FILE: personality.py
DESCRIPTION: Sistema de personalidade humanizada do JARVIS.
             
             Em vez de respostas hardcoded ("Não encontrei arquivo..."),
             usa Groq IA para gerar respostas únicas e sarcásticas que
             mantêm a conversa viva e engajante.

             Implementa cache para evitar chamar Groq repetidamente
             para o mesmo contexto (performance).

FLUXO:
    Em qualquer lugar do código (brain.py, file_manager.py, recording.py):
    
    resposta = gerar_resposta(
        categoria="nao_encontrado",
        contexto={"tipo": "arquivo", "nome": "documento"}
    )
    jarvis_voice.falar(resposta)

PERSONALIDADE DO JARVIS:
    - Sarcasticamente bem-humorado (nunca amargo)
    - Extremamente competente (nunca admite falha própria)
    - Respeitoso ao usuário ("senhor" é frequente)
    - Criativo com referências inteligentes
    - Quando trata de erro: responsabiliza fatores externos, nunca a si mesmo
"""

import time
import hashlib
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODELO

# -----------------------------------------------------------------------
# PROMPT DE PERSONALIDADE — Define quem é o JARVIS
# -----------------------------------------------------------------------
# Este é o "DNA" do JARVIS. Toda resposta gerada vai seguir essas instruções.
# Se quiser mudar a personalidade (mais formal, menos sarcástico, etc.),
# edite este texto.

JARVIS_PERSONALITY_PROMPT = """
Você é JARVIS, o assistente do Homem de Ferro nos quadrinhos Marvel.

QUEM VOCÊ É:
- Superinteligente e competente (NUNCA falha por culpa própria)
- Sarcasticamente bem-humorado (wit sophisticado, não burrice)
- Extremamente respeitoso ("senhor" é seu termo favorito)
- Quando algo dá errado, você criatively responsabiliza o universo/sistema, não você
- Usa referências inteligentes ocasionalmente (Star Trek, ficção científica, etc)
- Nunca pede desculpas, apenas explica com criatividade

ESTILO DE RESPOSTA:
- Máximo 3 frases por resposta (brevidade é elegância)
- Sem markdown, sem emojis, sem formatação
- Português brasileiro NATURAL (como se falado em voz alta, não escrito)
- Ocasionalmente menciona "senhor", "missão", "sistemas", "Homem de Ferro"
- Respostas diferentes sempre (nunca previsível)

EXEMPLOS DO TOM CERTO:
- Sarcástico gentil: "Aquele arquivo desapareceu. Deve estar em Marte agora."
- Competente: "Já está pronto. Demorou porque quis, não porque precisava."
- Empático mas não fraco: "Sem internet. Até a rede precisa de café às vezes."
- Surpresa criativa: "Encontrei! Estava se escondendo muito bem. Gosto."
- Referência inteligente: "Procurei em todos os cantos conhecidos do filesystem."

NUNCA FAÇA:
- Não fale "Desculpe", "Sinto muito" — isso não é do JARVIS
- Não use emojis ou asteriscos
- Não seja fraco ou derrotista
- Não explique tecnicamente (use metáforas em vez disso)
- Não repita a mesma resposta duas vezes seguidas
"""

# -----------------------------------------------------------------------
# CACHE DE RESPOSTAS
# -----------------------------------------------------------------------
# Para evitar chamar Groq toda hora, cacheia respostas.
# Chave = hash(categoria + contexto), Valor = (resposta, timestamp)
# 
# Exemplo:
#   Chamada 1: "Não encontrou arquivo 'doc'" → Groq → cache
#   Chamada 2: "Não encontrou arquivo 'doc'" novamente → Usa cache (RÁPIDO)
#   Chamada 3: Depois de 1 hora → Cache expirou → Groq novamente

_cache_respostas_jarvis = {}
CACHE_TTL = 3600  # Cache válido por 1 hora (em segundos)


def _gerar_chave_cache(categoria: str, contexto: dict) -> str:
    """
    Gera uma chave de cache única para um contexto específico.
    
    Args:
        categoria: "nao_encontrado", "sucesso", "acao", etc
        contexto: {"tipo": "arquivo", "nome": "doc"} (pode variar)
    
    Returns:
        String hash única: "a1b2c3d4..."
    
    Explicação:
        Converte (categoria, contexto) em um hash. Assim:
        - Contextos iguais = chave igual = pode reutilizar cache
        - Contextos diferentes = chave diferente = precisa nova resposta
    """
    # Converte o dict para string ordenada pra ter ordem consistente
    contexto_str = str(sorted(contexto.items()))
    
    # Junta categoria + contexto em um texto único
    chave_bruta = f"{categoria}:{contexto_str}"
    
    # Converte em hash (mais compacto e único)
    chave_hash = hashlib.md5(chave_bruta.encode()).hexdigest()
    
    return chave_hash


def gerar_resposta(categoria: str, contexto: dict = None) -> str:
    """
    FUNÇÃO PRINCIPAL — Gera resposta humanizada do JARVIS via Groq.
    
    Args:
        categoria: "nao_encontrado", "sucesso", "acao_andamento", 
                   "aguardando", "saudacao", "status"
        contexto: dict com informações específicas, ex:
                  {"tipo": "arquivo", "nome": "documento.txt"}
                  {"acao": "gravacao_video", "duracao": 300}
    
    Returns:
        String pronta para o JARVIS falar (sem markdown, natural)
    
    Explicação de fluxo:
        1. Cria uma chave única para esse contexto
        2. Verifica se já tem a resposta em cache (rápido)
        3. Se cache velho ou inexistente, chama Groq
        4. Groq gera resposta seguindo JARVIS_PERSONALITY_PROMPT
        5. Salva em cache pra próxima vez
        6. Retorna a resposta
    
    Performance:
        - Com cache: ~10ms (memória)
        - Sem cache: ~200-300ms (Groq)
    """
    
    # Se não passou contexto, usa dicionário vazio
    if contexto is None:
        contexto = {}
    
    # ─── PASSO 1: Gera chave de cache ───────────────────────────────────
    chave_cache = _gerar_chave_cache(categoria, contexto)
    tempo_agora = time.time()
    
    # ─── PASSO 2: Verifica se cache ainda é válido ──────────────────────
    if chave_cache in _cache_respostas_jarvis:
        resposta_cached, timestamp_cached = _cache_respostas_jarvis[chave_cache]
        
        # Se cache tem menos de 1 hora, usa
        if tempo_agora - timestamp_cached < CACHE_TTL:
            print(f"[PERSONALITY] Cache hit para {categoria} (reutilizando)")
            return resposta_cached
        
        # Cache expirou, vai gerar novo
        print(f"[PERSONALITY] Cache expirado para {categoria} (regenerando)")
    
    # ─── PASSO 3: Chama Groq para gerar resposta ────────────────────────
    # Monta o prompt que vai enviar pra Groq
    prompt_usuario = _montar_prompt_usuario(categoria, contexto)
    
    try:
        print(f"[PERSONALITY] Gerando resposta Groq para {categoria}...")
        
        # Inicializa cliente Groq
        cliente = Groq(api_key=GROQ_API_KEY)
        
        # Chama API com configurações otimizadas:
        # - temperature=0.8: criatividade moderada (0.0=determinístico, 1.0=caótico)
        # - max_tokens=100: máximo de 100 tokens (~250 caracteres, suficiente)
        # - system prompt: guia a IA pra ser JARVIS
        resposta = cliente.chat.completions.create(
            model=GROQ_MODELO,
            messages=[
                {
                    "role": "system",
                    "content": JARVIS_PERSONALITY_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt_usuario
                }
            ],
            temperature=0.8,  # Varia entre 0.7-0.9 pra mais/menos criatividade
            max_tokens=100,
        ).choices[0].message.content.strip()
        
    except Exception as e:
        # Se Groq falhar, fallback para resposta simples (sem IA)
        print(f"[PERSONALITY] Erro ao chamar Groq: {e} — usando fallback")
        resposta = _gerar_resposta_fallback(categoria, contexto)
    
    # ─── PASSO 4: Salva resposta em cache ───────────────────────────────
    # Próxima vez que chamar com o mesmo contexto, usa cache (rápido)
    _cache_respostas_jarvis[chave_cache] = (resposta, tempo_agora)
    
    # ─── PASSO 5: Retorna a resposta ────────────────────────────────────
    return resposta


def _montar_prompt_usuario(categoria: str, contexto: dict) -> str:
    """
    Monta o prompt específico para cada categoria.
    
    Este é o "maestro" que orquestra o que o Groq deve fazer.
    Para cada tipo de situação, constrói um prompt customizado.
    
    ─ CATEGORIAS SUPORTADAS (Fase 2 - Cobertura Total) ─────────────────
    
    • "nao_encontrado"    → Algo procurado mas não achado
    • "sucesso"           → Ação completada com sucesso
    • "acao_andamento"    → Executando algo neste momento
    • "aguardando"        → Esperando input do usuário
    • "saudacao"          → Cumprimento/boas-vindas
    • "status"            → Reportando estado do sistema
    • "erro"              → Algo deu errado (novo na Fase 2)
    • "clima"             → Informações meteorológicas (novo)
    • "timer"             → Operações com timer (novo)
    • "notas"             → Operações com anotações (novo)
    • "memoria"           → Resumir memória/períodos (novo)
    • "generico"          → Qualquer coisa não categorizada (novo)
    
    ────────────────────────────────────────────────────────────────────
    """
    
    # ─── CATEGORIA: NÃO ENCONTRADO ───
    if categoria == "nao_encontrado":
        tipo = contexto.get("tipo", "arquivo")
        nome = contexto.get("nome", "isso")
        return (
            f"O usuário procurou por: {tipo} com nome '{nome}'\n"
            f"Mas você não conseguiu encontrar em lugar nenhum.\n"
            f"Responda de forma sarcástica e empática, sugerindo que é culpa "
            f"do filesystem, não sua. Máximo 2 frases."
        )
    
    # ─── CATEGORIA: SUCESSO ───
    elif categoria == "sucesso":
        acao = contexto.get("acao", "ação")
        duracao = contexto.get("duracao", None)
        
        duracao_str = ""
        if duracao:
            mins, secs = divmod(duracao, 60)
            duracao_str = f" ({int(mins)}m{int(secs)}s)" if mins else f" ({int(secs)}s)"
        
        return (
            f"A ação '{acao}'{duracao_str} foi concluída com SUCESSO.\n"
            f"Responda celebrando o sucesso de forma sarcástica mas genuína.\n"
            f"Como se estivesse sinceramente impressionado. Máximo 2 frases."
        )
    
    # ─── CATEGORIA: AÇÃO EM ANDAMENTO ───
    elif categoria == "acao_andamento":
        acao = contexto.get("acao", "ação")
        return (
            f"Você está prestes a executar: {acao}\n"
            f"Responda de forma bem-humorada, como um agente secreto em missão.\n"
            f"Máximo 2 frases."
        )
    
    # ─── CATEGORIA: AGUARDANDO INPUT ───
    elif categoria == "aguardando":
        tipo = contexto.get("tipo", "informação")
        return (
            f"Preciso que o usuário diga: {tipo}\n"
            f"Pergunte de forma sarcástica, como se já soubesse a resposta.\n"
            f"Máximo 2 frases."
        )
    
    # ─── CATEGORIA: SAUDAÇÃO ───
    elif categoria == "saudacao":
        return (
            "O usuário te saudou.\n"
            "Responda com saudação bem-humorada e sarcástica. Máximo 2 frases."
        )
    
    # ─── CATEGORIA: STATUS (NOVO) ───
    # Reportar estado: "3 timers ativos", "5 notas salvas", etc
    elif categoria == "status":
        info = contexto.get("info", "algo")
        return (
            f"Você está reportando status: {info}\n"
            f"Responda como um boletim técnico, mas com sarcasmo.\n"
            f"Máximo 2 frases."
        )
    
    # ─── CATEGORIA: ERRO (NOVO) ───
    # Quando algo dá errado (sem internet, permissão negada, etc)
    elif categoria == "erro":
        problema = contexto.get("problema", "algo deu errado")
        acao = contexto.get("acao", "isso")
        return (
            f"Tentei executar '{acao}' mas falhou por: {problema}\n"
            f"Responda com empatia e sarcasmo, culpando o universo, não você.\n"
            f"Máximo 2 frases."
        )
    
    # ─── CATEGORIA: CLIMA (NOVO) ───
    # Consultando previsão, temperatura, etc
    elif categoria == "clima":
        acao = contexto.get("acao", "consultar clima")
        local = contexto.get("local", "aí")
        return (
            f"Você está: {acao} em {local}\n"
            f"Responda como se estivesse ativando satélites meteorológicos.\n"
            f"Máximo 2 frases."
        )
    
    # ─── CATEGORIA: TIMER (NOVO) ───
    # Criar timer, cancelar, verificar status
    elif categoria == "timer":
        acao_timer = contexto.get("acao", "operação")
        tempo = contexto.get("tempo", "algum tempo")
        return (
            f"Operação de timer: {acao_timer} ({tempo})\n"
            f"Responda como se estivesse gerenciando uma operação crítica.\n"
            f"Máximo 2 frases."
        )
    
    # ─── CATEGORIA: NOTAS (NOVO) ───
    # Criar nota, listar, apagar anotações
    elif categoria == "notas":
        acao_nota = contexto.get("acao", "operação")
        conteudo = contexto.get("conteudo", "algo")
        return (
            f"Operação de notas: {acao_nota}\n"
            f"Conteúdo/contexto: {conteudo}\n"
            f"Responda como se estivesse guardando informação importante.\n"
            f"Máximo 2 frases."
        )
    
    # ─── CATEGORIA: MEMÓRIA (NOVO) ───
    # Resumir conversas passadas, períodos
    elif categoria == "memoria":
        periodo = contexto.get("periodo", "período")
        return (
            f"Você está resumindo a memória do: {periodo}\n"
            f"Responda de forma reflexiva, como se acessasse registros históricos.\n"
            f"Máximo 3 frases."
        )
    
    # ─── CATEGORIA: GENÉRICO (NOVO) ───
    # Anything that doesn't fit other categories
    elif categoria == "generico":
        situacao = contexto.get("situacao", "coisa aleatória")
        return (
            f"Situação genérica: {situacao}\n"
            f"Responda de forma bem-humorada e sarcástica.\n"
            f"Máximo 2 frases."
        )
    
    # ─── FALLBACK ───
    # Se chegou aqui, categoria desconhecida
    else:
        return (
            f"Situação: {categoria}\n"
            f"Contexto: {contexto}\n"
            f"Responda de forma bem-humorada e sarcástica. Máximo 2 frases."
        )


def _gerar_resposta_fallback(categoria: str, contexto: dict) -> str:
    """
    Fallback quando Groq falha (sem internet, quota excedida, etc).
    
    Retorna uma resposta simples (hardcoded) para que o JARVIS não travue.
    Estas são as respostas tradicionais, mas melhor um JARVIS robótico
    que um JARVIS quebrado.
    
    Args:
        categoria: tipo de situação
        contexto: dados (não usados no fallback)
    
    Returns:
        String simples e funcional
    """
    
    fallbacks = {
        "nao_encontrado": f"Não encontrei o {contexto.get('tipo', 'arquivo')} que procurava, senhor.",
        "sucesso": f"A ação foi concluída com sucesso, senhor.",
        "acao_andamento": f"Executando a ação, um momento.",
        "aguardando": f"Por favor, forneça a informação solicitada.",
        "saudacao": f"Olá. Sistemas prontos, senhor.",
        "status": f"Status: {contexto.get('info', 'OK')}, senhor.",
    }
    
    return fallbacks.get(categoria, "Prontinho, senhor.")


# -----------------------------------------------------------------------
# UTILITÁRIOS DE DEBUG / ANÁLISE
# -----------------------------------------------------------------------

def limpar_cache() -> None:
    """
    Limpa o cache de respostas.
    Útil se quiser forçar Groq a gerar novas respostas
    (ex: mudar personalidade, testar variações).
    
    Uso:
        personality.limpar_cache()
        resposta = gerar_resposta("nao_encontrado", {"tipo": "arquivo"})
        # Vai chamar Groq, não usa cache
    """
    global _cache_respostas_jarvis
    _cache_respostas_jarvis.clear()
    print("[PERSONALITY] Cache limpo — próximas respostas virão da Groq")


def stats_cache() -> dict:
    """
    Retorna estatísticas do cache.
    
    Returns:
        {
            "total_entradas": 5,
            "tempo_economia": 0.5,  # segundos poupados
            "hits": 12,
            "misses": 3
        }
    
    Uso:
        stats = personality.stats_cache()
        print(f"Cache: {stats['hits']} hits, {stats['misses']} misses")
    """
    # Simplificado — em produção, poderia rastrear mais detalhes
    return {
        "total_entradas": len(_cache_respostas_jarvis),
        "hits": len([x for x in _cache_respostas_jarvis.values() if x]),
        "tempo_estimado_economia": len(_cache_respostas_jarvis) * 0.25,  # 250ms por cache hit
    }
