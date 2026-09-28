"""
FILE: command_box_proc.py
DESCRIPTION: PROCESSO SEPARADO do bloco de comandos do JARVIS.

             Roda SOZINHO (só stdlib + PyQt5 — nunca importa cv2 nem
             módulos do JARVIS), por isso não conflita com o Qt embutido
             no OpenCV.

REDE (modelo conexão-por-request — resolve o bug do delay crescente):
             A versão anterior mantinha UM socket persistente e uma
             thread por Enter: respostas lentas ficavam no buffer e eram
             lidas como resposta do comando SEGUINTE (dessincronização),
             Enters repetidos multiplicavam timeouts em série via lock,
             e meia-conexões nunca fechavam. Agora: cada comando abre a
             própria conexão (estilo HTTP/1.0), uma única thread consome
             a fila de comandos em ordem, e um ping idle mantém o status
             honesto. Em localhost, reconectar custa <1ms.

DIAGNÓSTICO: todas as etapas são impressas no STDERR (herdado pelo
             terminal do JARVIS). Se algo falhar, a mensagem exata
             aparece lá — e o watchdog do command_box.py anuncia a morte.

USO (automático): o JARVIS lança com a porta como argumento:
    python3 command_box_proc.py 51234

CONTROLES: Enter envia | Esc limpa | arraste com o mouse | ✕ fecha
"""

import json
import os
import queue
import socket
import sys
import threading
import time


def _log(msg: str):
    """Diagnóstico visível no terminal do JARVIS (stderr é herdado)."""
    print(f"[BOX-PROC] {msg}", file=sys.stderr, flush=True)


_log(f"iniciando (pid {os.getpid()}, porta "
     f"{sys.argv[1] if len(sys.argv) > 1 else 'default'})")

# --- BLINDAGEM CONTRA CONFLITO DE PLUGINS QT ---
# O cv2 (no processo do JARVIS) embute o PRÓPRIO Qt. Se qualquer variável
# de ambiente apontar o caminho de plugins para o cv2, o PyQt5 aqui falha
# com "Could not load the Qt platform plugin xcb". Forçamos o PyQt5 a
# usar os plugins DELE e o backend xcb (X11).
try:
    from PyQt5.QtCore import QLibraryInfo
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = QLibraryInfo.location(
        QLibraryInfo.PluginsPath)
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    _log("plugins Qt do PyQt5 forçados (blindagem anti-cv2).")
except Exception as e:
    _log(f"AVISO: blindagem de plugins falhou ({e})")

try:
    from PyQt5.QtWidgets import (QApplication, QWidget, QLineEdit, QLabel,
                                 QVBoxLayout, QPushButton)
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QPainter, QColor
    _log("PyQt5 importado com sucesso.")
except Exception:
    import traceback
    traceback.print_exc()
    _log("FALHA ao importar PyQt5 — instale com: pip install PyQt5")
    sys.exit(1)


HOST = "127.0.0.1"
PORTA = int(sys.argv[1]) if len(sys.argv) > 1 else 51234

# False = fundo opaco. Use se a janela não aparecer ou sair toda preta
# (sessão do XFCE sem compositor ativo).
TRANSPARENTE = True

# Timeout da resposta: comandos lentos (Groq, adb subindo o server,
# clima) podem levar vários segundos. 25s cobre o pior caso legítimo.
TIMEOUT_RESPOSTA = 25
# Ping de vitalidade quando ocioso (atualiza ONLINE/OFFLINE).
INTERVALO_PING_SEG = 30

STYLE = """
    QWidget {
        background: rgba(8, 15, 26, 190);
        border: 1px solid rgba(0, 195, 255, 130);
        border-radius: 12px;
    }
    QLabel#header {
        background: transparent; border: none;
        color: #00E5FF;
        font-family: 'DejaVu Sans Mono';
        font-size: 14px; font-weight: bold;
    }
    QLabel#status {
        background: transparent; border: none;
        color: rgba(0, 229, 255, 150);
        font-family: 'DejaVu Sans Mono';
        font-size: 8px;
    }
    QLineEdit#entrada {
        background: rgba(0, 30, 45, 120);
        border: 1px solid rgba(0, 195, 255, 80);
        border-radius: 6px;
        color: #D7F5FF;
        font-family: 'DejaVu Sans Mono';
        font-size: 13px;
        padding: 7px 9px;
        selection-background-color: rgba(0, 195, 255, 90);
    }
    QLabel#feedback {
        background: transparent; border: none;
        color: rgba(160, 220, 200, 220);
        font-family: 'DejaVu Sans Mono';
        font-size: 9px;
    }
    QPushButton#fechar {
        background: transparent; border: none;
        color: rgba(0, 195, 255, 120);
        font-size: 12px;
    }
    QPushButton#fechar:hover { color: #FF5555; }
"""


def _recv_linha(sock) -> bytes | None:
    buf = b""
    while b"\n" not in buf:
        pedaco = sock.recv(4096)
        if not pedaco:
            return None
        buf += pedaco
    return buf.split(b"\n", 1)[0]


class Box(QWidget):
    def __init__(self):
        super().__init__()
        # [FIX] Qt.Tool removido — janela-tool frameless sem "pai transitório"
        # pode não mapear em alguns WMs (xfwm4). StayOnTop já basta.
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        if TRANSPARENTE:
            self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.resize(480, 122)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(4)

        header = QLabel("J A R V I S")
        header.setObjectName("header")
        self.status = QLabel("CONECTANDO...")
        self.status.setObjectName("status")

        self.entrada = QLineEdit()
        self.entrada.setObjectName("entrada")
        self.entrada.setPlaceholderText("Comando e Enter... ('ajuda' imprime no terminal)")

        self.feedback = QLabel("")
        self.feedback.setObjectName("feedback")

        layout.addWidget(header)
        layout.addWidget(self.status)
        layout.addWidget(self.entrada)
        layout.addWidget(self.feedback)

        # ✕ (janela frameless não tem barra de título) — criado COM pai
        # direto: criar sem pai e só depois setParent posicionava errado
        fechar = QPushButton("✕", self)
        fechar.setObjectName("fechar")
        fechar.setFixedSize(20, 20)
        fechar.move(self.width() - 30, 10)
        fechar.clicked.connect(self.close)

        self.entrada.returnPressed.connect(self._enviar)

        # ---- filas ----
        # _fila: resultados -> UI (consumida pelo QTimer, thread-safe)
        self._fila = queue.Queue()
        # _fila_cmds: comandos -> ÚNICO consumidor em background.
        # Enter durante comando ocupado = enfileira (feedback de posição),
        # em vez de multiplicar threads/ timeouts como na versão antiga.
        self._fila_cmds = queue.Queue()
        self._ocupado = False

        consumo = QTimer(self)
        consumo.timeout.connect(self._consumir)
        consumo.start(100)

        # consumidor serial de comandos (rede)
        threading.Thread(target=self._consumir_cmds, daemon=True).start()

        # ping de vitalidade quando ocioso (deteta morte do JARVIS cedo;
        # roda em background — o QTimer só dispara a thread)
        self._ping = QTimer(self)
        self._ping.timeout.connect(self._ping_idle)
        self._ping.start(INTERVALO_PING_SEG * 1000)
        threading.Thread(target=self._executar_ping, daemon=True).start()

        # linha de escaneamento (vida ao vidro)
        self._scan = QTimer(self)
        self._scan.timeout.connect(self.update)
        self._scan.start(50)

        self._arraste = None
        tela = QApplication.primaryScreen().availableGeometry()
        self.move(tela.right() - self.width() - 24, tela.top() + 24)
        self.entrada.setFocus()

    # -------------------- rede (conexão por request) --------------------

    def _conexao(self, timeout_resp: float) -> socket.socket:
        """Abre UMA conexão nova (connect 3s) — modelo HTTP/1.0."""
        s = socket.create_connection((HOST, PORTA), timeout=3)
        s.settimeout(timeout_resp)
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        return s

    def _executar_comando(self, texto: str) -> tuple:
        """
        Uma conexão TCP por comando. Elimina por construção: buffer com
        resposta velha, respostas trocadas, meia-conexão zumbi — as
        causas do 'delay que cresce até morrer' da versão persistente.
        """
        try:
            with self._conexao(timeout_resp=TIMEOUT_RESPOSTA) as s:
                s.sendall((json.dumps({"cmd": texto}) + "\n").encode("utf-8"))
                linha = _recv_linha(s)
            if linha is None:
                return ("erro", "JARVIS encerrou a conexão.")
            resp = json.loads(linha.decode("utf-8"))
            return ("ok" if resp.get("ok") else "erro", resp.get("msg", ""))
        except socket.timeout:
            return ("erro",
                    "JARVIS não respondeu em "
                    f"{TIMEOUT_RESPOSTA}s — comando lento ou travado.")
        except (OSError, ValueError) as e:
            return ("erro", f"Sem conexão com o JARVIS: {e}")

    def _consumir_cmds(self):
        """Único consumidor da fila de comandos (serializa, em ordem)."""
        while True:
            texto = self._fila_cmds.get()
            self._ocupado = True
            _log(f"comando: '{texto[:60]}'")
            resultado = self._executar_comando(texto)
            self._fila.put(resultado)          # fila da UI (thread-safe)
            self._ocupado = False

    def _ping_idle(self):
        """Ocioso → dispara ping em background (não trava a UI)."""
        if self._ocupado or not self._fila_cmds.empty():
            return
        threading.Thread(target=self._executar_ping, daemon=True).start()

    def _executar_ping(self):
        try:
            with self._conexao(timeout_resp=3) as s:
                s.sendall(b'{"cmd": "__ping__"}\n')
                _recv_linha(s)
            self._fila.put(("status", "SISTEMA DE COMANDOS • ONLINE"))
        except (OSError, socket.timeout):
            self._fila.put(("status", "OFFLINE — JARVIS NÃO RESPONDE"))

    # -------------------- interação --------------------

    def _enviar(self):
        texto = self.entrada.text().strip()
        if not texto:
            return
        self.entrada.clear()
        if self._ocupado:
            n = self._fila_cmds.qsize() + 1
            self.feedback.setText(f"enfileirado (posição {n})...")
        else:
            self.feedback.setText("...")
        self._fila_cmds.put(texto)

    def _consumir(self):
        try:
            while True:
                tipo, msg = self._fila.get_nowait()
                if tipo == "status":
                    self.status.setText(msg)
                elif tipo == "ok":
                    self.feedback.setText(msg or "✓")
                else:
                    self.feedback.setText(msg)
        except queue.Empty:
            pass

    def mousePressEvent(self, e):
        # Salva tamanho original para restauração
        if not hasattr(self, "_tamanho_original"):
            self._tamanho_original = self.size()
        # Reduz a janela para 20% do tamanho atual
        novo_largura = int(self.width() * 0.2)
        novo_altura = int(self.height() * 0.2)
        self.resize(novo_largura, novo_altura)
        self._arraste = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._arraste is not None:
            self.move(e.globalPos() - self._arraste)

    def mouseReleaseEvent(self, _):
        self._arraste = None
        # Restaura o tamanho original ao soltar o mouse
        if hasattr(self, "_tamanho_original"):
            self.resize(self._tamanho_original)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.entrada.clear()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        x = int((time.time() * 90) % self.width())
        p.setPen(QColor(0, 220, 255, 45))
        p.drawLine(x, 8, x, self.height() - 8)
        p.end()


if __name__ == "__main__":
    try:
        _log("criando QApplication...")
        app = QApplication(sys.argv[1:])
        _log("QApplication criada. Montando a janela...")
        box = Box()
        box.show()
        box.raise_()
        box.activateWindow()
        _log(f"janela exibida: visível={box.isVisible()} "
             f"posição=({box.x()},{box.y()}) "
             f"tamanho=({box.width()}x{box.height()})")
        _log("loop de eventos ativo — feche pelo ✕.")
        sys.exit(app.exec_())
    except Exception:
        import traceback
        _log("ERRO FATAL no box:")
        traceback.print_exc()
        sys.exit(1)
