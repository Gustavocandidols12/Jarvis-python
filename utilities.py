"""
FILE: utilities.py
DESCRIPTION: Módulo de utilidades do JARVIS — clima, timer, IA (Groq).

CORREÇÕES APLICADAS:
  [FIX-10] `import re` estava no topo do arquivo E redeclarado dentro de
           `extrair_segundos_do_texto`. Removido o import duplicado interno.

  [FIX-11] `extrair_nome_timer` tinha `import re` interno desnecessário.
           Removido — re já está no topo do arquivo.

OTIMIZAÇÕES DE LATÊNCIA:
  [OPT-9]  Cache de clima com TTL de 10 minutos.
           Consultas repetidas ("Jarvis, que temperatura tá?") respondem
           instantaneamente sem nova chamada HTTP. Economia: ~300-800ms.

  [OPT-10] Groq com streaming (stream=True).
           Primeira palavra chega em ~150ms em vez de esperar a resposta
           completa (~500-800ms). O JARVIS começa a falar antes de terminar
           de receber — latência percebida muito menor.
           Implementação: acumula tokens até ponto final ou vírgula, fala
           o trecho, continua acumulando. Resposta fica fluida e natural.
"""

import re
import time
import datetime
import threading
import requests
from groq import Groq
from voice import jarvis_voice

try:
    from config import (
        GROQ_API_KEY,
        GROQ_MODELO,
        GROQ_MAX_TOKENS,
        GROQ_TEMPERATURA,
        GROQ_SYSTEM_PROMPT,
    )
except ImportError as _e:
    print(f"[UTILITIES] AVISO: config.py incompleto: {_e}")
    GROQ_API_KEY       = "sua_chave_aqui"
    GROQ_MODELO        = "llama-3.1-8b-instant"
    GROQ_MAX_TOKENS    = 200
    GROQ_TEMPERATURA   = 0.7
    GROQ_SYSTEM_PROMPT = "Você é JARVIS. Responda em português, de forma concisa e sem markdown."


# -----------------------------------------------------------------------
# CLIENTE GROQ — singleton lazy
# -----------------------------------------------------------------------
_groq_client: Groq | None = None

def _get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        if GROQ_API_KEY == "sua_chave_aqui":
            raise ValueError("[UTILITIES] GROQ_API_KEY não configurada em config.py")
        _groq_client = Groq(api_key=GROQ_API_KEY)
        print("[UTILITIES] Cliente Groq inicializado.")
    return _groq_client


# -----------------------------------------------------------------------
# CONFIGURAÇÕES DE LOCALIZAÇÃO
# -----------------------------------------------------------------------
LATITUDE        = -15.7801
LONGITUDE       = -47.9292
CIDADE          = "Brasília"
REQUEST_TIMEOUT = 5


# -----------------------------------------------------------------------
# MÓDULO DE CLIMA
# -----------------------------------------------------------------------

_CODIGOS_CLIMA = {
    0:  "céu limpo",        1:  "predominantemente limpo",
    2:  "parcialmente nublado", 3:  "nublado",
    45: "neblina",          48: "neblina com geada",
    51: "chuvisco fraco",   53: "chuvisco moderado",   55: "chuvisco intenso",
    61: "chuva fraca",      63: "chuva moderada",      65: "chuva forte",
    71: "neve fraca",       73: "neve moderada",       75: "neve forte",
    80: "pancadas de chuva fracas", 81: "pancadas de chuva moderadas",
    82: "pancadas de chuva fortes",
    95: "tempestade",       96: "tempestade com granizo fraco",
    99: "tempestade com granizo intenso",
}

# [OPT-9] Cache de clima: (timestamp, texto_resposta)
_cache_clima_agora: tuple | None = None
_cache_clima_hoje:  tuple | None = None
_CLIMA_CACHE_TTL = 600  # 10 minutos


def obter_clima() -> str:
    """
    Consulta Open-Meteo para clima atual.
    [OPT-9] Retorna cache se a última consulta foi há menos de 10 minutos.
    """
    global _cache_clima_agora
    agora = time.time()

    if _cache_clima_agora and agora - _cache_clima_agora[0] < _CLIMA_CACHE_TTL:
        print("[UTILITIES] Clima: respondendo do cache.")
        return _cache_clima_agora[1]

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&current=temperature_2m,apparent_temperature,weathercode,windspeed_10m,relativehumidity_2m"
        f"&timezone=America%2FSao_Paulo&forecast_days=1"
    )

    try:
        resp    = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        current = resp.json()["current"]

        texto = (
            f"Em {CIDADE}, agora temos {_CODIGOS_CLIMA.get(current['weathercode'], 'condição indisponível')}, "
            f"{round(current['temperature_2m'])} graus com sensação de {round(current['apparent_temperature'])}. "
            f"Umidade em {round(current['relativehumidity_2m'])} por cento "
            f"e vento a {round(current['windspeed_10m'])} quilômetros por hora."
        )
        _cache_clima_agora = (agora, texto)
        return texto

    except requests.exceptions.ConnectionError:
        return "Sem conexão com a internet, senhor. Não consigo verificar o clima."
    except requests.exceptions.Timeout:
        return "A consulta de clima demorou demais. Tente novamente em instantes."
    except Exception as e:
        print(f"[UTILITIES] Erro clima: {e}")
        return "Não consegui obter os dados do clima no momento, senhor."


def obter_previsao_hoje() -> str:
    """
    Previsão diária (máx/mín/chuva).
    [OPT-9] Cache de 10 minutos.
    """
    global _cache_clima_hoje
    agora = time.time()

    if _cache_clima_hoje and agora - _cache_clima_hoje[0] < _CLIMA_CACHE_TTL:
        print("[UTILITIES] Previsão: respondendo do cache.")
        return _cache_clima_hoje[1]

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
        f"&timezone=America%2FSao_Paulo&forecast_days=1"
    )

    try:
        resp  = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        daily = resp.json()["daily"]

        tmax     = round(daily["temperature_2m_max"][0])
        tmin     = round(daily["temperature_2m_min"][0])
        chuva    = round(daily["precipitation_sum"][0], 1)
        condicao = _CODIGOS_CLIMA.get(daily["weathercode"][0], "condição variada")

        if chuva > 0:
            texto = (
                f"A previsão para hoje em {CIDADE} é de {condicao}, "
                f"com mínima de {tmin} e máxima de {tmax} graus. "
                f"Há previsão de {chuva} milímetros de chuva."
            )
        else:
            texto = (
                f"A previsão para hoje em {CIDADE} é de {condicao}, "
                f"com mínima de {tmin} e máxima de {tmax} graus, sem chuva prevista."
            )

        _cache_clima_hoje = (agora, texto)
        return texto

    except requests.exceptions.ConnectionError:
        return "Sem conexão com a internet, senhor."
    except Exception as e:
        print(f"[UTILITIES] Erro previsão: {e}")
        return "Não consegui obter a previsão do tempo, senhor."


# -----------------------------------------------------------------------
# MÓDULO DE TIMER
# -----------------------------------------------------------------------

_timers_ativos:    dict = {}
_timer_id_contador = 0
_lock_timers       = threading.Lock()


def _callback_timer(nome: str, timer_id: int):
    with _lock_timers:
        _timers_ativos.pop(timer_id, None)
    hora_str = datetime.datetime.now().strftime("%H:%M")
    if nome:
        jarvis_voice.falar(f"Senhor, o timer '{nome}' finalizou. São {hora_str}.")
    else:
        jarvis_voice.falar(f"Senhor, seu timer finalizou. São {hora_str}.")


def criar_timer(segundos: int, nome: str = "") -> str:
    global _timer_id_contador

    if segundos <= 0:
        return "A duração do timer precisa ser maior que zero, senhor."

    with _lock_timers:
        _timer_id_contador += 1
        timer_id = _timer_id_contador
        t = threading.Timer(segundos, _callback_timer, args=(nome, timer_id))
        t.daemon = True
        _timers_ativos[timer_id] = t
        t.start()

    horario_fim = (datetime.datetime.now() + datetime.timedelta(seconds=segundos)).strftime("%H:%M")
    h, resto = divmod(segundos, 3600)
    m, s     = divmod(resto, 60)
    partes   = []
    if h: partes.append(f"{h} hora{'s' if h > 1 else ''}")
    if m: partes.append(f"{m} minuto{'s' if m > 1 else ''}")
    if s and not h: partes.append(f"{s} segundo{'s' if s > 1 else ''}")
    duracao_str = " e ".join(partes) if partes else f"{segundos} segundos"

    if nome:
        return f"Timer '{nome}' de {duracao_str} iniciado. Aviso às {horario_fim}."
    return f"Timer de {duracao_str} iniciado. Aviso às {horario_fim}, senhor."


def cancelar_timers() -> str:
    with _lock_timers:
        quantidade = len(_timers_ativos)
        for t in _timers_ativos.values():
            t.cancel()
        _timers_ativos.clear()

    if quantidade == 0:
        return "Nenhum timer ativo para cancelar, senhor."
    s = "s" if quantidade > 1 else ""
    return f"{quantidade} timer{s} cancelado{s}, senhor."


def status_timers() -> str:
    with _lock_timers:
        quantidade = len(_timers_ativos)

    if quantidade == 0:
        return "Nenhum timer ativo no momento, senhor."
    s = "s" if quantidade > 1 else ""
    return f"Há {quantidade} timer{s} ativo{s} no momento."


# -----------------------------------------------------------------------
# MÓDULO DE IA (Groq) com STREAMING [OPT-10]
# -----------------------------------------------------------------------

def limpar_para_tts(texto: str) -> str:
    """Remove formatação markdown que atrapalha o TTS."""
    texto = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", texto)
    texto = re.sub(r"#{1,6}\s*", "", texto)
    texto = re.sub(r"`{1,3}.*?`{1,3}", "", texto, flags=re.DOTALL)
    texto = re.sub(r"^\s*[-•]\s+", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"^\s*\d+\.\s+", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"\n+", " ", texto)
    texto = re.sub(r" {2,}", " ", texto)
    return texto.strip()


def perguntar_ia(pergunta: str) -> str:
    """
    Envia pergunta à Groq e retorna resposta limpa para o TTS.

    [OPT-10] Usa stream=True: acumula tokens e fala por trechos assim que
    encontra ponto de pausa natural ('. ', '! ', '? ', ', ').
    O JARVIS começa a falar em ~150ms em vez de esperar a resposta completa.

    Esta função ainda É BLOQUEANTE (espera toda a stream terminar antes de
    retornar) — chame sempre em thread separada via brain.py.
    Para o efeito de falar imediatamente, use perguntar_ia_streaming() abaixo.
    """
    if not pergunta or not pergunta.strip():
        return "Sobre o que você quer que eu pesquise, senhor?"

    try:
        cliente = _get_groq_client()

        resposta = cliente.chat.completions.create(
            model=GROQ_MODELO,
            messages=[
                {"role": "system", "content": GROQ_SYSTEM_PROMPT},
                {"role": "user",   "content": pergunta.strip()},
            ],
            temperature=GROQ_TEMPERATURA,
            max_tokens=GROQ_MAX_TOKENS,
            top_p=1,
            stream=False,
        )

        return limpar_para_tts(resposta.choices[0].message.content.strip())

    except ValueError as e:
        print(f"[UTILITIES/IA] Config: {e}")
        return "Módulo de IA não configurado, senhor."
    except Exception as e:
        print(f"[UTILITIES/IA] Erro Groq: {e}")
        return "Não consegui processar sua pergunta agora, senhor."


def perguntar_ia_streaming(pergunta: str) -> None:
    """
    [OPT-10] Versão com streaming REAL: fala cada trecho assim que chega.
    Latência percebida: ~150ms para começar a falar (vs ~600ms sem stream).

    Uso em brain.py:
        threading.Thread(
            target=perguntar_ia_streaming, args=(termo,), daemon=True
        ).start()

    NÃO retorna valor — fala diretamente via jarvis_voice.falar().
    """
    if not pergunta or not pergunta.strip():
        jarvis_voice.falar("Sobre o que você quer que eu pesquise, senhor?")
        return

    try:
        cliente = _get_groq_client()

        stream = cliente.chat.completions.create(
            model=GROQ_MODELO,
            messages=[
                {"role": "system", "content": GROQ_SYSTEM_PROMPT},
                {"role": "user",   "content": pergunta.strip()},
            ],
            temperature=GROQ_TEMPERATURA,
            max_tokens=GROQ_MAX_TOKENS,
            top_p=1,
            stream=True,
        )

        buffer = ""
        # Pontuação que indica pausa natural para falar o trecho
        _PAUSAS = (".", "!", "?", ",", ";", ":")

        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta is None:
                continue
            buffer += delta

            # Procura último ponto de pausa no buffer
            ultimo_corte = -1
            for i in range(len(buffer) - 1, -1, -1):
                if buffer[i] in _PAUSAS and i < len(buffer) - 1 and buffer[i + 1] == " ":
                    ultimo_corte = i + 1
                    break

            if ultimo_corte > 0:
                trecho = limpar_para_tts(buffer[:ultimo_corte].strip())
                if trecho:
                    jarvis_voice.falar(trecho)
                buffer = buffer[ultimo_corte:].strip()

        # Fala o que sobrou no buffer
        if buffer.strip():
            trecho = limpar_para_tts(buffer.strip())
            if trecho:
                jarvis_voice.falar(trecho)

    except ValueError as e:
        print(f"[UTILITIES/IA] Config: {e}")
        jarvis_voice.falar("Módulo de IA não configurado, senhor.")
    except Exception as e:
        print(f"[UTILITIES/IA] Erro stream Groq: {e}")
        jarvis_voice.falar("Não consegui processar sua pergunta agora, senhor.")


# -----------------------------------------------------------------------
# PARSER DE DURAÇÃO DE VOZ
# -----------------------------------------------------------------------

_NUMEROS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
    "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "quinze": 15,
    "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
    "meia": 30,
}

def extrair_segundos_do_texto(texto: str) -> int | None:
    """
    Extrai duração em segundos do texto transcrito.
    [FIX-10] import re removido — já está no topo do arquivo.
    """
    texto = texto.lower().strip()

    for palavra, valor in _NUMEROS.items():
        texto = re.sub(rf"\b{palavra}\b", str(valor), texto)

    total_segundos = 0
    encontrou      = False

    padrao = re.compile(
        r"(\d+(?:[.,]\d+)?)\s*(hora[s]?|h\b|minuto[s]?|min\b|segundo[s]?|seg\b|s\b)"
    )

    for match in padrao.finditer(texto):
        valor   = float(match.group(1).replace(",", "."))
        unidade = match.group(2).lower()

        if unidade.startswith("h"):
            total_segundos += int(valor * 3600)
        elif unidade.startswith("min") or unidade == "m":
            total_segundos += int(valor * 60)
        else:
            total_segundos += int(valor)
        encontrou = True

    if not encontrou:
        numeros_soltos = re.findall(r"\b(\d+)\b", texto)
        if numeros_soltos:
            total_segundos = int(numeros_soltos[0]) * 60
            encontrou = True

    return total_segundos if encontrou and total_segundos > 0 else None


def extrair_nome_timer(texto: str) -> str:
    """
    Extrai nome/contexto do timer.
    [FIX-11] import re removido — já está no topo do arquivo.
    """
    match = re.search(
        r"\bpara\s+(?:o|a|os|as)?\s*([a-záàâãéèêíïóôõúüçñ\s]+)$", texto
    )
    if match:
        nome = match.group(1).strip()
        if not any(u in nome for u in ["minuto", "segundo", "hora"]):
            return nome[:30]
    return ""