"""
FILE: main.py
DESCRIPTION: Ponto de entrada principal. Coordena vídeo, mãos e módulos.

v3 — filtro de humor APLICADO ao frame (a função existia mas nunca era
     chamada — PENSATIVO agora fica greyscale de verdade) + exemplo de
     gesto novo COMENTADO (procure [EXEMPLO-GESTO]).
"""
import cv2
import mediapipe as mp
import numpy as np
import pyautogui
import time
import datetime
import window
import emotions as jarvis_emotions_mod

from config import *
from voice import jarvis_voice
from gestures import *
from graphics import *
from emotions import jarvis_emotions
from brain import jarvis_brain
from listen import jarvis_listen
from vision import atualizar_frame
from recording import atualizar_frame as atualizar_frame_gravacao
import phone_commands
import command_box
import orbs

# [MEMÓRIA] DESIGN_CLASSICO=True volta ao círculo+elipses antigo
DESIGN_CLASSICO = False

# --- SETUP MEDIAPIPE ---
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.75,
    min_tracking_confidence=0.5,
)


def _abrir_camera() -> cv2.VideoCapture | None:
    """Testa índices 0-3 com múltiplos backends (V4L2/FFMPEG/AUTO)."""
    backends = [
        (cv2.CAP_V4L2,  "V4L2"),
        (cv2.CAP_FFMPEG, "FFMPEG"),
        (cv2.CAP_ANY,    "AUTO"),
    ]

    for indice in range(4):
        for backend, nome_backend in backends:
            cap = cv2.VideoCapture(indice, backend)
            if cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    print(f"[MAIN] Câmera aberta: índice={indice}, backend={nome_backend}.")
                    return cap
            cap.release()

    print("[MAIN] ERRO: Nenhuma câmera encontrada.")
    print("[MAIN] Dicas:")
    print("  1. Rode: ls /dev/video*")
    print("  2. Rode: v4l2-ctl --list-devices")
    print("  3. Verifique se outro app está usando a câmera")
    print("  4. Tente: sudo chmod 777 /dev/video0")
    return None


def aplicar_humor_frame(frame):
    """
    Filtro visual do humor (custo numpy mínimo por frame).
    PENSATIVO → greyscale | CANSADO → escurecido/azulado | ALEGRE → saturado
    """
    modo = jarvis_emotions.modo_visual

    if modo == "PENSATIVO":
        cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(cinza, cv2.COLOR_GRAY2BGR)

    if modo == "CANSADO":
        return cv2.convertScaleAbs(frame, alpha=0.75, beta=-12)

    if modo == "ALEGRE":
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = cv2.add(hsv[:, :, 1], 40)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    if modo == "FOCO":
        # vinheta roxa — centro nítido, bordas escurecidas
        overlay = np.zeros_like(frame)
        h_, w_ = frame.shape[:2]
        cv2.circle(overlay, (w_ // 2, h_ // 2), int(w_ * 0.45),
                   (30, 20, 50), -1)
        frame = cv2.addWeighted(frame, 0.75, overlay, 0.25, 0)
        return frame

    if modo == "FESTA":
        # saturação máxima + tint turquesa pulsante
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = cv2.add(hsv[:, :, 1], 70)
        frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        return frame

    if modo == "ZEN":
        # desaturação parcial — 60% colorido, 40% cinza
        cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cinza3 = cv2.cvtColor(cinza, cv2.COLOR_GRAY2BGR)
        return cv2.addWeighted(frame, 0.6, cinza3, 0.4, 0)

    if modo == "CAOS":
        # tremor sutil + vermelho leve (o caos mexe com você)
        desloc = np.random.randint(-3, 4, 2)
        M = np.float32([[1, 0, desloc[0]], [0, 1, desloc[1]]])
        frame = cv2.warpAffine(frame, M, (frame.shape[1], frame.shape[0]))
        frame[:, :, 2] = cv2.add(frame[:, :, 2], 15)   # canal R (BGR)
        return frame

    return frame


def main():
    cap = _abrir_camera()
    if cap is None:
        print("[MAIN] Encerrando — sem câmera disponível.")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 20)

    prev_mouse_x, prev_mouse_y = pyautogui.position()
    gesto_contador = {}
    falhas_leitura = 0
    MAX_FALHAS_CAM = 10

    CORPO_X, CORPO_Y = 505, 120
    jarvis_radius = 65

    print("JARVIS SYSTEM: INICIANDO...")

    # WINDOW_NORMAL permite redimensionar via cv2.resizeWindow (window.py v7+)
    cv2.namedWindow('JARVIS Interface', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('JARVIS Interface', 640, 480)

    # --- LISTENER DE VOZ ---
    jarvis_listen.registrar_callback(jarvis_brain.execute_voice_command)
    jarvis_listen.start()
    phone_commands.iniciar_terminal()
    command_box.iniciar()
    window.iniciar_agente()
    import alarm
    alarm.iniciar()   # [ALARM] despertador 07:30 + bom-dia IA
    from utilities import reativar_timers
    reativar_timers()                    # [BOOT-PERSIST] timers do disco
    import notes as _notes_boot
    _notes_boot.reativar_lembretes()     # [BOOT-PERSIST] lembretes do disco

    # [FIX] FORA do loop — dentro dele era resetada a cada frame
    # e a tecla M (modo surdo) nunca funcionava
    surdo_manual = False

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            falhas_leitura += 1
            print(f"[MAIN] Falha de leitura da câmera ({falhas_leitura}/{MAX_FALHAS_CAM})")
            if falhas_leitura >= MAX_FALHAS_CAM:
                print("[MAIN] Câmera perdida definitivamente. Encerrando.")
                break
            time.sleep(0.04)
            continue
        falhas_leitura = 0

        try:
            frame = cv2.flip(frame, 1)
            frame = aplicar_humor_frame(frame)   # [FIX-v3] humor no frame
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb_frame)

            tempo_agora = time.time()
            hora_atual = datetime.datetime.now().hour
            is_noite = 19 <= hora_atual or hora_atual < 6

            jarvis_emotions.update(results.multi_hand_landmarks is not None)

            # Pausa o listener enquanto fala OU modo surdo ativo
            jarvis_listen.pausado = jarvis_voice.boca_falando or surdo_manual

            # frame limpo p/ visão e gravação (sem overlays)
            atualizar_frame(frame)
            atualizar_frame_gravacao(frame)

            # [ORBS] novo design; clássico segue em graphics.py
            if DESIGN_CLASSICO:
                desenhar_jarvis(frame, CORPO_X, CORPO_Y, jarvis_radius,
                                jarvis_voice.boca_falando, jarvis_emotions.dormindo,
                                is_noite, modo=jarvis_emotions.modo_visual)
            else:
                orbs.desenhar_orbes(
                    frame,
                    falando=jarvis_voice.boca_falando,
                    gravando=jarvis_listen.gravando,
                    processando=jarvis_listen.processando,
                    dormindo=jarvis_emotions.dormindo,
                    modo=jarvis_emotions.modo_visual,
                    wake_ts=jarvis_listen._tempo_ultimo_wake,
                    cx=CORPO_X, cy=CORPO_Y,
                )

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

                    draw_custom_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

                    is_right_hand = True
                    if results.multi_handedness and len(results.multi_handedness) > idx:
                        is_right_hand = results.multi_handedness[idx].classification[0].label == 'right'

                    wrist_to_middle_mcp = np.array([hand_landmarks.landmark[0].x - hand_landmarks.landmark[9].x,
                                                    hand_landmarks.landmark[0].y - hand_landmarks.landmark[9].y])
                    palm_length = np.linalg.norm(wrist_to_middle_mcp)

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
                        gesto_atual = "scroll_down" if jarvis_brain.gestos_bloqueados_7 else "1"
                    elif i_est and m_est and a_dob and mi_dob and p_dob:
                        gesto_atual = "scroll_up" if jarvis_brain.gestos_bloqueados_7 else "2"
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

                    # [EXEMPLO-GESTO] Como ligar um gesto a um comando novo:
                    # 1) Descomente o exemplo abaixo (polegar + mindinho
                    #    estendidos, os demais dobrados = "shaka").
                    # 2) Em brain.py, procure [EXEMPLO-GESTO] no
                    #    process_command e descomente o elif "IG" lá.
                    # elif p_est and mi_est and not i_est and not m_est and not a_est:
                    #     gesto_atual = "IG"

                    # Confirmação de quadros
                    if gesto_atual:
                        gesto_contador[gesto_atual] = gesto_contador.get(gesto_atual, 0) + 1
                        if gesto_contador[gesto_atual] < CONFIRMACAO_FRAMES:
                            gesto_atual = None
                    else:
                        gesto_contador.clear()

                    jarvis_brain.execute(gesto_atual, cap)

            # HUD Info
            cv2.putText(frame, "JARVIS SYSTEM: ONLINE", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_JARVIS_MAIN, 1)
            if jarvis_brain.gestos_bloqueados_7:
                cv2.putText(frame, "MODO MOUSE: ATIVADO", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            if surdo_manual:
                cv2.putText(frame, "MODO SURDO: ATIVADO [M]", (20, 90),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            # [v9-ESQUIVA] aviso quando a esquiva de mouse falha — canto
            # SUPERIOR DIREITO (oposto ao ONLINE, que fica à esquerda)
            if window.esquiva_falhou():
                cv2.putText(frame, "ESQUIVA DE MOUSE: OFF", (frame.shape[1] - 250, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            import alarm as _alarm_hud
            if _alarm_hud.despertador_tocando():
                cv2.putText(frame, "DESPERTADOR TOCANDO", (frame.shape[1] - 250, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

            # [CLEAN] painel de comandos fora do frame (a pedido) — brackets ficam
            #desenhar_painel_comandos(frame)
            desenhar_cantos_hud(frame)

            window.atualizar_por_frame()   # [WINDOW v7] janela via OpenCV
            cv2.imshow('JARVIS Interface', frame)

        except Exception as e:
            print(f"[MAIN] ERRO no loop de vídeo (frame ignorado): {type(e).__name__}: {e}")

        # --- CONTROLE DE TECLADO DA JANELA ---
        tecla = cv2.waitKey(1) & 0xFF
        if tecla == ord('q'):
            break
        if tecla in (ord('m'), ord('M')):
            surdo_manual = not surdo_manual
            if surdo_manual:
                print("[MAIN] MODO SURDO ativado — pressione M para reativar a escuta.")
                jarvis_voice.falar("Modo surdo ativado. Não vou escutar mais nada.")
            else:
                print("[MAIN] Escuta reativada.")
                jarvis_voice.falar("Ouvidos de volta ao ar, senhor.")

    # Encerramento limpo
    jarvis_listen.stop()
    window.parar_agente()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
