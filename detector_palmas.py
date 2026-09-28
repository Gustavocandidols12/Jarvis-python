#!/usr/bin/env python3
"""
detector_palmas.py

Roda em segundo plano monitorando o microfone. Quando detecta uma "palma"
(pico de volume acima de um limiar, sustentado por um tempo mínimo), alterna
o JARVIS: se não estiver rodando, abre em um terminal novo; se já estiver
rodando, encerra.

Dependências:
    pip install sounddevice numpy
"""

import os
import subprocess
import sys
import time

import numpy as np
import sounddevice as sd

# ----------------- CONFIGURAÇÃO -----------------
# AJUSTE ESSA LINHA para o comando real que inicia seu JARVIS.
# --hold mantém a janela aberta se o JARVIS crashar, em vez de sumir na hora
# (assim dá pra ler o erro em vez de só ver a janela piscar no meio da tela).
JARVIS_CMD = ["kitty", "--start-as=minimized", "--hold", "-e", "python3", "/home/gustavo/Desktop/td/jarvis-python-refactor/main.py"]

# Se o JARVIS depende de arquivos relativos (config, assets), coloque aqui a
# pasta onde ele deve ser executado. Deixe None se não precisar.
JARVIS_DIR = None

LIMIAR_DB = -16.0     # volume mínimo (dB) pra considerar o gesto — bem mais alto, exige um som forte
DURACAO_MIN = 0.09    # tempo mínimo (s) SUSTENTADO acima do limiar — filtra cliques curtos
COOLDOWN = 1.5        # tempo mínimo (s) entre dois gestos, pra não contar o mesmo som 2x
TAXA_AMOSTRAGEM = 44100
BLOCO_MS = 10         # bloco menor = resolução mais fina pra medir a duração real do som
# --------------------------------------------------

DEBUG = "--debug" in sys.argv

processo_jarvis = None
tempo_acima_limiar = 0.0
ultima_deteccao = 0.0
ultimo_db = -100.0


def calcular_db(bloco):
    """Converte um bloco de áudio em dB aproximado, via RMS."""
    rms = np.sqrt(np.mean(bloco.astype(np.float64) ** 2)) + 1e-9
    return 20 * np.log10(rms)


def jarvis_esta_rodando():
    return processo_jarvis is not None and processo_jarvis.poll() is None


def abrir_jarvis():
    global processo_jarvis
    print("[detector] Palma detectada — abrindo JARVIS...")
    processo_jarvis = subprocess.Popen(
        JARVIS_CMD, preexec_fn=os.setsid, cwd=JARVIS_DIR
    )


def encerrar_jarvis():
    global processo_jarvis
    print("[detector] Gesto detectado — encerrando JARVIS...")
    try:
        processo_jarvis.terminate()  # fecha só a janela do kitty, não a sessão inteira
        processo_jarvis.wait(timeout=3)
    except subprocess.TimeoutExpired:
        processo_jarvis.kill()
    except ProcessLookupError:
        pass
    processo_jarvis = None


def ao_detectar_palma():
    if jarvis_esta_rodando():
        encerrar_jarvis()
    else:
        abrir_jarvis()


def callback(indata, frames, time_info, status):
    global tempo_acima_limiar, ultima_deteccao, ultimo_db

    agora = time.monotonic()
    db = calcular_db(indata)
    ultimo_db = db
    duracao_bloco = frames / TAXA_AMOSTRAGEM

    if db > LIMIAR_DB:
        tempo_acima_limiar += duracao_bloco
    else:
        tempo_acima_limiar = 0.0

    pronto_para_disparar = (
        tempo_acima_limiar >= DURACAO_MIN
        and (agora - ultima_deteccao) > COOLDOWN
    )

    if pronto_para_disparar:
        ultima_deteccao = agora
        tempo_acima_limiar = 0.0
        ao_detectar_palma()


def main():
    tamanho_bloco = int(TAXA_AMOSTRAGEM * BLOCO_MS / 1000)
    print("[detector] Monitorando microfone... (Ctrl+C para sair)")
    if DEBUG:
        print("[detector] Modo debug ligado — mostrando dB a cada 1s pra calibrar LIMIAR_DB")

    with sd.InputStream(
        channels=1,
        samplerate=TAXA_AMOSTRAGEM,
        blocksize=tamanho_bloco,
        callback=callback,
    ):
        try:
            while True:
                if DEBUG:
                    print(f"[debug] dB atual: {ultimo_db:.1f}")
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[detector] Encerrando detector...")
            if jarvis_esta_rodando():
                encerrar_jarvis()


if __name__ == "__main__":
    main()
