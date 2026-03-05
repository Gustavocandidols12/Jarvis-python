"""
INTEGRAÇÃO listen.py → brain.py e main.py
==========================================
Copie os trechos abaixo para os respectivos arquivos.
"""

# ══════════════════════════════════════════════════════════════
# TRECHO 1 — brain.py
# Adicionar no import e no final da classe Brain
# ══════════════════════════════════════════════════════════════

# --- IMPORTS (topo de brain.py) ---
# Nenhum import novo necessário. O listen.py chama execute_voice_command()
# diretamente como callback.

# --- MÉTODO NOVO na classe Brain ---
# Adicionar após o método process_command():

"""
    def execute_voice_command(self, intencao: str, texto_bruto: str):
        \"\"\"
        Callback registrado pelo listen.py.
        Recebe a intenção identificada e a mapeia para ações do sistema.
        Mantém os mesmos bloqueios e debounces do fluxo de gestos.

        Parâmetros:
            intencao   — ID da intenção (chave em INTENCOES, ex: "volume_up")
            texto_bruto — texto transcrito original para debug/log
        \"\"\"

        # Mapeamento: intenção de voz → comando equivalente ao gesto
        MAPA_INTENCAO_COMANDO = {
            "volume_up":      "2",
            "volume_down":    "1",
            "mute":           "Mute",
            "unmute":         "Mute",          # toggle, mesmo gesto
            "play_pause":     "Pause",
            "proximo":        "Next",
            "abrir_editor":   "Rock",
            "tela_cheia":     "DB",
            "recarregar":     "8",
            "clique":         "clique",
            "encerrar":       "Encerrar",
            "sair_jarvis":    "9",
            "voz_ligar":      "3",
            "voz_desligar":   "4",
            "mouse_ligar":    "7",
            "mouse_desligar": "7",             # toggle, mesmo gesto
            "hora":           "_voz_hora",     # comando exclusivo de voz (abaixo)
            "saudacao":       "_voz_saudacao",
        }

        cmd = MAPA_INTENCAO_COMANDO.get(intencao)
        if not cmd:
            print(f"[BRAIN] Intenção '{intencao}' sem mapeamento de ação.")
            return

        # Comandos exclusivos de voz (não existem como gestos)
        if cmd == "_voz_hora":
            import datetime
            hora_str = datetime.datetime.now().strftime("%H:%M")
            jarvis_voice.falar(f"São exatamente {hora_str}, senhor.")
            return

        if cmd == "_voz_saudacao":
            jarvis_voice.falar("Olá. Sistemas online e prontos.")
            return

        # Reutiliza o fluxo normal de gestos (com todos os bloqueios)
        # cap_ref não é necessário para comandos de voz — passa None
        print(f"[BRAIN] Executando via voz: '{cmd}' (intenção: {intencao})")
        self.execute(cmd, cap_ref=None)
"""


# ══════════════════════════════════════════════════════════════
# TRECHO 2 — main.py
# Adicionar no topo (imports) e dentro da função main()
# ══════════════════════════════════════════════════════════════

# --- IMPORTS (topo de main.py) ---
"""
from listen import jarvis_listen
"""

# --- DENTRO de main(), logo após "print("JARVIS SYSTEM: INICIANDO...")" ---
"""
    # Registra o callback de voz no Brain e inicia o listener
    jarvis_listen.registrar_callback(jarvis_brain.execute_voice_command)
    jarvis_listen.start()
"""

# --- DENTRO do loop while (após atualizar animação de fala) ---
# Pausa o listener enquanto o JARVIS está falando (evita capturar a própria voz TTS)
"""
    jarvis_listen.pausado = jarvis_voice.boca_falando
"""

# --- Ao encerrar (após cap.release()) ---
"""
    jarvis_listen.stop()
"""
