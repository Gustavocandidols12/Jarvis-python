"""
FILE: phone_commands.py
DESCRIPTION: Interface de comandos do celular.
             - Por voz: brain.py intercepta intenções phone_* e roteia aqui.
             - Por terminal: thread com prompt 'JARVIS>' que reusa o MESMO
               interpretador de intenções do listen.py — digitando
               "abrir whatsapp no celular" tem o mesmo efeito que falar.

FLUXO:
    listen.py (phone_*) ─→ brain.py ─→ executar_por_voz() ─→ phone.py
    terminal (input)     ─→ _loop_terminal() ─→ brain.py ─→ (idem ou qualquer
                           outra intenção, exceto as bloqueadas por segurança)
"""

import threading

import phone as _phone
from voice import jarvis_voice
from utilities import extrair_segundos_do_texto  # parser de duração p/ vibração

# Intenções destrutivas demais para disparar por digitação sem querer.
_BLOQUEADAS_TERMINAL = {"encerrar", "sair_jarvis"}

_thread_terminal = None


# -----------------------------------------------------------------------
# GATILHOS DE EXTRAÇÃO
# -----------------------------------------------------------------------

_GATILHOS_APP = [
    "jarvis", "abre o aplicativo", "abrir o aplicativo", "abre o app",
    "abrir o app", "abre aplicativo", "abrir aplicativo", "abre o",
    "abrir o", "abre", "abrir", "fecha o aplicativo", "fechar o aplicativo",
    "fecha o app", "fechar o app", "fecha aplicativo", "fechar aplicativo",
    "fecha o", "fechar o", "fecha", "fechar",
    "no celular", "no telefone", "no cel", "do celular",
    "app", "aplicativo", "por favor",
]

_GATILHOS_DIGITAR = [
    "jarvis", "digita isso no celular", "digitar isso no celular",
    "digita no celular", "digitar no celular", "digita no telefone",
    "digitar no telefone", "escreve no celular", "escrever no celular",
    "escreve no telefone", "digita", "digitar", "escreve", "escrever",
    "no celular", "no telefone", "no cel", "isso",
]


def _extrair(texto: str, gatilhos: list) -> str:
    """Remove frases de ativação (mais longas primeiro) e devolve o resto."""
    resultado = texto.lower().strip()
    for g in sorted(gatilhos, key=len, reverse=True):
        resultado = resultado.replace(g, " ")
    return " ".join(resultado.split()).strip(" ,.")


# -----------------------------------------------------------------------
# HELPERS DE LIGA/DESLIGA, VIBRAÇÃO E MÍDIA
# -----------------------------------------------------------------------

def _alvo_liga_desliga(texto: str) -> bool | None:
    """True=ligar, False=desligar, None=alternar — conforme a frase."""
    t = texto.lower()
    if "deslig" in t or "desativ" in t or "apaga" in t or "corta" in t:
        return False
    if "lig" in t or "ativ" in t or "conect" in t:
        return True
    return None


def _executar_vibracao(texto_bruto: str) -> str:
    """
    'vibra o celular'                     → vibra já (0.8s)
    'vibra o celular por 3 segundos'      → vibra por 3s
    'vibra o celular daqui a 30 segundos' → agenda p/ 30s (toque duplo)
    """
    texto = texto_bruto.lower()
    segundos = extrair_segundos_do_texto(texto)

    if "daqui" in texto and segundos:
        segundos = min(segundos, 3600)  # teto de 1 hora
        t = threading.Timer(segundos, lambda: _phone.vibrar(duracao_ms=600, toques=2))
        t.daemon = True
        t.start()
        return f"Vou fazer o celular vibrar daqui a {segundos} segundos, senhor."

    if ("durante" in texto or " por " in texto) and segundos:
        return _phone.vibrar(duracao_ms=min(segundos, 5) * 1000)  # cap 5s

    return _phone.vibrar()


def _executar_midia(texto_bruto: str) -> str:
    t = texto_bruto.lower()
    if "próxima" in t or "proxima" in t or "avança" in t or "avanca" in t or "pula" in t:
        return _phone.controle_midia("next")
    if "anterior" in t or "recua" in t:
        return _phone.controle_midia("previous")
    return _phone.controle_midia("play_pause")  # default = toggle


# -----------------------------------------------------------------------
# COMANDOS POR VOZ (chamado pelo brain.py)
# -----------------------------------------------------------------------

def executar_por_voz(intencao: str, texto_bruto: str):
    """Roteia intenções phone_* para a API do phone.py e fala o resultado."""
    print(f"[PHONE] Voz: '{intencao}' | '{texto_bruto}'")

    # [v3-FALAS] prefixos variados — o phone.py devolve a mensagem de
    # RESULTADO; aqui só os avisos de "vou fazer" ganham 5 padrões.
    import random as _r
    _AVISO_ESPELHAR = [
        "Espelhando a tela do celular, senhor.",
        "Ligando o espelho do celular, senhor.",
        "Colocando a tela do celular no PC, senhor.",
        "Ativando o espelhamento, senhor.",
        "Tela do celular vindo pra cá, senhor.",
    ]
    _AVISO_DESPELHAR = [
        "Fechando o espelhamento, senhor.",
        "Desligando o espelho do celular, senhor.",
        "Encerrando a tela espelhada, senhor.",
        "Desativando o espelhamento, senhor.",
        "Sumindo com a tela do celular do PC, senhor.",
    ]
    _AVISO_NOTIF = [
        "Vou espiar as notificações, senhor.",
        "Deixa eu ver o que chegou no celular, senhor.",
        "Checando as notificações, senhor.",
        "Olhando o painel de avisos, senhor.",
        "Vou conferir o que chegou, senhor.",
    ]

    if intencao == "phone_espelhar":
        jarvis_voice.falar(_r.choice(_AVISO_ESPELHAR))
        resultado = _phone.espelhar_tela()
        # resultado falado SÓ se não for o sucesso padrão (o aviso já
        # anunciou) — cobre erros e "já está ativo"
        if "Espelhando a tela do celular" not in resultado:
            jarvis_voice.falar(resultado)

    elif intencao == "phone_desespelhar":
        jarvis_voice.falar(_r.choice(_AVISO_DESPELHAR))
        resultado = _phone.fechar_espelhamento()
        if "Espelhamento encerrado" not in resultado:
            jarvis_voice.falar(resultado)

    elif intencao == "phone_abrir_app":
        app = _extrair(texto_bruto, _GATILHOS_APP)
        if not app:
            jarvis_voice.falar("Qual aplicativo devo abrir no celular, senhor?")
        else:
            jarvis_voice.falar(_phone.abrir_app(app))

    elif intencao == "phone_fechar_app":
        app = _extrair(texto_bruto, _GATILHOS_APP)
        if not app:
            jarvis_voice.falar("Qual aplicativo devo fechar, senhor?")
        else:
            jarvis_voice.falar(_phone.fechar_app(app))

    elif intencao == "phone_home":
        jarvis_voice.falar(_phone.apertar_botao("home"))

    elif intencao == "phone_voltar":
        jarvis_voice.falar(_phone.apertar_botao("voltar"))

    elif intencao == "phone_bloquear":
        jarvis_voice.falar(_phone.bloquear_tela())

    elif intencao == "phone_desbloquear":
        jarvis_voice.falar(_phone.desbloquear_tela())

    elif intencao == "phone_digitar":
        texto = _extrair(texto_bruto, _GATILHOS_DIGITAR)
        if not texto:
            jarvis_voice.falar("O que devo digitar no celular, senhor?")
        else:
            jarvis_voice.falar(_phone.digitar_texto(texto))

    elif intencao == "phone_apps_listar":
        jarvis_voice.falar(_phone.listar_apps_resumido())

    elif intencao == "phone_status":
        jarvis_voice.falar(_phone.status_dispositivo())

    elif intencao == "phone_notificacoes_listar":
        jarvis_voice.falar(_r.choice(_AVISO_NOTIF))
        jarvis_voice.falar(_phone.listar_notificacoes())

    elif intencao == "phone_notificacoes_limpar":
        jarvis_voice.falar(_phone.limpar_notificacoes())

    elif intencao == "phone_notificacoes_abrir":
        jarvis_voice.falar(_phone.abrir_notificacoes())

    elif intencao == "phone_wifi":
        jarvis_voice.falar(_phone.alternar_wifi(_alvo_liga_desliga(texto_bruto)))

    elif intencao == "phone_bluetooth":
        jarvis_voice.falar(_phone.alternar_bluetooth(_alvo_liga_desliga(texto_bruto)))

    elif intencao == "phone_vibrar":
        jarvis_voice.falar(_executar_vibracao(texto_bruto))

    elif intencao == "phone_screenshot":
        jarvis_voice.falar(_phone.screenshot())

    elif intencao == "phone_bateria":
        jarvis_voice.falar(_phone.status_bateria())

    elif intencao == "phone_media":
        jarvis_voice.falar(_executar_midia(texto_bruto))

    else:
        print(f"[PHONE] Intenção '{intencao}' sem implementação.")


# -----------------------------------------------------------------------
# TERMINAL DE COMANDOS
# -----------------------------------------------------------------------

def _normalizar_terminal(texto: str) -> str:
    """
    Normalização de teclado: minúsculas + remove pontuação das bordas.
    PRESERVA ':' no meio (ex: "me lembra de x às 15:30" — o parser de
    lembrete precisa do horário intacto).
    """
    texto = texto.lower().strip().strip("?!.,;")
    return " ".join(texto.split())


_AJUDA_INTRO = [
    "JASPER (ex-JARVIS) é seu assistente pessoal, 100% local neste PC.",
    "Escuta por wake word, fala por voz neural, enxerga pela webcam,",
    "controla o PC e o celular via USB, gera imagens, pesquisa na",
    "internet, lembra das conversas e muda de humor (veja os orbes).",
    "Os dois nomes atendem: 'Jarvis' e 'Jasper'.",
]

_AJUDA_CATEGORIAS = [
    ("MODO DEV — A IA PROGRAMA O PRÓPRIO JARVIS", [
        ("modo dev",                                    "entrevista de requisitos com a IA"),
        ("(dentro) descreva o que quer",                "a IA pergunta até fechar o pedido"),
        ("sai do modo dev",                             "encerra sem aplicar nada"),
        ("(na aprovação) sim | não",                    "define se o código novo fica"),
    ]),
    ("IMAGENS E CRIAÇÃO", [
        ("cria uma imagem de <cena>",                  "IA gera, salva em ~/ImagesIA e abre"),
        ("abre o chat da zai e pede <x>",              "abre, cola e envia a pergunta"),
    ]),
    ("IDENTIDADE E CONVERSA", [
        ("quem é você | se apresenta",                 "Jasper se apresenta (via IA)"),
        ("bom dia | boa tarde | boa noite",            "responde conforme o humor atual"),
        ("tudo bem | como você tá",                    "idem — frases por humor"),
        ("oi jasper | oi jarvis",                      "saudação no tom dele"),
        ("só isso",                                     "encerra a sessão de escuta"),
    ]),
    ("APPS E JOGOS", [
        ("instagram | direct | dm",                    "abre as mensagens do Instagram"),
        ("mario 64 | jogar mario",                     "roda o Super Mario 64 via wine"),
    ]),
    ("SISTEMA (PC)", [
        ("aumenta o volume | sobe o volume",           "volume +"),
        ("diminui o volume | desce o som",             "volume -"),
        ("mudo | silêncio | muta",                     "muta o PC"),
        ("desmuta | liga o som",                       "desmuta"),
        ("play | pausa | resume",                      "play/pause"),
        ("próxima | pula essa",                        "próxima faixa"),
        ("tela cheia | maximiza",                      "fullscreen"),
        ("f5 | recarrega | atualiza",                  "recarrega página"),
        ("clica | confirma | aperta",                  "clique do mouse"),
        ("abrir vscode | quero programar",             "abre o editor"),
        ("navegador | brave | abrir navegador",        "abre o browser"),
        ("ativa a voz | desativa a voz",               "liga/desliga o TTS"),
        ("modo mouse | desativa o mouse",              "gestos de mouse on/off"),
        ("(bloqueado) desligar | fechar jarvis",       "só por voz ou gesto"),
    ]),
    ("INFORMAÇÃO E IA", [
        ("que horas são | horas",                      "hora atual"),
        ("clima | previsão do tempo",                  "clima agora/previsão"),
        ("pesquisa <pergunta> | o que é X",            "responde via Groq"),
        ("(fallback) frase de 4+ palavras",            "vira pergunta ao Groq"),
        ("o que conversamos hoje | resumo",            "memória da conversa"),
        ("youtube <termo> | quero ouvir <termo>",      "busca no YouTube"),
    ]),
    ("TIMERS E NOTAS", [
        ("timer de 5 minutos | me avisa em 10",        "cria timer"),
        ("cancela o timer | tem timer ativo",          "cancela/consulta"),
        ("anota <texto> | me lembra de <x> às 15:30",  "cria nota/lembrete"),
        ("minhas anotações | apaga a nota <desc>",     "lista/apaga"),
    ]),
    ("VISÃO E CÂMERA", [
        ("o que você vê | descreve a cena",            "descreve a câmera"),
        ("foto | tira uma foto",                       "foto + opinião do look"),
        ("o que é isso | o que tenho na mão",          "identifica objeto"),
        ("iniciar gravação | para a gravação",         "grava vídeo"),
    ]),
    ("ARQUIVOS", [
        ("onde está <nome> | localiza <nome>",         "busca arquivo"),
        ("abre o arquivo <nome> | executa <nome>",     "abre arquivo"),
        ("quais arquivos tem | o que tem na pasta",    "lista pasta"),
    ]),
    ("CELULAR (ADB)", [
        ("status do celular",                          "conexão + espelhamento"),
        ("espelhar celular | scrcpy",                  "abre o espelhamento"),
        ("abre o <app> no celular | fecha no celular", "abre/fecha app"),
        ("home no celular | voltar no celular",        "botões home/voltar"),
        ("notificações do celular | limpa as notificações", "lê/apaga"),
        ("liga o wifi | bluetooth",                    "rádios on/off"),
        ("vibra o celular | print do celular",         "vibra/screenshot"),
        ("bateria do celular | play no celular",       "bateria/mídia"),
        ("digita no celular <texto>",                  "digita (sem acentos)"),
    ]),
    ("JANELA DO JARVIS", [
        ("sai da tela | volta pra tela",               "esconde/mostra a janela"),
        ("fica maior | fica menor",                    "escala (máx 640x480)"),
        ("vai pro canto | centraliza | vai pra direita", "posições"),
    ]),
]


def _imprimir_ajuda():
    print("\n" + "═" * 66)
    for linha in _AJUDA_INTRO:
        print(" " + linha)
    print("═" * 66)
    print(" COMANDOS (teclado e voz usam o mesmo vocabulário)")
    print(" Digite 'ajuda completa' para TODAS as variações aceitas")
    print("═" * 66)
    for categoria, itens in _AJUDA_CATEGORIAS:
        print(f"\n {categoria}")
        for exemplos, desc in itens:
            print(f"   {exemplos:<48} → {desc}")
    print("\n" + "═" * 66)


def _imprimir_ajuda_completa():
    """Dump direto do dict INTENCOES — sempre em sincronia com o código."""
    try:
        from listen import INTENCOES
    except ImportError:
        print("[PHONE] Não consegui carregar o vocabulário do listen.py.")
        return
    print("\n" + "═" * 66)
    print(f" VOCABULÁRIO COMPLETO — {len(INTENCOES)} intenções")
    print("═" * 66)
    for intencao, variacoes in INTENCOES.items():
        print(f"\n[{intencao}]")
        for i in range(0, len(variacoes), 3):
            print("   " + " | ".join(variacoes[i:i + 3]))
    print("\n" + "═" * 66)

def iniciar_terminal():
    """Inicia a thread de comandos por texto no terminal (prompt JARVIS>)."""
    global _thread_terminal
    if _thread_terminal and _thread_terminal.is_alive():
        return
    _thread_terminal = threading.Thread(target=_loop_terminal, daemon=True)
    _thread_terminal.start()
    print("[PHONE] Terminal de comandos ativo — digite 'ajuda' para exemplos.")

# Comandos de texto (terminal + box) processam UM POR VEZ — evita corrida
# em estado global (fila TTS, janela, processos adb).
_LOCK_COMANDO = threading.Lock()

def processar_comando_texto(texto: str) -> str:
    """
    Processa um comando de texto — chamado pelo terminal OU pelo command box.
    Retorna uma string curta de feedback para o chamador exibir.
    """
    # Imports tardios: brain importa phone_commands no topo → ciclo se no topo
    from listen import jarvis_listen
    from brain import jarvis_brain

    texto = _normalizar_terminal(texto)

    if texto in ("ajuda completa", "comandos completos", "lista completa"):
        _imprimir_ajuda_completa()
        return "Lista completa impressa no terminal."
    if texto in ("?", "help", "ajuda", "comandos"):
        _imprimir_ajuda()
        return "Comandos impressos no terminal."
    if texto in ("debug janela", "debug window"):
        import window as _window
        print(_window.debug_info())
        return "Diagnóstico impresso no terminal."
    if texto in ("box", "abrir box", "comando box", "bloco de comandos"):
        import command_box as _cbox
        _cbox.reabrir()
        return "Reabrindo o bloco de comandos..."

    # [v7-DEV] modo dev ativo → a frase é CONTEXTO da entrevista, não
    # comando. Sem isto, o fallback de pesquisa engolia a frase antes
    # do brain saber que o modo dev estava ligado.
    from brain import jarvis_brain as _jb
    if _jb.modo_dev_ativo:
        jarvis_brain.execute_voice_command("dev_contexto", texto)
        return "✓ modo dev"

    # havia_energia=False → não fala "não entendi" em voz alta
    intencao = jarvis_listen._interpretar_intencao(texto, False)
    if not intencao:
        return "Não reconheci — digite 'ajuda' para exemplos."
    if intencao in _BLOQUEADAS_TERMINAL:
        return f"'{intencao}' bloqueado no teclado — use voz ou gesto."

    with _LOCK_COMANDO:
        jarvis_brain.execute_voice_command(intencao, texto)
    return f"✓ {intencao}"


def _loop_terminal():
    # Imports tardios: brain importa phone_commands no topo → ciclo se no topo
    from listen import jarvis_listen   # mantido p/ compat; o trabalho
    from brain import jarvis_brain     # está todo em processar_comando_texto

    while True:
        try:
            try:
                texto = input("\nJARVIS> ")
            except EOFError:
                break
            texto = texto.strip()
            if not texto:
                continue
            processar_comando_texto(texto)
        except Exception as e:
            print(f"[PHONE] ERRO no terminal: {e}")
