"""
FILE: phone.py
DESCRIPTION: Módulo de controle do celular Android conectado via USB.
             Comunica-se com o dispositivo via ADB (shell) e espelha a
             tela no PC via scrcpy com mouse/teclado HID físicos.

REQUISITOS DE SISTEMA:
    sudo apt install -y adb scrcpy
    No celular: Opções do desenvolvedor → Depuração USB ativada e o PC
    autorizado no diálogo de confiança.

LIMITAÇÕES CONHECIDAS:
    - As flags --hid-* do scrcpy só funcionam via USB (não via adb tcpip).
    - `adb shell input text` não aceita acentos — o texto é convertido
      automaticamente ("você" → "voce").
"""
import datetime
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata

# -----------------------------------------------------------------------
# CONFIGURAÇÕES
# -----------------------------------------------------------------------
ADB_BIN     = "adb"
SCRCPY_BIN  = "scrcpy"
# -w desliga a tela do celular durante o espelhamento (economiza bateria
# e evita interferir em tela danificada); --hid-* emulam periféricos USB.
SCRCPY_ARGS = ["--hid-mouse", "--hid-keyboard", "-w"]
ADB_TIMEOUT = 6
APPS_LISTA_MAX = 12

# Apps populares → package Android. Chaves SEM acento (a entrada de voz
# é normalizada antes da consulta).
APPS_CONHECIDOS = {
    "whatsapp": "com.whatsapp",      "whats": "com.whatsapp",
    "wpp": "com.whatsapp",           "youtube": "com.google.android.youtube",
    "instagram": "com.instagram.android", "insta": "com.instagram.android",
    "chrome": "com.android.chrome",  "navegador": "com.android.chrome",
    "gmail": "com.google.android.gm","email": "com.google.android.gm",
    "spotify": "com.spotify.music",  "telegram": "org.telegram.messenger",
    "tiktok": "com.zhiliaoapp.musically", "facebook": "com.facebook.katana",
    "maps": "com.google.android.apps.maps", "mapa": "com.google.android.apps.maps",
    "play store": "com.android.vending",   "configuracoes": "com.android.settings",
    "settings": "com.android.settings",    "calculadora": "com.google.android.calculator",
    "telefone": "com.android.dialer","discord": "com.discord",
    "twitter": "com.twitter.android", "x": "com.twitter.android",
    "camera": "com.android.camera2", "galeria": "com.google.android.apps.photos",
    "fotos": "com.google.android.apps.photos", "netflix": "com.netflix.mediaclient",
    "twitch": "tv.twitch.android.app",
}

KEYCODES = {
    "home": 3,         "voltar": 4,      "back": 4,      "menu": 82,
    "recentes": 187,   "power": 26,      "volume_up": 24, "volume_down": 25,
    "volume_mute": 164, "enter": 66,     "delete": 67,    "tab": 61,
    "escape": 111,     "notificacoes": 83,
}

# -----------------------------------------------------------------------
# ESTADO INTERNO
# -----------------------------------------------------------------------
_lock        = threading.Lock()
_scrcpy_proc = None
_cache_pkgs  = None


# -----------------------------------------------------------------------
# UTILITÁRIOS
# -----------------------------------------------------------------------

def _sem_acento(texto: str) -> str:
    """minúsculas + sem acentos — normaliza entrada de voz/teclado."""
    texto = unicodedata.normalize("NFKD", texto.lower().strip())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _adb(*args, timeout: int = ADB_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [ADB_BIN, *args], capture_output=True, text=True, timeout=timeout
    )


def _adb_safe(*args) -> tuple:
    """
    Executa adb sem deixar exceção vazar.
    Retorna (resultado, erro) — erro None significa sucesso na chamada.
    """
    try:
        return _adb(*args), None
    except FileNotFoundError:
        return None, "O adb não está instalado. Rode: sudo apt install adb, senhor."
    except subprocess.TimeoutExpired:
        return None, "O celular demorou para responder, senhor."


def _precondicao() -> str | None:
    """
    Checagens comuns a toda operação de celular.
    Retorna mensagem de erro pronta para falar, ou None se tudo certo.
    """
    if shutil.which(ADB_BIN) is None:
        return "O adb não está instalado. Rode: sudo apt install adb, senhor."
    if not dispositivo_conectado():
        return ("Nenhum celular conectado via USB, senhor. "
                "Verifique o cabo e a depuração USB.")
    return None


def _listar_packages() -> list:
    """Lista packages instalados (cache em memória — chamada adb única)."""
    global _cache_pkgs
    with _lock:
        if _cache_pkgs is None:
            r, erro = _adb_safe("shell", "pm", "list", "packages")
            _cache_pkgs = [] if erro else [
                l.replace("package:", "").strip()
                for l in (r.stdout or "").splitlines()
                if l.startswith("package:")
            ]
    return _cache_pkgs


def invalidar_cache_apps():
    """Chame após instalar/desinstalar apps para atualizar a lista."""
    global _cache_pkgs
    with _lock:
        _cache_pkgs = None


# -----------------------------------------------------------------------
# API PÚBLICA — CONEXÃO E ESPELHAMENTO
# -----------------------------------------------------------------------

def dispositivo_conectado() -> bool:
    """True se há um dispositivo adb no estado 'device' (autorizado)."""
    if shutil.which(ADB_BIN) is None:
        return False
    r, _ = _adb_safe("devices")
    if r is None:
        return False
    return "\tdevice" in (r.stdout or "")


def espelhamento_ativo() -> bool:
    """True se o processo scrcpy existe e ainda está rodando."""
    return _scrcpy_proc is not None and _scrcpy_proc.poll() is None


def espelhar_tela() -> str:
    """Abre o scrcpy com mouse/teclado HID e tela do celular desligada."""
    global _scrcpy_proc
    if espelhamento_ativo():
        return "O espelhamento já está ativo, senhor."
    erro = _precondicao()
    if erro:
        return erro
    if shutil.which(SCRCPY_BIN) is None:
        return "O scrcpy não está instalado. Rode: sudo apt install scrcpy, senhor."
    try:
        _scrcpy_proc = subprocess.Popen([SCRCPY_BIN, *SCRCPY_ARGS])
        return "Espelhando a tela do celular, senhor."
    except Exception as e:
        return f"Não consegui abrir o espelhamento: {e}, senhor."


def fechar_espelhamento() -> str:
    global _scrcpy_proc
    if _scrcpy_proc is None:
        return "O espelhamento não está ativo, senhor."
    if _scrcpy_proc.poll() is not None:
        # Terminou sozinho (janela fechada manualmente) — só limpa o handle
        _scrcpy_proc = None
        return "O espelhamento não está ativo, senhor."
    _scrcpy_proc.terminate()
    try:
        _scrcpy_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        _scrcpy_proc.kill()
    _scrcpy_proc = None
    return "Espelhamento encerrado, senhor."


# [v3-FALAS] 5 padrões de frase por estado — random.choice() decide
_FALAS_STATUS = {
    "conectado_espelhado": [
        "Celular conectado e espelhamento ativo, senhor. Tela no PC e pronto pra uso.",
        "Conexão firme com o celular, senhor, e o espelhamento está rodando.",
        "Celular no PC, espelho ligado. Tudo sob controle, senhor.",
        "Ligação com o celular estável e a tela espelhada, senhor.",
        "Celular conectado, espelhamento ativo. Pode comandar por aqui, senhor.",
    ],
    "conectado_sem_espelho": [
        "Celular conectado, mas o espelhamento está desligado, senhor.",
        "Conexão com o celular OK, senhor. O espelho da tela, porém, não está ativo.",
        "Celular no PC, senhor, mas sem espelhamento. Quer que eu ligue?",
        "Conectado ao celular, espelho desligado. É só pedir pra espelhar, senhor.",
        "A ligação com o celular existe, o espelhamento não, senhor.",
    ],
    "desconectado": [
        "Nenhum celular conectado ao PC no momento, senhor.",
        "Sem celular na linha, senhor. Verifique o cabo USB.",
        "Não vejo nenhum celular conectado, senhor.",
        "Celular ausente, senhor. Nada plugado no USB.",
        "Nenhuma conexão com celular agora, senhor.",
    ],
}


def status_dispositivo() -> str:
    import random as _r
    if not dispositivo_conectado():
        return _r.choice(_FALAS_STATUS["desconectado"])
    if espelhamento_ativo():
        return _r.choice(_FALAS_STATUS["conectado_espelhado"])
    return _r.choice(_FALAS_STATUS["conectado_sem_espelho"])

# -----------------------------------------------------------------------
# API PÚBLICA — APPS
# -----------------------------------------------------------------------

def resolver_package(nome: str) -> str | None:
    """
    Resolve nome amigável → package Android.
    Ordem: dicionário direto → alias parcial → busca nos instalados.
    """
    alvo = _sem_acento(nome)
    if not alvo:
        return None
    if alvo in APPS_CONHECIDOS:
        return APPS_CONHECIDOS[alvo]
    if len(alvo) >= 4:  # evita falso positivo com nomes muito curtos
        for chave, pkg in APPS_CONHECIDOS.items():
            if alvo in chave:
                return pkg
    alvo_flat = alvo.replace(" ", "")
    for pkg in _listar_packages():
        if alvo_flat and alvo_flat in pkg.replace(".", ""):
            return pkg
    return None


def abrir_app(nome: str) -> str:
    erro = _precondicao()
    if erro:
        return erro
    pkg = resolver_package(nome)
    if not pkg:
        return f"Não encontrei o aplicativo {nome} no celular, senhor."
    r, erro = _adb_safe("shell", "monkey", "-p", pkg,
                        "-c", "android.intent.category.LAUNCHER", "1")
    if erro:
        return erro
    if r.returncode == 0:
        return f"Abrindo {nome} no celular, senhor."
    return f"Não consegui abrir {nome} no celular, senhor."


def fechar_app(nome: str) -> str:
    erro = _precondicao()
    if erro:
        return erro
    pkg = resolver_package(nome)
    if not pkg:
        return f"Não encontrei o aplicativo {nome} para fechar, senhor."
    r, erro = _adb_safe("shell", "am", "force-stop", pkg)
    if erro:
        return erro
    if r.returncode == 0:
        return f"Fechei {nome} no celular, senhor."
    return f"Não consegui fechar {nome}, senhor."


def listar_apps_resumido() -> str:
    erro = _precondicao()
    if erro:
        return erro
    pkgs = _listar_packages()
    if not pkgs:
        return "Não consegui listar os aplicativos, senhor."
    pkgs_set = set(pkgs)
    # Prioriza apps conhecidos instalados (nomes amigáveis, sem aliases)
    vistos, principais = set(), []
    for nome, pkg in APPS_CONHECIDOS.items():
        if pkg in pkgs_set and pkg not in vistos:
            vistos.add(pkg)
            principais.append(nome)
    if principais:
        lista = ", ".join(principais[:APPS_LISTA_MAX])
        return (f"{len(pkgs)} aplicativos instalados. "
                f"Entre os principais: {lista}, senhor.")
    return f"{len(pkgs)} aplicativos instalados no celular, senhor."


# -----------------------------------------------------------------------
# API PÚBLICA — BOTÕES, TELA E DIGITAÇÃO
# -----------------------------------------------------------------------

def apertar_botao(nome: str) -> str:
    erro = _precondicao()
    if erro:
        return erro
    chave = _sem_acento(nome)
    if chave not in KEYCODES:
        return f"Não conheço o botão {nome} do celular, senhor."
    r, erro = _adb_safe("shell", "input", "keyevent", str(KEYCODES[chave]))
    if erro:
        return erro
    if r.returncode == 0:
        return f"Botão {nome} pressionado no celular, senhor."
    return f"Não consegui pressionar o botão {nome}, senhor."


def bloquear_tela() -> str:
    """KEYCODE_SLEEP (223) — dorme a tela sempre (não é toggle)."""
    erro = _precondicao()
    if erro:
        return erro
    r, erro = _adb_safe("shell", "input", "keyevent", "223")
    if erro:
        return erro
    return "Celular bloqueado, senhor."


def desbloquear_tela() -> str:
    """KEYCODE_WAKEUP (224) + swipe up — best effort; senha exige digitação."""
    erro = _precondicao()
    if erro:
        return erro
    _adb_safe("shell", "input", "keyevent", "224")
    r, erro = _adb_safe("shell", "input", "swipe", "540", "1500", "540", "500", "300")
    if erro:
        return erro
    return ("Desbloqueando o celular, senhor. "
            "Se houver senha, digite-a com o teclado do espelhamento.")


def digitar_texto(texto: str) -> str:
    erro = _precondicao()
    if erro:
        return erro
    original = texto.strip()
    if not original:
        return "Não há nada para digitar, senhor."

    # input text só aceita ASCII; escapamos metacaracteres do shell Android
    # (backslash PRIMEIRO) e codificamos espaços como %s.
    txt = _sem_acento(original)
    aviso = "" if txt == original.lower() else " (sem acentos — limitação do teclado ADB)"
    for especial in ['\\', '"', "'", ':', ';', '(', ')', '<', '>', '|',
                     '*', '&', '$', '#', '!', '?', '[', ']', '{', '}',
                     ',', '%', '-']:
        txt = txt.replace(especial, "\\" + especial)
    txt = txt.replace(" ", "%s")

    r, erro = _adb_safe("shell", "input", "text", txt)
    if erro:
        return erro
    if r.returncode == 0:
        return f"Digitado no celular{aviso}, senhor."
    return "Não consegui digitar no celular, senhor."

# -----------------------------------------------------------------------
# API PÚBLICA — NOTIFICAÇÕES
# -----------------------------------------------------------------------

def _nome_amigavel(pkg: str) -> str:
    """package Android → nome amigável (ou último trecho do package)."""
    for nome, p in APPS_CONHECIDOS.items():
        if p == pkg:
            return nome
    return pkg.rsplit(".", 1)[-1]


def listar_notificacoes() -> str:
    """
    Lista notificações com REMETENTE e resumo do conteúdo, lendo o
    dumpsys --noredact (que expõe android.title/android.text no shell
    adb — validado no Redmi 9 / Android 12).

    Saída agrupada por app no estilo:
      "3 notificações: WhatsApp — Zap de fulano: 'vamos sair hoje?';
       Instagram — falcao.061: 'Enviou um reel para você'; ..."
    Filtro de ruído: notificações de sistema (USB, teclado, Gboard)
    ficam de fora do resumo falado (contadas à parte).
    """
    erro = _precondicao()
    if erro:
        return erro
    r, erro = _adb_safe("shell", "dumpsys", "notification", "--noredact")
    if erro:
        return erro
    if r.returncode != 0:
        return "Não consegui ler as notificações, senhor."

    # --- parse: blocos de notificação no dumpsys (formato Redmi/A12):
    # 'NotificationRecord(0x...): pkg=com.instagram.android ...'
    # 'android.title=String (falcao.061)'
    # 'android.text=String (Enviou um reel para você)'
    # O pkg NÃO vem no começo da linha → buscar por ocorrência, não prefixo.
    itens = []          # (pkg, titulo, texto)
    pkg_atual = None
    titulo = texto = None

    def _fecha_bloco():
        if pkg_atual and (titulo or texto):
            itens.append((pkg_atual, titulo or "", texto or ""))

    for linha in (r.stdout or "").splitlines():
        ls = linha.strip()
        # package: 'pkg=ALGO' em QUALQUER posição da linha
        if "pkg=" in ls:
            _fecha_bloco()
            pkg_atual = ls.split("pkg=", 1)[1].split()[0].rstrip(",")
            titulo = texto = None
        # título/texto: prefixos com valor String(...)
        elif ls.startswith("android.title=String (") and ls.endswith(")"):
            titulo = ls[len("android.title=String ("):-1]
        elif ls.startswith("android.text=String (") and ls.endswith(")"):
            texto = ls[len("android.text=String ("):-1]
    _fecha_bloco()

    # remove duplicatas idênticas (dumpsys repete o mesmo item às vezes)
    vistos, unicos = [], set()
    for it in itens:
        if it not in vistos:
            vistos.append(it)
            unicos.add(it)
    itens = vistos

    if not itens:
        return "Nenhuma notificação ativa no celular, senhor."

    # --- classifica: apps de mensagem vs sistema ---
    _MSG_APPS = {
        "com.whatsapp": "WhatsApp",
        "com.instagram.android": "Instagram",
        "com.facebook.katana": "Facebook",
        "org.telegram.messenger": "Telegram",
        "com.discord": "Discord",
    }
    _BANCO_PKGS = ("bancointer", "inter.co")     # Inter (achado por conter)
    _SISTEMA = ("android", "com.android", "com.google.android.gms",
                "com.google.android.inputmethod")

    msgs, banco, sistema = [], [], 0
    for pkg, titulo, texto in itens:
        if any(pkg.startswith(s) for s in _SISTEMA) or \
           any(k in pkg for k in ("usb", "inputmethod", "keyboard")):
            sistema += 1
        elif any(b in pkg for b in _BANCO_PKGS):
            banco.append((titulo, texto))
        else:
            nome = _MSG_APPS.get(pkg, _nome_amigavel(pkg))
            msgs.append((nome, titulo, texto))

    # --- monta a fala ---
    partes = []
    if msgs:
        detalhes = []
        for nome, titulo, texto in msgs[:6]:    # no máx 6 itens falados
            quem = titulo if titulo else "alguém"
            o_que = f": {texto[:40]}" if texto else ""
            detalhes.append(f"{nome} — {quem}{o_que}")
        plural = "notificações" if len(msgs) > 1 else "notificação"
        partes.append(f"{len(msgs)} {plural} de mensagem: "
                      + "; ".join(detalhes))
    if banco:
        detalhes = []
        for titulo, texto in banco[:4]:
            quem = "Banco Inter" if not titulo else titulo
            o_que = f": {texto[:40]}" if texto else ""
            detalhes.append(f"{quem}{o_que}")
        partes.append(f"{len(banco)} aviso{'s' if len(banco) > 1 else ''} do "
                      f"Inter: " + "; ".join(detalhes))
    if sistema:
        partes.append(f"e {sistema} de sistema, que ignoro")

    if not partes:
        return "Só notificações de sistema no celular, senhor. Nada de mensagem."

    total = len(msgs) + len(banco)
    intro = (f"{total} notificações no celular: " if total > 1
             else "Uma notificação no celular: ")
    return intro + "; ".join(partes) + ", senhor."

def _extrair_keys_notificacoes() -> list:
    """
    Extrai notification-keys (formato AOSP 'user|pkg|id|tag|uid') de
    DUAS fontes: dumpsys (linhas 'key=...') e cmd notification list.
    Retorna lista única e ordenada.
    """
    keys = set()
    padrao_key = r"(\d+\|[a-zA-Z][\w.]*\|-?\d+\|[\w.\-]*\|\d+)"

    r, _ = _adb_safe("shell", "dumpsys", "notification", "--noredact")
    if r is not None and r.returncode == 0:
        for m in re.finditer(r"key=" + padrao_key, r.stdout or ""):
            keys.add(m.group(1))

    r2, _ = _adb_safe("shell", "cmd", "notification", "list")
    if r2 is not None and r2.returncode == 0:
        for m in re.finditer(padrao_key, r2.stdout or ""):
            keys.add(m.group(1))

    return sorted(keys)


def limpar_notificacoes() -> str:
    """
    [v4-FIX] Android 12 do Redmi 9 NÃO tem 'remove_all' nem 'remove'
    (confirmado na listagem de subcomandos do aparelho) — as versões
    antigas falhavam em silêncio por isso. O que EXISTE no A12 é
    'snooze --for <msec> <notification-key>' — snooze de 90 dias
    remove a notificação do painel na prática.

    Cascata:
    1. remove_all (Android 13+ — mantém pro futuro)
    2. snooze 90 dias por key (extraídas de dumpsys + list)
    3. painel aberto (fallback manual)
    """
    erro = _precondicao()
    if erro:
        return erro

    # 1) remove_all — só funciona em Android 13+
    r, _ = _adb_safe("shell", "cmd", "notification", "remove_all")
    if r is not None and r.returncode == 0:
        return "Notificações limpas, chefe."

    # 2) snooze de 90 dias (7.776.000.000 ms) por key
    keys = _extrair_keys_notificacoes()
    print(f"[PHONE] snooze: {len(keys)} key(s) extraída(s)")
    snoozadas = 0
    for key in keys:
        rr, _ = _adb_safe("shell", "cmd", "notification", "snooze",
                          "--for", "7776000000", key)
        if rr is not None and rr.returncode == 0:
            snoozadas += 1
        else:
            err = ((rr.stderr if rr else "") or (rr.stdout if rr else "") or "").strip()
            print(f"[PHONE] snooze falhou p/ '{key}': {err[:80]}")

    if snoozadas:
        return (f"Joguei {snoozadas} notificação(ões) pro limbo de 90 dias, "
                f"chefe. Painel limpo.")
    if keys:
        print("[PHONE] keys achadas mas snooze falhou — mande as linhas "
              "[PHONE] acima que eu ajusto o formato da key")

    # 3) fallback: ANDROID 12 não deixa apagar por comando → arma o cenário
    #    completo: ESPELHA o celular (você vê o painel no PC, tela grande,
    #    mouse do scrcpy funciona) + EXPANDE o painel no celular — só falta
    #    você clicar no "limpar tudo" com o mouse do espelhamento.
    print("[PHONE] snooze não resolveu — preparando espelhamento + painel")
    _adb_safe("shell", "input", "keyevent", "83")      # expande o painel
    if not espelhamento_ativo():
        resultado = espelhar_tela()                    # scrcpy sobe junto
        print(f"[PHONE] auto-espelhamento: {resultado}")
    return ("O Android 12 desse celular não deixa apagar por comando, "
            "chefe. Espelhei o celular e abri o painel de notificações — "
            "só clicar no limpar tudo aí, com o mouse.")


# -----------------------------------------------------------------------
# API PÚBLICA — WIFI E BLUETOOTH
# -----------------------------------------------------------------------

def status_wifi() -> bool | None:
    r, _ = _adb_safe("shell", "settings", "get", "global", "wifi_on")
    if r is None or r.returncode != 0:
        return None
    return r.stdout.strip() == "1"


def alternar_wifi(ligar: bool | None = None) -> str:
    """True=ligar, False=desligar, None=alternar conforme estado atual."""
    erro = _precondicao()
    if erro:
        return erro
    atual = status_wifi()
    alvo = (not atual) if ligar is None else ligar
    if atual == alvo:
        return f"O wifi já está {'ligado' if alvo else 'desligado'}, senhor."
    r, erro = _adb_safe("shell", "svc", "wifi", "enable" if alvo else "disable")
    if erro:
        return erro
    if r.returncode == 0:
        return f"Wifi {'ligando' if alvo else 'desligando'}, senhor."
    return "Não consegui alternar o wifi, senhor."


def status_bluetooth() -> bool | None:
    r, _ = _adb_safe("shell", "settings", "get", "global", "bluetooth_on")
    if r is None or r.returncode != 0:
        return None
    return r.stdout.strip() == "1"


def alternar_bluetooth(ligar: bool | None = None) -> str:
    """svc (Android 13+) → fallback bluetooth_manager (10-12)."""
    erro = _precondicao()
    if erro:
        return erro
    atual = status_bluetooth()
    alvo = (not atual) if ligar is None else ligar
    if atual is not None and atual == alvo:
        return f"O bluetooth já está {'ligado' if alvo else 'desligado'}, senhor."
    acao = "enable" if alvo else "disable"
    r, _ = _adb_safe("shell", "svc", "bluetooth", acao)
    if r is None or r.returncode != 0:
        r, _ = _adb_safe("shell", "cmd", "bluetooth_manager", acao)
    if r is not None and r.returncode == 0:
        return f"Bluetooth {'ligando' if alvo else 'desligando'}, senhor."
    return ("Não consegui alternar o bluetooth por comando, senhor. "
            "Alguns Androids só permitem pela tela.")


# -----------------------------------------------------------------------
# API PÚBLICA — VIBRAÇÃO, PRINT, BATERIA E MÍDIA
# -----------------------------------------------------------------------

def vibrar(duracao_ms: int = 800, toques: int = 1) -> str:
    """
    Faz o celular vibrar. duracao_ms: 200-5000 (clamp). toques: 1-3.
    Monta uma waveform: [vibra, pausa, vibra, ...] com amplitude 255.
    """
    erro = _precondicao()
    if erro:
        return erro
    duracao_ms = max(200, min(duracao_ms, 5000))
    toques = max(1, min(toques, 3))

    timings, amplitudes = [], []
    for i in range(toques):
        timings.append(str(duracao_ms // toques))
        amplitudes.append("255")
        if i < toques - 1:
            timings.append("300")   # pausa entre toques
            amplitudes.append("0")

    sessao = str(int(time.time()) % 100000)
    r, erro = _adb_safe("shell", "cmd", "vibration", "waveform",
                        sessao, " ".join(timings), " ".join(amplitudes))
    if erro:
        return erro
    if r.returncode == 0:
        return "Celular vibrando, senhor."
    # fallback: efeito pré-definido (click)
    r, _ = _adb_safe("shell", "cmd", "vibration", "prebaked", sessao, "0", "1")
    if r is not None and r.returncode == 0:
        return "Celular vibrando, senhor."
    return "Não consegui fazer o celular vibrar, senhor."


PASTA_SCREENSHOTS = os.path.join(os.path.expanduser("~"), "Jarvis_screenshots")


def screenshot() -> str:
    """Captura a tela do celular, salva no PC e abre no visualizador."""
    erro = _precondicao()
    if erro:
        return erro
    os.makedirs(PASTA_SCREENSHOTS, exist_ok=True)
    caminho = os.path.join(
        PASTA_SCREENSHOTS,
        f"celular_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
    )
    try:
        with open(caminho, "wb") as f:
            proc = subprocess.run(
                [ADB_BIN, "exec-out", "screencap", "-p"],
                stdout=f, stderr=subprocess.PIPE, timeout=10,
            )
    except subprocess.TimeoutExpired:
        return "A captura demorou demais, senhor."

    if proc.returncode != 0 or os.path.getsize(caminho) < 1000:
        try:
            os.remove(caminho)   # remove arquivo vazio/corrompido
        except OSError:
            pass
        return "Não consegui capturar a tela do celular, senhor."

    subprocess.Popen(["xdg-open", caminho])
    return "Print do celular salvo e aberto, senhor."


def status_bateria() -> str:
    erro = _precondicao()
    if erro:
        return erro
    r, erro = _adb_safe("shell", "dumpsys", "battery")
    if erro:
        return erro
    if r.returncode != 0:
        return "Não consegui ler a bateria, senhor."

    saida = r.stdout or ""
    m = re.search(r"level:\s*(\d+)", saida)
    if not m:
        return "Não consegui ler o nível de bateria, senhor."

    nivel = int(m.group(1))
    carregando = bool(re.search(r"USB powered:\s*true|AC powered:\s*true", saida))
    st = re.search(r"status:\s*(\d+)", saida)
    _STATUS = {2: "carregando", 3: "usando bateria",
               4: "carregada", 5: "com carga completa"}
    estado = _STATUS.get(int(st.group(1)) if st else 0, "") or ("carregando" if carregando else "")

    msg = f"Bateria do celular em {nivel} por cento"
    if estado:
        msg += f", {estado}"
    if nivel <= 20 and not carregando:
        msg += ". Atenção senhor, está acabando"
    return msg + ", senhor."


_MEDIA_KEYS = {
    "play_pause": 85,   # KEYCODE_MEDIA_PLAY_PAUSE
    "next": 87,         # KEYCODE_MEDIA_NEXT
    "previous": 88,     # KEYCODE_MEDIA_PREVIOUS
}


def controle_midia(acao: str) -> str:
    """Controla mídia tocando no celular (Spotify, YouTube etc.)."""
    erro = _precondicao()
    if erro:
        return erro
    chave = acao.lower().strip()
    if chave not in _MEDIA_KEYS:
        return f"Não conheço o controle {acao}, senhor."
    r, erro = _adb_safe("shell", "input", "keyevent", str(_MEDIA_KEYS[chave]))
    if erro:
        return erro
    if r.returncode == 0:
        desc = {"play_pause": "Reprodução alternada",
                "next": "Próxima faixa",
                "previous": "Faixa anterior"}[chave]
        return f"{desc} no celular, senhor."
    return "Não consegui controlar a mídia, senhor."
