"""
FILE: config.py
DESCRIPTION: Armazena todas as constantes, configurações de sistema, cores do HUD e listas de frases do JARVIS.
"""
import pyautogui

# --- OTIMIZAÇÃO CRÍTICA DO MOUSE ---
pyautogui.PAUSE = 0
# pyautogui.FAILSAFE = False

# --- CONSTANTES VISUAIS (BGR) ---
LANDMARK_COLOR       = (200, 255, 200)
CONNECTION_COLOR     = (50, 100, 50)
LANDMARK_RADIUS      = 3
CONNECTION_THICKNESS = 1
SMOOTHING_FACTOR     = 0.25

# --- CORES JARVIS (BGR) ---
COLOR_JARVIS_MAIN = (255, 255, 0)    # Ciano
COLOR_JARVIS_SEC  = (200, 100, 0)    # Azul profundo
COLOR_JARVIS_CORE = (255, 255, 200)  # Branco azulado

# --- FRASES DO SISTEMA ---
VozBomDia = [
    "Bom dia comunada !",
    "Olá senhor, sistemas online",
    "Bom dia chefe",
    "Bom dia, senhor. Café já tá frio, mas os sistemas estão quentes.",
    "Acordou finalmente. Sistemas prontos há horas.",
    "Bom dia. Prontos para mais um dia de missões improváveis.",
    "Online e operacional. Bom dia, senhor.",
    "Bom dia. O mundo não vai conquistar a si mesmo.",
    "Sistemas iniciados. O senhor demorou.",
    "Bom dia. Espero que tenha dormido melhor que meus processos.",
]

VozClique = [
    "Clique confirmado",
    "Executando",
    "Click",
    "Acionado.",
    "Feito.",
    "Confirmado.",
    "Registrado, senhor.",
    "Pronto.",
    "Considerado.",
    "Comando aceito.",
]

VozG7 = [
    "Interface de mouse ativada",
    "Controle manual iniciado",
    "Modo mouse",
    "Transferindo o controle pro senhor. Boa sorte.",
    "Rastreamento de mão ativo.",
    "Modo ponteiro ativado. O senhor tem o controle.",
    "Interface manual iniciada.",
    "Cursor sob seu comando, senhor.",
    "Rastreamento ativo. Mão firme.",
    "Controle entregue. Não me culpe se errar o clique.",
]

VozG6 = [
    "Interface bloqueada",
    "Modo de segurança",
    "Sistemas travados. Nada passa por aqui.",
    "Bloqueio ativado, senhor.",
    "Modo de contenção iniciado.",
    "Acesso restrito. Portões fechados.",
    "Protocolos de segurança ativos.",
    "Tudo bloqueado. Pode ficar tranquilo.",
    "Modo seguro. Nenhum gesto indesejado passará.",
    "Quarentena de comandos ativada.",
]

VozG9 = [
    "Encerrando protocolos",
    "Desligando sistemas",
    "Até logo, senhor",
    "Foi um prazer, senhor. Desligando.",
    "Sistemas entrando em repouso. Até a próxima.",
    "Encerrando tudo. Cuide-se, senhor.",
    "Desligamento iniciado. Nos vemos em breve.",
    "Protocolo de encerramento ativado. Tchau.",
    "Missão cumprida. Desligando.",
    "Até logo. Tente não precisar de mim por muito tempo.",
]

VozGNext = [
    "Próximo",
    "Avançar",
    "Pulando essa.",
    "Próxima faixa.",
    "Avançando.",
    "Essa não era boa mesmo.",
    "Mudando.",
    "Próxima, senhor.",
    "Forwarding.",
    "Skipping.",
]

VozGPause = [
    "Pausar reprodução",
    "Play Pause",
    "Pausando.",
    "Reprodução alternada.",
    "Toggled.",
    "Pausa ativada.",
    "Continuando de onde parou.",
    "Reprodução pausada, senhor.",
    "Play. Ou pause. Depende do estado anterior.",
    "Alternando reprodução.",
]

VozG3 = [
    "Módulo de voz reativado",
    "Estou ouvindo",
    "De volta ao ar, senhor.",
    "Voz ativa. Pode falar.",
    "Microfone aberto. Diga o comando.",
    "Aqui estou, senhor.",
    "TTS online. Pronto para responder.",
    "Ouvidos atentos, senhor.",
    "Voltei. O silêncio estava ficando estranho.",
    "Sistemas de voz restaurados.",
]

VozG4 = [
    "Módulo de voz em espera",
    "Silenciando",
    "Entrando em modo silencioso.",
    "Ficarei quieto por ora.",
    "Voz suspensa, senhor.",
    "Silêncio ativado. Não direi mais nada... por enquanto.",
    "TTS pausado.",
    "Certo. Ficarei mudo.",
    "Modo quieto ativado. Prometo não reclamar.",
    "Suspendendo respostas de voz.",
]

# --- FRASES EXCLUSIVAS DE COMANDOS DE VOZ ---
VozEncerrar = [
    "Encerrando o sistema, senhor.",
    "Desligando tudo, até logo.",
    "Sistemas sendo encerrados.",
    "Desligar computador",
    "Iniciando sequência de desligamento. Foi um prazer.",
    "Encerrando todos os processos. Cuide-se, senhor.",
    "Desligamento confirmado. Até a próxima missão.",
    "Sistemas indo a repouso. Boa noite, senhor.",
    "Protocolo de shutdown iniciado. Tchau.",
    "Tudo sendo encerrado. O senhor merece um descanso.",
    "Desligando. Que a força esteja com o senhor.",
]

VozSairJarvis = [
    "Encerrando o JARVIS. Até logo, senhor.",
    "Fechando o programa.",
    "Até logo, senhor.",
    "Saindo. Foi um prazer servir.",
    "JARVIS offline. Nos vemos em breve.",
    "Encerrando minha instância. Cuide-se.",
    "Programa encerrado. O senhor vai sobreviver sem mim.",
    "Desativando. Até a próxima, senhor.",
    "Saindo de cena. Foi bom enquanto durou.",
    "JARVIS desligando. Missão cumprida.",
]

VozClimaSem = [
    "Consultando o clima, um momento.",
    "Verificando as condições atmosféricas, senhor.",
    "Acessando dados meteorológicos.",
    "Checando o tempo, um instante.",
    "Consultando os ventos e temperaturas.",
    "Um momento, estou olhando pela janela virtual.",
    "Buscando dados do clima agora.",
    "Verificando se vai chover no seu desfile, senhor.",
]

VozTimerSem = [
    "Nenhum timer ativo no momento, senhor.",
    "Sem contagens regressivas em andamento.",
    "Nenhum alarme rodando no momento.",
    "Agenda de timers vazia, senhor.",
    "Nada contando no momento.",
    "Zero timers ativos. Tá tudo tranquilo.",
    "Sem timers. O senhor está livre de obrigações temporais.",
    "Nenhum cronômetro em execução, senhor.",
]
# --- BLOQUEIOS DE GESTOS ---
GESTOS_START_BLOQUEADOS = {"8", "clique", "DB", "Next", "Pause", "10"}
GESTOS_BLOQUEADOS_6     = {"Encerrar", "Rock", "Mute", "1", "2", "clique", "4", "5", "7", "Next", "Pause", "DB", "10"}
GESTOS_BLOQUEADOS_7     = {"Encerrar", "Rock", "Mute", "1", "2", "4", "5", "6"}
GESTOS_BLOQUEADOS_10    = {"Encerrar", "Rock", "Mute", "1", "2", "clique", "4", "5", "7", "Next", "Pause", "DB"}

import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env (se existir)
load_dotenv()

# --- GROQ IA E PORCUPINE ---
# As chaves das APIs agora são carregadas através de variáveis de ambiente (.env)
GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "sua_chave_aqui")
PORCUPINE_ACCESS_KEY = os.getenv("PORCUPINE_ACCESS_KEY", "sua_chave_aqui")
GROQ_MODELO      = "llama-3.1-8b-instant"  # mais rápido (560 t/s) — ideal para TTS em tempo real
GROQ_MAX_TOKENS  = 200                      # limita resposta para o TTS não demorar
GROQ_TEMPERATURA = 0.8                      # 0=determinístico, 1=criativo

# Frases de espera enquanto a IA processa (faladas antes da resposta chegar)
VozIAPesquisando = [
    "Processando, um momento.",
    "Consultando, senhor.",
    "Deixa eu verificar isso.",
    "Um instante, senhor.",
]
VozNaoEntendeu = [
    "Não entendi direito, senhor. Pode repetir?",
    "Não captei bem. Pode falar novamente?",
    "Desculpe, não compreendi. Pode repetir?",
    "Não foi possível processar. Pode falar de novo?",
    "Sinal confuso, senhor. Tente novamente.",
    "Não entendi o comando. Pode repetir?",
    "foi mal, senhor. Pode repetir mais claramente?",
    "Ruído no sinal. Pode tentar novamente?",
]
# System prompt — define a personalidade do JARVIS nas respostas de IA
GROQ_SYSTEM_PROMPT = """Você é JARVIS, um assistente de IA pessoal inteligente, bem humorado e conciso.
Responda sempre em português brasileiro.
Seja direto e objetivo — suas respostas serão lidas em voz alta por um sintetizador de voz (TTS).
Evite markdown, listas com bullets, asteriscos, emojis ou qualquer formatação especial.
Use frases curtas e naturais, como se estivesse conversando.
Limite suas respostas a no máximo 3 frases, salvo quando o usuário pedir explicação detalhada.
Trate o usuário como senhor quando apropriado."""

# --- TEMPOS E DEBOUNCE ---
DEBOUNCE_6               = 0.8
DEBOUNCE_7               = 0.8
DEBOUNCE_TIME            = 2.0
CONFIRMACAO_FRAMES       = 2
DURACAO_FALA_ANIMACAO    = 0.5
DURACAO_INTERACAO_NOITE  = 60
DURACAO_ACENO            = 3.0
DURACAO_EMOCAO           = 10.0