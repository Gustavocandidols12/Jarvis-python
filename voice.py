"""
FILE: voice.py
DESCRIPTION: Gerencia o motor de síntese de voz (TTS) do JARVIS.
             Usa edge-tts (Microsoft Azure Neural) + mpv para reprodução.
             Voz: pt-BR-AntonioNeural em +40% de velocidade.

[ECO-GUARD] Este módulo registra as últimas frases faladas e expõe
             get_ultimas_falas() — o listen.py compara as transcrições
             contra elas para descartar o próprio eco do TTS captado
             pelo microfone (o JARVIS se auto-comandava ao ouvir a
             própria resposta do clima, por exemplo).
"""
import threading
import queue
import asyncio
import tempfile
import os
import subprocess
from config import VozNaoEntendeu

try:
    import memory as _memory
    _MEMORY_OK = True
except ImportError:
    _MEMORY_OK = False

# [ECO-GUARD] últimas frases ditas pelo JARVIS (texto minúsculo normalizado).
# Append/remove sob GIL são atômicos — seguro entre threads.
_ULTIMAS_FALAS = []
_MAX_ECO = 4


def get_ultimas_falas() -> list:
    """Últimas frases faladas pelo JARVIS — para o eco-guard do listen.py."""
    return list(_ULTIMAS_FALAS)


# ═══ [MEMÓRIA] Versão antiga — pyttsx3 / espeak. Primeiro rosto do JARVIS.
# Mantida como registro. Para voltar: descomente e comente o bloco edge-tts. ═══
# import pyttsx3
# ... (bloco histórico removido da ativação — ver git para o conteúdo)
# ═══ [FIM DA VERSÃO ANTIGA] ═══


# ═══ [VERSÃO ATUAL — edge-tts + mpv] ═══

EDGE_VOZ       = "pt-BR-AntonioNeural"
EDGE_VELOCIDADE = "+40%"


class VoiceEngine:
    def __init__(self):
        self.boca_falando = False
        self.voz_ativa    = True
        self._fila        = queue.Queue()
        self._lock        = threading.Lock()

        self._edge_ok = self._verificar_edge_tts()
        self._mpv_ok  = self._verificar_mpv()

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
        """Gera áudio via edge-tts com STREAMING e alimenta o mpv em tempo real."""
        import edge_tts

        async def _stream():
            comunicar = edge_tts.Communicate(texto, EDGE_VOZ, rate=EDGE_VELOCIDADE)
            mpv_proc = subprocess.Popen(
                ["mpv", "--really-quiet", "--demuxer=lavf",
                 "--demuxer-lavf-format=mp3", "-"],
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
            self._sintetizar_e_tocar_fallback(texto)

    def _sintetizar_e_tocar_fallback(self, texto: str):
        """Fallback: salva MP3 em disco, depois toca."""
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
        """Worker do TTS — um texto por vez, para sempre."""
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
        """Enfileira o texto — retorna imediatamente."""
        if not self.voz_ativa:
            print(f"[VOZ DESATIVADA]: {texto}")
            return

        print(f"[VOZ]: {texto}")

        # Registra na memória tudo que o JARVIS fala
        if _MEMORY_OK:
            _memory.registrar(texto)

        # [ECO-GUARD] registra a fala p/ o listener descartar o próprio eco
        _ULTIMAS_FALAS.append(" ".join(str(texto).lower().split()))
        if len(_ULTIMAS_FALAS) > _MAX_ECO:
            _ULTIMAS_FALAS.pop(0)

        self._fila.put(texto)

    def falar_sincronizado(self, texto):
        """Enfileira e aguarda terminar. Use antes de encerrar o sistema."""
        self.falar(texto)
        self._fila.join()


# Instância única
jarvis_voice = VoiceEngine()
