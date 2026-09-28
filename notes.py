"""
FILE: notes.py
DESCRIPTION: Sistema de anotações do JARVIS.
             Gerencia dois tipos de entrada:
             - "nota"      → anotação simples, salva e consultável
             - "lembrete"  → anotação com horário, dispara aviso no horário certo

COMO FUNCIONA:
    - Anotações ficam em jarvis_notes.json (pasta do projeto)
    - brain.py chama as funções deste módulo via intenções de voz
    - Lembretes usam threading.Timer igual ao sistema de timers existente
    - Apagar usa Groq para identificar qual nota remover por palavras-chave

ESTRUTURA DE CADA NOTA NO JSON:
    {
        "id":        "note_1709123456",
        "tipo":      "nota" | "lembrete",
        "texto":     "criar novo módulo de expressão facial",
        "criado_em": "2025-03-01T14:32:10",
        "data":      "2025-03-01",
        "hora":      "14:32",
        "lembrar_as": "15:30"   (só para lembretes — None para notas)
    }

INTEGRAÇÃO:
    - brain.py  → importa e chama as funções deste módulo
    - listen.py → intenções: nota_criar, nota_lembrar, nota_listar, nota_apagar
"""

import json
import os
import re
import time
import datetime
import threading
from voice import jarvis_voice   # [BOOT-PERSIST] fala dos lembretes perdidos

try:
    from config import GROQ_API_KEY, GROQ_MODELO
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    GROQ_API_KEY = ""
    GROQ_MODELO  = "llama-3.3-70b-versatile"

# -----------------------------------------------------------------------
# CONFIGURAÇÕES
# -----------------------------------------------------------------------

NOTES_ARQUIVO    = os.path.join(os.path.dirname(__file__), "jarvis_notes.json")
NOTES_MAX        = 500

# Timers de lembretes ativos: {id_nota: threading.Timer}
_timers_lembretes: dict = {}
_lock_timers = threading.Lock()

# -----------------------------------------------------------------------
# NÚCLEO — LEITURA E ESCRITA
# -----------------------------------------------------------------------

def _carregar() -> list:
    if not os.path.exists(NOTES_ARQUIVO):
        return []
    try:
        with open(NOTES_ARQUIVO, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _salvar(notas: list):
    if len(notas) > NOTES_MAX:
        notas = notas[-NOTES_MAX:]
    try:
        with open(NOTES_ARQUIVO, "w", encoding="utf-8") as f:
            json.dump(notas, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"[NOTES] Erro ao salvar: {e}")


def _gerar_id() -> str:
    return f"note_{int(time.time())}"


# -----------------------------------------------------------------------
# PARSER DE HORÁRIO
# -----------------------------------------------------------------------

def _extrair_horario(texto: str) -> str | None:
    """
    Extrai horário do texto transcrito pelo Whisper.
    Suporta:
      - "às 15:30" / "as 15:30"
      - "às 3 da tarde" / "às 8 da manhã" / "às 10 da noite"
      - "às 22 horas" / "as 22"
      - Horários por extenso: "às vinte e uma horas", "às nove da manhã"
    Retorna string "HH:MM" ou None.

    CORREÇÃO: adicionado suporte a "as" sem acento (Whisper frequentemente
    transcreve "às" sem acento), extenso por escrito e melhor validação.
    """
    texto = texto.lower()

    # Mapa de números por extenso → inteiro (cobre horas 1–23)
    _EXTENSO = {
        "uma": 1, "um": 1, "duas": 2, "dois": 2, "três": 3, "tres": 3,
        "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
        "nove": 9, "dez": 10, "onze": 11, "doze": 12,
        "treze": 13, "catorze": 14, "quatorze": 14, "quinze": 15,
        "dezesseis": 16, "dezessete": 17, "dezoito": 18,
        "dezenove": 19, "vinte": 20, "vinte e uma": 21, "vinte e um": 21,
        "vinte e duas": 22, "vinte e dois": 22, "vinte e três": 23,
        "vinte e tres": 23, "meia-noite": 0, "meia noite": 0, "meio-dia": 12,
    }

    # 1) Formato HH:MM direto (ex: "15:30", "9:05")
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", texto)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"

    # 2) "às/as X da tarde/manhã/noite" com número
    m = re.search(
        r"\b(?:às?|as)\s+(\d{1,2})\s*(?:hora[s]?)?\s*da\s*(manhã|manha|tarde|noite|madrugada)",
        texto
    )
    if m:
        h = int(m.group(1))
        periodo = m.group(2)
        if ("tarde" in periodo or "noite" in periodo) and h != 12 and h < 12:
            h += 12
        elif ("manhã" in periodo or "manha" in periodo) and h == 12:
            h = 0
        elif "madrugada" in periodo and h >= 12:
            h = h - 12
        if 0 <= h <= 23:
            return f"{h:02d}:00"

    # 3) "às/as X horas" ou só "às X" no final da frase
    m = re.search(r"\b(?:às?|as)\s+(\d{1,2})\s*(?:horas?)?\b", texto)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"

    # 4) Número por extenso com período: "às nove da manhã", "às vinte e uma horas"
    for extenso, valor in sorted(_EXTENSO.items(), key=lambda x: len(x[0]), reverse=True):
        if extenso in texto:
            h = valor
            if re.search(r"da\s*(tarde|noite)", texto) and h < 12:
                h += 12
            elif re.search(r"da\s*(manhã|manha)", texto) and h == 12:
                h = 0
            if 0 <= h <= 23:
                return f"{h:02d}:00"

    return None


def _extrair_texto_nota(texto: str) -> str:
    """
    Remove palavras de ativação do início da frase e extrai só o conteúdo.
    Ex: "jarvis me lembra de gravar o vídeo às 21" → "gravar o vídeo"

    CORREÇÃO: gatilhos só removidos do INÍCIO da frase (startswith em loop),
    nunca do meio — evita cortar palavras como "de", "para", "que" no conteúdo.
    Regex de horário removida do final apenas se aparecer depois do conteúdo.
    """
    # Gatilhos de ativação — apenas frases completas, sem palavras curtas genéricas
    gatilhos = [
        "jarvis não esquece de", "jarvis nao esquece de",
        "jarvis não esqueça de", "jarvis nao esqueca de",
        "jarvis me lembra de", "jarvis me lembra",
        "jarvis lembra de", "jarvis lembra",
        "jarvis me avisa de", "jarvis me avisa",
        "jarvis cria uma anotação", "jarvis cria anotacao",
        "jarvis cria uma nota", "jarvis cria nota",
        "jarvis anota aí", "jarvis anota ai", "jarvis anota",
        "jarvis salva isso", "jarvis salva",
        "jarvis registra",
        "criar lembrete para", "criar lembrete",
        "cria lembrete para", "cria lembrete",
        "não esquece de", "nao esquece de",
        "não esqueça de", "nao esqueca de",
        "me lembra de", "me lembra",
        "lembra de", "lembra",
        "me avisa de", "me avisa",
        "cria uma anotação", "cria anotacao",
        "criar anotação", "criar anotacao",
        "criar nota", "cria uma nota", "cria nota",
        "anota aí", "anota ai", "anota",
        "salva aí", "salva ai", "salva isso", "salva",
        "registra",
        "jarvis",
    ]

    resultado = texto.lower().strip()

    # Remove gatilhos do início — mais longos primeiro para evitar match parcial
    for g in sorted(gatilhos, key=len, reverse=True):
        if resultado.startswith(g):
            resultado = resultado[len(g):].strip()
            break  # só remove um gatilho por vez, o maior que casar

    # Remove horário APENAS no final da frase (não no meio do conteúdo)
    # Ex: "gravar o vídeo às 21 horas" → "gravar o vídeo"
    resultado = re.sub(
        r"\s+(?:às?|as)\s+\d{1,2}(?::\d{2})?\s*(?:horas?)?\s*(?:da\s*(?:manhã|manha|tarde|noite|madrugada))?\s*$",
        "", resultado
    ).strip()

    resultado = re.sub(r"\s+", " ", resultado).strip(" ,.")
    return resultado if resultado else texto.strip()


# -----------------------------------------------------------------------
# API PÚBLICA — CRIAR NOTA
# -----------------------------------------------------------------------

def criar_nota(texto_bruto: str) -> str:
    """
    Cria uma anotação simples (sem horário).
    Retorna string para o JARVIS falar.
    """
    conteudo = _extrair_texto_nota(texto_bruto)
    if not conteudo:
        return "Não entendi o que devo anotar, senhor."

    nota = {
        "id":         _gerar_id(),
        "tipo":       "nota",
        "texto":      conteudo,
        "criado_em":  datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "data":       datetime.datetime.now().strftime("%Y-%m-%d"),
        "hora":       datetime.datetime.now().strftime("%H:%M"),
        "lembrar_as": None,
    }

    notas = _carregar()
    notas.append(nota)
    _salvar(notas)

    print(f"[NOTES] Nota criada: '{conteudo}'")
    return f"Anotado, senhor. Registrei: {conteudo}."


# -----------------------------------------------------------------------
# API PÚBLICA — CRIAR LEMBRETE
# -----------------------------------------------------------------------

def _disparar_lembrete(nota_id: str, texto: str):
    """Callback do timer — fala o lembrete e remove da lista de ativos."""
    from voice import jarvis_voice
    with _lock_timers:
        _timers_lembretes.pop(nota_id, None)
    hora_str = datetime.datetime.now().strftime("%H:%M")
    jarvis_voice.falar(f"Senhor, lembrete: {texto}. São {hora_str}.")


def criar_lembrete(texto_bruto: str) -> str:
    """
    Cria um lembrete com horário específico.
    Retorna string para o JARVIS falar.
    """
    horario = _extrair_horario(texto_bruto)
    if not horario:
        return "Não identifiquei o horário do lembrete, senhor. Diga por exemplo: Jarvis, me lembra de ligar às 15:30."

    conteudo = _extrair_texto_nota(texto_bruto)
    if not conteudo:
        return "Não entendi o que devo lembrar, senhor."

    # Calcula segundos até o horário
    agora   = datetime.datetime.now()
    h, m    = map(int, horario.split(":"))
    alvo    = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    if alvo <= agora:
        alvo += datetime.timedelta(days=1)  # se já passou, agenda para amanhã

    segundos = (alvo - agora).total_seconds()

    nota = {
        "id":         _gerar_id(),
        "tipo":       "lembrete",
        "texto":      conteudo,
        "criado_em":  agora.strftime("%Y-%m-%dT%H:%M:%S"),
        "data":       agora.strftime("%Y-%m-%d"),
        "hora":       agora.strftime("%H:%M"),
        "lembrar_as": horario,
    }

    notas = _carregar()
    notas.append(nota)
    _salvar(notas)

    # Agenda o timer
    t = threading.Timer(segundos, _disparar_lembrete, args=(nota["id"], conteudo))
    t.daemon = True
    with _lock_timers:
        _timers_lembretes[nota["id"]] = t
    t.start()

    print(f"[NOTES] Lembrete criado: '{conteudo}' às {horario}")

    dia_str = ""
    if alvo.date() > agora.date():
        dia_str = " de amanhã"
    return f"Lembrete criado, senhor. Vou te avisar sobre '{conteudo}' às {horario}{dia_str}."

def reativar_lembretes():
    """
    [BOOT-PERSIST] Reativa lembretes pendentes ao iniciar:
    - horário futuro → reagendado;
    - perdeu há menos de 5 min → dispara em 1s;
    - perdeu há mais → avisa a perda (agrupado numa fala) e remove.
    Chame no main.py durante a inicialização.
    """
    notas = _carregar()
    agora = datetime.datetime.now()
    reativados = 0
    perdidos = []
    restantes = []

    for nota in notas:
        if nota.get("tipo") != "lembrete" or not nota.get("lembrar_as"):
            restantes.append(nota)
            continue
        if nota["id"] in _timers_lembretes:
            restantes.append(nota)   # já ativo (não ocorre no boot)
            continue
        try:
            h, m = map(int, nota["lembrar_as"].split(":"))
        except (ValueError, AttributeError):
            restantes.append(nota)
            continue

        alvo = datetime.datetime.combine(
            datetime.date.fromisoformat(nota["data"]),
            datetime.time(h, m))
        atraso_min = (agora - alvo).total_seconds() / 60

        if atraso_min <= 0:                      # futuro → reagenda
            segundos = -atraso_min * 60
            t = threading.Timer(segundos, _disparar_lembrete,
                                args=(nota["id"], nota["texto"]))
            t.daemon = True
            with _lock_timers:
                _timers_lembretes[nota["id"]] = t
            t.start()
            reativados += 1
            restantes.append(nota)
        elif atraso_min <= 5:                    # atraso curto → dispara já
            t = threading.Timer(1.0, _disparar_lembrete,
                                args=(nota["id"], nota["texto"]))
            t.daemon = True
            with _lock_timers:
                _timers_lembretes[nota["id"]] = t
            t.start()
            reativados += 1
            restantes.append(nota)
        else:                                    # perdido há muito → avisa e remove
            perdidos.append((nota["texto"], nota["lembrar_as"]))

    _salvar(restantes)

    if reativados:
        print(f"[NOTES] {reativados} lembrete(s) reativado(s) no boot.")
    if perdidos:
        lista = "; ".join(f"'{texto}' às {hora}" for texto, hora in perdidos)
        print(f"[NOTES] Lembretes perdidos: {lista}")
        jarvis_voice.falar(
            f"Senhor, perdi {len(perdidos)} lembrete(s) enquanto estive "
            f"desligado: {lista}.")

# -----------------------------------------------------------------------
# API PÚBLICA — LISTAR ANOTAÇÕES
# -----------------------------------------------------------------------

def listar_notas() -> str:
    """
    Retorna um resumo das anotações ativas para o JARVIS falar.
    """
    notas = _carregar()
    if not notas:
        return "Nenhuma anotação salva no momento, senhor."

    notas_simples   = [n for n in notas if n["tipo"] == "nota"]
    lembretes       = [n for n in notas if n["tipo"] == "lembrete"]

    partes = []

    if notas_simples:
        if len(notas_simples) == 1:
            partes.append(f"Uma anotação: {notas_simples[0]['texto']}.")
        else:
            textos = "; ".join(n["texto"] for n in notas_simples[-5:])
            partes.append(f"{len(notas_simples)} anotações. As mais recentes: {textos}.")

    if lembretes:
        pendentes = [n for n in lembretes if n["id"] in _timers_lembretes]
        if pendentes:
            itens = "; ".join(f"{n['texto']} às {n['lembrar_as']}" for n in pendentes)
            partes.append(f"{len(pendentes)} lembrete(s) ativo(s): {itens}.")

    if not partes:
        return "Nenhuma anotação ativa no momento, senhor."

    resumo = " ".join(partes)
    return f"{resumo} Posso ajudar com alguma delas, senhor?"


# -----------------------------------------------------------------------
# API PÚBLICA — APAGAR ANOTAÇÃO
# -----------------------------------------------------------------------

def apagar_nota(texto_bruto: str) -> str:
    """
    Busca a anotação mais parecida com o texto e a remove.
    Usa Groq para identificar a nota correta se houver múltiplas.
    Retorna string para o JARVIS falar.
    """
    notas = _carregar()
    if not notas:
        return "Não há anotações para apagar, senhor."

    # Extrai palavras-chave do pedido de remoção
    gatilhos_apagar = [
        "jarvis", "apaga", "apagar", "apague", "remove", "remover",
        "remova", "deleta", "deletar", "delete", "cancela", "cancelar",
        "anotação sobre", "anotacao sobre", "nota sobre", "lembrete sobre",
        "anotação de", "nota de", "lembrete de",
        "a anotação", "a nota", "o lembrete",
    ]
    termo = texto_bruto.lower().strip()
    for g in sorted(gatilhos_apagar, key=len, reverse=True):
        termo = termo.replace(g, "").strip()
    termo = re.sub(r"[\"']", "", termo).strip(" ,.")

    if not termo:
        return "Não entendi qual anotação apagar, senhor."

    # Busca por similaridade simples primeiro
    palavras_termo = set(termo.split())
    melhor_nota    = None
    melhor_score   = 0.0

    for nota in notas:
        palavras_nota = set(nota["texto"].lower().split())
        intersecao    = palavras_termo & palavras_nota
        uniao         = palavras_termo | palavras_nota
        score = len(intersecao) / len(uniao) if uniao else 0

        # Boost se o termo aparece como substring
        if termo in nota["texto"].lower():
            score = min(score + 0.4, 1.0)

        if score > melhor_score:
            melhor_score = score
            melhor_nota  = nota

    # Se score baixo e há múltiplas notas, usa Groq para desambiguar
    if melhor_score < 0.25 and len(notas) > 1 and GROQ_API_KEY:
        melhor_nota = _identificar_nota_groq(termo, notas)

    if not melhor_nota:
        return f"Não encontrei nenhuma anotação sobre '{termo}', senhor."

    # Remove da lista e cancela timer se for lembrete
    nota_id = melhor_nota["id"]
    with _lock_timers:
        if nota_id in _timers_lembretes:
            _timers_lembretes[nota_id].cancel()
            _timers_lembretes.pop(nota_id)

    notas = [n for n in notas if n["id"] != nota_id]
    _salvar(notas)

    print(f"[NOTES] Nota removida: '{melhor_nota['texto']}'")
    return f"Pronto, senhor. Removi a anotação sobre '{melhor_nota['texto']}'."


def _identificar_nota_groq(termo: str, notas: list) -> dict | None:
    """
    Usa Groq para identificar qual nota o usuário quer apagar.
    Retorna a nota identificada ou None.
    """
    try:
        from groq import Groq
        cliente = Groq(api_key=GROQ_API_KEY)

        lista = "\n".join(f"{i+1}. {n['texto']}" for i, n in enumerate(notas))
        prompt = (
            f"O usuário quer apagar a anotação sobre: '{termo}'.\n"
            f"Lista de anotações:\n{lista}\n\n"
            f"Responda APENAS com o número da anotação mais relacionada. "
            f"Se nenhuma for relacionada, responda 0."
        )

        resposta = cliente.chat.completions.create(
            model=GROQ_MODELO,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=5,
        )
        num = int(re.search(r"\d+", resposta.choices[0].message.content).group())
        if 1 <= num <= len(notas):
            return notas[num - 1]
    except Exception as e:
        print(f"[NOTES] Erro Groq ao identificar nota: {e}")

    return None


# -----------------------------------------------------------------------
# UTILITÁRIOS
# -----------------------------------------------------------------------

def total_notas() -> int:
    return len(_carregar())


def limpar_notas():
    """Apaga todas as anotações. Use com cautela."""
    with _lock_timers:
        for t in _timers_lembretes.values():
            t.cancel()
        _timers_lembretes.clear()
    if os.path.exists(NOTES_ARQUIVO):
        os.remove(NOTES_ARQUIVO)
    print("[NOTES] Todas as anotações removidas.")
