"""
FILE: command_box.py
DESCRIPTION: Servidor do bloco de comandos do JARVIS + lançador do processo.

             O box visual (PyQt5) roda em PROCESSO SEPARADO
             (command_box_proc.py) porque o OpenCV empacota seu próprio Qt
             — criar um QApplication PyQt5 no mesmo processo colide com
             ele ("Could not load Qt platform plugin xcb" → core dump).

             Este módulo fica no processo do JARVIS:
               1. Abre um servidor TCP em 127.0.0.1 (porta preferida
                  51234; se ocupada, usa uma livre aleatória).
               2. Cada comando recebido vai pelo MESMO pipeline do
                  terminal: phone_commands.processar_comando_texto().
               3. Lança o processo do box com a porta como argumento.

             Protocolo (JSON por linha):
                 box → JARVIS : {"cmd": "que horas são"}
                 JARVIS → box : {"ok": true, "msg": "✓ hora"}
"""

import time
import json
import os
import socket
import subprocess
import sys
import threading

HOST            = "127.0.0.1"
PORTA_PREFERIDA = 51234

_ouvinte = None   # socket servidor
_porta   = None
_proc    = None   # Popen do box


# -----------------------------------------------------------------------
# SERVIDOR
# -----------------------------------------------------------------------

def _recv_linha(sock) -> bytes | None:
    """Lê até o \\n (TCP não preserva fronteiras de mensagem)."""
    buf = b""
    while b"\n" not in buf:
        pedaco = sock.recv(4096)
        if not pedaco:
            return None
        buf += pedaco
    return buf.split(b"\n", 1)[0]


def _atender(conn: socket.socket):
    """
    Uma conexão = um comando (HTTP/1.0). O box fecha após ler a resposta.
    Timeout de leitura: conexão abandonada morre sozinha em vez de vazar
    thread presa em recv para sempre.
    """
    import phone_commands
    conn.settimeout(10)
    try:
        try:
            linha = _recv_linha(conn)
        except socket.timeout:
            return
        if linha is None:
            return
        try:
            dados = json.loads(linha.decode("utf-8"))
            cmd = (dados.get("cmd") or "").strip()
        except (ValueError, UnicodeDecodeError):
            return

        if cmd == "__ping__":
            conn.sendall(b'{"ok": true, "msg": "pong"}\n')
            return
        if not cmd:
            return

        try:
            msg = phone_commands.processar_comando_texto(cmd)
            ok = True
        except Exception as e:
            msg, ok = f"Erro interno: {e}", False
        try:
            conn.sendall(
                (json.dumps({"ok": ok, "msg": msg}) + "\n").encode("utf-8"))
        except OSError:
            pass   # cliente desistiu (timeout) — resposta cai no vazio, sem dano
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _aceitar():
    while True:
        try:
            conn, _ = _ouvinte.accept()
        except OSError:
            return  # servidor fechado
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        threading.Thread(target=_atender, args=(conn,), daemon=True).start()


# -----------------------------------------------------------------------
# LANÇADOR DO PROCESSO VISUAL
# -----------------------------------------------------------------------

def reabrir():
    """Lança (ou relança) o processo do box, com watchdog de vitalidade."""
    global _proc
    if _proc is not None and _proc.poll() is None:
        return
    caminho = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "command_box_proc.py")
    try:
        # stdout e stderr HERDADOS: o box loga o próprio nascimento no
        # terminal do JARVIS (marcadores [BOX-PROC]) — sem mais silêncio.
        _proc = subprocess.Popen([sys.executable, caminho, str(_porta)])
        print(f"[BOX] Bloco de comandos ativo (porta {_porta}, processo separado).")

        # Watchdog: quando um processo NETO morre, o bash NÃO imprime
        # "Aborted" (só reporta filhos diretos). Sem isto, a morte do box
        # era invisível — parecia "janela que não abriu".
        def _vigiar(proc, porta):
            while proc.poll() is None:
                time.sleep(2)
            print(f"[BOX] Processo do box encerrou (código {proc.returncode}).")
            print(f"[BOX] Diagnóstico manual em outro terminal: "
                  f"python3 command_box_proc.py {porta}")

        threading.Thread(target=_vigiar, args=(_proc, _porta),
                         daemon=True).start()
    except Exception as e:
        print(f"[BOX] Não consegui abrir o bloco de comandos ({e}).")
# -----------------------------------------------------------------------
# API PÚBLICA (main.py chama isto)
# -----------------------------------------------------------------------

def iniciar():
    """Sobe o servidor e lança o box. Não bloqueia o boot do JARVIS."""
    global _ouvinte, _porta
    if _ouvinte is not None:
        return
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((HOST, PORTA_PREFERIDA))
        except OSError:
            srv.bind((HOST, 0))          # porta livre aleatória
        srv.listen(4)
        _porta = srv.getsockname()[1]
    except Exception as e:
        print(f"[BOX] Servidor de comandos falhou ({e}). Box desativado.")
        return
    _ouvinte = srv
    threading.Thread(target=_aceitar, daemon=True).start()
    reabrir()
