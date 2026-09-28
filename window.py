"""
FILE: window.py
DESCRIPTION: Controla a janela do JARVIS — posição, tamanho e o
             comportamento "natural" de entrar/sair da tela.

v10 — [ESQUIVA-REFLEXO] zona de alerta AO REDOR da janela
     (ESQUIVA_MARGEM_PX), gatilho curto (0,3s), fuga com lerp
     acelerado (ESQUIVA_VELOCIDADE) e janela encolhida a 40% do
     tamanho durante a fuga (ESQUIVA_FATOR_TAM). Mouse longe por
     ESQUIVA_RETORNO_SEG → volta ao tamanho normal (fica onde está —
     voltar pro lugar antigo seria se jogar debaixo do mouse de novo).
     O enxame recebe o aviso (orbs.esquivar) e faz a animação de susto.

v9 — [ESQUIVA-DE-MOUSE] mouse parado sobre a janela por 3s → ela
     desliza ~260px pro lado com mais espaço (cooldown de 2s entre
     fugas — anti-perseguição). Roda DENTRO de atualizar_por_frame()
     (thread do imshow — mesma regra de sempre: só ela toca na janela).
     Qualquer erro → esquiva se desliga sozinha e esquiva_falhou()
     acende o aviso na HUD do main.py. O resto do sistema segue vivo.

v8.1 — _alvo_global() corrigido (faltava 'wa'), 'sair da tela' sem
     clamp, sequências de waypoints simples, calibração no 1º frame.
v8 — autocalibração de offset, workarea conservadora, janela viva.
v7 — posicionamento via próprio OpenCV (cv2.moveWindow no loop vídeo).

REQUISITOS: sudo apt install xdotool x11-utils
"""

import random
import shutil
import subprocess
import threading
import time

import cv2

from voice import jarvis_voice

# -----------------------------------------------------------------------
# PARÂMETROS (ajuste livre)
# -----------------------------------------------------------------------
NOME_JANELA     = "JARVIS Interface"

TAM_PADRAO      = (640, 480)
TAM_CANTO       = (320, 240)
TAM_MIN_LARG    = 220
FATOR_MAIOR     = 1.25
FATOR_MENOR     = 0.90

MARGEM_CANTO    = 16
MARGEM_INFERIOR = 10
MARGEM_TOPO     = 24
MARGEM_LADO     = 60
TIRA_VISIVEL    = 5
MARGEM_SEGURANCA = 20

IDLE_SAIR_SEG   = 220
LOOP_AGENTE_SEG = 0.1
SUAVIDADE       = 0.22

# --- VIDA ---
AUTONOMIA_ATIVA          = True
AUTONOMIA_MIN_SEG        = 8
AUTONOMIA_MAX_SEG        = 40
AUTONOMIA_CHANCE_MOVER   = 0.85
AUTONOMIA_CHANCE_ESPIAR  = 0.35
PASSO_ESPIAR_PX          = 80
TAM_AUTO_MIN             = 250
MARGEM_VAGAR             = 65
VAGAR_PASSOS             = (2, 4)
ESPIAR_OLHADINHAS        = (1, 3)

# --- [v10-ESQUIVA] FUGIR DO MOUSE (reflexo rápido) ---
# Mouse na ZONA DE ALERTA (janela + margem ao redor) por um instante curto
# → encolhe pra 40% do tamanho (60% menor) e desliza pro lado com mais
# espaço, com lerp acelerado. Mouse longe por uns segundos → volta ao
# tamanho normal (fica onde está — voltar pro lugar antigo seria se
# jogar debaixo do mouse de novo).
# Erro em qualquer parte → desliga e acende "ESQUIVA DE MOUSE: OFF" na HUD.
ESQUIVA_ATIVA          = True
ESQUIVA_MARGEM_PX      = 36     # zona de alerta AO REDOR da janela (px)
ESQUIVA_TEMPO_SEG      = 0.30   # mouse na zona por isso → foge (era 1.7)
ESQUIVA_FATOR_TAM      = 0.40   # tamanho na fuga = 40% do atual (60% menor)
ESQUIVA_TAM_MIN        = 120    # piso da fuga (embaixo vira poeira de pixel)
ESQUIVA_DESLOC_PX      = 360    # quanto desliza
ESQUIVA_COOLDOWN_SEG   = 1.2    # pausa entre fugas (anti-perseguição)
ESQUIVA_VELOCIDADE     = 0.55   # lerp acelerado DURANTE a fuga (SUAVIDADE = 0.22)
ESQUIVA_RETORNO_SEG    = 2.5    # mouse longe por isso → volta ao tamanho normal

# --- HUMOR ---
HUMOR_ATIVO              = True
HUMOR_MIN_SEG            = 60
HUMOR_MAX_SEG            = 150
HUMOR_CHANCE_TROCAR      = 0.47

XDOTOOL_BIN     = "xdotool"

# -----------------------------------------------------------------------
# ESTADO INTERNO
# _pos_atual/_alvo/_seq são escritos SÓ no loop de vídeo (thread do
# imshow) — sem lock. _acao_pendente vem de outras threads → com _lock.
# -----------------------------------------------------------------------
_lock          = threading.Lock()
_agente_ativo  = False
_thread_agente = None
_win_id        = None
_fora_da_tela  = False
_pre_canto     = None
_acao_pendente = None
_ultima_fala   = time.time()

_alvo        = None
_pos_atual   = None
_no_alvo     = True
_seq         = None
_seq_espera  = 0.0
_seq_ts      = None

_off_x, _off_y = 0, 0

# [v10-ESQUIVA] estado da esquiva (escrito só na thread do vídeo)
_esquiva_ts         = None    # quando o mouse ENTROU na zona (None = fora)
_esquiva_ultima     = 0.0     # timestamp da última fuga (cooldown)
_esquiva_aviso      = False   # True = esquiva FALHOU e se desligou
_esquiva_fugindo    = False   # True = janela está no modo encolhido
_esquiva_tam_antes  = None    # (w, h) de antes de encolher (pro retorno)
_esquiva_fora_desde = None    # quando o mouse saiu da zona (timer de retorno)

_wa_cache = None
_wa_ts    = 0.0
_WA_TTL   = 30.0


# -----------------------------------------------------------------------
# LEITURA DO X (boot/debug — nada disto roda no caminho crítico)
# -----------------------------------------------------------------------

def _disponivel() -> bool:
    return shutil.which(XDOTOOL_BIN) is not None


def _run(*args, timeout=3) -> subprocess.CompletedProcess:
    return subprocess.run([XDOTOOL_BIN, *args],
                          capture_output=True, text=True, timeout=timeout)


def _janela_id() -> int | None:
    global _win_id
    if _win_id is not None:
        return _win_id
    try:
        r = _run("search", "--onlyvisible", "--name", NOME_JANELA)
        for linha in (r.stdout or "").splitlines():
            linha = linha.strip()
            if linha.isdigit():
                _win_id = int(linha)
                return _win_id
    except Exception:
        pass
    return None


def _geometria_x() -> tuple | None:
    wid = _janela_id()
    if wid is None:
        return None
    try:
        r = _run("getwindowgeometry", "--shell", str(wid))
        dados = {}
        for linha in (r.stdout or "").splitlines():
            if "=" in linha:
                k, v = linha.split("=", 1)
                dados[k.strip()] = v.strip()
        return (int(dados["X"]), int(dados["Y"]),
                int(dados["WIDTH"]), int(dados["HEIGHT"]))
    except Exception:
        return None


def _workarea_bruta() -> tuple:
    try:
        r = subprocess.run(["xprop", "-root", "_NET_WORKAREA"],
                           capture_output=True, text=True, timeout=3)
        nums = r.stdout.split("=")[-1].split(",")
        if len(nums) == 4:
            x, y, w, h = (int(n.strip()) for n in nums)
            if w > 200 and h > 200:
                return x, y, w, h
    except Exception:
        pass
    try:
        r = _run("getdisplaygeometry")
        w, h = r.stdout.split()
        return 0, 0, int(w), int(h)
    except Exception:
        return 0, 0, 1920, 1080


def _workarea() -> tuple:
    """Workarea CONSERVADORA (cache 30s): a bruta menos margem de segurança."""
    global _wa_cache, _wa_ts
    if _wa_cache is None or time.time() - _wa_ts > _WA_TTL:
        wx, wy, ww, wh = _workarea_bruta()
        m = MARGEM_SEGURANCA
        _wa_cache = (wx + m, wy + m,
                     max(400, ww - 2 * m), max(300, wh - 2 * m))
        _wa_ts = time.time()
    return _wa_cache


def _remover_decoracoes():
    wid = _janela_id()
    if wid is None or shutil.which("xprop") is None:
        return
    try:
        subprocess.run(
            ["xprop", "-id", str(wid), "-f", "_MOTIF_WM_HINTS", "32c",
             "-set", "_MOTIF_WM_HINTS", "0x2, 0x0, 0x0, 0x0, 0x0"],
            capture_output=True, timeout=3,
        )
        print("[WINDOW] Decorações do WM removidas (HUD frameless).")
    except Exception as e:
        print(f"[WINDOW] Não consegui remover decorações: {e}")


# -----------------------------------------------------------------------
# [v8] CALIBRAÇÃO
# -----------------------------------------------------------------------

def _calibrar_offset():
    """
    Move a janela para (100,100) pela API do OpenCV, lê onde caiu de
    verdade e guarda o offset. Chamada UMA vez, no 1º frame (thread certa).
    """
    global _off_x, _off_y
    try:
        cv2.moveWindow(NOME_JANELA, 100, 100)
        time.sleep(0.25)
        g = _geometria_x()
        if g:
            _off_x = g[0] - 100
            _off_y = g[1] - 100
            if abs(_off_x) > 5 or abs(_off_y) > 5:
                print(f"[WINDOW] Calibração: offset de correção "
                      f"({_off_x:+d}, {_off_y:+d}) — WM reposiciona pedidos.")
            else:
                _off_x, _off_y = 0, 0
    except Exception:
        _off_x, _off_y = 0, 0


# -----------------------------------------------------------------------
# GEOMETRIA SEGURA
# -----------------------------------------------------------------------

def _caber(w: int, h: int, wa: tuple) -> tuple:
    _, _, ww, wh = wa
    if w > ww or h > wh:
        escala = min(ww / w, wh / h)
        return int(w * escala), int(h * escala)
    return int(w), int(h)


def _clampar(nx, ny, w: int, h: int, wa: tuple) -> tuple:
    """Alvo dentro da área útil + OFFSET compensado."""
    wx, wy, ww, wh = wa
    nx = int(nx) - _off_x
    ny = int(ny) - _off_y
    nx = max(wx - _off_x, min(nx, wx + ww - w - _off_x))
    ny = max(wy - _off_y, min(ny, wy + wh - h - _off_y))
    return int(nx), int(ny)


def _teto_tamanho(wa: tuple) -> tuple:
    _, _, ww, wh = wa
    max_w = min(TAM_PADRAO[0], ww - 32)
    max_h = min(TAM_PADRAO[1], wh - 32)
    if int(max_w * TAM_PADRAO[1] / TAM_PADRAO[0]) > max_h:
        max_w = int(max_h * TAM_PADRAO[0] / TAM_PADRAO[1])
    return max_w, max_h


# -----------------------------------------------------------------------
# POSIÇÕES CALCULADAS
# -----------------------------------------------------------------------

def _pos_centro(wa, w, h):
    wx, wy, ww, wh = wa
    return wx + (ww - w) // 2, wy + (wh - h) // 2


def _pos_lado(wa, w, h, lado: str):
    wx, wy, ww, wh = wa
    if lado == "esquerda":
        return wx + MARGEM_LADO, wy + (wh - h) // 2
    if lado == "direita":
        return wx + ww - w - MARGEM_LADO, wy + (wh - h) // 2
    if lado == "cima":
        return wx + (ww - w) // 2, wy + MARGEM_TOPO
    return wx + (ww - w) // 2, wy + wh - h - MARGEM_INFERIOR


def _pos_canto(wa, w, h, canto="inferior_esquerdo"):
    """[v8] canto padrão = INFERIOR ESQUERDO (a pedido)."""
    wx, wy, ww, wh = wa
    if canto == "inferior_direito":
        return wx + ww - w - MARGEM_CANTO, wy + wh - h - MARGEM_INFERIOR
    if canto == "superior_direito":
        return wx + ww - w - MARGEM_CANTO, wy + MARGEM_TOPO
    if canto == "superior_esquerdo":
        return wx + MARGEM_CANTO, wy + MARGEM_TOPO
    return wx + MARGEM_CANTO, wy + wh - h - MARGEM_INFERIOR


def _pos_fora(wa, w, h, lado="direita"):
    wx, wy, ww, wh = wa
    y = wy + (wh - h) // 2
    if lado == "direita":
        return wx + ww - TIRA_VISIVEL, y
    return -w + TIRA_VISIVEL, y


# -----------------------------------------------------------------------
# EXECUÇÃO DE AÇÕES — roda no loop de vídeo (thread do imshow)
# -----------------------------------------------------------------------

def _tamanho_atual() -> tuple:
    if _pos_atual:
        return _pos_atual[2], _pos_atual[3]
    return TAM_PADRAO


def _alvo_global(x, y, w, h, clamp=True):
    """
    [v8.1-FIX] Define _alvo. Resolve o wa INTERNAMENTE.

    clamp=True  → área útil + offset compensado (posições normais)
    clamp=False → só compensa offset ('sair da tela': o alvo É ficar fora)
    """
    global _alvo, _no_alvo
    if clamp:
        x, y = _clampar(x, y, w, h, _workarea())
    else:
        x, y = int(x) - _off_x, int(y) - _off_y
    _alvo = (int(x), int(y), int(w), int(h))
    _no_alvo = False


def _executar_acao(acao: str):
    """
    Converte uma ação em ALVO (ou SEQUÊNCIA de waypoints). Só mexe em
    estado Python — quem aplica é o lerp do loop de vídeo.
    """
    global _fora_da_tela, _pre_canto, _seq, _seq_espera
    global _esquiva_fugindo, _esquiva_tam_antes, _esquiva_fora_desde
    wa = _workarea()
    _seq = None
    _seq_espera = 0.0

    # [v10] comando explícito de posição/tamanho cancela o estado de
    # fuga (esses comandos já definem o tamanho deles mesmos)
    if (acao in ("voltar", "centro", "esquerda", "direita", "cima", "baixo",
                 "restaurar", "maior", "menor")
            or acao.startswith("canto")):
        _esquiva_fugindo = False
        _esquiva_tam_antes = None
        _esquiva_fora_desde = None

    if acao in ("sair", "sair_esquerda"):
        tamanho = (_esquiva_tam_antes
                   if (_esquiva_fugindo and _esquiva_tam_antes)
                   else _tamanho_atual())
        w, h = _caber(*tamanho, wa)
        lado = "direita" if acao == "sair" else "esquerda"
        x, y = _pos_fora(wa, w, h, lado)
        _alvo_global(x, y, w, h, clamp=False)
        _fora_da_tela = True
        print(f"[WINDOW] Sai da tela ({lado}) → alvo ({x}, {y})")

    elif acao in ("voltar", "centro"):
        w, h = _caber(*TAM_PADRAO, wa)
        x, y = _pos_centro(wa, w, h)
        _alvo_global(x, y, w, h)
        _fora_da_tela = False
        print(f"[WINDOW] {'Voltou' if acao == 'voltar' else 'Centro'} → alvo ({x}, {y})")

    elif acao in ("esquerda", "direita", "cima", "baixo"):
        w, h = _caber(*TAM_PADRAO, wa)
        x, y = _pos_lado(wa, w, h, acao)
        _alvo_global(x, y, w, h)
        _fora_da_tela = False
        print(f"[WINDOW] {acao.capitalize()} → alvo ({x}, {y})")

    elif acao.startswith("canto"):
        if _pos_atual:
            _pre_canto = tuple(_pos_atual)
        canto = {"canto": "inferior_esquerdo",
                 "canto_inf_dir": "inferior_direito",
                 "canto_sup_esq": "superior_esquerdo",
                 "canto_sup_dir": "superior_direito"}.get(acao, "inferior_esquerdo")
        w, h = _caber(*TAM_CANTO, wa)
        x, y = _pos_canto(wa, w, h, canto)
        _alvo_global(x, y, w, h)
        print(f"[WINDOW] Canto {canto} → alvo ({x}, {y})")

    elif acao == "restaurar":
        w, h = _caber(*TAM_PADRAO, wa)
        wx, wy, ww, wh = wa
        if _pre_canto:
            x = max(wx, min(_pre_canto[0], wx + ww - w))
            y = max(wy, min(_pre_canto[1], wy + wh - h))
        else:
            x, y = _pos_centro(wa, w, h)
        _alvo_global(x, y, w, h)
        _pre_canto = None

    elif acao in ("maior", "menor"):
        _definir_escala(FATOR_MAIOR if acao == "maior" else FATOR_MENOR)

    elif acao == "autoescala":
        _definir_escala(FATOR_MAIOR if random.random() < 0.5 else FATOR_MENOR)

    elif acao == "vagar":
        tamanho = (_esquiva_tam_antes
                   if (_esquiva_fugindo and _esquiva_tam_antes)
                   else _tamanho_atual())
        w, h = _caber(*tamanho, wa)
        wx, wy, ww, wh = wa
        range_x = ww - w - 2 * MARGEM_VAGAR
        range_y = wh - h - 2 * MARGEM_VAGAR
        if range_x < 100 or range_y < 100:
            w, h = _caber(*TAM_PADRAO, wa)
            range_x = ww - w - 2 * MARGEM_VAGAR
            range_y = wh - h - 2 * MARGEM_VAGAR
        passos = random.randint(*VAGAR_PASSOS)
        seq = []
        for passo in range(passos):
            x = wx + MARGEM_VAGAR + random.randint(0, max(0, range_x))
            y = wy + MARGEM_VAGAR + random.randint(0, max(0, range_y))
            espera = random.uniform(1.5, 5.0) if passo < passos - 1 else 0.0
            seq.append(((x, y, w, h), espera))
        _seq = seq
        _alvo_global(*seq[0][0])
        print(f"[WINDOW] Vontade própria → passeio de {passos} trechos")

    elif acao == "espiar":
        if _pos_atual:
            w, h = (_esquiva_tam_antes
                    if (_esquiva_fugindo and _esquiva_tam_antes)
                    else (_pos_atual[2], _pos_atual[3]))
            original = (int(_pos_atual[0]), int(_pos_atual[1]), w, h)
            seq = []
            for _ in range(random.randint(*ESPIAR_OLHADINHAS)):
                nx = _pos_atual[0] + random.randint(-160, 160)
                ny = _pos_atual[1] + random.randint(-100, 100)
                nx, ny = _clampar(nx, ny, w, h, wa)
                seq.append(((nx, ny, w, h), random.uniform(1.2, 2.5)))
            seq.append((original, 0.0))
            _seq = seq
            _alvo_global(*seq[0][0])
            print("[WINDOW] Vontade própria → espiando ao redor...")

    else:
        print(f"[WINDOW] ⚠ Ação desconhecida: '{acao}'")
        return


def _definir_escala(fator: float):
    """Define alvo de escala com o centro da janela fixo."""
    wa = _workarea()
    if _pos_atual:
        x, y, w, h = _pos_atual
    else:
        w, h = TAM_PADRAO
        x, y = _pos_centro(wa, w, h)
    max_w, max_h = _teto_tamanho(wa)

    nw = max(TAM_MIN_LARG, min(int(w * fator), max_w))
    nh = int(nw * TAM_PADRAO[1] / TAM_PADRAO[0])
    if nh > max_h:
        nh = max_h
        nw = int(nh * TAM_PADRAO[0] / TAM_PADRAO[1])

    cx, cy = x + w // 2, y + h // 2
    _alvo_global(cx - nw // 2, cy - nh // 2, nw, nh)
    print(f"[WINDOW] Escala {fator:.2f}x → alvo {nw}x{nh}")


# -----------------------------------------------------------------------
# [v10-ESQUIVA] o coração da esquiva — roda NO LOOP DE VÍDEO
# -----------------------------------------------------------------------

def _esquiva_do_mouse():
    """
    [v10] Reflexo: mouse na zona de alerta por ESQUIVA_TEMPO_SEG →
    encolhe pra ESQUIVA_FATOR_TAM do tamanho e desliza pro lado com
    mais espaço (lerp acelerado). Mouse longe por ESQUIVA_RETORNO_SEG
    → volta ao tamanho normal (mantendo onde está).

    Anti-bugs embutidos:
    - cooldown entre fugas (sem perseguição infinita);
    - sem espaço (<40px) → desiste desta fuga;
    - QUALQUER exceção → esquiva desligada + _esquiva_aviso aceso
      (a HUD do main.py mostra 'ESQUIVA DE MOUSE: OFF' e segue a vida).
    """
    global _esquiva_ts, _esquiva_ultima, _esquiva_aviso
    global _esquiva_fugindo, _esquiva_tam_antes, _esquiva_fora_desde
    try:
        import pyautogui as _pag
        mx, my = _pag.position()
        if _pos_atual is None:
            return

        x = int(_pos_atual[0]) + _off_x
        y = int(_pos_atual[1]) + _off_y
        w = int(_pos_atual[2])
        h = int(_pos_atual[3])

        # [v10] zona de alerta: janela + margem ao redor — o reflexo
        # dispara ANTES do mouse encostar nela
        m = ESQUIVA_MARGEM_PX
        perto = (x - m <= mx <= x + w + m) and (y - m <= my <= y + h + m)

        agora_t = time.time()

        if not perto:
            _esquiva_ts = None
            # fora da zona há tempo suficiente → volta ao tamanho normal
            if _esquiva_fugindo:
                if _fora_da_tela:
                    # saiu da tela pequena — "voltar" já traz tamanho cheio
                    _esquiva_fugindo = False
                    _esquiva_tam_antes = None
                    _esquiva_fora_desde = None
                elif _esquiva_fora_desde is None:
                    _esquiva_fora_desde = agora_t
                elif agora_t - _esquiva_fora_desde >= ESQUIVA_RETORNO_SEG:
                    _restaurar_pos_esquiva()
            return

        _esquiva_fora_desde = None      # mouse voltou → cancela o retorno

        if _esquiva_ts is None:
            _esquiva_ts = agora_t       # acabou de chegar — começa a contar
            return
        if agora_t - _esquiva_ts < ESQUIVA_TEMPO_SEG:
            return
        if agora_t - _esquiva_ultima < ESQUIVA_COOLDOWN_SEG:
            return

        # Zona + tempo + cooldown vencidos → REFLEXO
        _esquiva_ts = None
        wa = _workarea()
        wx, wy, ww, wh = wa

        # tamanho de fuga: 40% do atual (60% menor), com piso
        fw = max(ESQUIVA_TAM_MIN, int(w * ESQUIVA_FATOR_TAM))
        fh = int(fw * h / max(1, w))
        if not _esquiva_fugindo:
            _esquiva_tam_antes = (w, h)   # só na 1ª fuga da sequência

        esp_esq = x - wx
        esp_dir = (wx + ww) - (x + w)
        dx = -ESQUIVA_DESLOC_PX if esp_dir >= esp_esq else ESQUIVA_DESLOC_PX

        cx, cy = x + w // 2, y + h // 2
        nx, ny = _clampar(cx + dx - fw // 2, cy - fh // 2, fw, fh, wa)
        if abs(nx - x) < 40 and abs(ny - y) < 20:
            _esquiva_ultima = agora_t    # sem espaço — desiste desta
            return

        _alvo_global(nx, ny, fw, fh)
        _esquiva_fugindo = True
        _esquiva_ultima = agora_t
        print(f"[WINDOW] Reflexo! Encolheu p/ {fw}x{fh} + deslizou → ({nx}, {ny})")

        # [ORBS] animação de susto do enxame (enfeite — falhar não derruba nada)
        try:
            import orbs as _orbs
            _orbs.esquivar(1 if dx > 0 else -1)
        except Exception:
            pass

    except Exception as e:
        _esquiva_aviso = True
        print(f"[WINDOW] ⚠ Esquiva de mouse desativada (erro: {e})")


def _restaurar_pos_esquiva():
    """Perigo passou → volta ao tamanho de antes, mantendo a posição atual."""
    global _esquiva_fugindo, _esquiva_tam_antes, _esquiva_fora_desde
    _esquiva_fora_desde = None
    if not _esquiva_fugindo:
        return
    _esquiva_fugindo = False
    if _esquiva_tam_antes and _pos_atual:
        wa = _workarea()
        ow, oh = _caber(*_esquiva_tam_antes, wa)
        cx = _pos_atual[0] + _pos_atual[2] / 2.0
        cy = _pos_atual[1] + _pos_atual[3] / 2.0
        nx, ny = _clampar(cx - ow / 2.0, cy - oh / 2.0, ow, oh, wa)
        _alvo_global(nx, ny, ow, oh)
        print(f"[WINDOW] Perigo passou — voltando ao tamanho {ow}x{oh}.")
    _esquiva_tam_antes = None


# -----------------------------------------------------------------------
# LOOP DE VÍDEO — o coração da solução (chamado pelo main.py)
# -----------------------------------------------------------------------

def atualizar_por_frame():
    """
    Chamado pelo main.py a CADA FRAME (mesma thread do cv2.imshow).
    Consome ações, avança sequências, ESQUIVA DO MOUSE, interpola até
    o alvo via cv2.moveWindow/resizeWindow.
    """
    global _pos_atual, _alvo, _acao_pendente, _seq, _seq_espera, _seq_ts, _no_alvo

    # 1) ação pendente (voz/box/agente)
    with _lock:
        acao = _acao_pendente
        _acao_pendente = None
    if acao:
        _executar_acao(acao)

    # 2) [v10-ESQUIVA] mouse na zona de alerta? → reflexo (mesma thread!)
    if ESQUIVA_ATIVA and not _esquiva_aviso:
        _esquiva_do_mouse()

    # 3) dt interno + avanço da sequência
    agora_t = time.time()
    dt_seq = min(0.1, agora_t - _seq_ts) if _seq_ts else 0.0
    _seq_ts = agora_t
    if _seq and _no_alvo:
        _seq_espera -= dt_seq
        if _seq_espera <= 0:
            _seq.pop(0)
            if _seq:
                _alvo_global(*_seq[0][0])
            else:
                _seq = None

    # 4) PRIMEIRO FRAME: calibra + slide de entrada
    if _pos_atual is None:
        _calibrar_offset()
        wa = _workarea()
        w, h = _caber(*TAM_PADRAO, wa)
        cx_c, cy_c = _pos_centro(wa, w, h)
        cv2.moveWindow(NOME_JANELA, -w, cy_c)
        cv2.resizeWindow(NOME_JANELA, w, h)
        _pos_atual = [float(-w), float(cy_c), float(w), float(h)]
        if _alvo is None:
            _alvo = (cx_c, cy_c, w, h)
            _no_alvo = False
        print("[WINDOW] Slide de entrada → centro.")

    if _alvo is None:
        return

    # 5) lerp exponencial em direção ao alvo
    #    [v10] durante a fuga usa lerp acelerado — reflexo tem que ser RÁPIDO
    tx, ty, tw, th = _alvo
    suav = ESQUIVA_VELOCIDADE if _esquiva_fugindo else SUAVIDADE
    mudou = False
    for i, (cur, tgt) in enumerate(zip(_pos_atual, (tx, ty, tw, th))):
        d = tgt - cur
        if abs(d) > 0.75:
            _pos_atual[i] = cur + d * suav
            mudou = True
        else:
            _pos_atual[i] = tgt

    # 6) aplica no OpenCV; ao chegar, arma a espera da sequência
    if mudou or not _no_alvo:
        cv2.moveWindow(NOME_JANELA,
                       int(_pos_atual[0]), int(_pos_atual[1]))
        cv2.resizeWindow(NOME_JANELA,
                         int(_pos_atual[2]), int(_pos_atual[3]))
        if not mudou:
            _no_alvo = True
            if _seq:
                _seq_espera = _seq[0][1]
            print(f"[WINDOW] ✓ chegou em ({int(tx)}, {int(ty)}, "
                  f"{int(tw)}x{int(th)})")


# -----------------------------------------------------------------------
# API — SOLICITAR, DIAGNÓSTICO E ESQUIVA
# -----------------------------------------------------------------------

def solicitar(acao: str):
    """Enfileira uma ação (voz/box/agente). Executa o loop de vídeo."""
    global _acao_pendente
    with _lock:
        _acao_pendente = acao


def esquiva_falhou() -> bool:
    """[v9-ESQUIVA] True quando a esquiva desligou por erro — HUD avisa."""
    return _esquiva_aviso


def debug_info() -> str:
    """Diagnóstico completo ('debug janela' no terminal/box)."""
    wa = _workarea()
    g = _geometria_x()
    esquiva_txt = ("FALHOU (OFF)" if _esquiva_aviso else
                   "desligada por config" if not ESQUIVA_ATIVA else
                   "FUGINDO (encolhida)" if _esquiva_fugindo else "ativa")
    linhas = [
        f"[WINDOW-DEBUG] posicionamento:        via OpenCV (nativo)",
        f"[WINDOW-DEBUG] workarea conservadora: {wa}",
        f"[WINDOW-DEBUG] workarea bruta:         {_workarea_bruta()}",
        f"[WINDOW-DEBUG] offset calibração:      ({_off_x:+d}, {_off_y:+d})",
        f"[WINDOW-DEBUG] rastreio interno:       {tuple(_pos_atual) if _pos_atual else None}",
        f"[WINDOW-DEBUG] alvo atual:             {_alvo}",
        f"[WINDOW-DEBUG] sequência:              {_seq if _seq else '—'}",
        f"[WINDOW-DEBUG] geometria real (X):     {g}",
        f"[WINDOW-DEBUG] fora da tela:           {_fora_da_tela}",
        f"[WINDOW-DEBUG] esquiva de mouse:       {esquiva_txt}",
    ]
    return "\n".join(linhas)


# -----------------------------------------------------------------------
# AGENTE (thread autônoma — decide, NUNCA toca na janela)
# -----------------------------------------------------------------------

def iniciar_agente(entrada: bool = True):
    global _agente_ativo, _thread_agente, _ultima_fala
    if not _disponivel():
        print("[WINDOW] xdotool não encontrado — leitura de tela limitada.")
        print("[WINDOW] Instale com: sudo apt install xdotool")

    exigidas = ("atualizar_por_frame", "_executar_acao", "_workarea",
                "_caber", "_alvo_global", "_ACAO_DA_INTENCAO",
                "_calibrar_offset", "_esquiva_do_mouse",
                "_restaurar_pos_esquiva")
    faltando = [f for f in exigidas if f not in globals()]
    if faltando:
        print(f"[WINDOW] ⚠ ARQUIVO MISTURADO — faltam: {faltando}")
        print("[WINDOW] Apague o window.py e cole a versão atual INTEIRA.")
        return

    if _thread_agente and _thread_agente.is_alive():
        return
    _agente_ativo = True
    _ultima_fala = time.time()
    _thread_agente = threading.Thread(target=_loop_agente,
                                      args=(entrada,), daemon=True)
    _thread_agente.start()


def parar_agente():
    global _agente_ativo
    _agente_ativo = False


def _loop_agente(entrada: bool):
    global _ultima_fala

    import brain as _brain   # import tardio — evita ciclo

    for _ in range(20):
        if _janela_id() is not None:
            break
        time.sleep(0.5)
    if _janela_id() is not None:
        _remover_decoracoes()
    print("[WINDOW] Agente de janela ativo (via OpenCV, calibrado no 1º frame).")

    falando_antes = False
    mouse_antes   = False
    proxima_autonomia = time.time() + random.uniform(AUTONOMIA_MIN_SEG, AUTONOMIA_MAX_SEG)
    proximo_humor    = time.time() + random.uniform(HUMOR_MIN_SEG, HUMOR_MAX_SEG)

    while _agente_ativo:
        # 1) fala — borda de subida traz ele de volta pra conversar
        falando = jarvis_voice.boca_falando
        if falando:
            _ultima_fala = time.time()
            if _fora_da_tela and not falando_antes:
                print("[WINDOW] Vou falar — voltando à tela.")
                solicitar("voltar")
        falando_antes = falando

        # 2) modo mouse → encolhe pro canto / restaura
        try:
            mouse_agora = _brain.jarvis_brain.gestos_bloqueados_7
        except Exception:
            mouse_agora = False
        if mouse_agora != mouse_antes:
            if mouse_agora:
                print("[WINDOW] Modo mouse — encolhendo pro canto.")
                solicitar("canto")
            else:
                print("[WINDOW] Modo mouse desligado — restaurando.")
                solicitar("restaurar")
            mouse_antes = mouse_agora

        # 3) idle — sai da tela em silêncio
        if (not _fora_da_tela and not falando
                and time.time() - _ultima_fala > IDLE_SAIR_SEG):
            print("[WINDOW] Idle — saindo da tela em silêncio.")
            solicitar("sair")

        # 4) vontade própria
        if (AUTONOMIA_ATIVA and not _fora_da_tela and not falando
                and not mouse_agora and time.time() > proxima_autonomia):
            if random.random() < AUTONOMIA_CHANCE_MOVER:
                rolagem = random.random()
                if rolagem < AUTONOMIA_CHANCE_ESPIAR:
                    solicitar("espiar")
                elif rolagem < AUTONOMIA_CHANCE_ESPIAR + 0.30:
                    solicitar("autoescala")
                else:
                    solicitar("vagar")
            proxima_autonomia = time.time() + random.uniform(
                AUTONOMIA_MIN_SEG, AUTONOMIA_MAX_SEG)

        # 5) humor
        if HUMOR_ATIVO and time.time() > proximo_humor:
            if random.random() < HUMOR_CHANCE_TROCAR:
                _trocar_humor()
            proximo_humor = time.time() + random.uniform(
                HUMOR_MIN_SEG, HUMOR_MAX_SEG)

        time.sleep(LOOP_AGENTE_SEG)


def _trocar_humor():
    try:
        import emotions as _emotions
        humores = ["NORMAL", "PENSATIVO", "CANSADO", "ALEGRE"]
        escolhido = random.choices(humores, weights=[4, 2, 2, 2])[0]
        if escolhido == "NORMAL":
            _emotions.jarvis_emotions.definir_humor("NORMAL", 1.0)
            print("[WINDOW] Humor voltou ao NORMAL.")
        else:
            dur = random.uniform(60, 180)
            _emotions.jarvis_emotions.definir_humor(escolhido, dur)
            print(f"[WINDOW] Humor mudou para {escolhido} ({dur:.0f}s).")
    except Exception as e:
        print(f"[WINDOW] ERRO ao trocar humor: {e}")


# -----------------------------------------------------------------------
# COMANDOS POR VOZ (chamado pelo brain.py)
# -----------------------------------------------------------------------

_FALAS = {
    "janela_sair": [
        "Claro, vou sair da sua frente, senhor.",
        "Saindo da tela. Continuo te ouvindo, senhor.",
    ],
    "janela_voltar": ["Voltando à tela, senhor.", "Eis-me de volta, senhor."],
    "janela_centro": ["Centralizando, senhor.", "Voltando ao centro."],
    "janela_esquerda": ["Indo pra esquerda, senhor."],
    "janela_direita": ["Indo pra direita, senhor."],
    "janela_cima": ["Subindo, senhor.", "Indo pra cima da tela."],
    "janela_baixo": ["Descendo, senhor.", "Indo pra baixo da tela."],
    "janela_maior": ["Crescendo, senhor.", "Aumentando minha presença."],
    "janela_menor": ["Encolhendo, senhor.", "Ficando discreto."],
    "janela_canto": ["Indo pro canto, senhor.", "Me encolhendo no cantinho."],
    "janela_canto_sup_esq": ["Canto superior esquerdo, senhor."],
    "janela_canto_inf_esq": ["Canto inferior esquerdo, senhor."],
    "janela_canto_sup_dir": ["Canto superior direito, senhor."],
}

_ACAO_DA_INTENCAO = {
    "janela_sair":          "sair",
    "janela_voltar":        "voltar",
    "janela_centro":        "centro",
    "janela_esquerda":      "esquerda",
    "janela_direita":       "direita",
    "janela_cima":          "cima",
    "janela_baixo":         "baixo",
    "janela_maior":         "maior",
    "janela_menor":         "menor",
    "janela_canto":         "canto",
    "janela_canto_sup_esq": "canto_sup_esq",
    "janela_canto_inf_esq": "canto",
    "janela_canto_sup_dir": "canto_sup_dir",
}


def executar_por_voz(intencao: str, texto_bruto: str):
    print(f"[WINDOW] Voz: '{intencao}' | '{texto_bruto}'")

    falas = _FALAS.get(intencao)
    if falas:
        jarvis_voice.falar(random.choice(falas))

    acao = _ACAO_DA_INTENCAO.get(intencao)
    if acao:
        solicitar(acao)
    else:
        print(f"[WINDOW] Intenção '{intencao}' sem implementação.")
