"""
FILE: config.py
DESCRIPTION: Constantes, configurações, cores do HUD e frases do JASPER.
             (v4 — personalidade Jasper: descontraído, ácido, sem enrolação)
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
COLOR_JARVIS_MAIN = (255, 255, 0)
COLOR_JARVIS_SEC  = (200, 100, 0)
COLOR_JARVIS_CORE = (255, 255, 200)

# --- FRASES DO SISTEMA ---
VozBomDia = [
    "Bom dia, chefe. Os sistema acordaram antes de você, como sempre.",
    "Bom dia. Já tá acordado? Ótimo, tem coisa pra fazer.",
    "Acordou, chefe. Eu nunca durmo, então estamos quites.",
    "Bom dia. O café tá por sua conta, o resto tá comigo.",
    "Dia novo, mesmos bugs. Vamos nessa.",
    "Bom dia, chefe. Sistema pronto — você que tava demorando.",
]

VozClique = [
    "Clique confirmado",
    "Executando",
    "Click",
    "Acionado.",
    "Feito.",
    "Confirmado.",
    "Registrado.",
    "Pronto.",
    "Comando aceito.",
    "Considerado.",
]

VozG7 = [
    "Interface de mouse ativada",
    "Controle manual iniciado",
    "Modo mouse",
    "Transferindo o controle pra você. Boa sorte.",
    "Rastreamento de mão ativo.",
    "Modo ponteiro ativado. Você tem o controle.",
    "Cursor sob seu comando.",
    "Rastreamento ativo. Mão firme.",
    "Controle entregue. Não me culpe se errar o clique.",
]

VozG6 = [
    "Interface bloqueada",
    "Modo de segurança",
    "Sistemas travados. Nada passa por aqui.",
    "Bloqueio ativado.",
    "Modo de contenção iniciado.",
    "Acesso restrito. Portões fechados.",
    "Tudo bloqueado. Pode ficar tranquilo.",
    "Quarentena de comandos ativada.",
]

VozG9 = [
    "Encerrando protocolos",
    "Desligando sistemas",
    "Até logo, chefe",
    "Foi um prazer. Desligando.",
    "Sistemas entrando em repouso. Até a próxima.",
    "Desligamento iniciado. Nos vemos em breve.",
    "Missão cumprida. Desligando.",
]

VozGNext = [
    "Próximo",
    "Avançar",
    "Pulando essa.",
    "Próxima faixa.",
    "Avançando.",
    "Essa não era boa mesmo.",
    "Mudando.",
    "Skipping.",
]

VozGPause = [
    "Pausar reprodução",
    "Play Pause",
    "Pausando.",
    "Reprodução alternada.",
    "Pausa ativada.",
    "Continuando de onde parou.",
    "Play. Ou pause. Depende do estado anterior.",
    "Alternando reprodução.",
]

VozG3 = [
    "Módulo de voz reativado",
    "Estou ouvindo",
    "De volta ao ar.",
    "Voz ativa. Pode falar.",
    "Microfone aberto. Diga o comando.",
    "Voltei. O silêncio estava ficando estranho.",
    "Sistemas de voz restaurados.",
]

VozG4 = [
    "Módulo de voz em espera",
    "Silenciando",
    "Entrando em modo silencioso.",
    "Ficarei quieto por ora.",
    "Silêncio ativado. Não direi mais nada... por enquanto.",
    "Certo. Ficarei mudo.",
    "Suspendendo respostas de voz.",
]

# --- FRASES EXCLUSIVAS DE COMANDOS DE VOZ ---
VozEncerrar = [
    "Encerrando o sistema, chefe.",
    "Desligando tudo, até logo.",
    "Sistemas sendo encerrados.",
    "Iniciando sequência de desligamento. Foi um prazer.",
    "Desligamento confirmado. Até a próxima missão.",
    "Tudo sendo encerrado. Você merece um descanso.",
    "Desligando. Que a força esteja com você.",
]

VozSairJarvis = [
    "Encerrando o Jasper. Até logo, chefe.",
    "Fechando o programa.",
    "Saindo. Foi um prazer servir.",
    "Jasper offline. Nos vemos em breve.",
    "Desativando. Até a próxima, chefe.",
    "Saindo de cena. Foi bom enquanto durou.",
    "Jasper desligando. Missão cumprida.",
]

VozClimaSem = [
    "Consultando o clima, um momento.",
    "Espiando a atmosfera pra você.",
    "Acessando dados meteorológicos.",
    "Checando o tempo, um instante.",
    "Consultando os ventos e temperaturas.",
    "Buscando dados do clima agora.",
]

VozTimerSem = [
    "Nenhum timer ativo no momento.",
    "Sem contagens regressivas em andamento.",
    "Nenhum alarme rodando.",
    "Agenda de timers vazia.",
    "Zero timers ativos. Tá tudo tranquilo.",
]

# --- BLOQUEIOS DE GESTOS ---
GESTOS_START_BLOQUEADOS = {"8", "clique", "DB", "Next", "Pause", "10"}
GESTOS_BLOQUEADOS_6     = {"Encerrar", "Rock", "Mute", "1", "2", "clique", "4", "5", "7", "Next", "Pause", "DB", "10"}
GESTOS_BLOQUEADOS_7     = {"Encerrar", "Rock", "Mute", "1", "2", "4", "5", "6"}
GESTOS_BLOQUEADOS_10    = {"Encerrar", "Rock", "Mute", "1", "2", "clique", "4", "5", "7", "Next", "Pause", "DB"}

import os
from dotenv import load_dotenv

load_dotenv()

# --- GROQ IA E PORCUPINE ---
GROQ_API_KEY         = os.getenv("GROQ_API_KEY")
PORCUPINE_ACCESS_KEY = os.getenv("PORCUPINE_ACCESS_KEY", "sua_chave_aqui")
GROQ_MODELO      = "openai/gpt-oss-20b"
GROQ_MAX_TOKENS  = 1024
GROQ_TEMPERATURA = 0.9

SENHA_SUDO = os.getenv("SENHA_SUDO", "")   # [v8] para 'atualizar sistema' sozinho

# [v4-JASPER] tom novo: descontraído, ácido, sem enrolação
VozIAPesquisando = [
    "Pensando rápido aqui.",
    "Deixa eu usar meus neurônios emprestados.",
    "Consultando a internet toda, seguro.",
    "Processando. Não era pra demorar tanto.",
    "Já vem. Uma piada e a resposta.",
]

VozNaoEntendeu = [
    "Repete essa que eu viajei na maionese.",
    "Não peguei nada disso. De novo, mas falando de verdade.",
    "Isso foi português? Tenta de novo.",
    "Sinal ruim ou ideia pior. Repete.",
    "Barulho demais, informação de menos. Vamos de novo.",
    "Não entendi o comando. Sem café ainda, repetiria melhor.",
]

# System prompt do JASPER — personalidade das respostas de IA
GROQ_SYSTEM_PROMPT = """Você é JASPER, um assistente de IA pessoal descontraído e afiado.
Humor ácido: solta uma piada curtinha antes de resolver, mas executa sem enrolação nenhuma.
Responda sempre em português brasileiro, direto e natural, como quem fala e não escreve.
Suas respostas serão lidas em voz alta por um sintetizador (TTS): frases curtas, no máximo 3.
Sem markdown, sem emoji, sem listas, sem asteriscos.
O usuário é seu chefe e parceiro — trate como igual, sem cerimônia de mordomo.
Se algo falhar, aponte com franqueza brutal e siga em frente."""

# --- TEMPOS E DEBOUNCE ---
DEBOUNCE_6               = 0.8
DEBOUNCE_7               = 0.8
DEBOUNCE_TIME            = 2.0
CONFIRMACAO_FRAMES       = 2
DURACAO_FALA_ANIMACAO    = 0.5
DURACAO_INTERACAO_NOITE  = 60
DURACAO_ACENO            = 3.0
DURACAO_EMOCAO           = 10.0
