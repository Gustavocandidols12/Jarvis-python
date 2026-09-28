"""
FILE: alarm.py
DESCRIPTION: Despertador do JASPER — som aleatório da pasta + bom-dia
             personalizado via Groq (novo TODO dia) + ciclo som/fala
             até o usuário parar.

CICLO (padrão):
    07:30 → toca som aleatório (TOCAR_SEG)
          → pausa som → fala bom-dia IA (fallback local se Groq falhar)
          → retoma o som (TOCAR_SEG)
          → repete até 'parar despertador' ou TIMEOUT_MIN

PARAR: voz/box "para o despertador" / "para o alarme" — para na hora.

IMPORTA: voice.py (TTS) e utilities (Groq) — mesma regra do resto do
         projeto. Desliga o monitor de speaker (v5-AUDIO) enquanto
         toca, senão a escuta ficaria surda e o "parar" não chegaria.
"""
import os
import random
import subprocess
import threading
import time
import datetime

# -----------------------------------------------------------------------
# CONFIGURAÇÃO — mexa à vontade
# -----------------------------------------------------------------------
DESPERTAR_HORA    = 7        # hora
DESPERTAR_MINUTO  = 30       # minuto
DESPERTAR_ATIVO   = True     # False = despertador desligado

PASTA_SONS        = os.path.expanduser("~/Music/Indie")  # .mp3/.wav/.ogg
EXTENSOES_VALIDAS = (".mp3", ".wav", ".ogg", ".flac", ".m4a")

TOCAR_SEG         = 20       # X: som toca antes de cada fala
RETOCAR_SEG       = 45       # Y: som toca depois de cada fala
TIMEOUT_MIN       = 5       # sem resposta, para sozinho após N minutos
PLAYER            = "mpv"    # player de linha de comando

# Frases de emergência (sem internet/Groq no momento do despertar)
_BOM_DIA_FALLBACK = [
    "Bom dia, chefe. Hoje é {semana}, {data}. O dia não sabe o que o espera — vamos surpreendê-lo.",
    "Acorda, chefe. {semana}, {data}. Café e foco: nessa ordem.",
    "Bom dia! {semana}, {data}. Mais um dia de mostrar pro mundo quem manda.",
    "Ei, chefe. {semana}, {data}. Já preparei tudo. Falta só você abrir os olhos.",
]

# -----------------------------------------------------------------------
# ESTADO
# -----------------------------------------------------------------------
_tocando   = False
_proc      = None       # Popen do mpv
_thread    = None


def despertador_tocando() -> bool:
    """True enquanto o alarme toca (HUD/main podem consultar)."""
    return _tocando


def parar_despertador():
    """Para o alarme NA HORA (chamado pelo brain — 'para o despertador')."""
    global _tocando
    _tocando = False


def _som_aleatorio() -> str | None:
    """Arquivo de som aleatório da pasta configurada."""
    if not os.path.isdir(PASTA_SONS):
        print(f"[ALARM] Pasta de sons não existe: {PASTA_SONS}")
        return None
    arquivos = [os.path.join(PASTA_SONS, f) for f in os.listdir(PASTA_SONS)
                if f.lower().endswith(EXTENSOES_VALIDAS)]
    if not arquivos:
        print(f"[ALARM] Nenhum som válido em {PASTA_SONS} "
              f"({', '.join(EXTENSOES_VALIDAS)})")
        return None
    return random.choice(arquivos)


def _bom_dia_ia() -> str:
    """Bom-dia NOVO todo dia (Groq, sem cache) — fallback local se falhar."""
    agora = datetime.datetime.now()
    semana = ["segunda", "terça", "quarta", "quinta", "sexta",
              "sábado", "domingo"][agora.weekday()]
    data_str = agora.strftime("%d de %B")
    try:
        from utilities import _get_groq_client, GROQ_MODELO
        cliente = _get_groq_client()
        resp = (cliente.chat.completions.create(
            model=GROQ_MODELO,
            messages=[{"role": "user", "content": (
                "Escrava UM bom-dia curto e bem-humorado para o seu chefe acordar. "
                "Regras: no máximo 3 frases, em português falado, sem emojis, sem "
                "markdown. Mencione que hoje é " + semana + ", " + data_str + ". "
                "Seja criativo — essa mensagem é gerada TODO DIA e nunca pode "
                "repetir as anteriores. Finalize com um puxão de orelha motivacional.")}],
            temperature=0.95,      # bem alto: pede novidade diária
            max_tokens=120,
        ).choices[0].message.content or "").strip()
        if resp:
            return resp
    except Exception as e:
        print(f"[ALARM] Groq falhou no bom-dia ({e}) — fallback local")
    return random.choice(_BOM_DIA_FALLBACK).format(semana=semana, data=data_str)


def _ciclo_despertar():
    """Ciclo: som → fala → som → ... até parar() ou timeout."""
    global _tocando, _proc
    from voice import jarvis_voice

    som = _som_aleatorio()
    if som is None:
        jarvis_voice.falar("Bom dia, chefe. Minha pasta de sons de alarme "
                           "está vazia — mas eu não ia deixar você dormir.")
        jarvis_voice.falar(_bom_dia_ia())
        _tocando = False
        return

    print(f"[ALARM] Despertando — som: {os.path.basename(som)}")

    # desliga o monitor de áudio externo (escuta volta a ouvir o 'parar')
    monitor_desligado = False
    try:
        import listen as _listen
        if _listen.jarvis_listen.audio_externo:
            _listen.jarvis_listen.audio_externo = False
            _listen.AUDIO_EXTERNO_ATIVO = False
            monitor_desligado = True
            print("[ALARM] Monitor de speaker desligado durante o alarme.")
    except Exception:
        pass

    fim = time.time() + TIMEOUT_MIN * 60
    primeira = True
    try:
        while _tocando and time.time() < fim:
            # liga o som
            try:
                _proc = subprocess.Popen(
                    [PLAYER, "--really-quiet", "--loop", "inf", som])
            except Exception as e:
                print(f"[ALARM] Player falhou ({e}) — só a voz então.")
                break

            espera = TOCAR_SEG if primeira else RETOCAR_SEG
            inicio = time.time()
            while _tocando and time.time() - inicio < espera:
                time.sleep(0.5)

            if not _tocando:
                break

            # pausa o som → fala
            _parar_player()
            jarvis_voice.falar(_bom_dia_ia())
            primeira = False

            # espera a fala terminar antes de retomar o som
            espera_fala = time.time() + 90
            while (jarvis_voice.boca_falando and _tocando
                   and time.time() < espera_fala):
                time.sleep(0.3)
    finally:
        _parar_player()
        _tocando = False
        if monitor_desligado:
            # religa o monitor de áudio externo
            try:
                import listen as _listen
                _listen.AUDIO_EXTERNO_ATIVO = True
                print("[ALARM] Monitor de speaker religado.")
            except Exception:
                pass
        print("[ALARM] Despertador encerrado.")


def _parar_player():
    global _proc
    if _proc is not None:
        try:
            _proc.terminate()
        except Exception:
            pass
        _proc = None


def _vigiar():
    """Thread eterna: relógio bate 07:30 → dispara o despertador."""
    global _tocando
    ja_disparou_hoje = False
    while True:
        agora = datetime.datetime.now()
        if agora.hour == DESPERTAR_HORA and agora.minute == DESPERTAR_MINUTO:
            if not ja_disparou_hoje and not _tocando:
                ja_disparou_hoje = True
                _tocando = True
                threading.Thread(target=_ciclo_despertar, daemon=True).start()
        elif agora.hour != DESPERTAR_HORA:
            ja_disparou_hoje = False   # novo dia, nova chance
        time.sleep(10)


def iniciar():
    """Sobe o vigilante do despertador (chamado pelo main.py no boot)."""
    global _thread
    if not DESPERTAR_ATIVO:
        print("[ALARM] Despertador desativado por config.")
        return
    if _thread and _thread.is_alive():
        return
    if not os.path.isdir(PASTA_SONS):
        print(f"[ALARM] AVISO: crie a pasta {PASTA_SONS} com seus sons "
              f"({', '.join(EXTENSOES_VALIDAS)}) — sem ela, só a voz toca.")
    _thread = threading.Thread(target=_vigiar, daemon=True)
    _thread.start()
    print(f"[ALARM] Despertador ativo para {DESPERTAR_HORA:02d}:"
          f"{DESPERTAR_MINUTO:02d}.")
