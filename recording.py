"""
FILE: recording.py
DESCRIPTION: Módulo de gravação de câmera do JARVIS.
             Inicia/cancela gravação de vídeo (com áudio, quando possível)
             por comando de voz, salva em GravacaoCamera/ e avisa o usuário
             quando o tempo está acabando.

FLUXO:
    main.py  → recording.atualizar_frame(frame)    [a cada frame, ~26x/s]
    brain.py → recording.iniciar_gravacao()         [quando o usuário pede]
    brain.py → recording.cancelar_gravacao()        [quando o usuário pede]

DEPENDÊNCIAS:
    cv2         → já presente no projeto (igual vision.py).
    sounddevice → biblioteca Python já usada em listen.py, mas seu
        funcionamento depende também da lib de sistema PortAudio estar
        instalada (sudo apt install libportaudio2). Se ausente, este
        módulo detecta isso na importação e desativa só o áudio,
        sem impedir o resto do JARVIS de funcionar.
    ffmpeg (binário de sistema) → OPCIONAL. Usado só para juntar vídeo + áudio
        no arquivo final. Se não estiver instalado, a gravação continua
        funcionando normalmente, mas o vídeo final fica sem áudio (mudo).
        Instalar com: sudo apt install ffmpeg

CONFIGURAÇÃO PRINCIPAL:
    REC_TIME_SEGUNDOS — duração total da gravação (5 minutos por padrão).
    REC_AVISO_SEGUNDOS — quando soar o aviso de "tempo acabando" (4min30s).

[NOVO] CAPTURA DE ÁUDIO:
    cv2.VideoWriter (já usado para o vídeo) NÃO grava áudio — é uma
    limitação da própria biblioteca, não deste módulo. Para ter vídeo
    com áudio, o fluxo é:
      1. Vídeo é gravado normalmente em um arquivo temporário mudo (.mp4).
      2. Áudio é capturado em paralelo via sounddevice, salvo num .wav temporário.
      3. Ao final, ffmpeg junta os dois num .mp4 final (vídeo + áudio).
      4. Os arquivos temporários são apagados.
    Se qualquer etapa do áudio falhar (mic ocupado, sounddevice indisponível,
    ffmpeg não instalado), a gravação NÃO é interrompida — o vídeo mudo já
    capturado é salvo normalmente como fallback.
"""

import os
import cv2
import time
import wave
import shutil
import datetime
import threading
import subprocess
import numpy as np
from voice import jarvis_voice

try:
    import personality as _personality  # [NOVO] respostas humanizadas
except ImportError:
    _personality = None

try:
    import sounddevice as sd
    _SOUNDDEVICE_OK = True
except Exception:
    # [CORRIGIDO] sounddevice pode falhar de duas formas diferentes:
    # ImportError (pacote não instalado) ou OSError (pacote instalado mas
    # a biblioteca de sistema PortAudio está ausente — caso real encontrado
    # em testes). Captura genérica garante que qualquer falha aqui NUNCA
    # impede o resto do recording.py (e, por consequência, o JARVIS inteiro)
    # de carregar — só desativa a gravação de áudio.
    _SOUNDDEVICE_OK = False

# -----------------------------------------------------------------------
# CONFIGURAÇÕES
# -----------------------------------------------------------------------

# Pasta de destino dos vídeos — criada automaticamente se não existir.
# [ALTERADO] Antes usava os.path.expanduser("~") (pasta home pessoal,
# ex: /home/gustavo/GravacaoCamera). Agora usa os.path.dirname(__file__),
# o mesmo recurso já usado em memory.py/notes.py para MEMORIA_ARQUIVO e
# NOTES_ARQUIVO — a pasta fica dentro da pasta do projeto (onde este
# arquivo recording.py está salvo), seja ela "jarvis-python-refactor"
# ou qualquer outro nome, em qualquer máquina.
PASTA_GRAVACOES = os.path.join(os.path.dirname(__file__), "GravacaoCamera")

# Pasta temporária para os arquivos intermediários (vídeo mudo + áudio),
# antes da junção final via ffmpeg. Fica dentro da própria PASTA_GRAVACOES
# para garantir que esteja no mesmo disco (move/delete mais seguro).
PASTA_TEMP_GRAVACAO = os.path.join(PASTA_GRAVACOES, ".tmp")

# --- RecTime: duração total da gravação, em segundos ---
REC_TIME_SEGUNDOS = 5 * 60          # 5 minutos

# Aviso de tempo acabando: aos 4min30s (30s antes do fim)
REC_AVISO_SEGUNDOS = (4 * 60) + 30

FPS_GRAVACAO   = 20.0   # mesmo valor configurado em main.py (cap.set CAP_PROP_FPS)
CODEC_GRAVACAO = "mp4v"  # codec leve, amplamente suportado no Linux

# --- [NOVO] Áudio ---
AUDIO_SAMPLE_RATE = 44100   # taxa padrão de gravação de áudio (qualidade CD)
AUDIO_CANAIS      = 1       # mono — suficiente para narração/ambiente
_FFMPEG_DISPONIVEL: bool | None = None  # cache da verificação, None = ainda não checado

# -----------------------------------------------------------------------
# ESTADO INTERNO
# -----------------------------------------------------------------------

_lock_frame      = threading.Lock()
_frame_atual: np.ndarray | None = None

_lock_gravacao   = threading.Lock()
_gravando        = False
_thread_gravacao: threading.Thread | None = None
_cancelar_flag   = False  # sinaliza à thread de gravação que deve parar antes do tempo


# -----------------------------------------------------------------------
# API PÚBLICA — FRAME COMPARTILHADO
# -----------------------------------------------------------------------

def atualizar_frame(frame: np.ndarray) -> None:
    """
    Chamado pelo main.py a cada iteração do loop de vídeo (~26x/s).
    Mantém uma cópia thread-safe do frame mais recente, igual ao
    padrão já usado em vision.py.
    """
    global _frame_atual
    with _lock_frame:
        _frame_atual = frame.copy()


def esta_gravando() -> bool:
    """Retorna True se há uma gravação em andamento neste momento."""
    with _lock_gravacao:
        return _gravando


# -----------------------------------------------------------------------
# [NOVO] ÁUDIO — detecção de ffmpeg e captura em thread paralela
# -----------------------------------------------------------------------

def _ffmpeg_disponivel() -> bool:
    """
    Verifica se o binário ffmpeg está instalado no sistema.
    Resultado é cacheado (mesmo padrão de cache já usado em brain.py
    para _detectar_browser()), para não checar isso a cada gravação.
    """
    global _FFMPEG_DISPONIVEL
    if _FFMPEG_DISPONIVEL is not None:
        return _FFMPEG_DISPONIVEL

    try:
        resultado = subprocess.run(["which", "ffmpeg"], capture_output=True)
        _FFMPEG_DISPONIVEL = resultado.returncode == 0
    except Exception:
        _FFMPEG_DISPONIVEL = False

    if not _FFMPEG_DISPONIVEL:
        print("[RECORDING] ffmpeg não encontrado — gravações serão salvas sem áudio.")
    return _FFMPEG_DISPONIVEL


class _GravadorAudio:
    """
    Captura áudio do microfone padrão em paralelo à gravação de vídeo,
    usando sounddevice (mesma biblioteca já usada em listen.py).
    Roda numa thread própria e acumula os blocos recebidos em uma lista,
    que é concatenada e salva em .wav só ao final (parar()).
    """

    def __init__(self):
        self._blocos: list = []
        self._stream = None
        self._ativo  = False

    def iniciar(self) -> bool:
        if not _SOUNDDEVICE_OK:
            return False
        try:
            def _callback(indata, frames, time_info, status):
                self._blocos.append(indata.copy())

            self._stream = sd.InputStream(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=AUDIO_CANAIS,
                dtype="int16",
                callback=_callback,
            )
            self._stream.start()
            self._ativo = True
            return True
        except Exception as e:
            print(f"[RECORDING] Áudio indisponível, gravação seguirá sem som: {e}")
            self._ativo = False
            return False

    def parar_e_salvar(self, caminho_wav: str) -> bool:
        """Para a captura e salva o .wav. Retorna True se salvou com sucesso."""
        if not self._ativo:
            return False
        try:
            self._stream.stop()
            self._stream.close()
        except Exception as e:
            # Mesmo se falhar ao parar/fechar o stream, NÃO interrompe o
            # fluxo aqui — os blocos de áudio já capturados em self._blocos
            # continuam válidos em memória e ainda podem ser salvos abaixo.
            print(f"[RECORDING] Erro ao parar stream de áudio: {e}")

        if not self._blocos:
            return False

        try:
            audio = np.concatenate(self._blocos, axis=0)
            with wave.open(caminho_wav, "wb") as wf:
                wf.setnchannels(AUDIO_CANAIS)
                wf.setsampwidth(2)  # int16 = 2 bytes
                wf.setframerate(AUDIO_SAMPLE_RATE)
                wf.writeframes(audio.tobytes())
            return True
        except Exception as e:
            print(f"[RECORDING] Erro ao salvar áudio: {e}")
            return False


def _juntar_video_audio(caminho_video_mudo: str, caminho_audio: str, caminho_final: str) -> bool:
    """
    Usa ffmpeg para juntar vídeo mudo + áudio num único .mp4.
    Retorna True se deu certo. Em qualquer falha, retorna False e quem
    chamou deve usar o vídeo mudo como fallback.
    """
    try:
        resultado = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", caminho_video_mudo,
                "-i", caminho_audio,
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                caminho_final,
            ],
            capture_output=True,
            timeout=60,
        )
        return resultado.returncode == 0 and os.path.exists(caminho_final)
    except Exception as e:
        print(f"[RECORDING] Erro ao juntar vídeo e áudio com ffmpeg: {e}")
        return False


# -----------------------------------------------------------------------
# NÚCLEO — LOOP DE GRAVAÇÃO (roda em thread separada)
# -----------------------------------------------------------------------

def _criar_video_writer(largura: int, altura: int, timestamp: str) -> tuple[cv2.VideoWriter, str]:
    """
    Cria a pasta de destino (se não existir) e o VideoWriter de saída.
    [ALTERADO] Agora recebe o timestamp como parâmetro (em vez de gerar
    internamente), para que o vídeo mudo temporário e o áudio temporário
    usem exatamente o mesmo timestamp e possam ser juntados depois.
    Retorna (writer, caminho_arquivo).
    """
    os.makedirs(PASTA_GRAVACOES, exist_ok=True)
    os.makedirs(PASTA_TEMP_GRAVACAO, exist_ok=True)

    nome_arquivo = f"jarvis_rec_{timestamp}_mudo.mp4"
    caminho      = os.path.join(PASTA_TEMP_GRAVACAO, nome_arquivo)

    fourcc = cv2.VideoWriter_fourcc(*CODEC_GRAVACAO)
    writer = cv2.VideoWriter(caminho, fourcc, FPS_GRAVACAO, (largura, altura))

    return writer, caminho


def _loop_gravacao():
    """
    Roda em thread daemon dedicada. Captura o frame compartilhado a cada
    ciclo (mesma fonte de vision.py), grava no arquivo, dispara o aviso
    de tempo acabando e finaliza sozinha ao atingir REC_TIME_SEGUNDOS —
    ou antes, se _cancelar_flag for sinalizada.

    [ALTERADO] Agora também inicia a captura de áudio em paralelo
    (se disponível) e, ao final, tenta juntar vídeo + áudio com ffmpeg.
    Se qualquer etapa do áudio falhar, o vídeo mudo é salvo como fallback
    — a gravação de vídeo NUNCA é interrompida por causa do áudio.
    """
    global _gravando, _cancelar_flag

    with _lock_frame:
        frame_inicial = _frame_atual.copy() if _frame_atual is not None else None

    if frame_inicial is None:
        jarvis_voice.falar("Não consigo acessar a câmera agora, senhor.")
        with _lock_gravacao:
            _gravando = False
        return

    altura, largura = frame_inicial.shape[:2]
    timestamp        = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    writer, caminho_video_mudo = _criar_video_writer(largura, altura, timestamp)

    # [NOVO] Tenta iniciar captura de áudio em paralelo. Se falhar por
    # qualquer motivo (sounddevice ausente, mic ocupado, etc.), a gravação
    # de vídeo continua normalmente — só não terá áudio no arquivo final.
    gravador_audio = _GravadorAudio()
    audio_ativo    = gravador_audio.iniciar()

    print(f"[RECORDING] Gravação iniciada → {caminho_video_mudo} "
          f"(áudio: {'ativo' if audio_ativo else 'indisponível'})")

    tempo_inicio   = time.time()
    aviso_dado     = False
    intervalo_frame = 1.0 / FPS_GRAVACAO

    while True:
        with _lock_gravacao:
            if _cancelar_flag:
                break

        tempo_passado = time.time() - tempo_inicio
        if tempo_passado >= REC_TIME_SEGUNDOS:
            break

        if not aviso_dado and tempo_passado >= REC_AVISO_SEGUNDOS:
            aviso_dado = True
            # [NOVO] Aviso criativo via personality em vez de mensagem robótica
            if _personality:
                resposta = _personality.gerar_resposta(
                    categoria="acao_andamento",
                    contexto={"acao": "finalizar_gravacao", "tempo_restante": 30}
                )
            else:
                resposta = "Senhor, a gravação está terminando em 30 segundos."
            jarvis_voice.falar(resposta)

        with _lock_frame:
            frame_para_gravar = _frame_atual.copy() if _frame_atual is not None else None

        if frame_para_gravar is not None:
            writer.write(frame_para_gravar)

        time.sleep(intervalo_frame)

    writer.release()

    with _lock_gravacao:
        foi_cancelada  = _cancelar_flag
        _cancelar_flag = False
        _gravando      = False

    duracao_real = round(time.time() - tempo_inicio)

    # [NOVO] Finaliza áudio e tenta juntar com o vídeo via ffmpeg.
    # Cada etapa tem fallback: se áudio não foi capturado, ou ffmpeg não
    # está disponível, ou a junção falhar — o vídeo mudo é usado como
    # resultado final, sem nunca perder a gravação já feita.
    caminho_final     = os.path.join(PASTA_GRAVACOES, f"jarvis_rec_{timestamp}.mp4")
    caminho_audio_wav = os.path.join(PASTA_TEMP_GRAVACAO, f"jarvis_rec_{timestamp}_audio.wav")
    audio_salvo       = audio_ativo and gravador_audio.parar_e_salvar(caminho_audio_wav)
    tem_audio_no_resultado = False

    if audio_salvo and _ffmpeg_disponivel():
        if _juntar_video_audio(caminho_video_mudo, caminho_audio_wav, caminho_final):
            tem_audio_no_resultado = True

    if not tem_audio_no_resultado:
        # Fallback: usa o vídeo mudo como resultado final (move/renomeia).
        try:
            shutil.move(caminho_video_mudo, caminho_final)
        except Exception as e:
            print(f"[RECORDING] Erro ao mover vídeo final: {e}")
            caminho_final = caminho_video_mudo  # mantém o mudo no lugar original

    # Limpeza dos arquivos temporários remanescentes (não falha a gravação se der erro)
    for caminho_temp in (caminho_video_mudo, caminho_audio_wav):
        try:
            if os.path.exists(caminho_temp):
                os.remove(caminho_temp)
        except Exception:
            pass

    print(f"[RECORDING] Gravação finalizada ({duracao_real}s, "
          f"{'com áudio' if tem_audio_no_resultado else 'sem áudio'}) → {caminho_final}")

    # ─── RESPOSTAS VIA PERSONALITY (HUMANIZADAS VIA GROQ) ───
    # [NOVO] Em vez de respostas fixas, personality gera respostas criativas
    # que celebram a conclusão da gravação de forma sarcástica.
    
    if foi_cancelada:
        # Resposta para quando usuário cancelou a gravação
        if _personality:
            resposta = _personality.gerar_resposta(
                categoria="sucesso",
                contexto={
                    "acao": "gravacao_video_cancelada",
                    "duracao": duracao_real,
                    "tem_audio": tem_audio_no_resultado
                }
            )
        else:
            resposta = f"Gravação cancelada e salva, senhor. {duracao_real} segundos gravados."
        jarvis_voice.falar(resposta)
    else:
        # Resposta para quando gravação terminou naturalmente (tempo limite atingido)
        if _personality:
            resposta = _personality.gerar_resposta(
                categoria="sucesso",
                contexto={
                    "acao": "gravacao_video_concluida",
                    "duracao": duracao_real,
                    "tem_audio": tem_audio_no_resultado
                }
            )
        else:
            resposta = "Gravação finalizada e salva, senhor."
        jarvis_voice.falar(resposta)


# -----------------------------------------------------------------------
# API PÚBLICA — INICIAR / CANCELAR
# -----------------------------------------------------------------------

def iniciar_gravacao() -> str:
    """
    Inicia a gravação em thread separada (não bloqueia o loop de vídeo).
    Se já houver uma gravação em andamento, ela é interrompida e uma nova
    é iniciada (comportamento definido conforme combinado).
    Retorna string pronta para o JARVIS falar.
    """
    global _gravando, _thread_gravacao, _cancelar_flag

    with _lock_gravacao:
        ja_gravando = _gravando

    if ja_gravando:
        # Sinaliza a thread atual a parar e aguarda finalizar antes de iniciar a nova
        with _lock_gravacao:
            _cancelar_flag = True
        if _thread_gravacao is not None:
            _thread_gravacao.join(timeout=3)

    with _lock_gravacao:
        _gravando      = True
        _cancelar_flag = False

    _thread_gravacao = threading.Thread(target=_loop_gravacao, daemon=True)
    _thread_gravacao.start()

    # [NOVO] Respostas criativas via personality em vez de hardcoded
    if ja_gravando:
        # Caso em que usuário pediu gravar enquanto já estava gravando
        if _personality:
            resposta = _personality.gerar_resposta(
                categoria="acao_andamento",
                contexto={"acao": "reiniciar_gravacao"}
            )
        else:
            resposta = "Encerrando a gravação anterior e iniciando uma nova, senhor."
    else:
        # Caso normal: começando a gravar
        if _personality:
            resposta = _personality.gerar_resposta(
                categoria="acao_andamento",
                contexto={"acao": "iniciar_gravacao"}
            )
        else:
            resposta = "Iniciando gravação, senhor."
    
    return resposta


def cancelar_gravacao() -> str:
    """
    Sinaliza à thread de gravação ativa para parar antes do tempo,
    salvando o que já foi capturado até o momento.
    Retorna string pronta para o JARVIS falar.
    """
    global _cancelar_flag

    with _lock_gravacao:
        if not _gravando:
            # [NOVO] Resposta criativa quando não há gravação em andamento
            if _personality:
                resposta = _personality.gerar_resposta(
                    categoria="nao_encontrado",
                    contexto={"tipo": "gravação em andamento", "nome": "nenhuma"}
                )
            else:
                resposta = "Não há gravação em andamento, senhor."
            return resposta
        
        _cancelar_flag = True

    # [NOVO] Resposta criativa ao cancelar gravação
    if _personality:
        resposta = _personality.gerar_resposta(
            categoria="acao_andamento",
            contexto={"acao": "parar_gravacao"}
        )
    else:
        resposta = "Encerrando a gravação, senhor."
    
    return resposta
