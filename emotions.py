
"""
FILE: emotions.py
DESCRIPTION: Gerencia os estados emocionais e gatilhos baseados em horários (Café, Estudo, Sono).
"""
import time
import datetime
import random
from config import *
from voice import jarvis_voice

class EmotionalSystem:
    def __init__(self):
        self.modo_visual = "NORMAL"
        self.ultimo_evento_disparado = ""
        self.tempo_inicio_emocao = 0
        self.saudacao_manha_dada = False
        self.acenando_manha = False
        self.tempo_inicio_aceno = 0
        self.dormindo = False
        self.tempo_acordou_noite = 0

    def update(self, hand_detected):
        tempo_agora = time.time()
        now = datetime.datetime.now()
        hora_atual = now.hour
        hora_minuto_str = now.strftime("%H:%M")

        # --- GATILHOS TEMPORAIS ---
        self.check_trigger(hora_minuto_str, "13:25", "hora_do_cafe", "Hora do café, senhor. Níveis de cafeína críticos.", "CAFE")
        self.check_trigger(hora_minuto_str, "11:35", "hora_estudo", "Hora de estudar, senhor. conhecimento nunca é demais.", "ESTUDO")

        # Reset Automático de Modos
        tempo_passado = tempo_agora - self.tempo_inicio_emocao
        if self.modo_visual == "ESTUDO":
            if tempo_passado > 1500: # 25 min
                self.modo_visual = "NORMAL"
                jarvis_voice.falar("Modo estudo finalizado, senhor.")
        elif self.modo_visual != "NORMAL":
            if tempo_passado > DURACAO_EMOCAO:
                self.modo_visual = "NORMAL"

        # Lógica de Saudação
        is_manha = 6 <= hora_atual < 9
        if is_manha and not self.saudacao_manha_dada and hand_detected:
            jarvis_voice.falar(random.choice(VozBomDia))
            self.saudacao_manha_dada = True
            self.acenando_manha = True
            self.tempo_inicio_aceno = tempo_agora
        elif not is_manha:
            self.saudacao_manha_dada = False

        if self.acenando_manha and (tempo_agora - self.tempo_inicio_aceno > DURACAO_ACENO):
            self.acenando_manha = False

        # Lógica de Sono (Noite)
        is_noite = 19 <= hora_atual or hora_atual < 6
        if is_noite:
            if not self.dormindo and self.tempo_acordou_noite != 0 and (tempo_agora - self.tempo_acordou_noite > DURACAO_INTERACAO_NOITE):
                self.dormindo = True
            elif jarvis_voice.boca_falando and self.dormindo:
                self.dormindo = False
                self.tempo_acordou_noite = tempo_agora
            elif self.tempo_acordou_noite == 0:
                self.dormindo = True
        else:
            self.dormindo = False
            self.tempo_acordou_noite = 0

    def check_trigger(self, current_time, target_time, trigger_id, speech, visual_mode):
        if current_time == target_time and self.ultimo_evento_disparado != trigger_id:
            jarvis_voice.falar(speech)
            self.modo_visual = visual_mode
            self.tempo_inicio_emocao = time.time()
            self.ultimo_evento_disparado = trigger_id
        
        if self.ultimo_evento_disparado == trigger_id and current_time != target_time:
            self.ultimo_evento_disparado = ""

# Instância global
jarvis_emotions = EmotionalSystem()
