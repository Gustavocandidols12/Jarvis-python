"""
FILE: brain.py
DESCRIPTION: O "Cérebro" do JARVIS. Mapeia gestos e intenções de voz em ações do sistema.

CORREÇÕES APLICADAS:
  [FIX-4] Chave "Abrir_navegador" → "abrir_navegador" (consistente com listen.py).

  [FIX-7] CRÍTICO: Os blocos `_voz_memoria` e `_voz_youtube` tinham indentação
          errada (recuados como se fossem comentários dentro de outro if).
          Resultado: NUNCA executavam, pois o `return` dos blocos anteriores
          (_voz_nota_apagar etc.) impedia que o código chegasse até eles.
          Corrigido: todos os blocos `if cmd ==` agora têm indentação uniforme.

  [FIX-8] Clima e previsão chamavam obter_clima()/obter_previsao_hoje() de forma
          BLOQUEANTE (sem thread) na versão original do brain.py de referência.
          Mantida a versão com thread (já corrigida) para não travar o loop de vídeo.

  [FIX-9] `import threading`, `import re`, `import random`, `import subprocess`,
          `import urllib.parse` ocorriam DENTRO dos blocos if, sendo reimportados
          a cada chamada de voz. Movidos para o topo do arquivo.
"""
import os
import sys
import re
import time
import random
import datetime
import threading
import subprocess
import urllib.parse
import pyautogui
from config import *
from voice import jarvis_voice
from vision import analisar_frame
import memory as _memory
import notes as _notes
from utilities import (
    obter_clima,
    obter_previsao_hoje,
    criar_timer,
    cancelar_timers,
    status_timers,
    extrair_segundos_do_texto,
    extrair_nome_timer,
    perguntar_ia,
)


# -----------------------------------------------------------------------
# UTILITÁRIO — detecção automática de browser instalado
# -----------------------------------------------------------------------

_BROWSER_CACHE: list | None = None  # [FIX-CACHE] Detectado uma vez, reutilizado sempre


def _detectar_browser() -> list:
    """
    Retorna o comando do primeiro browser encontrado no sistema.
    Testa os mais comuns na ordem: Brave → Chrome → Chromium → Firefox.
    Fallback: xdg-open (abre com o browser padrão do sistema).

    [FIX-CACHE] Resultado é cacheado após a primeira detecção.
    Antes: chamava subprocess.run(["which", ...]) até 8 vezes A CADA uso de voz,
    bloqueando a thread por ~200-400ms desnecessariamente.
    """
    global _BROWSER_CACHE
    if _BROWSER_CACHE is not None:
        return _BROWSER_CACHE

    candidatos = [
        "brave-browser",
        "brave",
        "google-chrome",
        "google-chrome-stable",
        "chromium-browser",
        "chromium",
        "firefox",
        "firefox-esr",
    ]
    for nome in candidatos:
        resultado = subprocess.run(["which", nome], capture_output=True)
        if resultado.returncode == 0:
            print(f"[BRAIN] Browser detectado: {nome}")
            _BROWSER_CACHE = [nome]
            return _BROWSER_CACHE

    print("[BRAIN] Nenhum browser encontrado, usando xdg-open como fallback.")
    _BROWSER_CACHE = ["xdg-open"]
    return _BROWSER_CACHE


class Brain:
    def __init__(self):
        self.gestos_start_bloqueados = True
        self.gestos_bloqueados_6     = False
        self.gestos_bloqueados_7     = False
        self.mute_ativo              = False
        self.ultimo_gesto            = None
        self.last_6_toggle           = 0
        self.last_7_toggle           = 0
        self.last_toggle_time        = 0

    # -------------------------------------------------------------------
    # LOOP DE GESTOS
    # -------------------------------------------------------------------

    def execute(self, gesto_atual, cap_ref):
        current_time = time.time()

        if not gesto_atual:
            return

        if gesto_atual == "7" and self.gestos_bloqueados_6:
            return

        if gesto_atual == "6" and (current_time - self.last_6_toggle) >= DEBOUNCE_6:
            self.gestos_bloqueados_6 = not self.gestos_bloqueados_6
            self.last_6_toggle = current_time
            texto = random.choice(VozG6) if self.gestos_bloqueados_6 else "Sistemas desbloqueados"
            jarvis_voice.falar(texto)

        elif gesto_atual == "7" and (current_time - self.last_7_toggle) >= DEBOUNCE_7:
            self.gestos_bloqueados_7 = not self.gestos_bloqueados_7
            self.last_7_toggle = current_time
            self.gestos_start_bloqueados = False
            texto = random.choice(VozG7) if self.gestos_bloqueados_7 else "Controle manual desativado"
            jarvis_voice.falar(texto)

        elif gesto_atual is not None:
            is_blocked = False
            if self.gestos_bloqueados_6 and gesto_atual in GESTOS_BLOQUEADOS_6:
                is_blocked = True
            if self.gestos_bloqueados_7 and gesto_atual in GESTOS_BLOQUEADOS_7:
                is_blocked = True
            if self.gestos_start_bloqueados and gesto_atual in GESTOS_START_BLOQUEADOS:
                is_blocked = True

            if not is_blocked and gesto_atual != self.ultimo_gesto:
                self.process_command(gesto_atual, cap_ref)
                self.ultimo_gesto = gesto_atual

    # -------------------------------------------------------------------
    # COMANDOS DE VOZ
    # -------------------------------------------------------------------

    def execute_voice_command(self, intencao: str, texto_bruto: str):
        print(f"[BRAIN] Voz: '{intencao}' | '{texto_bruto}'")

        MAPA_INTENCAO_COMANDO = {
            "volume_up":          "2",
            "volume_down":        "1",
            "mute":               "Mute",
            "unmute":             "Mute",
            "play_pause":         "Pause",
            "proximo":            "Next",
            "abrir_editor":       "Rock",
            "tela_cheia":         "DB",
            "recarregar":         "8",
            "clique":             "clique",
            "encerrar":           "Encerrar",
            "sair_jarvis":        "9",
            "voz_ligar":          "3",
            "voz_desligar":       "4",
            "mouse_ligar":        "7",
            "mouse_desligar":     "7",
            "hora":               "_voz_hora",
            "saudacao":           "_voz_saudacao",
            "clima_agora":        "_voz_clima_agora",
            "clima_hoje":         "_voz_clima_hoje",
            "timer_criar":        "_voz_timer_criar",
            "timer_cancelar":     "_voz_timer_cancelar",
            "timer_status":       "_voz_timer_status",
            # [FIX-4] chave corrigida para minúsculo
            "abrir_navegador":    "_voz_abrir_programa",
            "pesquisar":          "_voz_pesquisar",
            "ver":                "_voz_ver",
            "identificar_objeto": "_voz_identificar_objeto",
            "youtube":            "_voz_youtube",
            "memoria":            "_voz_memoria",
            "nota_criar":         "_voz_nota_criar",
            "nota_lembrar":       "_voz_nota_lembrar",
            "nota_listar":        "_voz_nota_listar",
            "nota_apagar":        "_voz_nota_apagar",
        }

        cmd = MAPA_INTENCAO_COMANDO.get(intencao)
        if not cmd:
            print(f"[BRAIN] Intenção '{intencao}' sem mapeamento.")
            return

        # ---------------------------------------------------------------
        # HORA
        # ---------------------------------------------------------------
        if cmd == "_voz_hora":
            hora_str = datetime.datetime.now().strftime("%H:%M")
            jarvis_voice.falar(f"São exatamente {hora_str}, senhor.")
            return

        # ---------------------------------------------------------------
        # SAUDAÇÃO
        # ---------------------------------------------------------------
        if cmd == "_voz_saudacao":
            jarvis_voice.falar("Olá. Sistemas online e prontos, senhor.")
            return

        # ---------------------------------------------------------------
        # CLIMA AGORA (thread para não bloquear vídeo) [FIX-8]
        # ---------------------------------------------------------------
        if cmd == "_voz_clima_agora":
            jarvis_voice.falar("Consultando clima, um momento.")
            def _buscar():
                jarvis_voice.falar(obter_clima())
            threading.Thread(target=_buscar, daemon=True).start()
            return

        # ---------------------------------------------------------------
        # PREVISÃO DO DIA (thread) [FIX-8]
        # ---------------------------------------------------------------
        if cmd == "_voz_clima_hoje":
            jarvis_voice.falar("Verificando previsão do dia.")
            def _buscar():
                jarvis_voice.falar(obter_previsao_hoje())
            threading.Thread(target=_buscar, daemon=True).start()
            return

        # ---------------------------------------------------------------
        # TIMER — CRIAR
        # ---------------------------------------------------------------
        if cmd == "_voz_timer_criar":
            segundos = extrair_segundos_do_texto(texto_bruto)
            if not segundos:
                jarvis_voice.falar(
                    "Não entendi a duração. Diga por exemplo: Jarvis, timer de 10 minutos."
                )
                return
            nome = extrair_nome_timer(texto_bruto)
            jarvis_voice.falar(criar_timer(segundos, nome))
            return

        # ---------------------------------------------------------------
        # TIMER — CANCELAR
        # ---------------------------------------------------------------
        if cmd == "_voz_timer_cancelar":
            jarvis_voice.falar(cancelar_timers())
            return

        # ---------------------------------------------------------------
        # TIMER — STATUS
        # ---------------------------------------------------------------
        if cmd == "_voz_timer_status":
            jarvis_voice.falar(status_timers())
            return

        # ---------------------------------------------------------------
        # ABRIR NAVEGADOR — detecta automaticamente qual está instalado
        # ---------------------------------------------------------------
        if cmd == "_voz_abrir_programa":
            jarvis_voice.falar("Abrindo o seu navegador, senhor.")
            subprocess.Popen(_detectar_browser())
            return

        # ---------------------------------------------------------------
        # ANOTAÇÃO — CRIAR
        # ---------------------------------------------------------------
        if cmd == "_voz_nota_criar":
            jarvis_voice.falar(_notes.criar_nota(texto_bruto))
            return

        # ---------------------------------------------------------------
        # LEMBRETE — CRIAR
        # ---------------------------------------------------------------
        if cmd == "_voz_nota_lembrar":
            jarvis_voice.falar(_notes.criar_lembrete(texto_bruto))
            return

        # ---------------------------------------------------------------
        # ANOTAÇÕES — LISTAR
        # ---------------------------------------------------------------
        if cmd == "_voz_nota_listar":
            jarvis_voice.falar(_notes.listar_notas())
            return

        # ---------------------------------------------------------------
        # ANOTAÇÃO — APAGAR
        # ---------------------------------------------------------------
        if cmd == "_voz_nota_apagar":
            jarvis_voice.falar(_notes.apagar_nota(texto_bruto))
            return

        # ---------------------------------------------------------------
        # MEMÓRIA — [FIX-7] bloco agora no nível correto de indentação
        # ---------------------------------------------------------------
        if cmd == "_voz_memoria":
            jarvis_voice.falar(random.choice([
                "Deixa eu consultar minha memória, senhor.",
                "Verificando os registros, um momento.",
                "Buscando nos arquivos, senhor.",
            ]))
            def _executar():
                jarvis_voice.falar(_memory.resumir_periodo(texto_bruto))
            threading.Thread(target=_executar, daemon=True).start()
            return

        # ---------------------------------------------------------------
        # YOUTUBE — [FIX-7] bloco agora no nível correto de indentação
        # ---------------------------------------------------------------
        if cmd == "_voz_youtube":
            _GATILHOS = [
                "jarvis", "pesquisa no youtube", "pesquise no youtube",
                "busca no youtube", "procura no youtube", "abre no youtube",
                "coloca no youtube", "toca no youtube", "no youtube",
                "no you tube", "coloca pra tocar", "quero ouvir",
                "quero ver", "me coloca", "bota pra tocar", "coloca uma música",
                "toca uma música", "abre o youtube", "abre o vídeo",
                "abre o video", "mete no youtube", "joga no youtube",
                "roda no youtube", "toca aí", "coloca aí", "bota aí",
                "quero assistir", "me bota", "me coloca aí", "youtube",
                "toca",
            ]
            termo = texto_bruto.lower().strip()
            for g in sorted(_GATILHOS, key=len, reverse=True):
                termo = termo.replace(g, "").strip()
            termo = re.sub(r"^[\s,.\-:]+|[\s,.\-:]+$", "", termo).strip()

            if not termo:
                jarvis_voice.falar("O que quer que eu procure no YouTube, senhor?")
                return

            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(termo)}"
            print(f"[BRAIN] YouTube → '{termo}'")
            jarvis_voice.falar(f"Procurando {termo} no YouTube, senhor.")
            subprocess.Popen(_detectar_browser() + [url])
            return

        # ---------------------------------------------------------------
        # VISÃO — DESCREVER CENA
        # ---------------------------------------------------------------
        if cmd == "_voz_ver":
            _GATILHOS_VER = [
                "jarvis", "o que você vê", "o que está vendo", "o que vê",
                "descreve o que vê", "descreve a cena", "descreve o ambiente",
                "o que tem na câmera", "o que aparece na câmera",
                "o que está na câmera", "olha pela câmera",
                "analisa a imagem", "analisa o que vê", "analisa isso",
                "veja isso", "olha isso", "me diz o que vê",
                "o que está acontecendo aí", "o que está na frente",
                "o que está aqui", "tem alguém aí", "tem alguém aqui",
                "quem está aí", "quem está aqui", "o que está na minha frente",
                "o que está escrito", "lê o que está escrito",
                "consegue ler isso", "lê isso pra mim",
                "abre o olho", "usa a câmera", "me fala o que vê",
                "usa tua câmera", "olha pra câmera",
            ]
            pergunta = texto_bruto.lower().strip()
            for g in sorted(_GATILHOS_VER, key=len, reverse=True):
                pergunta = pergunta.replace(g, "").strip()
            pergunta = re.sub(r"^[\s,.\-:]+|[\s,.\-:]+$", "", pergunta).strip()

            jarvis_voice.falar(random.choice([
                "Analisando o que estou vendo, um momento.",
                "Deixa eu ver isso, senhor.",
                "Processando a imagem, aguarde.",
            ]))
            def _executar():
                jarvis_voice.falar(analisar_frame(pergunta))
            threading.Thread(target=_executar, daemon=True).start()
            return

        # ---------------------------------------------------------------
        # VISÃO — IDENTIFICAR OBJETO
        # ---------------------------------------------------------------
        if cmd == "_voz_identificar_objeto":
            _PROMPT = (
                "Olhe para esta imagem e identifique o objeto principal que aparece, "
                "especialmente qualquer coisa que esteja sendo segurada ou em destaque. "
                "Diga o nome, para que serve e uma característica relevante. "
                "Ignore o cenário ao fundo. Responda em no máximo 2 frases em português."
            )
            jarvis_voice.falar(random.choice([
                "Identificando o objeto, um momento.",
                "Deixa eu ver o que é isso.",
                "Analisando o objeto, senhor.",
            ]))
            def _executar():
                jarvis_voice.falar(analisar_frame(_PROMPT))
            threading.Thread(target=_executar, daemon=True).start()
            return

        # ---------------------------------------------------------------
        # PESQUISA / IA (Groq)
        # ---------------------------------------------------------------
        if cmd == "_voz_pesquisar":
            _GATILHOS_IA = [
                "jarvis", "pesquisa", "pesquise", "pesquisar",
                "busca", "busque", "buscar",
                "procura", "procure", "procurar",
                "me explica", "me explique",
                "me fala sobre", "me diz sobre", "me conta sobre", "me conta",
                "fala sobre", "fale sobre",
                "o que você sabe sobre", "o que sabe sobre",
                "me dá uma explicação", "me dê uma explicação",
                "pode me explicar", "consegue me explicar",
                "sabe me dizer", "sabe dizer",
                "descobre pra mim", "descobre aí",
                "pesquisa aí", "busca aí", "consulta aí",
            ]
            termo = texto_bruto.lower().strip()
            for g in sorted(_GATILHOS_IA, key=len, reverse=True):
                termo = termo.replace(g, "").strip()
            termo = re.sub(r"^[\s,.\-:]+|[\s,.\-:]+$", "", termo).strip()

            if not termo:
                jarvis_voice.falar("Sobre o que você quer que eu pesquise, senhor?")
                return

            jarvis_voice.falar(random.choice(VozIAPesquisando))

            def _executar():
                print(f"[BRAIN] IA → '{termo}'")
                jarvis_voice.falar(perguntar_ia(termo))
            threading.Thread(target=_executar, daemon=True).start()
            return

        # ---------------------------------------------------------------
        # COMANDOS QUE MAPEIAM PARA GESTOS — bypass de bloqueios físicos
        # ---------------------------------------------------------------
        print(f"[BRAIN] Executando via voz: '{cmd}' (intenção: {intencao})")
        self.process_command(cmd, cap_ref=None)

    # -------------------------------------------------------------------
    # EXECUÇÃO DE COMANDOS (gestos + voz mapeada)
    # -------------------------------------------------------------------

    def process_command(self, cmd, cap_ref):
        if cmd == "Encerrar":
            jarvis_voice.falar_sincronizado(random.choice(VozEncerrar))
            os.system("poweroff")
        elif cmd == "Rock":
            jarvis_voice.falar("Iniciando editor de código")
            os.system("code")
        elif cmd == "Mute":
            os.system("pactl set-sink-mute @DEFAULT_SINK@ toggle")
            self.mute_ativo = not self.mute_ativo
            jarvis_voice.falar("Silenciado" if self.mute_ativo else "Som ligado")
            self.last_toggle_time = time.time()
        elif cmd == "1":
            pyautogui.press('volumedown')
            jarvis_voice.falar("Diminuindo volume, senhor")
        elif cmd == "2":
            def _conectar_womic():
                # Carrega módulo de loopback com senha via stdin (não interativo)
                subprocess.run(
                    ["sudo", "-S", "modprobe", "snd-aloop"],
                    input="@Qnp09c49\n",
                    capture_output=True,
                    text=True
                )
                # Popen = roda em background, não trava o JARVIS
                subprocess.Popen([
                    "/home/gustavo/Downloads/micclient-x86_64.AppImage",
                    "-t", "WIFI", "192.168.1.15"
                ])
            threading.Thread(target=_conectar_womic, daemon=True).start()
            jarvis_voice.falar("Conectando ao celular, senhor.")
        elif cmd == "3":
            if not jarvis_voice.voz_ativa:
                jarvis_voice.voz_ativa = True
                jarvis_voice.falar(random.choice(VozG3))
        elif cmd == "4":
            if jarvis_voice.voz_ativa:
                jarvis_voice.falar(random.choice(VozG4))
                jarvis_voice.voz_ativa = False
        elif cmd == "clique":
            jarvis_voice.falar(random.choice(VozClique))
            pyautogui.click()
        elif cmd == "8":
            jarvis_voice.falar("Recarregando senhor")
            pyautogui.press("f5")
        elif cmd == "DB":
            jarvis_voice.falar("Tela cheia, senhor")
            pyautogui.press("f")
        elif cmd == "9":
            jarvis_voice.falar_sincronizado(random.choice(VozSairJarvis))
            if cap_ref:
                cap_ref.release()
            import cv2
            cv2.destroyAllWindows()
            # [FIX-EXIT] sys.exit(0) em thread secundária (voz) apenas levanta
            # SystemExit NESSA thread, sem matar o processo — o JARVIS ficava
            # rodando como zumbi. os._exit(0) encerra o processo de verdade.
            os._exit(0)
        elif cmd == "Pause":
            jarvis_voice.falar(random.choice(VozGPause))
            pyautogui.press("space")
        elif cmd == "Next":
            jarvis_voice.falar(random.choice(VozGNext))
            pyautogui.hotkey("shift", "n")

        GESTOS_REPETIVEIS = {"clique", "1", "2", "8", "Pause", "Next"}
        if cmd in GESTOS_REPETIVEIS:
            self.ultimo_gesto = None


# Instância global
jarvis_brain = Brain()