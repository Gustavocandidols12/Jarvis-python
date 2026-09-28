"""
FILE: orbs.py
DESCRIPTION: Enxame de orbes — o corpo visual do JARVIS (novo design).
             Substitui o círculo + elipses clássico (que segue em
             graphics.py, reativável via DESIGN_CLASSICO no main.py).

             80 orbes, cada um com PAPEL de módulo (por prioridade):
               nucleo  30%  cor do humor   — o "corpo", sempre presente
               voz     20%  âmbar         — TODOS formam onda sonora ao falar
               audio   14%  ciano-claro   — anel receptor ao gravar
               visao   12%  verde         — anel giratório ao olhar a câmera
               ia      10%  violeta       — órbita rápida ao pensar (Groq/STT)
               phone    9%  laranja       — ondas de transmissão (adb)
               curinga  5%  cinza         — emprestáveis ao módulo ativo

             O enxame VAGA pelo frame inteiro (campo de fluxo — correnteza
             própria por orbe, diagonais lentas, batida profunda ~2min).

             ESTADOS (prioridade): dormindo > esquiva (susto) > wake-flash
             > módulo anunciado (visao/phone) > falando > ouvindo >
             pensando (voz/ia) > idle

             [ESQUIVA] window.py chama esquivar(dir) quando a janela foge
             do mouse: impulso de pânico, aglomerado vibrante aceso ~1s.

             HUMORES (modo_visual) — mexem em cor, velocidade e física:
               ALEGRE     +velocidade, quiques, mais brilho
               PENSATIVO  lento, orbes agrupados em cachos que vagam
               CANSADO    gravidade: caem pro fundo, quicam frouxo, brilho −
               CAFE/ESTUDO/NORMAL — apenas a paleta de cor

             IMPORTA ZERO módulos do projeto (estado chega por parâmetros
             e pelo anunciar() do brain) — sem risco de import circular.

DESEMPENHO: sem colisão entre orbes; um overlay único por frame.
            MODO_ECONOMICO=True → metade dos orbes, sem glow.
"""

import math
import random
import time

import cv2

# -----------------------------------------------------------------------
# CONFIGURAÇÃO
# -----------------------------------------------------------------------
N_ORBES           = 80      # [v2] informativo — o total real vem de _PAPEIS
MODO_ECONOMICO    = False   # True = metade dos orbes, sem glow
RAIO_REGIAO       = 220.0   # [v2] 95 → 220: o enxame agora VAGA pelo frame
ALPHA_OVERLAY     = 0.85
K_MOLA            = 4.0     # rigidez da mola em direção ao alvo
VEL_MAX           = 520.0   # [v2] 420 → 520: correnteza mais viva
DURACAO_ATIVIDADE = 5.0     # s que um módulo anunciado fica em destaque
AMPLITUDE_FALA    = 55.0    # [v2] ±18px → ±55px: a onda DANÇA de verdade
CX_NOMEIO         = 0.52    # [v2] centro-x do enxame em fração do frame
CY_NOMEIO         = 0.42    # [v2] centro-y (evita o painel de comandos)

# --- [ESQUIVA] reflexo de susto (window.py chama quando a janela foge
#     do mouse): impulso de pânico + aglomerado vibrante aceso por ~1s ---
ESQUIVA_DUR  = 1.0     # duração da animação (s)
_esquiva_ts  = 0.0     # quando começou (0 = nunca aconteceu)
_esquiva_dir = 1.0     # -1 = fuga pra esquerda, +1 = pra direita

# --- [ACENDER] ACENDIMENTO ESPONTÂNEO (decorativo, só no idle) ---
# Módulos acendem sozinhos em intervalos aleatórios, cada um por 2-6s.
# A VOZ não entra: o brilho dela é dirigido pela fala real (estado falando).
ACENDER_ESPONTANEO    = True
ACENDER_INTERVALO_MIN = 8.0    # seg até o próximo acender do MESMO módulo
ACENDER_INTERVALO_MAX = 25.0
ACENDER_DURACAO_MIN   = 2.0    # duração de cada acendimento (2 a 6s)
ACENDER_DURACAO_MAX   = 6.0
_MODULOS_ACENDEM = ("audio", "visao", "ia", "phone")   # nucleo=corpo, voz=fala

# [v2] Papel proporcional a 80 orbes (nucleo 30% / voz 20% / ...)
_PAPEIS = [
    ("nucleo",  24, None),
    ("voz",     16, (40, 190, 255)),    # âmbar
    ("audio",   11, (210, 235, 255)),   # ciano-claro
    ("visao",   10, (90, 220, 90)),     # verde
    ("ia",       8, (235, 110, 200)),   # violeta
    ("phone",    7, (0, 140, 255)),     # laranja
    ("curinga",  4, (150, 150, 150)),   # cinza
]
_COR_PAPEL = {p: c for p, q, c in _PAPEIS if c is not None}

_PALETA_HUMOR = {
    "NORMAL":    (255, 255, 0),
    "CAFE":      (50, 100, 160),
    "ESTUDO":    (255, 0, 0),
    "PENSATIVO": (120, 110, 100),
    "CANSADO":   (120, 60, 20),
    "ALEGRE":    (255, 200, 120),
    # [v5-HUMORES] 4 modos novos de personalidade visual
    "FOCO":      (255, 60, 120),    # roxo/magenta profundo
    "FESTA":     (0, 255, 180),    # turquesa vibrante
    "ZEN":       (120, 200, 90),   # verde sereno
    "CAOS":      (60, 60, 220),    # vermelho intenso
}

# estado → papel que acende (os demais ficam apagados ~40%)
_PAPEL_POR_ESTADO = {
    "idle": "nucleo", "falando": "voz", "ouvindo": "audio",
    "pensando": "ia", "visao": "visao", "phone": "phone",
}

# -----------------------------------------------------------------------
# ESTADO INTERNO
# -----------------------------------------------------------------------
_orbes        = None
_t_ultimo     = None
_centro_swarm = None   # [v2] (cx, cy) com que o enxame foi criado
_atividades   = {}     # módulo -> timestamp (brain.py anuncia; expira sozinho)
_acendendo       = {}  # [ACENDER] papel -> fim (ts) do acendimento decorativo
_proximo_acender = {}  # [ACENDER] papel -> ts do próximo disparo


def anunciar(modulo: str):
    """
    Brain avisa que um módulo entrou em ação ("visao"/"ia"/"phone").
    Dict write/read atômicos sob GIL — seguro entre threads.
    """
    if modulo:
        _atividades[modulo] = time.time()


def esquivar(direcao: float = 1.0):
    """
    [ESQUIVA] window.py avisa que a janela fugiu do mouse → o enxame
    se assusta: impulso imediato de pânico na direção da fuga + estado
    "esquiva" (aglomerado vibrante aceso) por ESQUIVA_DUR segundos.
    """
    global _esquiva_ts, _esquiva_dir
    _esquiva_dir = 1.0 if direcao >= 0 else -1.0
    _esquiva_ts = time.time()
    if _orbes:
        for o in _orbes:
            o.vx += _esquiva_dir * random.uniform(260.0, 620.0)
            o.vy += random.uniform(-150.0, 150.0)


class _Orbe:
    __slots__ = ("papel", "papel_ef", "brilho", "x", "y", "vx", "vy",
                 "fase", "tam", "ang", "raio", "freq")

    def __init__(self, papel, cx, cy):
        self.papel    = papel
        self.papel_ef = papel
        self.brilho   = 0.5
        self.ang   = random.uniform(0, 2 * math.pi)
        self.raio  = random.uniform(0.18, 1.0)
        self.x     = cx + math.cos(self.ang) * self.raio * RAIO_REGIAO
        self.y     = cy + math.sin(self.ang) * self.raio * RAIO_REGIAO * 0.75
        self.vx    = 0.0
        self.vy    = 0.0
        self.fase  = random.uniform(0, 2 * math.pi)
        self.tam   = random.uniform(2.0, 3.4)
        self.freq  = random.uniform(1.2, 3.0)   # Hz do piscar


def _criar_swarm(cx, cy):
    global _orbes, _t_ultimo, _centro_swarm
    mult = 0.5 if MODO_ECONOMICO else 1.0
    _orbes = []
    for papel, qtd, _ in _PAPEIS:
        for _ in range(max(1, round(qtd * mult))):
            _orbes.append(_Orbe(papel, cx, cy))
    _t_ultimo = time.time()
    _centro_swarm = (cx, cy)
    print(f"[ORBS] Enxame ativo: {len(_orbes)} orbes — vaga pelo frame inteiro.")


def _alvo(orbe, pe, estado, i, n, k, np_, cx, cy, t):
    """
    [v2] Alvo de cada orbe. O padrão de fundo é um CAMPO DE FLUXO:
    cada orbe navega sua própria correnteza senoidal pelo frame — o
    enxame inteiro "é a água" atravessando a tela em diagonais suaves.
    """
    if estado == "wake":
        r = 14.0
        return cx + r * math.cos(orbe.fase * 3.0), cy + r * math.sin(orbe.fase * 3.0)

    # [ESQUIVA] bando apavorado: aglomerado apertado deslocado na
    # direção da fuga, cada orbe tremendo por conta própria
    if estado == "esquiva":
        rr = RAIO_REGIAO * 0.30
        a = orbe.fase * 2.7 + t * 16.0
        jx = math.sin(t * 33.0 + orbe.fase * 7.0) * 7.0
        jy = math.cos(t * 29.0 + orbe.fase * 5.0) * 7.0
        return (cx + _esquiva_dir * 58.0 + rr * math.cos(a) * 0.8 + jx,
                cy + rr * math.sin(a) * 0.6 + jy)

    # FALANDO: onda dupla, fase deslocada por posição — cada orbe sobe/desce
    # FORA de sincronia com o vizinho → serpenteação de água de verdade
    # (antes: amplitude pequena + todos em fase = só cresciam/encolhiam).
    if estado == "falando":
        frac = i / max(1, n - 1)
        tx = (cx - RAIO_REGIAO * 0.85) + frac * RAIO_REGIAO * 1.7
        onda = (math.sin(frac * 9.0 * math.pi + t * 7.0) * AMPLITUDE_FALA
                + math.sin(frac * 3.0 * math.pi - t * 4.5) * AMPLITUDE_FALA * 0.35)
        return tx, cy + onda

    frac_p = k / max(1, np_ - 1)

    # OUVINDO: anel receptor pulsante (papel audio)
    if estado == "ouvindo" and pe == "audio":
        raio = RAIO_REGIAO * (0.22 + 0.10 * math.sin(t * 2.2))
        a = frac_p * 2.0 * math.pi + t * 0.6
        return cx + raio * math.cos(a), cy + raio * math.sin(a) * 0.85

    # PENSANDO: órbita rápida interna (papel ia)
    if estado == "pensando" and pe == "ia":
        a = frac_p * 2.0 * math.pi + t * 4.2
        return cx + 34.0 * math.cos(a), cy + 34.0 * math.sin(a)

    # VISÃO: anel médio girando devagar
    if estado == "visao" and pe == "visao":
        a = frac_p * 2.0 * math.pi + t * 1.1
        return cx + RAIO_REGIAO * 0.35 * math.cos(a), cy + RAIO_REGIAO * 0.28 * math.sin(a)

    # PHONE: ondas concêntricas em leque (transmissão de sinal)
    if estado == "phone" and pe == "phone":
        onda = (frac_p * 0.7 + t * 0.35) % 1.0
        raio = 14.0 + 62.0 * onda
        ang = math.radians(-55.0 + 110.0 * frac_p)
        ox, oy = cx + RAIO_REGIAO * 0.30, cy
        return ox + raio * math.cos(ang), oy + raio * math.sin(ang)

    # ---- [v2] CAMPO DE FLUXO: o passeio do idle pelo frame inteiro ----
    # Correnteza própria de cada orbe: diagonais amplas, batidas lentas,
    # fases defasadas — ninguém para, ninguém repete, o enxame flutua.
    ang = (orbe.ang
           + t * 0.10                                  # deriva lenta da corrente
           + 0.55 * math.sin(t * 0.13 + orbe.fase)     # ondulação da massa d'água
           + 0.30 * math.sin(t * 0.05 + orbe.fase * 2.0))  # batida profunda (ciclo ~2min)
    # raio pulsante: ora perto do centro, ora raspando as bordas
    r = RAIO_REGIAO * (0.25 + 0.75 * (0.5 + 0.5 * math.sin(t * 0.21 + orbe.fase * 1.7)))
    resp = 1.0 + 0.05 * math.sin(t * 0.7)              # respiração do conjunto
    return cx + r * math.cos(ang) * resp, cy + r * math.sin(ang) * 0.62 * resp


def _modulo_ativo(agora):
    """Módulo anunciado mais recente e ainda fresco, ou None."""
    melhor, ts_melhor = None, -1.0
    for m, ts in list(_atividades.items()):
        if agora - ts > DURACAO_ATIVIDADE:
            del _atividades[m]
        elif ts > ts_melhor:
            melhor, ts_melhor = m, ts
    return melhor


def _estado(agora, falando, gravando, processando, dormindo, wake_ts):
    if dormindo:
        return "dormindo"
    if _esquiva_ts and agora - _esquiva_ts < ESQUIVA_DUR:
        return "esquiva"       # [ESQUIVA] reflexo de susto do enxame
    if wake_ts and agora - wake_ts < 0.8:
        return "wake"          # flash de convergência pós wake word
    # [v2] módulo anunciado (visao/phone) ganha de "falando": sem isso, o
    # TTS da resposta ("Espelhando a tela...") sempre esmaga o destaque
    # do orbe do módulo, que nunca chega a acender.
    m = _modulo_ativo(agora)
    if m in ("visao", "phone"):
        return m
    if falando:
        return "falando"
    if gravando:
        return "ouvindo"
    if processando:
        return "pensando"
    if m == "ia":
        return "pensando"
    return "idle"


def _acendimentos_espontaneos(agora: float, estado: str):
    """
    [ACENDER] Agenda e expira os acendimentos decorativos.

    No idle, cada módulo (audio/visao/ia/phone) acende sozinho por
    2-6s em intervalos aleatórios — pura decoração: a formação NÃO muda
    (os orbes seguem vagando no campo de fluxo), apenas o brilho sobe
    pra cor cheia + glow. A voz não participa: o brilho dela já é
    dirigido pela fala real.
    """
    # expira acabados (sempre — mesmo que o estado tenha mudado)
    for papel in list(_acendendo):
        if agora > _acendendo[papel]:
            del _acendendo[papel]

    if not ACENDER_ESPONTANEO or estado != "idle":
        return

    for papel in _MODULOS_ACENDEM:
        if papel not in _proximo_acender:
            # primeiro agendamento (boot): começa num instante aleatório
            _proximo_acender[papel] = agora + random.uniform(
                ACENDER_INTERVALO_MIN, ACENDER_INTERVALO_MAX)
        elif agora >= _proximo_acender[papel]:
            fim = agora + random.uniform(ACENDER_DURACAO_MIN, ACENDER_DURACAO_MAX)
            _acendendo[papel] = fim
            _proximo_acender[papel] = fim + random.uniform(
                ACENDER_INTERVALO_MIN, ACENDER_INTERVALO_MAX)


def _ancoras(cx, cy):
    """3 pontos de atração do modo PENSATIVO (cachos que vagam)."""
    return [(cx - 45, cy - 25), (cx + 40, cy - 10), (cx - 5, cy + 38)]


def _atualizar(estado, modo, cx, cy, dt, t, modulo=None):
    n = len(_orbes)
    papel_destaque = _PAPEL_POR_ESTADO.get(estado)

    def _efetivo(orbe):
        # curingas se emprestam ao módulo em destaque
        if orbe.papel == "curinga" and papel_destaque and papel_destaque != "nucleo":
            return papel_destaque
        return orbe.papel

    totais = {}
    for o in _orbes:
        pe = _efetivo(o)
        totais[pe] = totais.get(pe, 0) + 1

    cont = {}
    vel_mult  = {"ALEGRE": 1.35, "PENSATIVO": 0.60, "CANSADO": 0.55}.get(modo, 1.0)
    fator_damp = math.exp(-2.6 * dt)

    # [FIX-STANDBY] chão de queda calibrado pela ALTURA REAL do frame
    # (antes: cy + 0.66*RAIO ≈ 72% da altura — os orbes dormiam no MEIO
    # da tela). cy é sempre 0.42*altura (CY_NOMEIO), então inverter a
    # fração recupera a altura sem precisar de parâmetro novo. 18px de
    # folga da borda inferior.
    h_frame = cy / CY_NOMEIO
    chao = h_frame - 18

    for i, orbe in enumerate(_orbes):
        pe = _efetivo(orbe)
        k = cont.get(pe, 0)
        cont[pe] = k + 1
        orbe.papel_ef = pe
        np_ = totais.get(pe, 1)

        # ---------- ALVO ----------
        if modo == "PENSATIVO" and estado == "idle":
            ax_, ay_ = _ancoras(cx, cy)[i % 3]
            a = orbe.fase + t * 0.25
            tx = ax_ + 16.0 * math.cos(a)
            ty = ay_ + 12.0 * math.sin(a)
        else:
            tx, ty = _alvo(orbe, pe, estado, i, n, k, np_, cx, cy, t)

        # [FIX-STANDBY] vigias do sono: dormem NO CHÃO como os demais e
        # erguem a cabeça em ciclo lento (~9s) para "olhar o ambiente" —
        # antes flutuavam na altura do centro, reforçando a sensação de
        # enxame parado no meio da tela.
        if estado == "dormindo" and i % 12 == 0:
            tx = cx + (i / n - 0.5) * RAIO_REGIAO * 1.4
            ciclo = (math.sin(t * 0.35 + orbe.fase) + 1.0) / 2.0   # 0..1
            elev = ciclo * ciclo                                   # sobe/pousa suave
            ty = (chao - 40.0) * (1.0 - elev) + (chao - 6.0) * elev

        if modo == "ALEGRE":
            ty -= abs(math.sin(t * 5.0 + orbe.fase)) * 10.0    # quiques

        # ---------- FÍSICA ----------
        if estado == "dormindo" and i % 12 != 0:
            # não-vigias: caem devagar e descansam no chão
            orbe.vy += 26.0 * dt
            orbe.vx *= fator_damp
            orbe.x += orbe.vx * dt
            orbe.y += orbe.vy * dt
            if orbe.y > chao:
                orbe.y = chao
                orbe.vy *= -0.18
        else:
            # [ESQUIVA] mola 9x mais dura durante o susto — o bando
            # comprime num estalo, não desliza
            k_mola = K_MOLA * (9.0 if estado == "esquiva" else
                               6.0 if estado == "wake" else
                               0.5 if estado == "dormindo" else
                               0.35 if modo == "CANSADO" else 1.0)
            orbe.vx += (tx - orbe.x) * k_mola * dt
            orbe.vy += (ty - orbe.y) * k_mola * dt
            if modo == "CANSADO":
                orbe.vy += 55.0 * dt                  # gravidade do cansaço
            # ruído orgânico (nunca param de verdade) — escalado ao frame [v2]
            orbe.vx += math.sin(t * 1.3 + orbe.fase * 5.0) * 60.0 * dt
            orbe.vy += math.cos(t * 1.1 + orbe.fase * 7.0) * 60.0 * dt
            orbe.vx *= fator_damp
            orbe.vy *= fator_damp
            v = math.hypot(orbe.vx, orbe.vy)
            if v > VEL_MAX:
                s = VEL_MAX / v
                orbe.vx *= s
                orbe.vy *= s
            orbe.x += orbe.vx * dt * vel_mult
            orbe.y += orbe.vy * dt * vel_mult
            if modo == "CANSADO" and orbe.y > chao:
                orbe.y = chao
                orbe.vy *= -0.3                       # quique frouxo

        # [v2] clamp nos limites do FRAME — território é a tela toda.
        # [FIX-STANDBY] o limite inferior agora segue o CHÃO (antes era
        # cy + 0.70*RAIO = 355, que PRENDIA os orbes antes de chegarem
        # ao fundo — metade do bug do standby no meio da tela).
        lim_x = RAIO_REGIAO * 1.05
        lim_y = RAIO_REGIAO * 0.70
        orbe.x = max(cx - lim_x, min(cx + lim_x, orbe.x))
        orbe.y = max(cy - lim_y, min(chao + 6.0, orbe.y))

        # ---------- BRILHO ----------
        if estado == "wake":
            b = 1.15
        else:
            ativo = (pe == papel_destaque)
            # [FIX-MASCARA] Módulo em ação continua ACESO na própria cor
            # DENTRO da onda de fala — antes o estado "falando" tinha
            # prioridade e mascarava phone/visao/ia por completo
            if estado == "falando" and modulo and pe == modulo:
                ativo = True
            # [ACENDER] acendimento decorativo — só no idle: orbes seguem
            # vagando, apenas BRILHAM na cor do próprio módulo
            if estado == "idle" and pe in _acendendo:
                ativo = True
            base = 1.0 if ativo else 0.42
            f_blink = orbe.freq * (0.35 if (modo == "CANSADO" or estado == "dormindo") else 1.0)
            blink = 0.55 + 0.45 * math.sin(t * 2 * math.pi * f_blink + orbe.fase)
            b = base * blink
            if modo == "ALEGRE":
                b *= 1.25
            if modo == "CANSADO":
                b *= 0.7
            # [v5-HUMORES] brilho dos 4 modos novos
            if modo == "FESTA":
                b *= 1.35            # tudo bem aceso
            if modo == "ZEN":
                b *= 0.85            # luz baixa e constante
            if modo == "CAOS":
                b *= 1.15            # pulsos agressivos
            # (FOCO não mexe no brilho: o destaque dele é a formação densa)
            if estado == "dormindo":
                b *= 0.45
        if estado == "esquiva":
            b = max(b, 1.05)   # [ESQUIVA] pânico: enxame inteiro aceso
        if estado == "phone" and pe == "phone":
            frac_p = k / max(1, np_ - 1)
            onda = (frac_p * 0.7 + t * 0.35) % 1.0
            b *= (1.0 - 0.65 * onda)                  # onda esmaece ao expandir
        orbe.brilho = max(0.05, min(1.3, b))


def _desenhar(frame, estado, modo, cx, cy, t, modulo=None):
    # [FIX] 'modulo' na assinatura — sem ele a chamada do desenhar_orbes
    # dava "takes 6 positional arguments but 7 were given"
    overlay = frame.copy()
    papel_destaque = _PAPEL_POR_ESTADO.get(estado)

    for orbe in _orbes:
        if orbe.papel == "nucleo":
            cor = _PALETA_HUMOR.get(modo, _PALETA_HUMOR["NORMAL"])
        else:
            cor = _COR_PAPEL.get(orbe.papel_ef, (150, 150, 150))

        br = orbe.brilho
        c = (min(255, int(cor[0] * br)),
             min(255, int(cor[1] * br)),
             min(255, int(cor[2] * br)))
        x, y = int(orbe.x), int(orbe.y)
        destacado = (papel_destaque and orbe.papel_ef == papel_destaque) or \
                    (estado == "idle" and orbe.papel_ef in _acendendo) or \
                    (estado == "falando" and modulo and orbe.papel_ef == modulo) or \
                    estado == "esquiva"      # [ESQUIVA] glow de pânico geral
        tam = int(orbe.tam + (1.2 if destacado else 0.0))

        # glow só nos orbes em destaque (desligável)
        if not MODO_ECONOMICO and destacado:
            cv2.circle(overlay, (x, y), tam * 3,
                       (int(cor[0] * 0.22), int(cor[1] * 0.22), int(cor[2] * 0.22)),
                       -1, cv2.LINE_AA)
        cv2.circle(overlay, (x, y), max(1, tam), c, -1, cv2.LINE_AA)

    cv2.addWeighted(overlay, ALPHA_OVERLAY, frame, 1 - ALPHA_OVERLAY, 0, frame)

    if estado == "dormindo":
        # [FIX-STANDBY] texto ACIMA do enxame caído (os orbes agora dormem
        # no fundo do frame — cy + 1.15*RAIO ficava exatamente em cima deles)
        cv2.putText(frame, "Dormindo...", (int(cx - 30), int(cy - RAIO_REGIAO * 0.55)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 50, 100), 1)


# -----------------------------------------------------------------------
# API PÚBLICA — chamada pelo main.py a cada frame
# -----------------------------------------------------------------------

def desenhar_orbes(frame, falando, gravando, processando, dormindo, modo,
                   wake_ts=0.0, cx=505, cy=120):
    """Desenha o enxame no frame (estado entra por parâmetros)."""
    global _t_ultimo
    # [v2] centro calculado como FRAÇÃO do frame — funciona em qualquer
    # resolução e mantém o enxame longe do painel de comandos (inferior esq.)
    h, w = frame.shape[:2]
    cx = int(w * CX_NOMEIO)
    cy = int(h * CY_NOMEIO)

    if _orbes is None or _centro_swarm != (cx, cy):
        _criar_swarm(cx, cy)

    agora = time.time()
    dt = 0.033 if _t_ultimo is None else min(0.1, agora - _t_ultimo)
    _t_ultimo = agora
    t = agora % 10000.0   # evita floats gigantes dentro de sin()

    estado = _estado(agora, falando, gravando, processando, dormindo, wake_ts)
    _acendimentos_espontaneos(agora, estado)   # [ACENDER] brilhos decorativos
    modulo = _modulo_ativo(agora)              # [FIX-MASCARA] p/ fala + módulo juntos
    _atualizar(estado, modo, cx, cy, dt, t, modulo)
    _desenhar(frame, estado, modo, cx, cy, t, modulo)
