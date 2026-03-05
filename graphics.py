"""
FILE: graphics.py
DESCRIPTION: Gerencia a interface visual, HUD e a animação central (Core) do JARVIS.
"""
import cv2
import math
import time
from config import *

# Variáveis de estado de animação
jarvis_angle_1 = 0
jarvis_angle_2 = 0
jarvis_angle_3 = 0

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
]

def desenhar_painel_comandos(img, alpha_painel=0.45):
    """
    Desenha um painel semitransparente no canto inferior esquerdo
    com os principais comandos de gesto e voz do JARVIS.

    Parametros:
        img          - frame atual (modificado in-place)
        alpha_painel - transparencia do fundo (0.0=invisivel, 1.0=solido)
    """
    h, w = img.shape[:2]

    fonte       = cv2.FONT_HERSHEY_SIMPLEX
    escala      = 0.37
    espessura   = 1
    cor_titulo  = (200, 220, 255)
    cor_gesto   = (100, 220, 255)
    cor_desc    = (160, 200, 160)
    cor_divider = (60, 80, 100)

    linha_altura = 16
    padding_x    = 8
    padding_y    = 6
    titulo_h     = 18

    n_linhas  = len(COMANDOS_HUD)
    painel_h  = titulo_h + (n_linhas * linha_altura) + padding_y * 2
    painel_w  = 215

    x0 = 12
    y0 = h - painel_h - 12
    x1 = x0 + painel_w
    y1 = y0 + painel_h

    # Fundo semitransparente
    overlay = img.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (10, 15, 25), -1)
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (50, 80, 120), 1)
    cv2.addWeighted(overlay, alpha_painel, img, 1 - alpha_painel, 0, img)

    # Titulo
    cv2.putText(img, "COMANDOS PRINCIPAIS",
                (x0 + padding_x, y0 + padding_y + 10),
                fonte, 0.32, cor_titulo, 1, cv2.LINE_AA)

    # Linha divisoria
    cv2.line(img, (x0 + 4, y0 + titulo_h), (x1 - 4, y0 + titulo_h), cor_divider, 1)

    # Linhas de comandos
    for i, (gesto, descricao) in enumerate(COMANDOS_HUD):
        y_linha = y0 + titulo_h + padding_y + (i * linha_altura)
        cv2.putText(img, gesto,
                    (x0 + padding_x, y_linha + 10),
                    fonte, escala, cor_gesto, espessura, cv2.LINE_AA)
        cv2.putText(img, descricao,
                    (x0 + padding_x + 72, y_linha + 10),
                    fonte, escala, cor_desc, espessura, cv2.LINE_AA)


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