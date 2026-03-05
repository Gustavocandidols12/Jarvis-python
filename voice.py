"""
FILE: voice.py
DESCRIPTION: Gerencia o motor de síntese de voz (TTS) do JARVIS.
             Usa edge-tts (Microsoft Azure Neural) + mpv para reprodução.
             Voz: pt-BR-AntonioNeural em +40% de velocidade.

DEPENDÊNCIAS:
    pip install edge-tts
    sudo apt install mpv -y
"""
import threading
import queue
import asyncio
import tempfile
import os
import subprocess
from config import VozNaoEntendeu
# Importação lazy da memória — evita import circular
try:
    import memory as _memory
    _MEMORY_OK = True
except ImportError:
    _MEMORY_OK = False

# ═══════════════════════════════════════════════════════════════════════
# [VERSÃO ANTIGA — pyttsx3 / espeak]
# Desativada em favor do edge-tts (Microsoft Neural).
# Para voltar: descomente este bloco e comente o bloco edge-tts abaixo.
# ═══════════════════════════════════════════════════════════════════════
# import pyttsx3
#
# class VoiceEngine:
#     def __init__(self):
#         self.engine       = None
#         self.boca_falando = False
#         self.voz_ativa    = True
#         self._fila        = queue.Queue()
#         self._lock        = threading.Lock()
#
#         try:
#             self.engine = pyttsx3.init()
#             voices = self.engine.getProperty('voices')
#             voz_encontrada = False
#             print("--- Procurando por vozes em Português ---")
#             for voice in voices:
#                 if 'brazil' in voice.id.lower() or 'pt-br' in voice.id.lower():
#                     self.engine.setProperty('voice', voice.id)
#                     print(f"SUCESSO! Voz em Português configurada: {voice.id}")
#                     voz_encontrada = True
#                     break
#             if not voz_encontrada:
#                 print("AVISO: Nenhuma voz em PT-BR encontrada. Usando a voz padrão.")
#                 self.engine.setProperty('rate', 166)
#         except Exception as e:
#             print(f"Erro ao inicializar o motor de voz: {e}")
#
#         self._worker = threading.Thread(target=self._loop_worker, daemon=True)
#         self._worker.start()
#
#     def _loop_worker(self):
#         while True:
#             texto = self._fila.get()
#             if self.engine is None:
#                 self._fila.task_done()
#                 continue
#             with self._lock:
#                 self.boca_falando = True
#             try:
#                 self.engine.say(texto)
#                 self.engine.runAndWait()
#             except Exception as e:
#                 print(f"[VOZ] Erro no TTS: {e}")
#             finally:
#                 with self._lock:
#                     self.boca_falando = False
#                 self._fila.task_done()
#
#     def falar(self, texto):
#         if not self.engine or not self.voz_ativa:
#             print(f"[VOZ DESATIVADA]: {texto}")
#             return
#         print(f"[VOZ]: {texto}")
#         self._fila.put(texto)
#
#     def falar_sincronizado(self, texto):
#         self.falar(texto)
#         self._fila.join()
# ═══════════════════════════════════════════════════════════════════════
# [FIM DA VERSÃO ANTIGA]
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# [VERSÃO ATUAL — edge-tts + mpv]
# ═══════════════════════════════════════════════════════════════════════

# Voz e velocidade — altere aqui para customizar
EDGE_VOZ       = "pt-BR-AntonioNeural"
EDGE_VELOCIDADE = "+40%"   # +40% mais rápido que o padrão


class VoiceEngine:
    def __init__(self):
        self.boca_falando = False
        self.voz_ativa    = True
        self._fila        = queue.Queue()
        self._lock        = threading.Lock()

        # Verifica dependências na inicialização
        self._edge_ok = self._verificar_edge_tts()
        self._mpv_ok  = self._verificar_mpv()

        # Thread única e permanente que consome a fila
        self._worker = threading.Thread(target=self._loop_worker, daemon=True)
        self._worker.start()

        print(f"[VOZ] Motor edge-tts iniciado. Voz: {EDGE_VOZ} | Velocidade: {EDGE_VELOCIDADE}")

    def _verificar_edge_tts(self) -> bool:
        try:
            import edge_tts  # noqa
            return True
        except ImportError:
            print("[VOZ] ERRO: edge-tts não instalado. Rode: pip install edge-tts")
            return False

    def _verificar_mpv(self) -> bool:
        resultado = subprocess.run(["which", "mpv"], capture_output=True)
        if resultado.returncode != 0:
            print("[VOZ] ERRO: mpv não instalado. Rode: sudo apt install mpv -y")
            return False
        return True

    def _sintetizar_e_tocar(self, texto: str):
        """
        Gera o áudio via edge-tts com STREAMING e alimenta o mpv em tempo real.

        DIFERENÇA vs versão anterior (save → play):
        - Antes: edge-tts baixava o MP3 inteiro (~1-2s) → depois mpv tocava.
          Resultado: animação de fala começava, mas voz só saía 2-3s depois.
        - Agora: edge-tts abre um processo mpv e faz PIPE dos chunks de áudio
          direto para stdin do mpv conforme chegam da Microsoft.
          O mpv começa a tocar com os primeiros 200-400ms de áudio recebido,
          enquanto o resto ainda está sendo baixado em paralelo.
          Ganho: latência percebida cai de ~2-3s para ~300-500ms.

        COMO FUNCIONA EM PYTHON:
        1. subprocess.Popen abre o mpv com stdin=PIPE e --demuxer=lavf
           (força o mpv a ler MP3 de um stream, não de arquivo)
        2. asyncio roda edge_tts.Communicate.stream() — um gerador assíncrono
           que emite dicts com {"type": "audio", "data": bytes_mp3}
        3. Cada chunk de bytes é escrito imediatamente no stdin do mpv
        4. mpv decodifica e toca conforme recebe — sem esperar o fim do stream
        5. mpv_proc.stdin.close() sinaliza fim do stream; wait() aguarda término
        """
        import edge_tts

        async def _stream():
            comunicar = edge_tts.Communicate(texto, EDGE_VOZ, rate=EDGE_VELOCIDADE)

            mpv_proc = subprocess.Popen(
                [
                    "mpv",
                    "--really-quiet",
                    "--demuxer=lavf",          # lê MP3 de stdin
                    "--demuxer-lavf-format=mp3",
                    "-",                        # '-' = ler de stdin
                ],
                stdin=subprocess.PIPE,
            )

            try:
                async for chunk in comunicar.stream():
                    if chunk.get("type") == "audio":
                        mpv_proc.stdin.write(chunk["data"])
            finally:
                try:
                    mpv_proc.stdin.close()
                except Exception:
                    pass
                mpv_proc.wait()

        try:
            asyncio.run(_stream())
        except Exception as e:
            print(f"[VOZ] Erro ao sintetizar/tocar (streaming): {e}")
            # Fallback: método antigo com arquivo temporário
            self._sintetizar_e_tocar_fallback(texto)

    def _sintetizar_e_tocar_fallback(self, texto: str):
        """
        Fallback para o método antigo (salva MP3 em disco, depois toca).
        Usado automaticamente se o streaming falhar por qualquer razão.
        """
        import edge_tts

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            caminho_tmp = tmp.name

        try:
            async def _gerar():
                comunicar = edge_tts.Communicate(texto, EDGE_VOZ, rate=EDGE_VELOCIDADE)
                await comunicar.save(caminho_tmp)

            asyncio.run(_gerar())
            subprocess.run(["mpv", "--really-quiet", caminho_tmp], check=True)
        except Exception as e:
            print(f"[VOZ] Erro no fallback TTS: {e}")
        finally:
            if os.path.exists(caminho_tmp):
                os.remove(caminho_tmp)

    def _loop_worker(self):
        """
        Worker dedicado ao TTS. Roda para sempre em segundo plano.
        Retira um texto da fila, sintetiza e toca, um por vez.
        """
        while True:
            texto = self._fila.get()

            if not self.voz_ativa:
                self._fila.task_done()
                continue

            with self._lock:
                self.boca_falando = True

            try:
                if self._edge_ok and self._mpv_ok:
                    self._sintetizar_e_tocar(texto)
                else:
                    print(f"[VOZ FALLBACK]: {texto}")
            except Exception as e:
                print(f"[VOZ] Erro no worker: {e}")
            finally:
                with self._lock:
                    self.boca_falando = False
                self._fila.task_done()

    def falar(self, texto):
        """
        Enfileira o texto para ser falado assim que o TTS estiver livre.
        Retorna imediatamente — não bloqueia o chamador.
        """
        if not self.voz_ativa:
            print(f"[VOZ DESATIVADA]: {texto}")
            return

        print(f"[VOZ]: {texto}")

        # Registra na memória tudo que o JARVIS fala
        # CORRETO
        if _MEMORY_OK:
            _memory.registrar(texto)
            
        self._fila.put(texto)

    def falar_sincronizado(self, texto):
        """
        Enfileira e aguarda a fala terminar completamente.
        Use antes de sys.exit() ou os.system('poweroff').
        """
        self.falar(texto)
        self._fila.join()


# Instância única para ser usada pelo sistema
jarvis_voice = VoiceEngine()