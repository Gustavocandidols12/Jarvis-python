"""
FILE: graphics.py
DESCRIPTION: Gerencia a interface visual, HUD e a animação central (Core) do JARVIS.
"""
import cv2
import math
import time
import numpy as np
from config import *

# Variáveis de estado de animação
jarvis_angle_1 = 0
jarvis_angle_2 = 0
jarvis_angle_3 = 0
# [NOVO] Paletas dos humores — no mesmo padrão de CAFE/ESTUDO
COR_PENSATIVO = (120, 110, 100)   # cinza-quente (BGR)
COR_CANSADO    = (120, 60, 20)    # azul apagado
COR_ALEGRE     = (255, 200, 120)  # ciano vibrante

def draw_custom_landmarks(image, hand_landmarks, connections):
    for connection in connections:
        start_idx, end_idx = connection
        start_point = hand_landmarks.landmark[start_idx]
        end_point = hand_landmarks.landmark[end_idx]
        start_pixel = (int(start_point.x * image.shape[1]), int(start_point.y * image.shape[0]))
        end_pixel = (int(end_point.x * image.shape[1]), int(end_point.y * image.shape[0]))
        cv2.line(image, start_pixel, end_pixel, CONNECTION_COLOR, CONNECTION_THICKNESS)
    
    for idx, landmark in enumerate(hand_landmarks.landmark):
        x = int(landmark.x * image.shape[1])
        y = int(landmark.y * image.shape[0])
        cv2.circle(image, (x, y), 2, (0, 255, 255), -1) 

# Lista de comandos principais exibidos no painel inferior esquerdo
# Formato: (gesto/tecla, descricao)
COMANDOS_HUD = [
    ("[ Punho   ]", "Mute / Unmute"),
    ("[ 1 dedo  ]", "Volume -"),
    ("[ 2 dedos ]", "Volume +"),
    ("[ 3 dedos ]", "Ativar Voz"),
    ("[ 4 dedos ]", "Desativar Voz"),
    ("[ 5 dedos ]", "Tela Cheia"),
    ("[ Rock    ]", "Abrir VSCode"),
    ("[ Polegar ]", "Modo Mouse"),
    ("[ Next    ]", "Proxima Faixa"),
    ("[ Pause   ]", "Play / Pause"),
    ("[ Voz     ]", "Jarvis, encerrar"),
    ("[ Voz     ]", "Jarvis, que horas sao"),
    ("[ Tecla M  ]", "Modo Surdo (on/off)"),
    ("[ Tecla Q  ]", "Encerrar JARVIS"),
]

def desenhar_painel_comandos(img, alpha_painel=0.55):
    """
    Painel estilo HUD de vidro: cantos CHANFRADOS (sem retângulo chapado),
    borda ciano, fundo azul-profundo translúcido, título âmbar-ciano.
    """
    h, w = img.shape[:2]

    fonte      = cv2.FONT_HERSHEY_SIMPLEX
    escala     = 0.37
    cor_titulo = (255, 255, 0)      # ciano
    cor_gesto  = (40, 190, 255)     # âmbar suave (BGR)
    cor_desc   = (150, 200, 160)    # verde-acinzentado
    cor_borda  = (255, 255, 0)      # ciano puro na borda

    linha_altura = 16
    padding_x    = 10
    padding_y    = 6
    titulo_h     = 20
    chanfro      = 10

    n_linhas = len(COMANDOS_HUD)
    painel_h = titulo_h + (n_linhas * linha_altura) + padding_y * 2
    painel_w = 225

    x0 = 12
    y0 = h - painel_h - 12
    x1 = x0 + painel_w
    y1 = y0 + painel_h

    # octógono chanfrado — fundo translúcido + contorno ciano
    pts = np.array([
        [x0 + chanfro, y0], [x1 - chanfro, y0],
        [x1, y0 + chanfro], [x1, y1 - chanfro],
        [x1 - chanfro, y1], [x0 + chanfro, y1],
        [x0, y1 - chanfro], [x0, y0 + chanfro],
    ], np.int32)

    overlay = img.copy()
    cv2.fillPoly(overlay, [pts], (10, 16, 28))
    cv2.addWeighted(overlay, alpha_painel, img, 1 - alpha_painel, 0, img)
    cv2.polylines(img, [pts], True, cor_borda, 1, cv2.LINE_AA)

    # marcadores decorativos dos chanfros superiores (estilo Stark)
    cv2.line(img, (x0 + chanfro, y0), (x0 + chanfro + 14, y0), cor_borda, 2, cv2.LINE_AA)
    cv2.line(img, (x1 - chanfro, y0), (x1 - chanfro - 14, y0), cor_borda, 2, cv2.LINE_AA)

    cv2.putText(img, "COMANDOS PRINCIPAIS",
                (x0 + padding_x, y0 + padding_y + 10),
                fonte, 0.32, cor_titulo, 1, cv2.LINE_AA)
    cv2.line(img, (x0 + 4, y0 + titulo_h), (x1 - 4, y0 + titulo_h),
             (120, 160, 90), 1)  # divisor discreto

    for i, (gesto, descricao) in enumerate(COMANDOS_HUD):
        y_linha = y0 + titulo_h + padding_y + (i * linha_altura)
        cv2.putText(img, gesto,
                    (x0 + padding_x, y_linha + 10),
                    fonte, escala, cor_gesto, 1, cv2.LINE_AA)
        cv2.putText(img, descricao,
                    (x0 + padding_x + 76, y_linha + 10),
                    fonte, escala, cor_desc, 1, cv2.LINE_AA)

def desenhar_cantos_hud(img):
    """Brackets ciano nos 4 cantos do frame — 'câmera' vira HUD."""
    h, w = img.shape[:2]
    m, t = 8, 26
    cor  = COLOR_JARVIS_MAIN

    def _bracket(p1, p2, p3):
        cv2.polylines(img, [np.array([p1, p2, p3], np.int32)],
                      False, cor, 1, cv2.LINE_AA)

    _bracket((m, m + t),     (m, m),     (m + t, m))          # sup-esq
    _bracket((w - m - t, m), (w - m, m), (w - m, m + t))      # sup-dir
    _bracket((w - m, h - m - t), (w - m, h - m), (w - m - t, h - m))  # inf-dir
    _bracket((m + t, h - m), (m, h - m), (m, h - m - t))      # inf-esq

# ═══ [MEMÓRIA] Design clássico (círculo + elipses) — o primeiro rosto do JARVIS.
# Mantido intacto e funcional. Reative no main.py com DESIGN_CLASSICO = True. ═══
def desenhar_jarvis(img, x, y, raio, falando, dormindo, is_noite, modo="NORMAL"):
    global jarvis_angle_1, jarvis_angle_2, jarvis_angle_3
    
    overlay = img.copy()
    
    if modo == "CAFE":
        cor_principal = (30, 70, 110)   
        cor_secundaria = (50, 100, 160)
        cor_nucleo = (200, 220, 255)
    elif modo == "ESTUDO":
        cor_principal = (0, 0, 210)
        cor_secundaria = (0, 0, 255)
        cor_nucleo = COLOR_JARVIS_CORE
    elif modo == "PENSATIVO":
        cor_principal = COR_PENSATIVO
        cor_secundaria = (80, 75, 70)
        cor_nucleo = (210, 205, 200)
    elif modo == "CANSADO":
        cor_principal = COR_CANSADO
        cor_secundaria = (70, 35, 10)
        cor_nucleo = (150, 120, 90)
    elif modo == "ALEGRE":
        cor_principal = COR_ALEGRE
        cor_secundaria = (200, 140, 60)
        cor_nucleo = (255, 255, 255)
    else:
        cor_principal = COLOR_JARVIS_MAIN
        cor_secundaria = COLOR_JARVIS_SEC
        cor_nucleo = COLOR_JARVIS_CORE

    if dormindo and is_noite:
        cor_sleep = (0, 50, 100)
        cv2.circle(overlay, (x, y), int(raio * 0.5), cor_sleep, 2)
        cv2.putText(overlay, "STANDBY", (x - 30, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, cor_sleep, 1)
        alpha = 0.6
    else:
        speed = 2 if not falando else 8
        pulse = 0
        
        if falando:
            pulse = int(math.sin(time.time() * 20) * 5)
            cor_atual = (255, 200, 50) 
        else:
            pulse = int(math.sin(time.time() * 2) * 3)
            cor_atual = cor_principal

        jarvis_angle_1 += speed
        jarvis_angle_2 -= (speed * 0.7)
        jarvis_angle_3 += (speed * 0.3)
        raio_dinamico = raio + pulse

        # 1. Núcleo
        cv2.circle(overlay, (x, y), 8, cor_nucleo, -1)
        
        if modo == "CAFE":
            cv2.rectangle(overlay, (x-10, y-5), (x+10, y+10), cor_nucleo, 1)
        else:
            cv2.circle(overlay, (x, y), 12, cor_atual, 1)

        cv2.ellipse(overlay, (x, y), (int(raio_dinamico * 0.4), int(raio_dinamico * 0.4)), 
                    jarvis_angle_1, 0, 100, cor_atual, 2)
        cv2.ellipse(overlay, (x, y), (int(raio_dinamico * 0.4), int(raio_dinamico * 0.4)), 
                    jarvis_angle_1, 180, 280, cor_atual, 2)

        cv2.ellipse(overlay, (x, y), (int(raio_dinamico * 0.7), int(raio_dinamico * 0.7)), 
                    jarvis_angle_2, 0, 360, cor_secundaria, 1)

        cv2.ellipse(overlay, (x, y), (raio_dinamico, raio_dinamico), 
                    jarvis_angle_3, 0, 60, cor_atual, 2)
        cv2.ellipse(overlay, (x, y), (raio_dinamico, raio_dinamico), 
                    jarvis_angle_3, 120, 180, cor_atual, 2)
        cv2.ellipse(overlay, (x, y), (raio_dinamico, raio_dinamico), 
                    jarvis_angle_3, 240, 300, cor_atual, 2)

        alpha = 0.7 if not falando else 0.85

    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
