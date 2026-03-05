
"""
FILE: gestures.py
DESCRIPTION: Contém a lógica matemática e geométrica para detectar se os dedos estão estendidos ou dobrados.
"""
import numpy as np

def angulo_entre(v1, v2):
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    if norm_v1 == 0 or norm_v2 == 0:
        return 0
    v1 = v1 / norm_v1
    v2 = v2 / norm_v2
    dot = np.dot(v1, v2)
    return np.degrees(np.arccos(np.clip(dot, -1.0, 1.0)))

def dedo_estendido(landmarks, tip, pip, eixo="y", threshold_ratio=0.08, palm_length=1.0):
    tip_coord = getattr(landmarks[tip], eixo)
    pip_coord = getattr(landmarks[pip], eixo)
    diff = tip_coord - pip_coord
    effective_threshold = threshold_ratio * palm_length
    if eixo == "x":
        return diff > effective_threshold
    elif eixo == "y":
        return diff < -effective_threshold
    return False

def polegar_estendido_angulo(landmarks):
    mcp = np.array([landmarks[2].x, landmarks[2].y])
    ip = np.array([landmarks[3].x, landmarks[3].y])
    tip = np.array([landmarks[4].x, landmarks[4].y])
    v1 = ip - mcp
    v2 = tip - ip
    ang = angulo_entre(v1, v2)
    return ang < 40

def dedo_dobrado_y(landmarks, tip, pip, mcp, threshold_ratio=0.05, palm_length=1.0):
    tip_y = landmarks[tip].y
    pip_y = landmarks[pip].y
    mcp_y = landmarks[mcp].y
    effective_threshold = threshold_ratio * palm_length
    return (tip_y > pip_y + effective_threshold) and (pip_y > mcp_y + effective_threshold)

def dedo_dobrado_x(landmarks, tip, pip, mcp, is_right_hand, threshold_ratio=0.05, palm_length=1.0):
    tip_x = landmarks[tip].x
    pip_x = landmarks[pip].x
    mcp_x = landmarks[mcp].x
    effective_threshold = threshold_ratio * palm_length
    if is_right_hand:
        return (tip_x < pip_x - effective_threshold) and (pip_x < mcp_x - effective_threshold)
    else:
        return (tip_x > pip_x + effective_threshold) and (pip_x > mcp_x + effective_threshold)
