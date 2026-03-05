"""
FILE: main.py
DESCRIPTION: Ponto de entrada principal. Coordena a captura de vídeo, processamento de mãos e integração de todos os módulos.
"""
import cv2
import mediapipe as mp
import numpy as np
import pyautogui
import time
import datetime

# Importações dos módulos refatorados
from config import *
from voice import jarvis_voice
from gestures import *
from graphics import *
from emotions import jarvis_emotions
from brain import jarvis_brain
from listen import jarvis_listen
from vision import atualizar_frame        # ← NOVO: módulo de visão

# --- SETUP MEDIAPIPE ---
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.75,
    min_tracking_confidence=0.5,
)

def _abrir_camera() -> cv2.VideoCapture | None:
    """
    Tenta abrir a câmera testando índices 0-3 com múltiplos backends.
    O OpenCV no Linux às vezes falha com V4L2 mas funciona com FFMPEG e vice-versa.
    [FIX] Testa V4L2 e FFMPEG separadamente para contornar falhas de backend.
    """
    backends = [
        (cv2.CAP_V4L2,  "V4L2"),
        (cv2.CAP_FFMPEG, "FFMPEG"),
        (cv2.CAP_ANY,    "AUTO"),
    ]

    for indice in range(4):
        for backend, nome_backend in backends:
            cap = cv2.VideoCapture(indice, backend)
            if cap.isOpened():
                # Faz uma leitura de teste para confirmar que realmente funciona
                ok, _ = cap.read()
                if ok:
                    print(f"[MAIN] Câmera aberta: índice={indice}, backend={nome_backend}.")
                    return cap
            cap.release()

    print("[MAIN] ERRO: Nenhuma câmera encontrada.")
    print("[MAIN] Dicas:")
    print("  1. Rode: ls /dev/video*  — para ver os dispositivos disponíveis")
    print("  2. Rode: v4l2-ctl --list-devices  — para ver detalhes")
    print("  3. Verifique se outra janela/app está usando a câmera (ex: cheese, zoom, obs)")
    print("  4. Tente: sudo chmod 777 /dev/video0")
    return None


def main():
    cap = _abrir_camera()
    if cap is None:
        print("[MAIN] Encerrando — sem câmera disponível.")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 26)

    prev_mouse_x, prev_mouse_y = pyautogui.position()
    gesto_contador = {}
    
    CORPO_X, CORPO_Y = 505, 120 
    jarvis_radius = 65

    print("JARVIS SYSTEM: INICIANDO...")

    # --- CONFIGURAÇÃO DA JANELA (sem barra de ferramentas / decorações do OpenCV) ---
    # WINDOW_AUTOSIZE exibe a janela sem os ícones extras da toolbar Qt
    # (lupa de zoom, etc.) e é compatível com todas as builds do OpenCV.
    #cv2.namedWindow('JARVIS Interface', cv2.WINDOW_AUTOSIZE)

    # --- INICIALIZAÇÃO DO LISTENER DE VOZ ---
    # Registra o método do Brain como destino das intenções identificadas
    # e inicia a thread de escuta em paralelo ao loop de vídeo
    jarvis_listen.registrar_callback(jarvis_brain.execute_voice_command)
    jarvis_listen.start()

    while cap.isOpened():
        success, frame = cap.read()
        if not success: break

        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb_frame)

        tempo_agora = time.time()
        hora_atual = datetime.datetime.now().hour
        is_noite = 19 <= hora_atual or hora_atual < 6

        # Atualiza sistema emocional e estados baseados no tempo
        jarvis_emotions.update(results.multi_hand_landmarks is not None)

        # Pausa o listener enquanto o JARVIS está falando
        # Evita que o microfone capture a própria voz TTS e gere comandos fantasma
        jarvis_listen.pausado = jarvis_voice.boca_falando

        # ← NOVO: atualiza o frame compartilhado com o módulo de visão
        # Chamado antes de qualquer desenho de HUD para que a imagem
        # capturada seja limpa (sem overlays do JARVIS desenhados por cima)
        atualizar_frame(frame)

        # Desenha o Jarvis
        desenhar_jarvis(frame, CORPO_X, CORPO_Y, jarvis_radius, 
                        jarvis_voice.boca_falando, jarvis_emotions.dormindo, 
                        is_noite, modo=jarvis_emotions.modo_visual)

        gesto_atual = None

        if results.multi_hand_landmarks:
            for idx, hand_landmarks in enumerate(results.multi_hand_landmarks):
                
                # --- MODO MOUSE ---
                if jarvis_brain.gestos_bloqueados_7:
                    target_x_raw = hand_landmarks.landmark[10].x * frame.shape[1]
                    target_y_raw = hand_landmarks.landmark[10].y * frame.shape[0]
                    screen_w, screen_h = pyautogui.size()
                    
                    margem = 0.15
                    x_min, x_max = margem * frame.shape[1], (1 - margem) * frame.shape[1]
                    y_min, y_max = margem * frame.shape[0], (1 - margem) * frame.shape[0]

                    target_mouse_x = np.interp(target_x_raw, [x_min, x_max], [0, screen_w])
                    target_mouse_y = np.interp(target_y_raw, [y_min, y_max], [0, screen_h])

                    current_mouse_x = prev_mouse_x + (target_mouse_x - prev_mouse_x) * SMOOTHING_FACTOR
                    current_mouse_y = prev_mouse_y + (target_mouse_y - prev_mouse_y) * SMOOTHING_FACTOR
                    
                    pyautogui.moveTo(int(current_mouse_x), int(current_mouse_y))
                    prev_mouse_x, prev_mouse_y = current_mouse_x, current_mouse_y

                # Landmarks visuais
                draw_custom_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

                # Detecção de Geometria da Mão
                is_right_hand = True
                if results.multi_handedness and len(results.multi_handedness) > idx:
                    is_right_hand = results.multi_handedness[idx].classification[0].label == 'right'

                wrist_to_middle_mcp = np.array([hand_landmarks.landmark[0].x - hand_landmarks.landmark[9].x,
                                                hand_landmarks.landmark[0].y - hand_landmarks.landmark[9].y])
                palm_length = np.linalg.norm(wrist_to_middle_mcp)

                # Reconhecimento de dedos
                p_est = polegar_estendido_angulo(hand_landmarks.landmark)
                i_est = dedo_estendido(hand_landmarks.landmark, 8, 7, palm_length=palm_length)
                m_est = dedo_estendido(hand_landmarks.landmark, 12, 11, palm_length=palm_length)
                a_est = dedo_estendido(hand_landmarks.landmark, 16, 15, palm_length=palm_length)
                mi_est = dedo_estendido(hand_landmarks.landmark, 20, 19, palm_length=palm_length)
                
                i_dob = dedo_dobrado_y(hand_landmarks.landmark, 8, 7, 6, palm_length=palm_length)
                m_dob = dedo_dobrado_y(hand_landmarks.landmark, 12, 11, 10, palm_length=palm_length)
                a_dob = dedo_dobrado_y(hand_landmarks.landmark, 16, 15, 14, palm_length=palm_length)
                mi_dob = dedo_dobrado_y(hand_landmarks.landmark, 20, 19, 18, palm_length=palm_length)
                p_dob = not p_est

                # Lógica de Mapeamento de Gestos
                if m_est and not i_est and not a_est and not mi_est and p_est:
                    gesto_atual = "9" if jarvis_brain.gestos_bloqueados_7 else "Encerrar"
                elif i_est and mi_est and m_dob and a_dob and p_est:
                    gesto_atual = "Rock"
                elif i_dob and m_dob and a_dob and mi_dob and p_dob:
                    if (tempo_agora - jarvis_brain.last_toggle_time >= DEBOUNCE_TIME):
                        gesto_atual = "Pause" if jarvis_brain.gestos_bloqueados_7 else "Mute"
                elif i_est and m_dob and a_dob and mi_dob and p_dob:
                    gesto_atual = "1"
                elif i_est and m_est and a_dob and mi_dob and p_dob:
                    gesto_atual = "8" if jarvis_brain.gestos_bloqueados_7 else "2"
                elif i_est and m_est and p_est and a_dob and mi_dob:
                    gesto_atual = "clique" if jarvis_brain.gestos_bloqueados_7 else "3"
                elif i_est and m_est and a_est and mi_est and p_dob:
                    gesto_atual = "Next" if jarvis_brain.gestos_bloqueados_7 else "4"
                elif m_est and i_est and a_est and mi_est and p_est:
                    gesto_atual = "5"
                elif mi_est and i_dob and m_dob and a_dob and p_dob:
                    gesto_atual = "6"
                elif i_est and p_est and m_dob and a_dob and mi_dob:
                    gesto_atual = "7"
                elif p_est and i_dob and m_dob and a_dob and mi_dob:
                    gesto_atual = "DB"

                # Confirmação de quadros
                if gesto_atual:
                    gesto_contador[gesto_atual] = gesto_contador.get(gesto_atual, 0) + 1
                    if gesto_contador[gesto_atual] < CONFIRMACAO_FRAMES:
                        gesto_atual = None
                else:
                    gesto_contador.clear()

                # Executa no Cérebro
                jarvis_brain.execute(gesto_atual, cap)

        # HUD Info
        cv2.putText(frame, "JARVIS SYSTEM: ONLINE", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_JARVIS_MAIN, 1)
        if jarvis_brain.gestos_bloqueados_7:
            cv2.putText(frame, "MODO MOUSE: ATIVADO", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        # Painel de comandos semitransparente no canto inferior esquerdo
        desenhar_painel_comandos(frame)
        
        cv2.imshow('JARVIS Interface', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    # Encerramento limpo
    jarvis_listen.stop()
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()