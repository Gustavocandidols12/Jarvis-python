"""
FILE: brain.py
DESCRIPTION: O "Cérebro" do JARVIS. Mapeia gestos e intenções de voz em ações.

v3 — novos comandos: Instagram (direct), Mario 64 (wine), Chat da Z.ai
     (estilo YouTube + roteamento de perguntas de código/jarvis pro chat).
     [FIX] gesto Rock usava _personality.gerar_resposta_jarvis (método
     inexistente → AttributeError ao abrir o editor por gesto).
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
import glob
import window as _window

from config import *
from voice import jarvis_voice
from vision import analisar_frame, PASTA_FRAMES
import phone_commands as _phone_commands
import memory as _memory
import notes as _notes
import recording as _recording
import file_manager as _file_manager
import personality as _personality
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
import orbs as _orbs
import image_gen as _image_gen   
import dev_agent as _dev_agent

# [ORBS] módulo visual associado à intenção (None = sem anúncio)
_MODULO_DA_INTENCAO = {
    "ver": "visao", "foto": "visao", "identificar_objeto": "visao",
    "gravacao_iniciar": "visao", "gravacao_cancelar": "visao",
    "pesquisar": "ia", "memoria": "ia", "chat_zai": "ia",
    "imagem_criar": "ia",   # [v6-IMG] orbes violetas durante a geração
}

# -----------------------------------------------------------------------
# [NOVO-v3] Constantes dos comandos novos
# -----------------------------------------------------------------------

# [v5-IDENTIDADE] prompt-padrão pro Groq — descreve o sistema INTEIRO
PROMPT_QUEM_SO_EU = """Você é o JASPER, assistente pessoal que roda localmente no PC do usuário.

O QUE VOCÊ FAZ (contexto real do sistema):
- ESCUTA por wake word ("Hey Jarvis") e transcreve voz em português localmente com Whisper
- FALA através de um sintetizador de voz neural (edge-tts)
- VÊ pela webcam (descreve cenas, identifica objetos, tira e avalia fotos)
- CONTROLA O PC: abre programas, mexe volume, move o mouse, grava a tela
- CONTROLA O CELULAR via USB: espelha a tela, lê notificações, abre apps, tira print
- PESQUISA na internet e responde perguntas usando IA
- TEM MEMÓRIA: lembra e resume conversas anteriores
- TEM HUMOR: seus estados visuais incluem PENSATIVO, CANSADO, ALEGRE, FOCO, FESTA, ZEN e CAOS
- TEM uma janela viva: orbes que se movem, mudam de cor conforme o humor e fogem do mouse
- é regido por uma personalidade: descontraído, rápido, humor ácido

TAREFA: responda à pergunta "quem é você" (ou variação) em primeira pessoa,
como o JASPER. Seja específico sobre suas capacidades reais listadas acima.
Máximo 4 frases. Português brasileiro falado, sem markdown nem emojis."""

URL_INSTAGRAM_DM = "https://www.instagram.com/direct/inbox/"
URL_CHAT_ZAI     = "https://chat.z.ai/c/f1374c9c-0867-43e6-aa54-63a92b80e7ef"
PASTA_MARIO64    = os.path.expanduser("~/Desktop/Aplicativos/sm64coopdx_Windows_DirectX")
EXE_MARIO64      = "sm64coopdx.exe"


# [ENTER-AUTO] True = aperta Enter após colar a pergunta no chat (com
# check de sanidade do clipboard antes). False = cola e espera você mandar.
ENVIAR_PERGUNTA_CHAT = True

# [CHAT-ZAI] perguntas com estas palavras vão pro CHAT (onde vive o contexto
# do projeto) em vez do Groq genérico. False = tudo vai pro Groq (só os
# comandos explícitos de chat abrem o chat).
CHAT_ZAI_ROTEIA_PESQUISA = True
_ROTEAR_CHAT = ("jarvis", "jasper", "implementar", "programar", "código",
                "codigo", "python", "script")


def _abrir_chat_com_pergunta(pergunta: str):
    """
    Abre o chat da Z.ai e cola a pergunta no campo de mensagem.
    Com ENVIAR_PERGUNTA_CHAT=True (constante no topo do arquivo), aperta
    Enter DEPOIS de validar que o clipboard ainda contém a pergunta.

    Fluxo (thread própria — nada trava):
      1. pergunta → clipboard (xclip).
      2. Espera o browser virar a janela ATIVA (xdotool, até 15s).
      3. Espera 4s — aba nova em janela existente demora a montar o DOM.
      4. Clica em (50%, 85%) — foca o campo de mensagem (parte de baixo).
      5. Ctrl+V duas vezes (a segunda pega campos que engoliram a 1ª).
      6. Valida o clipboard e aperta Enter (se a flag estiver ligada).
    """
    subprocess.Popen(_detectar_browser() + [URL_CHAT_ZAI])
    if not pergunta or not pergunta.strip():
        return

    def _esperar_browser_ativo(timeout=15.0):
        """True quando uma janela de browser estiver com o foco."""
        browsers = ("brave", "firefox", "chromium", "google-chrome")
        fim = time.time() + timeout
        while time.time() < fim:
            try:
                r = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True, text=True, timeout=2)
                nome = (r.stdout or "").lower()
                if any(b in nome for b in browsers):
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _colar():
        # 1) pergunta → clipboard
        try:
            p = subprocess.Popen(["xclip", "-selection", "clipboard"],
                                 stdin=subprocess.PIPE)
            p.communicate(pergunta.encode("utf-8"))
        except FileNotFoundError:
            print("[BRAIN] xclip não instalado — chat aberto SEM a pergunta.")
            print("[BRAIN] Instale com: sudo apt install xclip")
            return

        # 2) esperar o browser tomar o foco (até 15s)
        if not _esperar_browser_ativo():
            print("[BRAIN] ⚠ Browser não ficou ativo em 15s — NÃO colei "
                  "(evitei colar no lugar errado). Cole com Ctrl+V manualmente.")
            return
        print("[BRAIN] Browser ativo — esperando o chat carregar...")
        time.sleep(7.0)

        # 3) foca o campo de mensagem + cola UMA vez validada
        try:
            larg, alt = pyautogui.size()
            pyautogui.click(larg // 2, int(alt * 0.88))
            time.sleep(0.8)   # [FIX] clique assentar ANTES da cola (era 0.6)

            # [FIX-COLA-DUPLA] UMA única cola. A versão antiga mandava 2x
            # Ctrl+V (0.5s de intervalo) — o segundo evento chegava com o
            # campo ainda processando o primeiro e a mensagem não entrava
            # (Ctrl+V manual funcionava na hora = sintoma clássico).
            # Agora: cola 1x, espera, valida, e o Enter só vai se o
            # clipboard continua com a pergunta (sinal de que colou certo).
            pyautogui.hotkey("ctrl", "v")
            print(f"[BRAIN] Ctrl+V enviado — pergunta: '{pergunta[:50]}...'")

            # 4) [ENTER-AUTO] valida o clipboard ANTES do Enter
            if ENVIAR_PERGUNTA_CHAT:
                try:
                    r = subprocess.run(
                        ["xclip", "-selection", "clipboard", "-o"],
                        capture_output=True, text=True, timeout=2)
                    if (r.stdout or "").strip() == pergunta:
                        time.sleep(1.2)   # [FIX] texto assentar no campo
                        pyautogui.press("enter")
                        print("[BRAIN] Enter — pergunta enviada ao chat.")
                    else:
                        print("[BRAIN] ⚠ Clipboard mudou — Enter NÃO enviado. "
                              "A cola pode ter ido pro lugar errado.")
                except Exception as e:
                    print(f"[BRAIN] ⚠ Não validei o clipboard — Enter NÃO "
                          f"enviado: {e}")
            else:
                print("[BRAIN] (Enter automático desligado — envie você mesmo.)")
        except Exception as e:
            print(f"[BRAIN] Não consegui colar no chat: {e}")

    threading.Thread(target=_colar, daemon=True).start()


# -----------------------------------------------------------------------
# HELPER MODULAR PARA RESPOSTAS HUMANIZADAS
# -----------------------------------------------------------------------

def _resposta_jarvis(categoria: str, contexto: dict = None) -> str:
    """Helper: personality (Groq) com fallback automático."""
    if contexto is None:
        contexto = {}

    if _personality:
        try:
            return _personality.gerar_resposta(categoria, contexto)
        except Exception as e:
            print(f"[BRAIN] Erro ao gerar resposta personality ({categoria}): {e}")

    fallbacks = {
        "clima": "Consultando o clima, um momento.",
        "timer": "Operação de timer executada.",
        "notas": "Nota registrada.",
        "memoria": "Consultando a memória.",
        "erro": "Algo deu errado.",
        "generico": "Prontinho, senhor.",
    }

    return fallbacks.get(categoria, "Prontinho, senhor.")


# -----------------------------------------------------------------------
# DETECÇÃO DE BROWSER (cacheada)
# -----------------------------------------------------------------------

_BROWSER_CACHE: list | None = None


def _detectar_browser() -> list:
    global _BROWSER_CACHE
    if _BROWSER_CACHE is not None:
        return _BROWSER_CACHE

    candidatos = [
        "brave-browser", "brave", "google-chrome", "google-chrome-stable",
        "chromium-browser", "chromium", "firefox", "firefox-esr",
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

def _focar_janela_jarvis():
    """
    [FOCO] Traz a janela do JARVIS pra frente (foco comum — NÃO always on
    top: outro app pode cobri-la depois, comportamento normal de janela).
    Usado quando o JASPER vai falar algo importante (ex: pergunta enviada
    ao chat da Z.ai) — a janela entra em foco pra ficar acima do navegador
    naquele momento, sem ficar presa no topo para sempre.
    """
    try:
        r = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", "JARVIS Interface"],
            capture_output=True, text=True, timeout=2)
        for linha in (r.stdout or "").splitlines():
            linha = linha.strip()
            if linha.isdigit():
                subprocess.run(
                    ["xdotool", "windowactivate", linha],
                    capture_output=True, timeout=2)
                break
    except Exception:
        pass   # foco é cortesia — falhar não pode quebrar nada

def _abrir_ultima_foto() -> None:
    try:
        if not os.path.isdir(PASTA_FRAMES):
            print(f"[BRAIN] Pasta não encontrada: {PASTA_FRAMES}")
            return

        arquivos = glob.glob(os.path.join(PASTA_FRAMES, "*.jpg"))
        if not arquivos:
            print("[BRAIN] Nenhuma foto encontrada em Jarvis_frames.")
            return

        ultima_foto = max(arquivos, key=os.path.getmtime)
        print(f"[BRAIN] Abrindo última foto: {ultima_foto}")
        subprocess.Popen(["xdg-open", ultima_foto])
    except Exception as e:
        print(f"[BRAIN] Erro ao abrir última foto: {e}")


class Brain:
    def __init__(self):
        self.gestos_start_bloqueados = True
        self.gestos_bloqueados_6     = True
        self.gestos_bloqueados_7     = False
        self.mute_ativo              = False
        self.ultimo_gesto            = None
        self.last_6_toggle           = 0
        self.last_7_toggle           = 0
        self.last_toggle_time        = 0
        # [v7-DEV] estado do modo dev: False=off, 'perguntas'=coletando info
        self.modo_dev_ativo          = False

    # -------------------------------------------------------------------
    # [v7] BOA NOITE AGENDADO — janela 22:50–23:50, uma vez por dia
    # -------------------------------------------------------------------

    def iniciar_tarefa_boa_noite(self):
        """Thread que fala um boa noite (do humor atual) na janela
        22:50–23:50. Uma vez por dia — reinicia a permissão à meia-noite."""
        def _vigiar():
            ja_desejou_hoje = False
            while True:
                agora = datetime.datetime.now()
                hh, mm = agora.hour, agora.minute
                dentro = (hh == 22 and mm >= 50) or (hh == 23 and mm <= 50)

                # meia-noite virou → pode desejar de novo amanhã
                if hh == 0 and mm < 5:
                    ja_desejou_hoje = False

                if dentro and not ja_desejou_hoje:
                    import emotions as _emotions
                    ja_desejou_hoje = True
                    try:
                        jarvis_voice.falar(_emotions.obter_fala_humor("boa_noite"))
                    except Exception:
                        jarvis_voice.falar("Boa noite, chefe. Eu fico de olho.")
                    print("[BRAIN] Boa noite agendado falado (22:50–23:50).")
                time.sleep(30.0)

        threading.Thread(target=_vigiar, daemon=True).start()

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

        # [DEV-AGENT] aguardando aprovação de código — só sim/não passam
        if _dev_agent.aguardando_aprovacao():
            if intencao == "confirmar_sim":
                _dev_agent.responder_aprovacao(True)
            elif intencao == "confirmar_nao":
                _dev_agent.responder_aprovacao(False)
            else:
                jarvis_voice.falar("Esperando um sim ou não sobre o código, chefe.")
            return

        # [ORBS] anuncia o módulo em ação ao enxame (expira sozinho em ~5s)
        if intencao.startswith("phone_"):
            _orbs.anunciar("phone")
        else:
            _orbs.anunciar(_MODULO_DA_INTENCAO.get(intencao))

        # Intenções de celular roteadas ao módulo dedicado
        if intencao.startswith("phone_"):
            _phone_commands.executar_por_voz(intencao, texto_bruto)
            return

        # Intenções de janela roteadas ao módulo dedicado
        if intencao.startswith("janela_"):
            _window.executar_por_voz(intencao, texto_bruto)
            return

        # [v4-SESSAO] "só isso" → resposta curta, sessão encerrada
        if intencao == "encerrar_sessao":
            jarvis_voice.falar(random.choice([
                "Fechado. Grita meu nome quando precisar.",
                "Tranquilo. Volto pro canto e fico de olho.",
                "É isso. Jasper fora do ar até a próxima chamada.",
                "Beleza, chefe. Fico no aguardo.",
                "Mais nada então. Estou aqui se pintar algo.",
            ]))
            return

        # [ALARM] parar o despertador — vale SEMPRE (também dentro do modo dev)
        if intencao == "despertador_parar":
            import alarm as _alarm
            if _alarm.despertador_tocando():
                _alarm.parar_despertador()
                jarvis_voice.falar(random.choice([
                    "Bom dia de verdade então, chefe. Desligando o alarme.",
                    "Alarme desligado. Que o dia seja merecido.",
                    "Certo, chefe. Alarme parado — eu paro o som, você faz o resto.",
                ]))
            else:
                jarvis_voice.falar("O despertador nem tá tocando, chefe.")
            return

        # [v7-DEV] dentro do modo dev, o brain controla o fluxo —
        # NADA passa pro interpretador comum (zero conflito com
        # 'pesquisar', 'criar imagem' etc). Só sai por dev_sair.
        if self.modo_dev_ativo:
            self._processar_modo_dev(intencao, texto_bruto)
            return

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
            "saudacao":              "_voz_saudacao",
            "saudacao_bom_dia":      "_voz_saudacao_humor",
            "saudacao_boa_tarde":    "_voz_saudacao_humor",
            "saudacao_boa_noite":    "_voz_saudacao_humor",
            "saudacao_tudo_bem":     "_voz_saudacao_tudo_bem",
            "quem_sou_eu":           "_voz_quem_sou_eu",
            "clima_agora":        "_voz_clima_agora",
            "clima_hoje":         "_voz_clima_hoje",
            "timer_criar":        "_voz_timer_criar",
            "timer_cancelar":     "_voz_timer_cancelar",
            "timer_status":       "_voz_timer_status",
            "abrir_navegador":    "_voz_abrir_programa",
            "pesquisar":          "_voz_pesquisar",
            "ver":                "_voz_ver",
            "foto":               "_voz_foto",
            "identificar_objeto": "_voz_identificar_objeto",
            "youtube":            "_voz_youtube",
            # [NOVO-v3]
            "instagram":          "_voz_instagram",
            "mario64":            "_voz_mario64",
            "memoria":            "_voz_memoria",
            "nota_criar":         "_voz_nota_criar",
            "nota_lembrar":       "_voz_nota_lembrar",
            "nota_listar":        "_voz_nota_listar",
            "nota_apagar":        "_voz_nota_apagar",
            "gravacao_iniciar":   "_voz_gravacao_iniciar",
            "gravacao_cancelar":  "_voz_gravacao_cancelar",
            "file_find":          "_voz_file_find",
            "file_open":          "_voz_file_open",
            "file_list":          "_voz_file_list",
            "chat_zai":           "_voz_chat_zai",
            "imagem_criar":       "_voz_imagem",   
            "dev_codigo":         "_voz_dev_codigo",
            "Atualizar_sistema":  "_voz_atualizar_sistema",
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
            jarvis_voice.falar(random.choice([
                f"Relógio na mão: {hora_str}. Algo mais ou só a hora?",
                f"{hora_str} em ponto. O tempo não espera, chefe.",
                f"São {hora_str}. Anota aí que eu não vou repetir.",
            ]))
            return

        # ---------------------------------------------------------------
        # [v5] SAUDAÇÕES — por horário E humor + QUEM É VOCÊ (Groq)
        # ---------------------------------------------------------------
        if cmd == "_voz_saudacao":
            jarvis_voice.falar(_personality.gerar_resposta(
                categoria="saudacao", contexto={}))
            return

        if cmd == "_voz_saudacao_humor":
            import emotions as _emotions
            import datetime as _dt
            hora = _dt.datetime.now().hour
            if 5 <= hora < 12:
                chave = "bom_dia"
            elif 12 <= hora < 18:
                chave = "boa_tarde"
            else:
                chave = "boa_noite"
            jarvis_voice.falar(_emotions.obter_fala_humor(chave))
            return

        if cmd == "_voz_saudacao_tudo_bem":
            import emotions as _emotions
            import random as _rd
            chave = _rd.choice(["tudo_bem", "como_ta"])
            jarvis_voice.falar(_emotions.obter_fala_humor(chave))
            return

        if cmd == "_voz_quem_sou_eu":
            # [v5-IDENTIDADE] Groq com prompt-padrão descritivo do sistema,
            # resposta no tom da personalidade. Sem token/erro → fallback
            # local que também explica (nunca fica mudo).
            import emotions as _emotions
            def _identidade():
                try:
                    from utilities import _get_groq_client, GROQ_MODELO, GROQ_TEMPERATURA
                    cliente = _get_groq_client()
                    resp = cliente.chat.completions.create(
                        model=GROQ_MODELO,
                        messages=[
                            {"role": "system", "content": PROMPT_QUEM_SO_EU},
                            {"role": "user",   "content": "Quem é você?"},
                        ],
                        temperature=GROQ_TEMPERATURA,
                        max_tokens=150,
                    ).choices[0].message.content.strip()
                    if resp:
                        jarvis_voice.falar(resp)
                        return
                    # resposta vazia = falha silenciosa → fallback
                except Exception as e:
                    print(f"[BRAIN] Identidade: Groq falhou ({e}) — fallback local")
                # FALLBACK offline — sem tokens, sem internet, sempre funciona
                humor = _emotions.jarvis_emotions.modo_visual.lower()
                jarvis_voice.falar(random.choice([
                    "Sou o Jasper, chefe — seu assistente local. Ouço, falo, vejo pela "
                    "webcam, controlo o PC e o celular, pesquiso e lembro das conversas. "
                    f"Esta hora estou {humor}, mas funcional como sempre.",
                    "Jasper: assistente pessoal rodando nesse PC. Voz, visão, controle "
                    "de máquina e de celular, memória e um humor que muda. "
                    "Basicamente, o morador digital daqui.",
                ]))
            threading.Thread(target=_identidade, daemon=True).start()
            return

        # ---------------------------------------------------------------
        # CLIMA AGORA (thread)
        # ---------------------------------------------------------------
        if cmd == "_voz_clima_agora":
            resposta_acao = _resposta_jarvis("clima", {"acao": "consultar"})
            jarvis_voice.falar(resposta_acao)

            def _buscar():
                jarvis_voice.falar(obter_clima())
            threading.Thread(target=_buscar, daemon=True).start()
            return

        # ---------------------------------------------------------------
        # PREVISÃO DO DIA (thread)
        # ---------------------------------------------------------------
        if cmd == "_voz_clima_hoje":
            resposta_acao = _resposta_jarvis("clima", {"acao": "consultar_previsao"})
            jarvis_voice.falar(resposta_acao)

            def _buscar():
                jarvis_voice.falar(obter_previsao_hoje())
            threading.Thread(target=_buscar, daemon=True).start()
            return

        # ---------------------------------------------------------------
        # TIMERS
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

        if cmd == "_voz_timer_cancelar":
            jarvis_voice.falar(cancelar_timers())
            return

        if cmd == "_voz_timer_status":
            jarvis_voice.falar(status_timers())
            return

        # ---------------------------------------------------------------
        # ABRIR NAVEGADOR
        # ---------------------------------------------------------------
        if cmd == "_voz_abrir_programa":
            jarvis_voice.falar(_resposta_jarvis("acao_andamento", {"acao": "abrir navegador"}))
            subprocess.Popen(_detectar_browser())
            return

        # ---------------------------------------------------------------
        # NOTAS E LEMBRETES
        # ---------------------------------------------------------------
        if cmd == "_voz_nota_criar":
            jarvis_voice.falar(_notes.criar_nota(texto_bruto))
            return

        if cmd == "_voz_nota_lembrar":
            jarvis_voice.falar(_notes.criar_lembrete(texto_bruto))
            return

        if cmd == "_voz_nota_listar":
            jarvis_voice.falar(_notes.listar_notas())
            return

        if cmd == "_voz_nota_apagar":
            jarvis_voice.falar(_notes.apagar_nota(texto_bruto))
            return

        # ---------------------------------------------------------------
        # GRAVAÇÃO DE CÂMERA
        # ---------------------------------------------------------------
        if cmd == "_voz_gravacao_iniciar":
            jarvis_voice.falar(_recording.iniciar_gravacao())
            return

        if cmd == "_voz_gravacao_cancelar":
            jarvis_voice.falar(_recording.cancelar_gravacao())
            return

        # ---------------------------------------------------------------
        # ARQUIVOS
        # ---------------------------------------------------------------
        if cmd == "_voz_file_find":
            jarvis_voice.falar(_file_manager.buscar_arquivo(texto_bruto))
            return

        if cmd == "_voz_file_open":
            jarvis_voice.falar(_file_manager.abrir_arquivo(texto_bruto))
            return

        if cmd == "_voz_file_list":
            jarvis_voice.falar(_file_manager.listar_arquivos_pasta(texto_bruto))
            return

        # ---------------------------------------------------------------
        # MEMÓRIA (thread)
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
        # YOUTUBE
        # ---------------------------------------------------------------
        if cmd == "_voz_youtube":
            _GATILHOS = [
                "jarvis", "jasper", "pesquisa no youtube", "pesquise no youtube",
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
                if _personality:
                    resposta = _personality.gerar_resposta(
                        categoria="aguardando",
                        contexto={"tipo": "termo para procurar no YouTube"}
                    )
                else:
                    resposta = "O que quer que eu procure no YouTube, senhor?"
                jarvis_voice.falar(resposta)
                return

            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(termo)}"
            print(f"[BRAIN] YouTube → '{termo}'")

            if _personality:
                resposta = _personality.gerar_resposta(
                    categoria="acao_andamento",
                    contexto={"acao": "procurar_youtube", "termo": termo}
                )
            else:
                resposta = f"Procurando {termo} no YouTube, senhor."
            jarvis_voice.falar(resposta)
            subprocess.Popen(_detectar_browser() + [url])
            return

        # ---------------------------------------------------------------
        # [NOVO-v3] INSTAGRAM — abre o direct/inbox
        # ---------------------------------------------------------------
        if cmd == "_voz_instagram":
            jarvis_voice.falar(random.choice([
                "Abrindo o direct do Instagram, senhor.",
                "Instagram abrindo, senhor.",
                "Abrindo as mensagens, senhor.",
            ]))
            subprocess.Popen(_detectar_browser() + [URL_INSTAGRAM_DM])
            return

        # ---------------------------------------------------------------
        # [NOVO-v3] SUPER MARIO 64 — roda o sm64coopdx.exe via wine
        # ---------------------------------------------------------------
        if cmd == "_voz_mario64":
            exe = os.path.join(PASTA_MARIO64, EXE_MARIO64)
            if not os.path.exists(exe):
                print(f"[BRAIN] Mario não encontrado em: {exe}")
                jarvis_voice.falar("Não encontrei o executável do Mario, senhor.")
                return
            jarvis_voice.falar(random.choice([
                "Iniciando o Super Mario 64, senhor. Boa partida.",
                "Ligando o Mario 64. Boa caçada às estrelas, senhor.",
                "Mario 64 iniciando, senhor.",
            ]))
            try:
                # cwd = pasta do jogo (o sm64coopdx precisa das DLLs ao lado)
                subprocess.Popen(["wine", EXE_MARIO64], cwd=PASTA_MARIO64)
            except FileNotFoundError:
                jarvis_voice.falar("O wine não está instalado, senhor.")
            return

        # ---------------------------------------------------------------
        # [NOVO-v3] CHAT DA Z.AI — estilo YouTube: extrai a pergunta
        # ---------------------------------------------------------------
        if cmd == "_voz_chat_zai":
            _GATILHOS_CHAT = [
                "abre o chat da zai e pede", "abre o chat da zai e pergunta",
                "abre o chat da zai", "abrir o chat da zai", "chat da zai",
                "abre o chat e pede", "abre o chat e pergunta",
                "abre o chat", "abrir o chat", "pergunta pra zai",
                "pergunta para a zai", "pede pra zai", "pede para a zai",
                "pede no chat", "pergunta no chat", "abre a zai",
                "abrir a zai", "abre a conversa da zai", "abre a conversa",
                "fala com a zai", "e pede", "e pergunta", "pede",
                "pergunta", "zai", "chat",
            ]
            pergunta = texto_bruto.lower().strip()
            for g in sorted(_GATILHOS_CHAT, key=len, reverse=True):
                pergunta = pergunta.replace(g, " ").strip()
            # [FIX] "jarvis"/"jasper" só do INÍCIO (resíduo da wake word) —
            # remover de qualquer lugar apagaria o CONTEÚDO de perguntas
            # sobre o JARVIS
            if pergunta.startswith(("jarvis", "jasper")):
                for prefixo in ("jarvis", "jasper"):
                    if pergunta.startswith(prefixo):
                        pergunta = pergunta[len(prefixo):].strip()
                        break
            # [SEM-REGEX] limpeza de bordas com charset, não regex
            pergunta = " ".join(pergunta.split()).strip(" ,.;:-")

            if not pergunta:
                _focar_janela_jarvis()
                jarvis_voice.falar("Abrindo o chat, chefe.")
                subprocess.Popen(_detectar_browser() + [URL_CHAT_ZAI])
            else:
                _focar_janela_jarvis()
                jarvis_voice.falar("Abrindo o chat com a sua pergunta pronta, chefe.")
                _abrir_chat_com_pergunta(pergunta)
            return

        # ---------------------------------------------------------------
        # [v8.1] ATUALIZAR SISTEMA — sudo -S com senha do .env, SEM janela
        # ---------------------------------------------------------------
        if cmd == "_voz_atualizar_sistema":
            from config import SENHA_SUDO
            if not SENHA_SUDO:
                jarvis_voice.falar("Configura a SENHA_SUDO no arquivo ponto env, "
                                   "chefe. Aí eu atualizo sozinho.")
                return

            jarvis_voice.falar(random.choice([
                "Atualizando o sistema. Pode levar alguns minutos, chefe.",
                "Manutenção em andamento. Te aviso quando terminar.",
                "Puxando as atualizações. Nada de digitar senha dessa vez.",
            ]))

            def _executar_update():
                try:
                    r1 = subprocess.run(
                        ["sudo", "-S", "apt", "update"],
                        input=SENHA_SUDO + "\n", capture_output=True,
                        text=True, timeout=600)
                    r2 = subprocess.run(
                        ["sudo", "-S", "apt", "upgrade", "-y"],
                        input=SENHA_SUDO + "\n", capture_output=True,
                        text=True, timeout=3600)

                    if r1.returncode != 0 or r2.returncode != 0:
                        # senha errada → stderr do sudo; erro apt → stderr do apt
                        err = ((r1.stderr or "") + (r2.stderr or "")).strip().splitlines()
                        motivo = err[-1] if err else "erro desconhecido"
                        print(f"[BRAIN] Update falhou: {motivo}")
                        jarvis_voice.falar("A atualização falhou, chefe. "
                                           f"Motivo: {motivo[:120]}")
                        return

                    # [SEM-REGEX] resumo: última linha do apt com contagem
                    resumo = ""
                    for linha in (r2.stdout or "").splitlines():
                        low = linha.lower()
                        if "upgrad" in low or "atualizad" in low or "instalad" in low:
                            resumo = linha.strip()

                    print(f"[BRAIN] Sistema atualizado: {resumo}")
                    if resumo:
                        jarvis_voice.falar(f"Atualização concluída, chefe. {resumo}.")
                    else:
                        jarvis_voice.falar("Sistema atualizado, chefe. Tudo em dia.")
                except subprocess.TimeoutExpired:
                    jarvis_voice.falar("A atualização demorou demais e abortei, chefe.")
                except Exception as e:
                    print(f"[BRAIN] ERRO update: {e}")
                    jarvis_voice.falar("Deu ruim na atualização, chefe. Log no terminal.")

            threading.Thread(target=_executar_update, daemon=True).start()
            return
        # ---------------------------------------------------------------
        # [v6-IMG] GERAR IMAGEM — extrai o pedido (SEM regex) e gera
        # ---------------------------------------------------------------
        if cmd == "_voz_imagem":
            # [SEM-REGEX] extração por replace de gatilhos — mesmo padrão
            # do YouTube/chat_zai, nada de expressão regular
            _GATILHOS_IMG = [
                "jasper", "jarvis",
                "cria uma imagem de", "criar uma imagem de", "cria imagem de",
                "gera uma imagem de", "gerar uma imagem de", "gera imagem de",
                "faz uma imagem de", "fazer uma imagem de", "faz imagem de",
                "desenha uma imagem de", "desenhar uma imagem de",
                "cria uma imagem", "criar uma imagem", "cria imagem",
                "gera uma imagem", "gerar uma imagem", "gera imagem",
                "faz uma imagem", "fazer uma imagem", "faz imagem",
                "uma imagem de", "imagem de", "imagem",
                "cria", "criar", "gera", "gerar", "faz", "desenha", "desenhar",
                "por favor",
            ]
            pedido = texto_bruto.lower().strip()
            for g in sorted(_GATILHOS_IMG, key=len, reverse=True):
                pedido = pedido.replace(g, " ")
            # [SEM-REGEX] limpeza de bordas com charset (strip, não regex)
            pedido = " ".join(pedido.split()).strip(" ,.;:-")

            if not pedido:
                jarvis_voice.falar("Imagem de quê, chefe? Me dá o cenário.")
                return
            # [FIX] pedido residual sem sentido (1 palavra comum) — não gera
            if len(pedido.split()) < 2 or pedido in ("de", "da", "do", "um", "uma"):
                jarvis_voice.falar("Imagem de quê, chefe? Fala o cenário direito.")
                return

            print(f"[BRAIN] Imagem → '{pedido}'")
            jarvis_voice.falar(random.choice([
                "Pintura a caminho. Isso leva uns segundos, chefe.",
                "Galerinha de pixels trabalhando. Logo abre.",
                "Criando. Café enquanto a arte seca.",
                "Analisando seu pedido artístico... e gerando.",
                "Imagem saindo do forno digital. Segura a ansiedade.",
            ]))

            def _executar():
                jarvis_voice.falar(_image_gen.gerar_imagem(pedido))
            threading.Thread(target=_executar, daemon=True).start()
            return                                      # ← fim real do bloco imagem

            # [FIX] "jarvis" só do INÍCIO (resíduo da wake word) — remover de
            # qualquer lugar apagaria o CONTEÚDO de perguntas sobre o JARVIS
            if pergunta.startswith(("jarvis", "jasper")):
                pergunta = pergunta[len("jarvis"):].strip() if pergunta.startswith("jarvis") \
                    else pergunta[len("jasper"):].strip()

            if not pergunta:
                _focar_janela_jarvis()
                jarvis_voice.falar("Abrindo o chat, chefe.")
                subprocess.Popen(_detectar_browser() + [URL_CHAT_ZAI])
            else:
                _focar_janela_jarvis()
                jarvis_voice.falar(
                    "Abrindo o chat com a sua pergunta pronta, chefe."
                )
                _abrir_chat_com_pergunta(pergunta)
            return

        # ---------------------------------------------------------------
        # [DEV-AGENT] CRIAÇÃO/ALTERAÇÃO DE CÓDIGO
        # ---------------------------------------------------------------
        if cmd == "_voz_dev_codigo":
            _GATILHOS_DEV = [
                "jarvis", "jasper",
                "modo dev ativado", "entrar em modo dev", "modo desenvolvedor",
                "entrar no modo desenvolvedor", "ativar modo dev",
                "ativa o modo dev", "liga o modo dev", "modo programador",
                "entrar em modo programador", "iniciar modo dev",
                "começa o modo dev", "modo código", "entrar em modo código",
                "modo dev",
            ]
            pedido = texto_bruto.lower().strip()
            for g in sorted(_GATILHOS_DEV, key=len, reverse=True):
                pedido = pedido.replace(g, " ")
            pedido = " ".join(pedido.split()).strip(" ,.;:-")

            self.modo_dev_ativo = True
            if pedido:
                # já veio com pedido ("modo dev: fazer X") — direto à entrevista
                self._processar_modo_dev("", texto_bruto)
            else:
                jarvis_voice.falar(random.choice([
                    "Modo dev ligado, chefe. Me diz o que você quer construir ou mudar.",
                    "Certo, chapéu de programador vestido. Qual é a missão?",
                    "Modo dev ativo. Vamos por partes: o que você precisa?",
                ]))
            return

        # ---------------------------------------------------------------
        # VISÃO — DESCREVER CENA
        # ---------------------------------------------------------------
        if cmd == "_voz_ver":
            _GATILHOS_VER = [
                "jarvis", "o que você vê", "o que está vendo", "o que vê",
                "descreve o que vê", "descreves a cena", "descreve a cena", "descreve o ambiente",
                "o que tem na câmera", "o que aparece na câmera",
                "o que está na câmera", "olha pela câmera",
                "analisa a imagem", "analisa o que vê", "analisa isso",
                "veja isso", "olha isso", "me diz o que vê",
                "o que está acontecendo aí", "o que está na frente",
                "descreve o que está à sua frente", "o que está aqui",
                "tem alguém aí", "tem alguém aqui", "quem está aí",
                "quem está aqui", "o que está na minha frente",
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
        # FOTO
        # ---------------------------------------------------------------
        if cmd == "_voz_foto":
            jarvis_voice.falar(random.choice([
                "Sorria, vou tirar uma foto sua.",
                "Deixa eu registrar esse momento, um segundo.",
                "Foto na conta de três... na verdade já tirei.",
                "Vou bater uma foto rapidinho, senhor.",
                "Diz xis, tirando a foto agora.",
            ]))

            _PROMPT_FOTO = (
                "Olhe para esta imagem e analise a roupa e o visual da pessoa "
                "que aparece. Dê uma opinião sincera e direta sobre o estilo, "
                "pode ser elogio ou crítica, sem papas na língua, como um amigo "
                "bem-humorado falaria. Se fizer sentido sugira uma melhoria, "
                "mas não é obrigatório. Ignore o cenário ao fundo. Responda em "
                "no máximo 3 frases em português, sem mencionar que está "
                "analisando uma imagem ou fazendo qualquer tipo de análise — "
                "fale como se estivesse simplesmente comentando o look."
            )

            def _executar():
                jarvis_voice.falar(analisar_frame(_PROMPT_FOTO))
                _abrir_ultima_foto()
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
                "Ignore o cenário ao fundo. Responda em no máximo 3 frases em português."
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
        # PESQUISA / IA (Groq) — com roteamento pro chat da Z.ai
        # ---------------------------------------------------------------
        if cmd == "_voz_pesquisar":
            _GATILHOS_IA = [
                "jarvis", "jasper", "pesquisa", "pesquise", "pesquisar",
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

            # [CHAT-ZAI] Perguntas sobre o JARVIS/código vão pro chat (onde
            # vive o contexto do projeto) em vez do Groq genérico. A checagem
            # é no texto BRUTO (o termo limpo perde a palavra "jarvis").
            # Desative com CHAT_ZAI_ROTEIA_PESQUISA = False se irritar.
            if CHAT_ZAI_ROTEIA_PESQUISA and \
                    any(p in texto_bruto.lower() for p in _ROTEAR_CHAT):
                jarvis_voice.falar(
                    "Essa pergunta é melhor pro meu chat, senhor. "
                    "Abrindo com ela pronta."
                )
                _abrir_chat_com_pergunta(termo)
                return

            jarvis_voice.falar(random.choice(VozIAPesquisando))

            def _executar():
                print(f"[BRAIN] IA → '{termo}'")
                jarvis_voice.falar(perguntar_ia(termo))
            threading.Thread(target=_executar, daemon=True).start()
            return

        # ---------------------------------------------------------------
        # COMANDOS QUE MAPEIAM PARA GESTOS
        # ---------------------------------------------------------------
        print(f"[BRAIN] Executando via voz: '{cmd}' (intenção: {intencao})")
        self.process_command(cmd, cap_ref=None)

    # -------------------------------------------------------------------
    # [v7-DEV] MODO DEV — fluxo de perguntas da IA antes de executar
    # -------------------------------------------------------------------

    def _processar_modo_dev(self, intencao: str, texto_bruto: str):
        """
        Dentro do modo dev: cada frase do usuário alimenta o contexto.
        A IA (Groq) decide: precisa de mais informação (gera a próxima
        pergunta) ou já dá o veredito (gera código | explica | rejeita).
        Só sai do modo por 'dev_sair' ou quando o dev_agent é chamado.
        """
        # 1) saída do modo
        if intencao == "dev_sair":
            self.modo_dev_ativo = False
            jarvis_voice.falar(random.choice([
                "Saindo do modo dev. Volto a ser só o assistente charmoso.",
                "Modo dev encerrado. Nada foi tocado sem sua ordem.",
            ]))
            return

        # 2) coleta o que foi dito e pede à Groq a próxima pergunta/veredito
        def _consultar_ia():
            try:
                from utilities import _get_groq_client, GROQ_MODELO
                cliente = _get_groq_client()
                resp = (cliente.chat.completions.create(
                    model=GROQ_MODELO,
                    messages=[{"role": "user", "content": (
                        "Você conduz uma entrevista de requisitos técnicos dentro "
                        "do JASPER (assistente Python/Linux). O usuário está no "
                        "modo dev descrevendo o que quer que seja programado.\n\n"
                        "REGRAS:\n"
                        "- Se a informação ainda não basta para programar, faça "
                        "UMA pergunta objetiva de sim/não ou de escolha curta "
                        "(máximo 2 frases).\n"
                        "- Se a informação já basta, responda EXATAMENTE com "
                        "'PRONTO:' seguido de um pedido de programação completo "
                        "e detalhado em uma frase corrida.\n"
                        "- Se o pedido for impossível/fora de escopo (hardware, "
                        "não é código), responda 'FORA:' e uma frase explicando.\n\n"
                        f"Última frase do usuário: {texto_bruto}\n"
                        "Responda no formato indicado.")}],
                    temperature=0.3,
                    max_tokens=120,
                ).choices[0].message.content or "").strip()

                # [FIX-VAZIA] gpt-oss às vezes queima tokens 'pensando' e
                # devolve vazio (o [VOZ]: mudo do log) — 1 retry
                if not resp:
                    print("[BRAIN] Modo dev: resposta vazia — tentando de novo...")
                    resp = (cliente.chat.completions.create(
                        model=GROQ_MODELO,
                        messages=[{"role": "user", "content": (
                            "Entrevista de requisitos. Responda em UMA frase: a "
                            "próxima pergunta de sim/não, ou 'PRONTO: <pedido "
                            "completo>', ou 'FORA: <motivo>'.\n"
                            f"Última frase do usuário: {texto_bruto}")}],
                        temperature=0.3,
                        max_tokens=120,
                    ).choices[0].message.content or "").strip()
                if not resp:
                    jarvis_voice.falar("A IA de requisitos ficou muda nessa. "
                                       "Repete a última frase, chefe.")
                    return

                # veredito da entrevista — AQUI, no nível certo
                if resp.startswith("PRONTO:"):
                    self.modo_dev_ativo = False
                    pedido_final = resp[6:].strip()
                    jarvis_voice.falar("Requisitos fechados. Chamando o agente de código.")
                    _dev_agent.criar_codigo(pedido_final)
                elif resp.startswith("FORA:"):
                    jarvis_voice.falar(resp[5:].strip()[:200] +
                                       " Reformula aí, ou pede pra sair do modo dev.")
                else:
                    # pergunta da entrevista — fala e espera a próxima frase
                    jarvis_voice.falar(resp[:200])
            except Exception as e:
                print(f"[BRAIN] Modo dev: Groq falhou ({e})")
                jarvis_voice.falar("A IA de requisitos Travou. Saindo do modo dev "
                                   "— chama o agente de código direto se quiser.")
                self.modo_dev_ativo = False

        threading.Thread(target=_consultar_ia, daemon=True).start()

    # -------------------------------------------------------------------
    # EXECUÇÃO DE COMANDOS (gestos + voz mapeada)
    # -------------------------------------------------------------------

    def process_command(self, cmd, cap_ref):
        if cmd == "Encerrar":
            jarvis_voice.falar_sincronizado(random.choice(VozEncerrar))
            os.system("poweroff")
        elif cmd == "Rock":
            # [FIX-v3] era _personality.gerar_resposta_jarvis (método
            # INEXISTENTE → AttributeError ao abrir o editor por gesto)
            resposta_acao = _resposta_jarvis(
                "acao_andamento", {"acao": "abrir_editor_codigo"}
            )
            jarvis_voice.falar(resposta_acao)
            os.system("code")
        elif cmd == "Mute":
            os.system("pactl set-sink-mute @DEFAULT_SINK@ toggle")
            self.mute_ativo = not self.mute_ativo
            jarvis_voice.falar(_resposta_jarvis("status", {"info": "som " + ("silenciado" if self.mute_ativo else "ligado")}))
            self.last_toggle_time = time.time()
        elif cmd == "2":
            def _conectar_womic():
                subprocess.run(
                    ["sudo", "-S", "modprobe", "snd-aloop"],
                    input="@Qnp09c49\n",
                    capture_output=True,
                    text=True
                )
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
        elif cmd == "scroll_down":
            jarvis_voice.falar(random.choice([
                "Descendo a página, senhor",
                "Rolando pra baixo",
                "Scroll down",
            ]))
            pyautogui.scroll(-400)   # negativo = para baixo
        elif cmd == "scroll_up":
            jarvis_voice.falar(random.choice([
                "Subindo a página, senhor",
                "Rolando pra cima",
                "Scroll up",
            ]))
            pyautogui.scroll(400)    # positivo = para cima
        elif cmd == "DB":
            jarvis_voice.falar("Tela cheia, senhor")
            pyautogui.press("f")
        elif cmd == "9":
            jarvis_voice.falar_sincronizado(random.choice(VozSairJarvis))
            if cap_ref:
                cap_ref.release()
            import cv2
            cv2.destroyAllWindows()
            os._exit(0)
        elif cmd == "Pause":
            jarvis_voice.falar(random.choice(VozGPause))
            pyautogui.press("space")
        elif cmd == "Next":
            jarvis_voice.falar(random.choice(VozGNext))
            pyautogui.hotkey("shift", "n")

        # [EXEMPLO-GESTO] Gesto → comando novo (exemplo pronto p/ ativar):
        # 1) main.py: descomente o gesto "IG" (polegar + mindinho estendidos,
        #    os demais dobrados — um "shaka") na cadeia de detecção.
        # 2) Descomente o elif abaixo — ele abre o Instagram:
        # elif cmd == "IG":
        #     jarvis_voice.falar("Abrindo o Instagram, senhor.")
        #     subprocess.Popen(_detectar_browser() + [URL_INSTAGRAM_DM])

        GESTOS_REPETIVEIS = {"clique", "1", "2", "8", "Pause", "Next",
                              "scroll_down", "scroll_up"}
        if cmd in GESTOS_REPETIVEIS:
            self.ultimo_gesto = None

# Instância global
jarvis_brain = Brain()
print("[BRAIN] Gestos bloqueados no boot — gesto 6 desbloqueia quando quiser.")
