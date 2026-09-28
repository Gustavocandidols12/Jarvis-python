"""
FILE: listen.py
DESCRIPTION: Gerencia a escuta ativa do JARVIS.
             Pipeline: Wake Word → Gravação → STT → Interpretação → Ação.

v3 — [ECO-GUARD] duas camadas anti-eco do próprio TTS:
     1) gravação aborta se o TTS começar a falar no meio dela;
     2) transcrição comparada às últimas falas do JARVIS (voice.py)
        — 40%+ de sobreposição com fala longa = descartada como eco.
     Sem isso, o JARVIS se auto-comandava ao ouvir a própria resposta
     ("a previsão para hoje..." → re-executava o comando do clima).

v3 — novos comandos: instagram, mario64, chat_zai.
     MAX_RETENTATIVAS_SEM_WAKE = 2 (uma re-escuta após "não entendi").
"""
import re
import threading
import time
import unicodedata
import subprocess
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
import random
from voice import jarvis_voice, get_ultimas_falas   # [ECO-GUARD]
from config import VozNaoEntendeu

import os
from dotenv import load_dotenv

load_dotenv()

# -----------------------------------------------------------------------
# CONFIGURAÇÕES DO MÓDULO
# -----------------------------------------------------------------------

WAKE_WORD_ATIVO           = True
PORCUPINE_ACCESS_KEY      = os.getenv("PORCUPINE_ACCESS_KEY", "sua_chave_aqui")
WAKE_WORD_KEYWORD         = "jarvis"
WAKE_WORD_SENSIBILIDADE   = 0.7
WAKE_WORD_GANHO           = 2.0
WAKE_WORD_CONFIRMACOES    = 1
WAKE_WORD_COOLDOWN_SEG    = 1.8

OWW_MODELO    = "hey_jarvis"
OWW_THRESHOLD = 0.48   # [v4] 0.5→0.42: detecta mais fácil. 0.35=quase sempre | 0.5=padrão

SAMPLE_RATE               = 18000
CANAIS                    = 1
BLOCKSIZE                 = 1024
GANHO_AMPLIFICACAO        = 4.0
DURACAO_GRAVACAO_SEG      = 3.2

WOMIC_SAMPLE_RATE         = 48000
WOMIC_DEVICE_HW           = "hw:1,1"
WOMIC_PROCESS_NAME        = "micclient"

SILENCIO_RMS_THRESHOLD_PC    = 0.002
SILENCIO_RMS_THRESHOLD_WOMIC = 0.005

GANHO_WOMIC = 3.0
GANHO_PC    = 4.0

FRAMES_SILENCIO_PARAR     = 18
FRAMES_IGNORAR_INICIO     = 3
FRACAO_FRAMES_VOZ_MINIMA  = 0.10

NORMALIZAR_AUDIO          = True
NIVEL_NORMALIZACAO        = 0.9

WHISPER_MODEL_SIZE        = "small"
WHISPER_DEVICE            = "cpu"
WHISPER_COMPUTE_TYPE      = "int8"
WHISPER_IDIOMA            = "pt"

DEBOUNCE_COMANDO_SEG      = 1.5
SIMILARIDADE_MINIMA       = 0.40
SCORE_EARLY_EXIT          = 0.85

# --- RETENTATIVA APÓS NÃO ENTENDER ---
# 1 = gravar UMA vez por wake word (zero re-escutas)
# 2 = gravar + re-ouvir UMA vez (o que você pediu)  ← atual
# 3 = re-ouvir duas vezes (comportamento antigo)
MAX_RETENTATIVAS_SEM_WAKE = 1

# --- FALLBACK DE PESQUISA ---
FALLBACK_PESQUISA_PALAVRAS = 5
# --- [v5-AUDIO] SURDEZ DURANTE SOM NO SPEAKER ---
# Enquanto QUALQUER áudio tocar nos speakers (YouTube, Spotify, vídeo,
# scrcpy), o listener pausa — o microfone não captura a voz do computador
# nem a confunde com comandos. Retoma sozinho quando o som para.
# False = desligado (comportamento antigo).
AUDIO_EXTERNO_ATIVO      = True
AUDIO_EXTERNO_POLL_SEG   = 0.75   # frequência da checagem, em segundos

# -----------------------------------------------------------------------
# AUTO-DETECÇÃO DO MICROFONE (WoMic vs PC)
# -----------------------------------------------------------------------

def _womic_ativo() -> bool:
    try:
        return subprocess.run(
            ["pgrep", "-f", WOMIC_PROCESS_NAME],
            capture_output=True
        ).returncode == 0
    except Exception:
        return False


def _detectar_mic() -> tuple:
    if _womic_ativo():
        print("[LISTEN] WoMic detectado → microfone: celular (48000Hz→16000Hz).")
        return WOMIC_DEVICE_HW, WOMIC_SAMPLE_RATE, GANHO_WOMIC, SILENCIO_RMS_THRESHOLD_WOMIC
    print("[LISTEN] WoMic inativo → microfone: PC.")
    return None, SAMPLE_RATE, GANHO_PC, SILENCIO_RMS_THRESHOLD_PC


def _resamplear(audio: np.ndarray, orig_rate: int, dest_rate: int) -> np.ndarray:
    if orig_rate == dest_rate:
        return audio
    razao         = dest_rate / orig_rate
    novo_tamanho  = int(len(audio) * razao)
    indices_orig  = np.linspace(0, len(audio) - 1, novo_tamanho)
    return np.interp(indices_orig, np.arange(len(audio)), audio).astype(audio.dtype)


# -----------------------------------------------------------------------
# MAPA DE INTENÇÕES
# -----------------------------------------------------------------------

INTENCOES = {

    "volume_up": [
        "aumentar volume", "mais alto", "aumenta o som", "eleva o volume",
        "sobe o volume", "aumenta o volume", "coloca mais alto", "tá baixo demais",
        "não tô ouvindo nada", "põe mais alto", "aumenta aí", "sobe o som",
        "deixa mais alto", "volume mais alto", "alça o volume", "tá muito baixo",
        "preciso ouvir melhor", "toca mais alto", "pode subir o som", "mais volume por favor",
    ],

    "volume_down": [
        "diminuir volume", "mais baixo", "baixa o som", "reduz o volume",
        "desce o volume", "diminui o volume", "coloca mais baixo", "tá alto demais",
        "tá muito alto", "baixa aí", "desce o som", "deixa mais baixo",
        "volume mais baixo", "abaixa o volume", "abaixa o som", "pode diminuir",
        "menos volume", "tá estourando", "tá ensurdecendo", "diminui aí por favor",
    ],

    "mute": [
        "silenciar", "mudo", "sem som", "corta o som", "desativa o som",
        "tira o som", "fica quieto", "silêncio", "para o som", "muta",
        "muta o som", "coloca no mudo", "deixa mudo", "corta o áudio",
        "desliga o som", "tira o áudio", "quero silêncio", "pode calar",
        "sem barulho", "zera o som",
    ],

    "unmute": [
        "ligar som", "ativa o som", "desfaz mudo", "volta o som",
        "tira do mudo", "retorna o som", "ativa o áudio", "quero ouvir de novo",
        "liga o áudio", "sai do mudo", "desmuta", "volta o áudio",
        "coloca o som de volta", "pode falar", "pode ouvir de novo",
        "destrava o som", "reativa o som", "liga o som de novo",
        "quero o som", "coloca pra tocar de novo",
    ],

    "play_pause": [
        "pausar", "play", "pause", "reproduzir", "continuar música",
        "para a música", "pausa aí", "para aí", "continua", "dá o play",
        "toca", "resume", "continua tocando", "deixa tocar", "para de tocar",
        "bota pra tocar", "para a reprodução", "continua a reprodução",
        "toca de novo", "pausa a música",
    ],

    "proximo": [
        "próxima", "próxima música", "avançar", "pular", "próximo",
        "pula essa", "vai pra próxima", "próxima faixa", "avança a música",
        "muda a música", "não gostei dessa", "coloca outra", "passa pra frente",
        "skip", "pula essa música", "próxima por favor", "vai pra frente",
        "muda de música", "toca outra coisa", "essa não quero",
    ],

    "abrir_editor": [
        "abre o editor", "abrir vscode", "abre o código", "abrir editor de código",
        "abre o vs code", "abre o visual studio", "quero programar",
        "abre o programa de código", "inicia o editor", "abre o vscode",
        "abre pra mim o editor", "quero codar", "vou programar",
        "inicia o visual studio code", "me abre o editor",
        "abre o programa de programação", "lança o editor",
        "inicializa o vscode", "abre o ambiente de desenvolvimento", "quero escrever código",
    ],

    "tela_cheia": [
        "tela cheia", "fullscreen", "maximizar tela", "expande a tela",
        "coloca em tela cheia", "vai pra tela cheia", "maximiza",
        "ocupa a tela toda", "expande", "toma a tela toda", "modo tela cheia",
        "deixa em tela cheia", "aumenta a janela", "janela cheia",
        "coloca maximizado", "expande a janela", "ocupa tudo",
        "modo cinema", "sem bordas", "tela inteira",
    ],

    "recarregar": [
        "recarregar", "atualizar página", "refresh", "f5", "atualiza",
        "recarrega", "atualiza a página", "dá um f5", "recarrega a página",
        "atualiza o navegador", "carrega de novo", "carrega novamente",
        "reinicia a página", "dá refresh", "força atualização", "reload",
        "bota pra carregar de novo", "recarrega tudo", "atualiza o site",
        "carrega a página de novo",
    ],

    "clique": [
        "clica", "clique", "seleciona", "confirma", "aperta", "pressiona",
        "dá um clique", "clica aí", "seleciona isso", "confirma aí",
        "aperta o botão", "aciona", "ativa", "escolhe esse", "marca esse",
        "dá enter", "executa", "abre", "clica nisso", "seleciona esse aqui",
    ],

    "encerrar": [
        "desligar", "encerrar", "desliga o computador", "finaliza o sistema",
        "shutdown", "desliga tudo", "encerra tudo", "desliga a máquina",
        "pode desligar", "desligue", "apaga o computador",
        "fecha tudo e desliga", "quero desligar", "desliga o pc",
        "encerra o sistema", "finaliza o computador", "desliga agora",
        "pode desligar tudo", "fecha e desliga",
    ],

    "sair_jarvis": [
        "fechar jasper", "encerra o jasper", "sai do jasper", "fecha o sistema",
        "para o jasper", "encerra o programa", "fecha o jasper",
        "desativa o jarvis", "para de rodar", "fecha o aplicativo",
        "encerrar o jarvis", "pode fechar", "termina o jasper",
        "encerra o assistente", "fecha o assistente", "desliga o jasper",
        "para o assistente", "encerra a aplicação", "fechar o programa", "sair",
    ],

    # [v4] Encerramento de sessão — "só isso" encerra a conversa atual
    # e volta DIRETO pro aguardando wake word (sem re-escutar)
    "encerrar_sessao": [
        "só isso", "so isso", "era isso", "só", "só isso mesmo",
        "é isso", "e isso", "era só isso", "mais nada", "nada mais",
        "pode deixar quieto", "deixa assim", "tá bom assim",
        "tá certo", "isso é tudo", "era só o que eu queria",
        "encerra a conversa", "fecha a conversa", "pode encerrar",
    ],

    "voz_ligar": [
        "ativa a voz", "fala de novo", "voz ligada", "reativa a voz",
        "pode falar", "volta a falar", "quero te ouvir", "ativa o áudio",
        "liga a voz", "fala outra vez", "retorna a voz", "quero ouvir você",
        "para de ficar mudo", "fala comigo", "responde de novo",
        "ativa o som da voz", "liga o tts", "volta a falar comigo",
        "reativa o áudio", "pode responder",
    ],

    "voz_desligar": [
        "silencia o jarvis", "desativa a voz", "para de falar", "modo silencioso",
        "fica quieto jarvis", "não preciso ouvir", "sem resposta de voz",
        "desliga a voz", "para de responder em voz", "muda pra texto",
        "só texto", "não fala mais", "para de falar comigo",
        "silencia a voz", "desativa o tts", "sem voz", "pode calar jarvis",
        "não preciso de voz agora", "responde só por escrito",
        "desativa as respostas de voz",
    ],

    "mouse_ligar": [
        "ativa o mouse", "modo mouse", "controle manual", "ligar modo mouse",
        "ativa o controle", "quero controlar o mouse", "ativa controle por gesto",
        "liga o modo mouse", "inicia o controle manual", "quero usar o mouse",
        "ativa o ponteiro", "modo de controle", "controla com a mão",
        "habilita o mouse", "liga o mouse por gesto", "ativa o rastreamento",
        "começa o modo mouse", "inicia rastreamento", "modo controle por mão",
        "quero mover o cursor", "modo sete",
    ],

    "mouse_desligar": [
        "desativa o mouse", "sai do modo mouse", "desligar controle manual",
        "para o controle", "desativa o controle", "desliga o modo mouse",
        "encerra controle manual", "para o rastreamento",
        "sai do controle por gesto", "para de rastrear", "desativa o ponteiro",
        "desliga o rastreamento", "encerra o modo mouse",
        "sai do modo de controle", "para o controle por mão",
        "desativa rastreamento", "não quero mais o mouse",
        "desliga o controle por gesto", "para o modo de controle",
        "sai do controle manual", "sair modo sete",
    ],

    "hora": [
        "que horas são", "horas", "que hora", "me diz a hora", "me fala a hora",
        "qual é a hora", "que horas tá", "que horas", "hora atual",
        "me diz que horas são", "quanto são as horas", "como estão as horas",
        "que hora é essa", "me informa a hora", "qual horário",
        "sabe que horas são", "me dá a hora", "que horas são agora",
        "me diz o horário", "qual o horário atual",
    ],

    # [v5-SAUDACOES] separadas por horário — brain.py responde conforme
    # o relógio E o humor (emotions.obter_fala_humor)
    "saudacao_bom_dia": [
        "bom dia", "bom dia jasper", "bom dia jarvis", "bom dia pra você",
        "bom dia chefe", "acordou bem", "saudações matinais",
    ],
    "saudacao_boa_tarde": [
        "boa tarde", "boa tarde jasper", "boa tarde jarvis",
        "boa tarde chefe",
    ],
    "saudacao_boa_noite": [
        "boa noite", "boa noite jasper", "boa noite jarvis",
        "boa noite chefe", "vou dormir", "boa noite pra você",
    ],
    "saudacao_tudo_bem": [
        "tudo bem", "tudo bom com você", "tá tudo bem", "tudo certo",
        "tudo certo jasper", "tudo bem jasper", "tudo bem jarvis",
        "como você tá", "como vai", "como você está", "tá bem",
        "como tá você", "você tá bem", "você está bem",
    ],

    "quem_sou_eu": [
        "quem é você", "quem é voce", "quem é você jasper",
        "quem é voce jasper", "quem é o jasper", "quem é o jarvis",
        "quem é você jarvis", "quem é voce jarvis", "quem te criou",
        "quem te fez", "o que você é", "o que voce é", "quem te programou",
        "se apresenta", "se apresente", "fala de você", "fale de voce",
        "quem sou eu falando", "com quem eu tô falando",
        "com quem estou falando",
    ],

    "saudacao": [
        # genéricas que não são por horário/estado
        "oi jasper", "olá jasper", "e aí jasper", "hey jasper",
        "oi tudo bem", "salve jasper", "fala jasper", "tudo certo jasper",
        "oi sumido", "olá tudo bem", "ei jasper", "e então", "tá acordado",
        # [v4-JASPER] variações do nome novo (Jarvis continua, pelos velhos tempos)
        "oi jarvis", "olá jarvis", "e aí jarvis", "hey jarvis", "fala jarvis",
        "salve jarvis", "ei jarvis", "jasper", "jarvis",
    ],

    "clima_agora": [
        "como está o clima", "como tá o tempo", "qual é o clima agora",
        "tá frio ou quente", "como tá lá fora", "que tempo tá fazendo",
        "temperatura agora", "como está o tempo agora", "tá chovendo",
        "vai chover", "como está o dia", "que temperatura tá", "tá quente hoje",
        "tá frio hoje", "qual a temperatura", "como está o clima hoje",
        "tempo agora", "como está fora", "consulta o clima", "me diz o clima", "clima",
    ],

    "clima_hoje": [
        "previsão do tempo", "previsão de hoje", "como vai ser o dia",
        "previsão do tempo hoje", "qual a previsão", "vai chover hoje",
        "como vai ser o tempo hoje", "previsão para hoje",
        "o que esperar do tempo", "vai ter chuva hoje", "como vai estar o dia",
        "qual a previsão do tempo", "como vai estar o clima hoje",
        "preciso de guarda chuva", "levo guarda chuva", "como vai estar o tempo",
        "previsão climática", "como vai ser amanhã", "vai fazer sol hoje",
        "previsão do clima",
    ],

    "timer_criar": [
        "coloca um timer", "cria um timer", "timer de", "põe um timer",
        "inicia um timer", "começa um timer", "define um timer", "set timer",
        "conta regressiva", "me avisa em", "me lembra em", "avisa em",
        "lembra em", "cronômetro de", "alarme em", "me avisa daqui",
        "conta daqui", "daqui a minutos", "espera minutos", "faz um timer",
        "timer", "alarme",
    ],

    "timer_cancelar": [
        "cancela o timer", "para o timer", "cancela os timers", "remove o timer",
        "desativa o timer", "apaga o timer", "cancela o alarme", "para o alarme",
        "cancela a contagem", "para a contagem", "não preciso mais do timer",
        "desliga o timer", "encerra o timer", "tira o timer", "remove o alarme",
        "cancela o cronômetro", "para o cronômetro", "esquece o timer",
        "não preciso do timer", "cancela tudo",
    ],

    "timer_status": [
        "tem timer ativo", "quantos timers", "como estão os timers",
        "tem algum timer", "tem alarme ativo", "verificar timers",
        "status do timer", "quais timers estão ativos", "tem conta regressiva",
        "tem cronômetro rodando", "tem timer rodando", "me diz os timers",
        "lista os timers", "quais alarmes", "tem algum alarme",
        "como estão os alarmes", "timer ativo", "cronômetro ativo",
        "tem alguma contagem", "status dos timers",
    ],

    "pesquisar": [
        "pesquisa", "pesquise", "pesquisar",
        "busca", "busque", "buscar",
        "procura", "procure", "procurar",
        "o que é", "o que são", "o que foi",
        "quem é", "quem foi", "quem são",
        "como funciona", "como funcionam", "como se faz",
        "me explica", "me explique", "me fala sobre",
        "me diz sobre", "me conta sobre", "me conta",
        "o que você sabe sobre", "o que sabe sobre",
        "fala sobre", "fale sobre",
        "me dá uma explicação", "me dê uma explicação",
        "pode me explicar", "consegue me explicar",
        "sabe me dizer", "sabe dizer",
        "me dá uma info sobre", "me dê uma info sobre",
        "tenho uma dúvida sobre", "tenho uma pergunta sobre",
        "quero saber sobre", "quero saber mais sobre",
        "me informa sobre", "me informe sobre",
        "descobre pra mim", "descobre aí",
        "pesquisa aí", "busca aí",
        "pergunta pra internet", "consulta aí",
    ],

    "abrir_navegador": [
        "abrir navegador", "navegador",
        "abrir brave", "brave", "brave browser",
    ],

    "memoria": [
        "o que conversamos hoje", "o que falamos hoje", "o que você disse hoje",
        "o que falei hoje", "resumo de hoje", "me lembra o que disse hoje",
        "o que conversamos ontem", "o que falamos ontem", "o que você disse ontem",
        "resumo de ontem", "me lembra de ontem",
        "o que conversamos na segunda", "o que conversamos na terça",
        "o que conversamos na quarta", "o que conversamos na quinta",
        "o que conversamos na sexta", "o que conversamos no sábado",
        "o que conversamos no domingo",
        "o que falamos de manhã", "o que falamos à tarde", "o que falamos à noite",
        "o que disse de manhã", "o que disse à tarde",
        "me lembra", "me lembra o que falamos", "o que foi conversado",
        "histórico de conversa", "histórico de hoje", "histórico de ontem",
        "o que aconteceu hoje", "o que rolou hoje", "o que rolou ontem",
        "resume nossa conversa", "resume o que conversamos",
        "o que você falou", "o que eu falei",
    ],

    "youtube": [
        "pesquisa no youtube", "pesquise no youtube", "busca no youtube",
        "procura no youtube", "abre no youtube", "coloca no youtube",
        "youtube", "no youtube", "no you tube",
        "toca no youtube", "coloca pra tocar",
        "quero ouvir", "quero ver", "me coloca",
        "bota pra tocar", "coloca uma música", "toca uma música",
        "abre o youtube", "abre o vídeo", "abre o video",
        "mete no youtube", "joga no youtube", "roda no youtube",
        "toca aí", "coloca aí", "bota aí",
        "quero assistir", "me bota", "me coloca aí",
        "abrir youtube", "abre youtube",
    ],

    # [NOVO-v3] Instagram (direct/DMs) — brain.py abre a URL do inbox
    "instagram": [
        "abre o instagram", "abrir instagram", "abrir o instagram",
        "instagram", "insta", "abre o insta", "abrir o insta",
        "abre as mensagens do instagram", "mensagens do instagram",
        "abre o direct", "abrir direct", "abre o direct do instagram",
        "direct", "abre o dm", "abrir o dm", "dm do instagram", "dm",
        "quero ver o instagram", "ver o instagram",
    ],

    # [NOVO-v3] Super Mario 64 (wine) — brain.py roda o sm64coopdx.exe
    "mario64": [
        "abrir mario 64", "abre o mario 64", "abrir o mario 64",
        "abre mario 64", "jogar mario 64", "quero jogar mario 64",
        "super mario 64", "supermario 64", "abre o super mario 64",
        "abrir super mario 64", "roda o mario 64", "inicia o mario 64",
        "mario 64", "abre o mario", "abrir o mario", "abre mario",
        "abrir mario", "jogar mario", "quero jogar mario", "liga o mario",
        "inicia o mario", "sm64", "abre o sm64", "mario",
    ],

    # [NOVO-v3] Chat da Z.ai — estilo YouTube: extrai a pergunta da frase
    "chat_zai": [
        "abre o chat da zai", "abrir o chat da zai", "chat da zai",
        "abre o chat", "abrir o chat", "abre a zai", "abrir a zai",
        "zai", "chat", "abre a conversa da zai", "abre a conversa",
        "fala com a zai", "pergunta pra zai", "pergunta para a zai",
        "pede pra zai", "pede para a zai", "pede no chat",
        "pergunta no chat", "abre o chat e pede", "abre o chat e pergunta",
    ],

    # [v6-IMG] Geração de imagem via Pollinations — brain.py extrai o
    # pedido (o resto da frase) e chama image_gen.py
    "imagem_criar": [
        "cria uma imagem de", "criar uma imagem de", "cria imagem de",
        "gera uma imagem de", "gerar uma imagem de", "gera imagem de",
        "faz uma imagem de", "fazer uma imagem de", "faz imagem de",
        "desenha uma imagem de", "desenhar uma imagem de",
        "cria uma imagem", "criar uma imagem", "cria imagem", "criar imagem",
        "gera uma imagem", "gerar uma imagem", "gera imagem", "gerar imagem",
        "faz uma imagem", "fazer uma imagem", "faz imagem", "fazer imagem",
        "cria imagem", "gera uma imagem", "desenha", "desenhar",
        "gerar imagem", "criar imagem",
    ],

    "ver": [
        "o que você vê", "o que está vendo", "o que vê",
        "descreve o que vê", "descreve a cena", "descreve o ambiente",
        "o que tem na câmera", "o que aparece na câmera",
        "o que está na câmera", "olha pela câmera",
        "analisa a imagem", "analisa o que vê", "analisa isso",
        "veja isso", "olha isso", "me diz o que vê",
        "o que está acontecendo aí", "o que está na frente",
        "descreve o que está à sua frente", "o que está aqui",
        "tem alguém aí", "tem alguém aqui", "quem está aí",
        "quem está aqui", "o que está na minha frente",
        "o que está escrito", "lê o que está escrito",
        "consegue ler isso", "lê isso pra mim",
        "abre o olho", "usa a câmera", "me fala o que vê",
        "usa tua câmera", "olha pra câmera",
    ],

    "foto": [
        "tirar foto", "foto", "tira uma foto",
        "bate uma foto", "me tira uma foto", "registra uma foto",
        "tira um print de mim", "captura minha imagem", "me fotografa",
    ],

    "identificar_objeto": [
        "o que é isso", "o que é esse", "o que é essa", "o que é aquilo",
        "que objeto é esse", "que objeto é esse aqui", "que coisa é essa",
        "o que é isso na minha mão", "o que tenho na mão",
        "o que estou segurando", "o que está na minha mão",
        "identifica o que está na minha mão", "o que seguro",
        "o que é esse objeto", "que objeto é esse na minha mão",
        "identifica isso", "identifica esse objeto", "identifica esse aqui",
        "me diz o que é isso", "me fala o que é isso",
        "o que você identifica", "consegue identificar isso",
        "sabe o que é isso", "reconhece isso",
        "que bagulho é esse", "que trem é esse", "o que raios é isso",
        "me explica o que é isso", "fala o que é esse negócio",
    ],

    "gravacao_iniciar": [
        "iniciar gravação", "iniciar gravacao", "começar gravação", "comecar gravacao",
        "começa a gravar", "comeca a gravar", "inicia a gravação", "inicia a gravacao",
        "grava isso aí", "grava isso ai", "grava aí", "grava ai",
        "começa a gravação", "comeca a gravacao", "quero gravar",
        "gravar vídeo", "gravar video", "ativa a gravação", "ativa a gravacao",
        "liga a câmera para gravar", "liga a camera para gravar",
        "inicia gravação de vídeo", "inicia gravacao de video",
        "começa a filmar", "comeca a filmar", "quero filmar",
        "filma isso aí", "filma isso ai",
    ],

    "gravacao_cancelar": [
        "para a gravação", "para a gravacao", "parar gravação", "parar gravacao",
        "cancela a gravação", "cancela a gravacao", "cancelar gravação", "cancelar gravacao",
        "encerra a gravação", "encerra a gravacao", "encerrar gravação", "encerrar gravacao",
        "para de gravar", "pare de gravar", "termina a gravação", "termina a gravacao",
        "finaliza a gravação", "finaliza a gravacao", "para de filmar",
        "encerra a filmagem", "cancela a filmagem",
    ],

    "file_find": [
        "onde está", "onde esta", "localiza", "localizar", "acha",
        "onde fica", "procura", "procura o arquivo", "me acha",
        "me encontra", "encontra o arquivo", "consegue achar",
        "sabe onde está", "sabe onde esta", "acha para mim",
        "qual é o caminho", "qual e o caminho", "qual a localização", "qual a localizacao",
        "onde se encontra", "acha aí", "acha ai",
    ],

    "file_open": [
        "abrir", "abre", "abre o arquivo", "abra o arquivo",
        "abrir arquivo", "abre para mim", "abre aí", "abre ai",
        "ativa", "ativa o arquivo", "execute", "executa",
        "executa o arquivo", "roda o arquivo", "rode esse arquivo",
        "abre para eu ver", "abre para eu visualizar",
        "abra para mim", "consegue abrir", "me abre",
    ],

    "file_list": [
        "quais arquivos tem", "quais arquivos temos", "o que tem na pasta",
        "o que tá na pasta", "o que ta na pasta", "lista de arquivos",
        "lista os arquivos", "me mostra os arquivos", "me lista os arquivos",
        "quais são os arquivos", "quais sao os arquivos", "me fala os arquivos",
        "quais arquivos estão", "quais arquivos estao", "o que tem lá",
        "o que tem aqui", "quantos arquivos tem", "quantos arquivos temos",
        "me fala o que tem", "mostra os arquivos", "quais arquivos existem",
    ],

    "nota_criar": [
        "não esqueces", "nao esquece", "não esqueça", "nao esqueca",
        "anota", "anota aí", "anota isso", "salva aí", "salva isso",
        "cria uma anotação", "cria anotação", "criar anotação",
        "criar nota", "cria uma nota", "cria nota",
        "registra", "registra aí", "registra isso",
        "guarda isso", "guarda aí", "bota no caderno",
        "anotação para", "nota para", "anota para mim",
        "salva essa informação", "salva essa info",
        "preciso lembrar", "preciso lembrar disso",
    ],

    "nota_lembrar": [
        "me lembra de", "me lembra às", "me avisa de", "me avise de",
        "me avisa às", "me avise às", "lembra de mim",
        "me avisa daqui", "me lembra daqui",
        "cria um lembrete", "criar lembrete", "cria lembrete",
        "lembrete para", "lembrete de", "lembrete às",
        "me lembra que", "não deixa eu esquecer de",
        "me notifica às", "me notifica de",
        "me fala às", "alarme para", "alarme de",
    ],

    "nota_listar": [
        "quais são minhas anotações", "minhas anotações",
        "lista as anotações", "lista minhas anotações",
        "o que eu anotei", "o que está anotado",
        "quais anotações tenho", "me mostra as anotações",
        "me fala as anotações", "me diz as anotações",
        "quais são meus lembretes", "meus lembretes",
        "lista os lembretes", "lista meus lembretes",
        "o que está salvo", "o que tenho anotado",
        "me resume as notas", "resume as anotações",
        "tem alguma anotação", "tem algum lembrete",
        "o que eu não posso esquecer",
    ],

    "nota_apagar": [
        "apaga a anotação", "apaga a nota", "apaga o lembrete",
        "apagar anotação", "apagar nota", "apagar lembrete",
        "remove a anotação", "remove a nota", "remove o lembrete",
        "remover anotação", "remover nota", "remover lembrete",
        "deleta a anotação", "deleta a nota", "deleta o lembrete",
        "apaga anotação sobre", "apaga nota sobre", "apaga lembrete sobre",
        "remove anotação sobre", "deleta anotação sobre",
        "cancela a anotação", "cancela o lembrete",
        "não preciso mais da anotação", "não preciso mais do lembrete",
        "tira essa anotação", "tira essa nota",
    ],

    # [NOVO] Controle do celular via ADB — brain.py roteia para phone_commands.py
    "phone_espelhar": [
        "espelhar celular", "espelha o celular", "espelhar o celular",
        "espelha a tela do celular", "espelhar a tela do celular",
        "abre o espelhamento", "abrir espelhamento",
        "abre o scrcpy", "abrir scrcpy", "scrcpy",
        "mostra a tela do celular", "mostrar a tela do celular",
        "projeta o celular", "projetar o celular", "espelhe o celular",
        "espelhar telefone", "espelha o telefone",
    ],

    "phone_desespelhar": [
        "fecha o espelhamento", "fechar espelhamento", "parar espelhamento",
        "para o espelhamento", "fecha o scrcpy", "fechar scrcpy",
        "encerra o espelhamento", "encerrar espelhamento",
    ],

    "phone_abrir_app": [
        "abrir no celular", "abre no celular", "abrir app no celular",
        "abre o app no celular", "abre aplicativo no celular",
        "abrir aplicativo no celular", "abre no telefone", "abrir no telefone",
        "abre no cel", "abrir no cel",
    ],

    "phone_fechar_app": [
        "fechar app no celular", "fecha o app no celular",
        "fechar aplicativo no celular", "fecha o aplicativo no celular",
        "fecha no celular", "fechar no celular",
        "fecha no telefone", "fechar no telefone",
    ],

    "phone_home": [
        "home no celular", "tela inicial do celular", "botão home do celular",
        "home do celular", "volta pro início do celular", "tela inicial do telefone",
        "home no telefone",
        # [FIX-CONFUSAO] variações curtas — antes sobras como "tela do celular"
        # casavam parcialmente com "mostra a tela do celular" (espelhar)
        "home", "botão home", "tela inicial", "menu", "menu do celular",
        "volta pra tela do celular", "volta pro celular",
        "volta pra tela inicial", "página inicial do celular",
        "home celular", "tela principal do celular",
    ],

    "phone_voltar": [
        "voltar no celular", "botão voltar do celular", "volta no celular",
        "voltar no telefone", "recua no celular", "botão de voltar do celular",
    ],

    "phone_bloquear": [
        "bloqueia o celular", "bloquear o celular", "trava o celular",
        "travar o celular", "bloqueia a tela do celular", "bloquear telefone",
        "trava o telefone", "bloqueia o telefone",
    ],

    "phone_desbloquear": [
        "desbloqueia o celular", "desbloquear o celular", "destrava o celular",
        "destravar o celular", "desbloqueia a tela do celular",
        "acorda o celular", "acordar o celular", "desbloqueia o telefone",
    ],

    "phone_digitar": [
        "digita no celular", "digitar no celular", "escreve no celular",
        "escrever no celular", "digita no telefone", "escreve no telefone",
        "digita isso no celular",
    ],

    "phone_apps_listar": [
        "quais apps tem no celular", "apps do celular", "lista os apps do celular",
        "aplicativos do celular", "quais aplicativos no celular",
        "apps instalados no celular", "lista os aplicativos do celular",
        "apps do telefone",
    ],

    "phone_status": [
        "celular conectado", "o celular tá conectado", "status do celular",
        "verifica o celular", "verificar o celular", "checa o celular",
        "checar o celular", "status do telefone", "telefone conectado",
    ],

    "phone_notificacoes_listar": [
        "notificações do celular", "quais notificações", "ver notificações",
        "tem notificação no celular", "quantas notificações",
        "lê as notificações", "leia as notificações",
        "notificações do telefone", "tem notificação no telefone",
        "o que chegou no celular", "quais as notificações",
    ],

    "phone_notificacoes_limpar": [
        "limpa as notificações", "apaga as notificações", "limpar notificações",
        "apagar notificações", "limpa as notificações do celular",
        "apaga as notificações do celular", "limpar notificações do celular",
        "apagar notificações do celular", "excluir notificações",
        "exclui as notificações", "limpa notificações do telefone",
    ],

    "phone_notificacoes_abrir": [
        "abre as notificações", "abrir notificações", "abre notificações",
        "abre o painel de notificações", "abrir painel de notificações",
        "abre as notificações do celular", "desce o painel de notificações",
    ],

    "phone_wifi": [
        "liga o wifi", "ligar wifi", "liga o wifi do celular", "liga wifi",
        "desliga o wifi", "desligar wifi", "desliga o wifi do celular",
        "ativa o wifi", "desativa o wifi", "conecta o wifi",
        "wifi do celular", "wifi",
    ],

    "phone_bluetooth": [
        "liga o bluetooth", "ligar bluetooth", "desliga o bluetooth",
        "desligar bluetooth", "ativa o bluetooth", "desativa o bluetooth",
        "bluetooth do celular", "bluetooth",
    ],

    "phone_vibrar": [
        "vibra o celular", "faz o celular vibrar", "vibrar o celular",
        "vibra o telefone", "faz o telefone vibrar", "vibra celular",
        "ping no celular", "tocar no celular",
    ],

    "phone_screenshot": [
        "print do celular", "captura a tela do celular", "screenshot do celular",
        "tira um print do celular", "printscreen do celular",
        "capturar tela do celular", "tira print do celular",
        "print da tela do celular",
    ],

    "phone_bateria": [
        "bateria do celular", "quanto de bateria no celular", "bateria do telefone",
        "nível de bateria do celular", "carga do celular", "bateria no celular",
        "como está a bateria do celular", "quanto de carga no celular",
    ],

    "phone_media": [
        "play no celular", "pausa no celular", "pausar no celular",
        "próxima música no celular", "passa a música no celular",
        "música anterior no celular", "dá play no celular",
        "play pause no celular", "toca no celular",
    ],

    # [NOVO] Controle da janela do JARVIS — brain.py roteia para window.py
    "janela_sair": [
        "sai da tela", "sair da tela", "some da tela", "sumir da tela",
        "sai da minha frente", "desaparece da tela", "esconde a janela",
        "esconde a interface", "tira a janela da tela", "pode sair da tela",
        "sai da view",
    ],

    "janela_voltar": [
        "volta pra tela", "voltar pra tela", "aparece na tela",
        "aparece de novo", "mostra a janela", "volta a janela",
        "pode voltar", "volta pra frente", "traz a janela de volta",
    ],

    "janela_maior": [
        "fica maior", "aumenta a janela", "aumenta a interface",
        "deixa a janela maior", "aumenta o jarvis", "fica grande",
        "cresce a janela",
    ],

    "janela_menor": [
        "fica menor", "diminui a janela", "diminui a interface",
        "deixa a janela menor", "diminui o jarvis", "fica pequena",
        "encolhe a janela", "encolhe",
    ],

    "janela_canto": [
        "vai pro canto", "vá pro canto", "vai pro canto da tela",
        "canto da tela", "vai pro cantinho", "se esconde no canto",
    ],

    "janela_centro": [
        "volta pro centro", "vai pro centro", "centro da tela",
        "centraliza", "centraliza a janela", "no centro da tela",
    ],

    "janela_esquerda": [
        "vai pra esquerda", "vai para a esquerda", "move pra esquerda",
        "janela pra esquerda", "vai pra lateral esquerda", "lateral esquerda",
    ],

    "janela_direita": [
        "vai pra direita", "vai para a direita", "move pra direita",
        "janela pra direita", "vai pra lateral direita", "lateral direita",
    ],

    "janela_cima": [
        "vai pra cima", "vai para cima", "move pra cima",
        "janela pra cima", "sobe a janela", "vai pro topo", "topo da tela",
    ],

    "janela_baixo": [
        "vai pra baixo", "vai para baixo", "move pra baixo",
        "janela pra baixo", "desce a janela", "vai pro rodapé",
        "rodapé da tela",
    ],

    "janela_canto_sup_esq": [
        "vai pro canto superior esquerdo", "canto superior esquerdo",
        "vai pro cantinho de cima", "canto de cima esquerda",
    ],

    "janela_canto_inf_esq": [
        "vai pro canto inferior esquerdo", "canto inferior esquerdo",
        "canto de baixo esquerda",
    ],

    "janela_canto_sup_dir": [
        "vai pro canto superior direito", "canto superior direito",
        "canto de cima direita",
    ],

    # [v7-DEV] MODO DEV — entra SOMENTE por frase explícita (evita
    # conflito com 'criar imagem', 'pesquisar' etc). Uma vez dentro,
    # o brain controla o fluxo — cada frase vira pergunta da IA.
    "dev_codigo": [
        "modo dev", "modo dev ativado", "entrar em modo dev",
        "modo desenvolvedor", "entrar no modo desenvolvedor",
        "ativar modo dev", "ativa o modo dev", "liga o modo dev",
        "modo programador", "entrar em modo programador",
        "iniciar modo dev", "começa o modo dev", "modo código",
        "entrar em modo código", "vamos atualizar esse codigo",
    ],

    # [v7-DEV] sair do modo dev (só válido quando estiver dentro — o brain
    # intercepta estas frases ANTES do interpretador comum)
    "dev_sair": [
        "sair do modo dev", "sai do modo dev", "sai do dev",
        "desativar modo dev", "desativa o modo dev", "fecha o modo dev",
        "encerra o modo dev", "sair do modo desenvolvedor",
        "sai do modo desenvolvedor", "modo dev off", "sai daqui",
        "cancela o modo dev", "exit dev",
    ],

    # [ALARM] parar o despertador quando estiver tocando
    "despertador_parar": [
        "para o despertador", "parar despertador", "desliga o despertador",
        "para o alarme", "parar alarme", "desliga o alarme",
        "cala esse alarme", "bom dia jarvis", "bom dia jasper",
        "acordei", "tô acordado", "tô de pé", "já tô acordado",
        "pode parar o alarme", "chega de alarme",
    ],

    # aprovação do dev agent (só valem enquanto ele espera sim/não)
    "confirmar_sim": [
        "sim", "pode sim", "aprovo", "aprovado", "confirmo", "manda ver",
        "pode aplicar", "tá aprovado", "aplica aí",
    ],

    "confirmar_nao": [
        "não", "nao", "negativo", "rejeito", "não aprovo", "nao aprovo",
        "cancela isso", "desfaz", "reverte", "não pode", "para tudo",
    ],
    "Atualizar_sistema": [
        "atualizar sistema", "atualiza o sistema", "atualizar o sistema",
        "atualiza sistema", "atualizar jarvis", "atualiza jarvis",
        "atualizar jasper", "atualiza jasper", "atualizar o jarvis",
        "atualiza o jarvis", "atualizar o jasper", "atualiza o jasper",
        "verificar atualizações", "verifica atualizações",
        "verificar atualizacoes", "verifica atualizacoes", "atualiza a maquina",
        "atualizar a maquina", "atualiza o sistema operacional", "atualizar o sistema operacional",
        "atualiza o sistema operacional do jarvis", "atualizar dependenciar" 
    ],
}


# -----------------------------------------------------------------------
# PRÉ-COMPILAÇÃO DE INTENÇÕES
# -----------------------------------------------------------------------
_INTENCOES_COMPILADAS: list = []

def _compilar_intencoes():
    global _INTENCOES_COMPILADAS
    _INTENCOES_COMPILADAS = [
        (intencao_id, [(set(v.split()), v) for v in variacoes])
        for intencao_id, variacoes in INTENCOES.items()
    ]

_compilar_intencoes()


def _normalizar_texto(texto: str) -> str:
    texto = texto.lower().strip()
    texto = "".join(
        c for c in texto
        if unicodedata.category(c) not in ("Po", "Ps", "Pe", "Pi", "Pf", "Pd", "Pc")
    )
    return " ".join(texto.split())


# -----------------------------------------------------------------------
# NÚCLEO DO LISTENER
# -----------------------------------------------------------------------

class ListenEngine:

    def __init__(self):
        self._modelo_stt        = None
        self._porcupine         = None
        self._oww_model         = None
        self._motor_wake_word   = None
        self._ativo             = False
        self._thread            = None

        self._ultimo_comando    = ""
        self._tempo_ultimo_cmd  = 0.0
        self._tempo_ultimo_wake = 0.0

        self._callbacks: list   = []
        self.pausado            = False

        # [ORBS] estados expostos para o enxame visual
        self.gravando    = False
        self.processando = False
        # [v5-AUDIO] True enquanto algo toca nos speakers (pactl RUNNING)
        self.audio_externo   = False
        self._thread_audio   = None
    # -------------------------------------------------------------------
    # API PÚBLICA
    # -------------------------------------------------------------------

    def registrar_callback(self, fn):
        self._callbacks.append(fn)

    def start(self):
        print("[LISTEN] Carregando modelo Whisper...")
        self._modelo_stt = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        print(f"[LISTEN] Modelo '{WHISPER_MODEL_SIZE}' carregado.")
        if WAKE_WORD_ATIVO:
            self._inicializar_wake_word()
        self._ativo  = True
        self._thread = threading.Thread(target=self._loop_principal, daemon=True)
        self._thread.start()
        print("[LISTEN] Sistema de escuta ATIVO.")

        # [v5-AUDIO] vigilância do speaker — pausa a escuta durante sons
        if AUDIO_EXTERNO_ATIVO:
            self._thread_audio = threading.Thread(
                target=self._monitor_audio_externo, daemon=True)
            self._thread_audio.start()
    def stop(self):
        """Encerra a escuta com segurança (join antes de deletar o Porcupine)."""
        self._ativo = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

        if self._porcupine:
            try:
                self._porcupine.delete()
            except Exception as e:
                print(f"[LISTEN] Aviso ao liberar Porcupine: {e}")
            self._porcupine = None

        print("[LISTEN] Sistema de escuta encerrado.")

    # -------------------------------------------------------------------
    # BIP
    # -------------------------------------------------------------------

    def _tocar_bip(self):
        t    = np.linspace(0, 0.10, int(SAMPLE_RATE * 0.10), False)
        onda = np.sin(1000 * t * 2 * np.pi) * 0.3
        sd.play(onda, SAMPLE_RATE)
        sd.wait()

    # -------------------------------------------------------------------
    # [v5-AUDIO] SURDEZ DURANTE SOM EXTERNO
    # -------------------------------------------------------------------

    def _monitor_audio_externo(self):
        """
        Vigia o PulseAudio: algo tocando nos speakers → escuta pausada;
        som parou → escuta retoma sozinha. Detecção: linhas
        'State: RUNNING' em 'pactl list sink-inputs'.

        - O TTS do próprio JARVIS (mpv) também conta — nesses momentos a
          escuta já está pausada via boca_falando; zero conflito.
        - pactl falhou → assume silêncio (a escuta NUNCA trava por erro).
        - Só pausa a ESCUTA: gravação em andamento NÃO é abortada (o
          eco-guard continua ligado apenas ao TTS, via self.pausado) —
          assim o bip da wake word nunca derruba o comando seguinte.
        """
        externo_antes = False
        while self._ativo:
            tocando = False
            try:
                r = subprocess.run(
                    ["pactl", "list", "sink-inputs"],
                    capture_output=True, text=True, timeout=2)
                tocando = "State: RUNNING" in (r.stdout or "")
            except Exception:
                tocando = False

            self.audio_externo = tocando
            if tocando != externo_antes:
                if tocando:
                    print("[LISTEN] Som no speaker — escuta pausada.")
                else:
                    print("[LISTEN] Speaker em silêncio — escuta retomada.")
                externo_antes = tocando

            time.sleep(AUDIO_EXTERNO_POLL_SEG)

    # -------------------------------------------------------------------
    # WAKE WORD
    # -------------------------------------------------------------------

    def _inicializar_wake_word(self):
        """Cascata: 1) Porcupine → 2) openWakeWord (fallback local) → 3) nenhum."""
        self._motor_wake_word = None
        self._porcupine       = None
        self._oww_model       = None

        if PORCUPINE_ACCESS_KEY and PORCUPINE_ACCESS_KEY != "sua_chave_aqui":
            try:
                import pvporcupine
                self._porcupine = pvporcupine.create(
                    access_key=PORCUPINE_ACCESS_KEY,
                    keywords=[WAKE_WORD_KEYWORD],
                    sensitivities=[WAKE_WORD_SENSIBILIDADE],
                )
                print(f"[LISTEN] Wake word '{WAKE_WORD_KEYWORD}' ativa via Porcupine.")
                self._motor_wake_word = "porcupine"
                return
            except Exception as e:
                print(f"[LISTEN] Porcupine falhou ({e}).")
        else:
            print("[LISTEN] Chave do Porcupine não configurada.")

        print("[LISTEN] Ativando fallback openWakeWord (100% local)...")
        try:
            from openwakeword.model import Model
            import openwakeword

            try:
                self._oww_model = Model(
                    wakeword_models=[OWW_MODELO],
                    inference_framework="onnx",
                )
            except Exception:
                print("[LISTEN] Modelo openWakeWord ausente localmente, baixando...")
                openwakeword.utils.download_models()
                self._oww_model = Model(
                    wakeword_models=[OWW_MODELO],
                    inference_framework="onnx",
                )

            self._motor_wake_word = "openwakeword"
            print(f"[LISTEN] Wake word '{OWW_MODELO}' ativa via openWakeWord.")
        except ImportError:
            print("[LISTEN] openwakeword não instalado (pip install openwakeword). "
                  "Wake word desativada — gravação contínua.")
        except Exception as e:
            print(f"[LISTEN] Falha no openWakeWord ({e}). Wake word desativada.")

    def _aguardar_wake_word(self) -> bool:
        if not self._motor_wake_word:
            return True

        frame_length = self._porcupine.frame_length if self._porcupine else 1280
        confirmacoes = 0

        mic_device, mic_rate, ganho_mic, _ = _detectar_mic()

        razao_rate   = mic_rate // SAMPLE_RATE
        blocksize_hw = frame_length * razao_rate

        try:
            stream_ctx = sd.InputStream(
                samplerate=mic_rate, channels=CANAIS,
                dtype='int16', blocksize=blocksize_hw,
                device=mic_device,
            )
        except Exception as e:
            print(f"[LISTEN] ERRO ao abrir stream wake word: {e}")
            time.sleep(3)
            return False

        fonte_label = "WoMic celular" if mic_device else "PC"
        nome_motor = "Hey Jarvis / Jasper" if self._motor_wake_word == "porcupine" else "Hey Jarvis / Jasper"
        print(f"[LISTEN] Aguardando '{nome_motor}'... "
              f"(sens={WAKE_WORD_SENSIBILIDADE}, ganho={ganho_mic}x, "
              f"device={fonte_label}, rate={mic_rate}Hz)")

        with stream_ctx as stream:
            while self._ativo:
                # [v5-AUDIO] pausa = TTS/surdo OU som tocando no speaker
                if self.pausado or self.audio_externo:
                    time.sleep(0.1)
                    continue
                try:
                    pcm_data, _ = stream.read(blocksize_hw)
                except Exception as e:
                    print(f"[LISTEN] ERRO leitura microfone: {e}")
                    time.sleep(1)
                    break

                pcm_float = pcm_data[:, 0].astype(np.float32) / 32768.0

                if razao_rate != 1:
                    pcm_float = _resamplear(pcm_float, mic_rate, SAMPLE_RATE)

                pcm_float = np.clip(pcm_float * ganho_mic, -1.0, 1.0)

                if len(pcm_float) < frame_length:
                    continue
                pcm_float = pcm_float[:frame_length]
                pcm_int16 = (pcm_float * 32767.0).astype(np.int16)

                detectou = False
                if self._motor_wake_word == "porcupine":
                    resultado = self._porcupine.process(pcm_int16.tolist())
                    detectou = resultado >= 0
                elif self._motor_wake_word == "openwakeword":
                    prediction = self._oww_model.predict(pcm_int16)
                    detectou = max(prediction.values(), default=0.0) > OWW_THRESHOLD

                if detectou:
                    agora = time.time()
                    if agora - self._tempo_ultimo_wake < WAKE_WORD_COOLDOWN_SEG:
                        confirmacoes = 0
                        continue

                    confirmacoes += 1
                    print(f"[LISTEN] Candidato wake word ({confirmacoes}/{WAKE_WORD_CONFIRMACOES})...")

                    if confirmacoes >= WAKE_WORD_CONFIRMACOES:
                        self._tempo_ultimo_wake = agora
                        confirmacoes = 0
                        print(f"[LISTEN] Wake word confirmada pelo motor {self._motor_wake_word}!")
                        threading.Thread(target=self._tocar_bip, daemon=True).start()
                        return True
                else:
                    confirmacoes = 0

        return False

    # -------------------------------------------------------------------
    # GRAVAÇÃO COM DETECÇÃO DE SILÊNCIO
    # -------------------------------------------------------------------

    def _gravar_comando(self) -> tuple:
        """
        Retorna (audio_array_16kHz, frames_com_voz).
        [ORBS] self.gravando exposto para o enxame (anel "ouvindo").
        [ECO-GUARD] aborta se o TTS começar a falar no meio da gravação.
        """
        print("[LISTEN] Gravando...")
        self.gravando = True
        try:
            frames_gravados  = []
            frames_silencio  = 0
            frames_com_voz   = 0

            mic_device, mic_rate, ganho_mic, threshold_silencio = _detectar_mic()
            total_frames_max = int(mic_rate * DURACAO_GRAVACAO_SEG)

            try:
                stream_ctx = sd.InputStream(
                    samplerate=mic_rate, channels=CANAIS,
                    dtype='float32', blocksize=BLOCKSIZE,
                    device=mic_device,
                )
            except Exception as e:
                print(f"[LISTEN] ERRO stream gravação: {e}")
                return np.array([], dtype=np.float32), 0

            with stream_ctx as stream:
                total_frames = 0
                while total_frames < total_frames_max and self._ativo:
                    try:
                        frame, _ = stream.read(BLOCKSIZE)
                    except Exception as e:
                        print(f"[LISTEN] ERRO leitura gravação: {e}")
                        break

                    # [ECO-GUARD] TTS começou a falar NO MEIO da gravação
                    # (resposta pendente na fila — thread do clima/IA demorou)
                    # → aborta: o microfone só ouviria a própria voz do JARVIS.
                    if self.pausado:
                        print("[LISTEN] TTS durante a gravação — abortando (anti-eco).")
                        return np.array([], dtype=np.float32), 0

                    frame = frame * ganho_mic
                    frames_gravados.append(frame.copy())
                    total_frames += len(frame)

                    rms = float(np.sqrt(np.mean(frame ** 2)))
                    if rms < threshold_silencio:
                        frames_silencio += 1
                    else:
                        frames_silencio = 0
                        frames_com_voz += 1

                    if frames_silencio >= FRAMES_SILENCIO_PARAR:
                        print("[LISTEN] Silêncio detectado — encerrando.")
                        break

            if not frames_gravados:
                return np.array([], dtype=np.float32), 0

            audio = np.concatenate(frames_gravados, axis=0).flatten()

            if mic_rate != SAMPLE_RATE:
                audio = _resamplear(audio, mic_rate, SAMPLE_RATE)

            return audio, frames_com_voz
        finally:
            self.gravando = False   # [ORBS] cobre TODOS os returns

    # -------------------------------------------------------------------
    # TRANSCRIÇÃO (STT)
    # -------------------------------------------------------------------

    def _transcrever(self, audio: np.ndarray) -> str:
        self.processando = True   # [ORBS]
        try:
            if self._modelo_stt is None:
                return ""

            prompt = (
                "Jasper, Jarvis, modo dev, modo desenvolvedor, mudar a cor da HUD, "
                "vscode, mute, timer, clima, música, reproduzir, f5, "
                "tela cheia, mudo, pesquisa, o que é, quem é você, me explica, "
                "anotação, lembrete, memória, youtube, câmera, instagram, mario, "
                "cria uma imagem de."
            )

            segments, _ = self._modelo_stt.transcribe(
                audio,
                language=WHISPER_IDIOMA,
                beam_size=1,
                best_of=1,
                initial_prompt=prompt,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=200),
            )

            return _normalizar_texto(" ".join(seg.text for seg in segments))
        finally:
            self.processando = False   # [ORBS] cobre todos os returns

    # -------------------------------------------------------------------
    # [ECO-GUARD] — descarta transcrição que repete a própria fala
    # -------------------------------------------------------------------

    def _eh_eco(self, texto: str) -> bool:
        """
        True se a transcrição repete uma fala recente do JARVIS — cobre o
        caso de o TTS ter tocado/terminado entre duas checagens de pausa.
        Só compara falas LONGAS (≥6 palavras): respostas curtas dariam
        falso positivo com comandos legítimos. Sem acento nos dois lados.
        """
        def _sem_acento(s: str) -> str:
            return "".join(c for c in unicodedata.normalize("NFKD", s)
                           if not unicodedata.combining(c))

        palavras = set(_sem_acento(texto).split())
        for fala in get_ultimas_falas():
            palavras_fala = set(_sem_acento(_normalizar_texto(fala)).split())
            if len(palavras_fala) < 6:
                continue
            inter = palavras & palavras_fala
            if len(inter) / len(palavras_fala) >= 0.4:
                return True
        return False

    # -------------------------------------------------------------------
    # INTERPRETAÇÃO DE INTENÇÃO
    # -------------------------------------------------------------------

    def _interpretar_intencao(self, texto: str, havia_energia: bool = True) -> str | None:
        if not texto:
            return None

        palavras_texto  = set(texto.split())
        melhor_intencao = None
        melhor_score    = 0.0

        for intencao_id, compiladas in _INTENCOES_COMPILADAS:
            for palavras_var, variacao_str in compiladas:
                intersecao = palavras_texto & palavras_var
                if not intersecao:
                    continue

                score = len(intersecao) / len(palavras_texto | palavras_var)
                if variacao_str in texto:
                    score = min(score + 0.3, 1.0)

                if score > melhor_score:
                    melhor_score    = score
                    melhor_intencao = intencao_id   # ← era AQUI: "intencao" sem _id

                    if melhor_score >= SCORE_EARLY_EXIT:
                        break

            if melhor_score >= SCORE_EARLY_EXIT:
                break

        if melhor_score >= SIMILARIDADE_MINIMA:
            print(f"[LISTEN] Intenção: '{melhor_intencao}' (score={melhor_score:.2f})")
            return melhor_intencao

        # [FALLBACK] frase longa sem intenção → tratada como pergunta (Groq)
        if FALLBACK_PESQUISA_PALAVRAS and len(palavras_texto) >= FALLBACK_PESQUISA_PALAVRAS:
            print(f"[LISTEN] Sem intenção (melhor={melhor_score:.2f}) → "
                  f"encaminhando como pergunta ao Groq.")
            return "pesquisar"

        print(f"[LISTEN] Nenhuma intenção (melhor={melhor_score:.2f})")
        if havia_energia:
            jarvis_voice.falar(random.choice(VozNaoEntendeu))
        return None
    # -------------------------------------------------------------------
    # DEBOUNCE
    # -------------------------------------------------------------------

    def _is_duplicado(self, intencao: str) -> bool:
        agora = time.time()
        if (intencao == self._ultimo_comando and
                agora - self._tempo_ultimo_cmd < DEBOUNCE_COMANDO_SEG):
            print(f"[LISTEN] Debounce: '{intencao}' ignorado.")
            return True
        return False

    def _registrar_execucao(self, intencao: str):
        self._ultimo_comando   = intencao
        self._tempo_ultimo_cmd = time.time()

    # -------------------------------------------------------------------
    # LOOP PRINCIPAL
    # -------------------------------------------------------------------

    def _loop_principal(self):
        # [v4-SESSAO] retentativas: 0 = exigir wake word. Falha soma 1;
        # comando compreendido (ou 'só isso') zera.
        retentativas = 0

        while self._ativo:
            try:
                # [FIX-SURDO] espera enquanto pausado (TTS/surdo) OU som
                # no speaker [v5-AUDIO] — música tocando = surdo até parar
                while (self.pausado or self.audio_externo) and self._ativo:
                    time.sleep(0.1)
                if not self._ativo:
                    break

                # Wake word apenas na primeira tentativa da sequência
                if WAKE_WORD_ATIVO and retentativas == 0:
                    if not self._aguardar_wake_word():
                        continue

                audio, frames_com_voz = self._gravar_comando()

                if len(audio) < SAMPLE_RATE * 0.5:
                    print("[LISTEN] Áudio muito curto, ignorando.")
                    retentativas = self._registrar_falha(retentativas)
                    continue

                total_frames  = len(audio) / BLOCKSIZE
                fracao_voz    = frames_com_voz / total_frames if total_frames > 0 else 0
                havia_energia = fracao_voz >= FRACAO_FRAMES_VOZ_MINIMA

                if not havia_energia:
                    print(f"[LISTEN] Energia insuficiente ({fracao_voz:.2f}), ignorando.")
                    retentativas = self._registrar_falha(retentativas)
                    continue

                texto = self._transcrever(audio)
                if not texto:
                    print("[LISTEN] Transcrição vazia, ignorando.")
                    retentativas = self._registrar_falha(retentativas)
                    continue

                # [ECO-GUARD] transcrição = própria fala do JARVIS → descarta
                if self._eh_eco(texto):
                    print(f"[LISTEN] Eco da própria voz descartado: '{texto[:40]}...'")
                    continue

                # [v4-SESSAO] atalho: encerramento explícito SEM interpretar
                # (comparação sem acento — o _normalizar_texto já tirou os
                # acentos da transcrição antes de chegar aqui)
                if texto in ("so isso", "era isso", "mais nada",
                             "nada mais", "deixa assim", "ta bom assim",
                             "era so isso", "e isso", "isso e tudo", "nada"):
                    print("[LISTEN] Sessão encerrada pelo usuário ('só isso').")
                    retentativas = 0          # ← volta a exigir wake word
                    self._disparar_callbacks("encerrar_sessao", texto)
                    continue

                intencao = self._interpretar_intencao(texto, havia_energia)
                if not intencao:
                    retentativas = self._registrar_falha(retentativas)
                    continue

                # Comando compreendido → sessão segue, próximo ciclo re-ouve
                retentativas = 0

                # [v4-SESSAO] encerramento via variação do vocabulário
                # (ex: "pode deixar quieto" — não está no atalho acima)
                if intencao == "encerrar_sessao":
                    self._disparar_callbacks(intencao, texto)
                    continue

                if self._is_duplicado(intencao):
                    continue

                self._registrar_execucao(intencao)
                self._disparar_callbacks(intencao, texto)

            except Exception as e:
                print(f"[LISTEN] ERRO no loop: {e}")
                time.sleep(0.5)
    def _registrar_falha(self, retentativas: int) -> int:
        """Conta uma falha; ao atingir o máximo, volta a exigir wake word."""
        retentativas += 1
        if retentativas >= MAX_RETENTATIVAS_SEM_WAKE:
            print(f"[LISTEN] {retentativas} tentativas sem comando válido — "
                  f"voltando a aguardar wake word.")
            return 0
        return retentativas

    def _disparar_callbacks(self, intencao: str, texto_bruto: str):
        print(f"[LISTEN] ► '{intencao}' | '{texto_bruto}'")

        try:
            import memory as _memory
            _memory.registrar(texto_bruto, tipo="usuario")
        except Exception as e:
            print(f"[LISTEN] ERRO ao registrar fala do usuário na memória: {e}")

        for fn in self._callbacks:
            try:
                fn(intencao, texto_bruto)
            except Exception as e:
                print(f"[LISTEN] ERRO callback: {e}")


# Instância única
jarvis_listen = ListenEngine()
