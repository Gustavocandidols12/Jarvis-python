"""
FILE: memory.py
DESCRIPTION: Sistema de memória do JARVIS.
             Registra tudo que o JARVIS fala em um arquivo JSON local,
             com data, hora e tipo. Permite consultas como:
             "o que conversamos ontem?", "o que falamos hoje de manhã?", etc.
             O resumo é gerado pela Groq (mesmo cliente já usado no sistema).

COMO FUNCIONA:
    1. voice.py chama memory.registrar() a cada fala do JARVIS
    2. As entradas são salvas em ~/jarvis_memory.json
    3. Quando o usuário pergunta sobre o histórico, brain.py chama
       memory.resumir_periodo() que filtra as entradas e pede resumo à Groq

ESTRUTURA DE CADA ENTRADA NO JSON:
    {
        "timestamp": "2025-03-01T14:32:10",
        "data":      "2025-03-01",
        "hora":      "14:32",
        "diaSemana": "sábado",
        "tipo":      "jarvis",
        "texto":     "Timer de 10 minutos iniciado."
    }

INTEGRAÇÃO NECESSÁRIA:
    - voice.py  → chamar memory.registrar(texto) dentro de falar()
    - brain.py  → mapear intenção "memoria" para _voz_memoria
    - listen.py → adicionar intenção "memoria" com suas variações
"""

import json
import os
import datetime

# Adiciona no topo do memory.py
import locale
try:
    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
except:
    pass
# -----------------------------------------------------------------------
# CONFIGURAÇÕES
# -----------------------------------------------------------------------

# Arquivo onde as memórias ficam salvas
MEMORIA_ARQUIVO = os.path.join(os.path.dirname(__file__), "jarvis_memory.json")

# Máximo de entradas salvas — as mais antigas são removidas ao ultrapassar
MEMORIA_MAX_ENTRADAS = 2000

# Máximo de entradas enviadas ao Groq para resumo (evita estourar tokens)
MEMORIA_MAX_RESUMO   = 80

try:
    from config import GROQ_API_KEY, GROQ_MODELO
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    GROQ_API_KEY = ""
    GROQ_MODELO  = "llama-3.1-8b-instant"

# Dias da semana em português
_DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira",
                "quinta-feira", "sexta-feira", "sábado", "domingo"]

# -----------------------------------------------------------------------
# NÚCLEO — LEITURA E ESCRITA
# -----------------------------------------------------------------------

def _carregar() -> list:
    """Carrega o arquivo JSON de memórias. Retorna lista vazia se não existe."""
    if not os.path.exists(MEMORIA_ARQUIVO):
        return []
    try:
        with open(MEMORIA_ARQUIVO, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _salvar(entradas: list):
    """Salva a lista de entradas no arquivo JSON."""
    if len(entradas) > MEMORIA_MAX_ENTRADAS:
        entradas = entradas[-MEMORIA_MAX_ENTRADAS:]
    try:
        with open(MEMORIA_ARQUIVO, "w", encoding="utf-8") as f:
            json.dump(entradas, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"[MEMORY] Erro ao salvar memória: {e}")


# -----------------------------------------------------------------------
# API PÚBLICA — REGISTRAR
# -----------------------------------------------------------------------

def registrar(texto: str, tipo: str = "jarvis"):
    """
    Registra uma fala no arquivo de memória.

    Chamado por voice.py dentro de falar() e falar_sincronizado().

    Parâmetros:
        texto — o texto que o JARVIS falou
        tipo  — quem falou ("jarvis" ou "usuario")
    """
    if not texto or not texto.strip():
        return

    agora      = datetime.datetime.now()
    dia_semana = _DIAS_SEMANA[agora.weekday()]

    entrada = {
        "timestamp": agora.strftime("%Y-%m-%dT%H:%M:%S"),
        "data":      agora.strftime("%Y-%m-%d"),
        "hora":      agora.strftime("%H:%M"),
        "diaSemana": dia_semana,
        "tipo":      tipo,
        "texto":     texto.strip(),
    }

    entradas = _carregar()
    entradas.append(entrada)
    _salvar(entradas)


# -----------------------------------------------------------------------
# API PÚBLICA — CONSULTA POR PERÍODO
# -----------------------------------------------------------------------

def _data_alvo(referencia: str) -> str | None:
    """
    Converte uma referência textual em data no formato YYYY-MM-DD.
    Suporta: "hoje", "ontem", dia da semana, ou data explícita DD/MM.
    """
    hoje = datetime.date.today()
    ref  = referencia.lower().strip()

    if "hoje" in ref:
        return hoje.strftime("%Y-%m-%d")

    if "ontem" in ref:
        return (hoje - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    # Dia da semana → última ocorrência desse dia
    mapa_dia = {
        "segunda": 0, "terça": 1, "terca": 1, "quarta": 2,
        "quinta": 3, "sexta": 4, "sábado": 5, "sabado": 5, "domingo": 6
    }
    for nome, num in mapa_dia.items():
        if nome in ref:
            dias_atras = (hoje.weekday() - num) % 7
            if dias_atras == 0:
                dias_atras = 7  # força semana passada se for o dia atual
            alvo = hoje - datetime.timedelta(days=dias_atras)
            return alvo.strftime("%Y-%m-%d")

    # Data explícita DD/MM ou DD/MM/AAAA
    import re
    m = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", ref)
    if m:
        dia = int(m.group(1))
        mes = int(m.group(2))
        ano = int(m.group(3)) if m.group(3) else hoje.year
        try:
            return datetime.date(ano, mes, dia).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


def _filtrar_por_hora(entradas: list, referencia: str) -> list:
    """
    Filtra entradas por período do dia se mencionado no texto.
    manhã=06-12 | tarde=12-18 | noite=18-24 | madrugada=00-06
    """
    ref = referencia.lower()
    if "manhã" in ref or "manha" in ref:
        return [e for e in entradas if 6  <= int(e["hora"].split(":")[0]) < 12]
    if "tarde" in ref:
        return [e for e in entradas if 12 <= int(e["hora"].split(":")[0]) < 18]
    if "noite" in ref:
        return [e for e in entradas if 18 <= int(e["hora"].split(":")[0]) < 24]
    if "madrugada" in ref:
        return [e for e in entradas if      int(e["hora"].split(":")[0]) <  6]
    return entradas


def buscar_entradas(texto_consulta: str) -> list:
    """
    Filtra as entradas de memória com base no texto da consulta.
    Extrai data e período do dia automaticamente.
    """
    data_alvo = _data_alvo(texto_consulta)
    entradas  = _carregar()

    if not entradas:
        return []

    if data_alvo:
        entradas = [e for e in entradas if e.get("data") == data_alvo]
    else:
        entradas = entradas[-50:]  # sem data → últimas 50 entradas

    entradas = _filtrar_por_hora(entradas, texto_consulta)
    return entradas[-MEMORIA_MAX_RESUMO:]


# -----------------------------------------------------------------------
# API PÚBLICA — RESUMO VIA GROQ
# -----------------------------------------------------------------------

_groq_client = None

def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


def resumir_periodo(texto_consulta: str) -> str:
    """
    Busca as entradas relevantes e pede um resumo à Groq.
    Retorna string pronta para ser falada pelo JARVIS.

    BLOQUEANTE — sempre chame em thread separada no brain.py.

    Parâmetros:
        texto_consulta — transcrição original do usuário
    """
    entradas = buscar_entradas(texto_consulta)

    if not entradas:
        data_alvo = _data_alvo(texto_consulta)
        if data_alvo:
            d        = datetime.datetime.strptime(data_alvo, "%Y-%m-%d")
            data_fmt = d.strftime("%d de %B").lstrip("0")
            return f"Não encontrei nenhum registro para {data_fmt}, senhor."
        return "Não encontrei registros para o período solicitado, senhor."

    # Monta bloco de histórico
    linhas = [f"[{e['hora']}] {e['tipo'].upper()}: {e['texto']}" for e in entradas]
    historico = "\n".join(linhas)

    data_alvo = _data_alvo(texto_consulta)
    if data_alvo:
        d        = datetime.datetime.strptime(data_alvo, "%Y-%m-%d")
        data_fmt = d.strftime("%A, %d de %B").capitalize()
    else:
        data_fmt = "período recente"

    prompt = (
        f"Abaixo estão os registros de conversa do JARVIS em {data_fmt}.\n"
        f"Faça um resumo conciso do que foi conversado, destacando os principais assuntos.\n"
        f"Fale como o JARVIS falaria: direto, sem markdown, sem bullets, no máximo 5 frases com de toque de bom humor.\n"
        f"Se houver poucos registros, mencione brevemente o que houve.\n\n"
        f"REGISTROS:\n{historico}"
    )

    try:
        cliente  = _get_groq()
        resposta = cliente.chat.completions.create(
            model=GROQ_MODELO,
            messages=[
                {"role": "system", "content": "Você é JARVIS. Responda em português, de forma concisa e sem markdown."},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.5,
            max_tokens=300,
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        print(f"[MEMORY] Erro ao chamar Groq: {e}")
        return f"Encontrei {len(entradas)} registros, mas não consegui gerar o resumo agora, senhor."


# -----------------------------------------------------------------------
# UTILITÁRIOS
# -----------------------------------------------------------------------

def total_entradas() -> int:
    """Retorna o número total de entradas salvas."""
    return len(_carregar())


def limpar_memoria():
    """Apaga todo o histórico. Use com cautela."""
    if os.path.exists(MEMORIA_ARQUIVO):
        os.remove(MEMORIA_ARQUIVO)
        print("[MEMORY] Memória apagada.")