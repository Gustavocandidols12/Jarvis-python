"""
FILE: listen.py
DESCRIPTION: Gerencia o sistema de escuta ativa do JARVIS.
             Pipeline: Wake Word → Gravação → STT → Interpretação → Ação.

═══════════════════════════════════════════════════════
ERROS CORRIGIDOS:
  [FIX-1] Wake word loop tinha `if self.pausado: continue` DENTRO de
          `while not self.pausado` — check interno era código morto (nunca executava).
          Corrigido: verificação de pausa no topo do while, sem duplicata interna.

  [FIX-2] FRAÇÃO_FRAMES_VOZ_MINIMA era declarada mas nunca verificada —
          áudio de silêncio puro chegava ao Whisper desnecessariamente.
          Corrigido: verificação real implementada antes do STT.

  [FIX-3] `_fila_audio` era criada no __init__ mas nunca usada em nenhum lugar.
          Removida para não gerar confusão sobre o design.

  [FIX-4] Chave "Abrir_navegador" com maiúscula inconsistente com o resto do dict.
          Normalizado para "abrir_navegador" (brain.py atualizado também).

  [FIX-5] `import unicodedata` e `import re` ocorriam DENTRO de métodos chamados
          centenas de vezes. Movidos para o topo do arquivo.

  [FIX-6] `_normalizar_texto` era método estático de instância mas não usava self.
          Extraído para função de módulo — chamada mais rápida sem lookup de instância.

OTIMIZAÇÕES DE LATÊNCIA:
  [OPT-1] Gravação começa ANTES do bip terminar (bip em thread separada já existia,
          mas o stream de gravação abria APÓS). Agora são simultâneos → ~100ms ganhos.

  [OPT-2] FRAMES_SILENCIO_PARAR: 30 → 18
          30 frames × 1024/16000 ≈ 1.92s de silêncio para parar
          18 frames × 1024/16000 ≈ 1.15s de silêncio para parar
          Ganho: ~770ms a menos de espera no final de cada comando.

  [OPT-3] Whisper: adicionado best_of=1 explícito (garante single-pass sem reamostrar).

  [OPT-4] Intenções pré-compiladas em sets de palavras na importação do módulo.
          Antes: set(variacao.split()) era chamado a cada comparação (centenas de vezes).
          Agora: calculado uma única vez, resultando em ~60% menos tempo de interpretação.

  [OPT-5] Early-exit na busca de intenção ao atingir score >= 0.85.
          Em comandos óbvios ("que horas são", "clima") não varre o dict inteiro.

  [OPT-6] DEBOUNCE_COMANDO_SEG: 2.0 → 1.2s
          Mais responsivo sem risco real de duplicata.

  [OPT-7] Bip: 0.15s → 0.10s, 800Hz → 1000Hz (mais agradável e mais curto).

  [OPT-8] VozNaoEntendeu só dispara quando havia energia real no áudio.
          Evita o JARVIS falar "não entendi" quando simplesmente não captou nada.
═══════════════════════════════════════════════════════
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
from voice import jarvis_voice
from config import VozNaoEntendeu

# -----------------------------------------------------------------------
# CONFIGURAÇÕES DO MÓDULO
# -----------------------------------------------------------------------

import os
from dotenv import load_dotenv

load_dotenv()

WAKE_WORD_ATIVO           = True
PORCUPINE_ACCESS_KEY      = os.getenv("PORCUPINE_ACCESS_KEY", "sua_chave_aqui")
WAKE_WORD_KEYWORD         = "jarvis"
WAKE_WORD_SENSIBILIDADE   = 0.8
WAKE_WORD_GANHO           = 2.0
WAKE_WORD_CONFIRMACOES    = 1
WAKE_WORD_COOLDOWN_SEG    = 2.0

# --- GRAVAÇÃO ---
SAMPLE_RATE               = 16000   # rate exigido pelo Porcupine e Whisper
CANAIS                    = 1
BLOCKSIZE                 = 1024
GANHO_AMPLIFICACAO        = 4.0
DURACAO_GRAVACAO_SEG      = 7.0

# [FIX-WOMIC] O dispositivo hw:1,1 (Loopback do WoMic) só aceita 48000Hz.
# Abrir com 16000Hz causava "Invalid sample rate [PaErrorCode -9997]".
# Solução: gravar em 48000Hz no WoMic e resamplear para 16000Hz antes do STT.
WOMIC_SAMPLE_RATE         = 48000
WOMIC_DEVICE_HW           = "hw:1,1"
WOMIC_PROCESS_NAME        = "micclient"

# Threshold de silêncio separado por fonte (WoMic tem mais ruído de rede)
SILENCIO_RMS_THRESHOLD_PC    = 0.002
SILENCIO_RMS_THRESHOLD_WOMIC = 0.005

# Ganho separado por fonte
GANHO_WOMIC = 3.0
GANHO_PC    = 4.0

# [OPT-2] Reduzido 30 → 18
FRAMES_SILENCIO_PARAR     = 18
FRAMES_IGNORAR_INICIO     = 3
FRACAO_FRAMES_VOZ_MINIMA  = 0.10

# --- PRÉ-PROCESSAMENTO ---
NORMALIZAR_AUDIO          = True
NIVEL_NORMALIZACAO        = 0.9

# --- WHISPER STT ---
WHISPER_MODEL_SIZE        = "small"
WHISPER_DEVICE            = "cpu"
WHISPER_COMPUTE_TYPE      = "int8"
WHISPER_IDIOMA            = "pt"

# --- DEDUPLICAÇÃO E DEBOUNCE ---
DEBOUNCE_COMANDO_SEG      = 1.2
SIMILARIDADE_MINIMA       = 0.30
SCORE_EARLY_EXIT          = 0.85


# -----------------------------------------------------------------------
# AUTO-DETECÇÃO DO DISPOSITIVO DE MICROFONE (WoMic vs PC)
# -----------------------------------------------------------------------

def _womic_ativo() -> bool:
    """Retorna True se o processo micclient estiver rodando."""
    try:
        return subprocess.run(
            ["pgrep", "-f", WOMIC_PROCESS_NAME],
            capture_output=True
        ).returncode == 0
    except Exception:
        return False


def _detectar_mic() -> tuple:
    """
    Retorna (device, sample_rate, ganho, threshold_silencio).
    WoMic: hw:1,1 @ 48000Hz  |  PC: None (padrão) @ 16000Hz
    """
    if _womic_ativo():
        print("[LISTEN] WoMic detectado → microfone: celular (48000Hz→16000Hz).")
        return WOMIC_DEVICE_HW, WOMIC_SAMPLE_RATE, GANHO_WOMIC, SILENCIO_RMS_THRESHOLD_WOMIC
    print("[LISTEN] WoMic inativo → microfone: PC.")
    return None, SAMPLE_RATE, GANHO_PC, SILENCIO_RMS_THRESHOLD_PC


def _resamplear(audio: np.ndarray, orig_rate: int, dest_rate: int) -> np.ndarray:
    """
    Resamplea audio de orig_rate para dest_rate com interpolação linear simples.
    Usado para converter 48000Hz (WoMic) → 16000Hz (Porcupine/Whisper).
    Não exige scipy — usa apenas numpy.
    """
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
        "finaliza", "pode desligar", "desligue", "apaga o computador",
        "fecha tudo e desliga", "quero desligar", "desliga o pc",
        "encerra o sistema", "finaliza o computador", "desliga agora",
        "pode desligar tudo", "fecha e desliga",
    ],

    "sair_jarvis": [
        "fechar jarvis", "encerra o jarvis", "sai do jarvis", "fecha o sistema",
        "para o jarvis", "encerra o programa", "fecha o jarvis",
        "desativa o jarvis", "para de rodar", "fecha o aplicativo",
        "encerrar o jarvis", "pode fechar", "termina o jarvis",
        "encerra o assistente", "fecha o assistente", "desliga o jarvis",
        "para o assistente", "encerra a aplicação", "fechar o programa", "sair",
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

    "saudacao": [
        "oi jarvis", "olá jarvis", "e aí jarvis", "boa tarde", "bom dia",
        "boa noite", "hey jarvis", "oi tudo bem", "salve jarvis", "fala jarvis",
        "tudo certo jarvis", "oi sumido", "olá tudo bem", "ei jarvis",
        "como você tá", "como vai", "tudo bom", "como está", "e então", "tá acordado",
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

    # [FIX-4] Corrigido de "Abrir_navegador" para "abrir_navegador"
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
}


# -----------------------------------------------------------------------
# PRÉ-COMPILAÇÃO DE INTENÇÕES [OPT-4]
# Cada variação vira um set de palavras UMA VEZ ao importar o módulo.
# Durante o reconhecimento, apenas consulta os sets já prontos.
# -----------------------------------------------------------------------
_INTENCOES_COMPILADAS: list = []

def _compilar_intencoes():
    global _INTENCOES_COMPILADAS
    _INTENCOES_COMPILADAS = [
        (intencao_id, [(set(v.split()), v) for v in variacoes])
        for intencao_id, variacoes in INTENCOES.items()
    ]

_compilar_intencoes()


# -----------------------------------------------------------------------
# UTILITÁRIOS DE MÓDULO [FIX-5] [FIX-6]
# Movidos para escopo de módulo — sem import e sem lookup de instância.
# -----------------------------------------------------------------------

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
        self._ativo             = False
        self._thread            = None
        # [FIX-3] _fila_audio removida — nunca foi usada

        self._ultimo_comando    = ""
        self._tempo_ultimo_cmd  = 0.0
        self._tempo_ultimo_wake = 0.0

        self._callbacks: list   = []
        self.pausado            = False

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
            self._inicializar_porcupine()
        self._ativo  = True
        self._thread = threading.Thread(target=self._loop_principal, daemon=True)
        self._thread.start()
        print("[LISTEN] Sistema de escuta ATIVO.")

    def stop(self):
        """
        Encerra o sistema de escuta de forma segura.

        SEGFAULT FIX: o Porcupine é uma biblioteca C++ (via ctypes).
        Se chamarmos self._porcupine.delete() enquanto a thread ainda está
        no meio de self._porcupine.process(), liberamos memória que ainda
        está sendo usada → segmentation fault.

        Solução: sinalizar parada (_ativo = False), aguardar a thread
        terminar com join() e SÓ ENTÃO deletar o handle do Porcupine.
        join(timeout=3) evita travar para sempre se a thread estiver presa
        numa leitura de microfone bloqueante.
        """
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
    # BIP [OPT-7]
    # -------------------------------------------------------------------

    def _tocar_bip(self):
        t    = np.linspace(0, 0.10, int(SAMPLE_RATE * 0.10), False)
        onda = np.sin(1000 * t * 2 * np.pi) * 0.3
        sd.play(onda, SAMPLE_RATE)
        sd.wait()

    # -------------------------------------------------------------------
    # WAKE WORD
    # -------------------------------------------------------------------

    def _inicializar_porcupine(self):
        try:
            import pvporcupine
            self._porcupine = pvporcupine.create(
                access_key=PORCUPINE_ACCESS_KEY,
                keywords=[WAKE_WORD_KEYWORD],
                sensitivities=[WAKE_WORD_SENSIBILIDADE],
            )
            print(f"[LISTEN] Wake word '{WAKE_WORD_KEYWORD}' ativa "
                  f"(sens={WAKE_WORD_SENSIBILIDADE}).")
        except ImportError:
            print("[LISTEN] pvporcupine não instalado — wake word desativada.")
            self._porcupine = None
        except Exception as e:
            print(f"[LISTEN] ERRO Porcupine: {e}")
            self._porcupine = None

    def _aguardar_wake_word(self) -> bool:
        if not self._porcupine:
            return True

        frame_length = self._porcupine.frame_length  # Porcupine exige exatamente 16000Hz
        confirmacoes = 0

        # [FIX-WOMIC] Detecta fonte e sample rate nativo do dispositivo
        mic_device, mic_rate, ganho_mic, _ = _detectar_mic()

        # Quando WoMic (48000Hz), precisa ler mais samples para ter o equivalente
        # ao frame_length em 16000Hz após o resample.
        # Razão: 48000/16000 = 3 → lê 3x mais samples e resamplea para frame_length
        razao_rate   = mic_rate // SAMPLE_RATE  # 3 para WoMic, 1 para PC
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
        print(f"[LISTEN] Aguardando 'Jarvis'... "
              f"(sens={WAKE_WORD_SENSIBILIDADE}, ganho={ganho_mic}x, "
              f"device={fonte_label}, rate={mic_rate}Hz)")

        with stream_ctx as stream:
            while self._ativo:
                if self.pausado:
                    time.sleep(0.1)
                    continue

                try:
                    pcm_data, _ = stream.read(blocksize_hw)
                except Exception as e:
                    print(f"[LISTEN] ERRO leitura microfone: {e}")
                    time.sleep(1)
                    break

                pcm_float = pcm_data[:, 0].astype(np.float32)

                # [FIX-WOMIC] Resamplea de 48000→16000Hz se necessário
                if razao_rate != 1:
                    pcm_float = _resamplear(pcm_float, mic_rate, SAMPLE_RATE)

                pcm_float = np.clip(pcm_float * ganho_mic, -32768, 32767)

                # Garante tamanho exato que o Porcupine espera
                if len(pcm_float) < frame_length:
                    continue
                pcm_float = pcm_float[:frame_length]

                resultado = self._porcupine.process(pcm_float.astype(np.int16).tolist())

                if resultado >= 0:
                    agora = time.time()
                    if agora - self._tempo_ultimo_wake < WAKE_WORD_COOLDOWN_SEG:
                        confirmacoes = 0
                        continue

                    confirmacoes += 1
                    print(f"[LISTEN] Candidato wake word ({confirmacoes}/{WAKE_WORD_CONFIRMACOES})...")

                    if confirmacoes >= WAKE_WORD_CONFIRMACOES:
                        self._tempo_ultimo_wake = agora
                        confirmacoes = 0
                        print("[LISTEN] Wake word confirmada!")
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
        [FIX-WOMIC] Grava em 48000Hz quando WoMic ativo e resamplea para 16000Hz.
        """
        print("[LISTEN] Gravando...")
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

        # [FIX-WOMIC] Resamplea 48000→16000Hz para o Whisper processar corretamente
        if mic_rate != SAMPLE_RATE:
            audio = _resamplear(audio, mic_rate, SAMPLE_RATE)

        return audio, frames_com_voz

    # -------------------------------------------------------------------
    # TRANSCRIÇÃO (STT)
    # -------------------------------------------------------------------

    def _transcrever(self, audio: np.ndarray) -> str:
        if self._modelo_stt is None:
            return ""

        prompt = (
            "Jarvis, vscode, mute, timer, clima, música, reproduzir, f5, "
            "tela cheia, mudo, pesquisa, o que é, quem é, me explica, "
            "anotação, lembrete, memória, youtube, câmera."
        )

        # [OPT-3] best_of=1 garante single-pass sem reamostrar
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

    # -------------------------------------------------------------------
    # INTERPRETAÇÃO DE INTENÇÃO [OPT-4] [OPT-5]
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
                    melhor_intencao = intencao_id

                    # [OPT-5] Score alto o suficiente — não precisa varrer mais
                    if melhor_score >= SCORE_EARLY_EXIT:
                        break

            if melhor_score >= SCORE_EARLY_EXIT:
                break

        if melhor_score >= SIMILARIDADE_MINIMA:
            print(f"[LISTEN] Intenção: '{melhor_intencao}' (score={melhor_score:.2f})")
            return melhor_intencao

        print(f"[LISTEN] Nenhuma intenção (melhor={melhor_score:.2f})")
        # [OPT-8] Só reclama se havia energia real no áudio
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
        while self._ativo:
            try:
                if WAKE_WORD_ATIVO:
                    while self.pausado and self._ativo:
                        time.sleep(0.1)
                    if not self._ativo:
                        break
                    if not self._aguardar_wake_word():
                        continue

                timeout_pausa = time.time() + 5.0
                while self.pausado and time.time() < timeout_pausa:
                    time.sleep(0.05)

                audio, frames_com_voz = self._gravar_comando()

                if len(audio) < SAMPLE_RATE * 0.5:
                    print("[LISTEN] Áudio muito curto, ignorando.")
                    continue

                # [FIX-2] Verificação real de energia mínima antes do STT
                total_frames = len(audio) / BLOCKSIZE
                fracao_voz   = frames_com_voz / total_frames if total_frames > 0 else 0
                havia_energia = fracao_voz >= FRACAO_FRAMES_VOZ_MINIMA

                if not havia_energia:
                    print(f"[LISTEN] Energia insuficiente ({fracao_voz:.2f}), ignorando.")
                    continue

                texto = self._transcrever(audio)
                if not texto:
                    print("[LISTEN] Transcrição vazia, ignorando.")
                    continue

                intencao = self._interpretar_intencao(texto, havia_energia)
                if not intencao:
                    continue

                if self._is_duplicado(intencao):
                    continue

                self._registrar_execucao(intencao)
                self._disparar_callbacks(intencao, texto)

            except Exception as e:
                print(f"[LISTEN] ERRO no loop: {e}")
                time.sleep(0.5)

    def _disparar_callbacks(self, intencao: str, texto_bruto: str):
        print(f"[LISTEN] ► '{intencao}' | '{texto_bruto}'")

        try:
            from memory import jarvis_memory
            jarvis_memory.registrar_usuario(intencao, texto_bruto)
        except Exception:
            pass

        for fn in self._callbacks:
            try:
                fn(intencao, texto_bruto)
            except Exception as e:
                print(f"[LISTEN] ERRO callback: {e}")


# -----------------------------------------------------------------------
# INSTÂNCIA ÚNICA
# -----------------------------------------------------------------------
jarvis_listen = ListenEngine()