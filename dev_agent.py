"""
FILE: dev_agent.py
DESCRIPTION: Agente de desenvolvimento do JARVIS. Recebe pedidos de código
             ("Jarvis, criar código: ..."), lê os arquivos do projeto, gera
             alterações via Groq, valida em ambiente de teste isolado, pede
             aprovação (sim/não por voz ou texto) e aplica:
             aprovado → reinicia o JARVIS com o código novo;
             rejeitado/timeout → restaura o backup.
             Todo o processo é registrado na memória (memory.py).

FLUXO:
    1. brain.py roteia "dev_codigo" → dev_agent.criar_codigo(pedido)  [thread]
    2. Groq escolhe até 3 arquivos para ler (inventário do projeto)
    3. Groq devolve blocos ARQUIVO/BUSCAR/SUBSTITUIR (ou ARQUIVO NOVO)
    4. Groq revisa os próprios blocos (2ª passada obrigatória)
    5. Aplicação em memória: BUSCAR precisa casar UMA vez; sintaxe via compile()
    6. Gravação com backup em .dev_backups/ + import isolado (JARVIS_TEST=1)
    7. Aprovação: voz (confirmar_sim/confirmar_nao) ou texto (s/n no terminal)
       — timeout = reversão automática
    8. sim → JARVIS reinicia | não → backup restaurado
"""
import os
import sys
import shutil
import subprocess
import threading
import time
from datetime import datetime

import memory as _memory
from voice import jarvis_voice

try:
    from utilities import _get_groq_client, GROQ_MODELO
    _GROQ_OK = True
except Exception:
    _GROQ_OK = False

# -----------------------------------------------------------------------
# CONFIGURAÇÕES
# -----------------------------------------------------------------------

PASTA_PROJETO     = os.path.expanduser("~/Desktop/td/jarvis-python-refactor")
PASTA_BACKUP      = os.path.join(PASTA_PROJETO, ".dev_backups")

MAX_ARQUIVOS_LER  = 3        # arquivos que a IA pode pedir para ler
MAX_CHARS_ARQUIVO = 40000    # leitura LOCAL (aplicação) — não vai pra API
MAX_CHARS_CONTEXTO = 11000   # teto TOTAL do contexto enviado à Groq#2 (~2750 tokens)
MAX_TOKENS_CODIGO = 3000     # resposta TAMBÉM consome TPM
GROQ_TPM_SEGURO   = 7500     # limite real 8000 — margem de segurança
TEMP_CODIGO       = 0.3      # código pede temperatura baixa (config usa 0.9 p/ voz)
REVISAO_AUTO      = True     # 2ª revisão da IA (obrigatória no prompt-padrão)
TESTE_IMPORT      = True     # import isolado em subprocesso (~300MB por alguns s)
TIMEOUT_APROVACAO = 90.0     # segundos esperando sim/não
ATRASO_REINICIO   = 3.0      # câmera/áudio precisam um instante pra soltar
TIMEOUT_TESTE_INTERATIVO = 600.0
MAX_TENTATIVAS_GERAR = 2

PULAR_PASTAS = {".git", "__pycache__", ".dev_backups", ".venv", "venv", "node_modules"}

PROMPT_SISTEMA = """Você é o agente de código do JARVIS (assistente de voz Python/Linux, modular:
brain.py decide, listen.py escuta, utilities.py helpers, voice.py fala, window.py/orbs.py visual,
main.py câmera/gestos, file_manager.py arquivos, memory.py memória).

REGRAS INEGOCIÁVEIS:
1. Mínimo de linhas, máxima legibilidade. Reaproveite o que já existe nos módulos.
2. NUNCA use regex (módulo re) — só métodos nativos de string (.split/.strip/.startswith/
   .endswith/in/.replace) e difflib.
3. Respeite a arquitetura: código novo no módulo certo.
4. Hardware fraco (i3, 3.6GB RAM, sem GPU): nada pesado — sem bibliotecas grandes ou
   processamento redundante.
5. Releia antes de enviar: lógica correta, sem redundância, BUSCAR casando exatamente
   (indentação incluída).

FORMATO DA RESPOSTA (só os blocos, sem markdown, sem texto fora deles).
Alterar trecho (BUSCAR casa UMA vez, caractere a caractere, com indentação original):
===ARQUIVO: nome.py===
===BUSCAR===
trecho atual exato
===SUBSTITUIR===
trecho novo
===FIM===
Inserir código novo: BUSCAR = linha-âncora existente, SUBSTITUIR = âncora + código novo.
Vários blocos por arquivo: o BUSCAR seguinte casa com o resultado do anterior.
Criar arquivo: ===ARQUIVO NOVO: nome.py=== ... conteúdo ... ===FIM===
Encerre com ===RESUMO=== (1-3 frases: o que mudou, por quê, cobertura do teste) ===FIM===

TESTE: o dev_agent.py valida sintaxe, importa os módulos em subprocesso isolado e abre um
JARVIS de teste em texto (jarvis_test.py) para o usuário aprovar. Avise no ===RESUMO=== o
que o teste não cobre."""

# -----------------------------------------------------------------------
# ORÇAMENTO TPM — Groq grátis: 8000 tokens/minuto. A requisição INTEIRA
# entra na conta (prompt + arquivos + resposta). Sem este guarda, a 2ª
# chamada em menos de 1 minuto estoura 413.
# -----------------------------------------------------------------------

_uso_tokens: list = []   # [(timestamp, tokens)] das chamadas do último minuto


def _estimar_tokens(texto: str) -> int:
    return len(texto) // 4 + 1


def _respeitar_tpm(estimativa: int):
    """Espera a janela de 1 minuto abrir se a soma estourar o teto seguro."""
    if estimativa > GROQ_TPM_SEGURO:
        return                          # nenhuma espera cabe — deixa falhar tratado
    agora = time.time()
    while _uso_tokens and agora - _uso_tokens[0][0] > 60.0:
        _uso_tokens.pop(0)
    usado = sum(t for _, t in _uso_tokens)
    if usado + estimativa <= GROQ_TPM_SEGURO:
        return
    espera = max(61.0 - (agora - _uso_tokens[0][0]), 2.0) if _uso_tokens else 2.0
    print(f"[DEV_AGENT] TPM do Groq em {usado} tokens/min — esperando {espera:.0f}s.")
    time.sleep(espera)
    _respeitar_tpm(estimativa)


def _registrar_uso(r):
    try:
        _uso_tokens.append((time.time(), int(r.usage.total_tokens)))
    except Exception:
        pass


def _chamada(cliente, **kwargs):
    """create() com raciocínio baixo (gpt-oss gasta tokens 'pensando');
    se o parâmetro não for aceito, chama sem ele."""
    try:
        return cliente.chat.completions.create(reasoning_effort="low", **kwargs)
    except Exception as e:
        if "reasoning" in str(e).lower() or "unsupported" in str(e).lower():
            return cliente.chat.completions.create(**kwargs)
        raise

# -----------------------------------------------------------------------
# ARQUIVOS DO PROJETO
# -----------------------------------------------------------------------

def _descricao_arquivo(caminho: str) -> str:
    try:
        with open(caminho, encoding="utf-8") as f:
            for linha in f.read(2000).splitlines():
                linha = linha.strip()
                if linha.startswith("DESCRIPTION:"):
                    return linha.replace("DESCRIPTION:", "").strip()
    except OSError:
        pass
    return ""

def _funcoes_do_arquivo(caminho: str) -> list:
    """Nomes de funções/métodos definidos no arquivo — mapa funcional barato
    (split de linhas, sem parse pesado). É isso que deixa a Groq julgar CERTO
    qual módulo guarda 'esquiva de mouse', 'timer', 'memória', etc."""
    funcoes = []
    try:
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha.startswith("def ") and "(" in linha:
                    nome = linha[4:].split("(")[0].strip()
                    if nome and "__" not in nome and nome not in funcoes:
                        funcoes.append(nome)
    except OSError:
        pass
    return funcoes[:14]

def _inventario() -> list:
    """LISTA X — todos os .py do projeto com descrição e funções.
    Vai INTEIRA na 1ª chamada Groq: é o mapa que ela usa para julgar."""
    inventario = []
    for raiz, pastas, arquivos in os.walk(PASTA_PROJETO):
        pastas[:] = [p for p in pastas if p not in PULAR_PASTAS]
        for arq in sorted(arquivos):
            if not arq.endswith(".py"):
                continue
            caminho = os.path.join(raiz, arq)
            partes = []
            desc = _descricao_arquivo(caminho)
            if desc:
                partes.append(desc)
            funcoes = _funcoes_do_arquivo(caminho)
            if funcoes:
                partes.append("funcoes: " + ", ".join(funcoes))
            inventario.append((arq, " | ".join(partes) or "sem descricao"))
    return inventario


def _caminho_seguro(nome: str) -> str | None:
    """Aceita só caminhos dentro de PASTA_PROJETO (bloqueia fuga com ../)."""
    partes = [p for p in nome.strip().replace("\\", "/").split("/")
              if p not in ("", ".", "..")]
    return os.path.join(PASTA_PROJETO, *partes) if partes else None


def _ler_arquivo(caminho: str) -> str | None:
    try:
        with open(caminho, encoding="utf-8") as f:
            texto = f.read(MAX_CHARS_ARQUIVO)
        if len(texto) >= MAX_CHARS_ARQUIVO:
            texto += "\n... [TRUNCADO - arquivo maior que o limite]"
        return texto
    except OSError as e:
        print(f"[DEV_AGENT] Falha ao ler {caminho}: {e}")
        return None

def _extrair_bloco_funcao(texto: str, nome_funcao: str) -> str | None:
    """Bloco 'def nome(...)' completo — do def até o próximo def/class
    do mesmo nível de indentação."""
    linhas = texto.splitlines()
    inicio = None
    for i, linha in enumerate(linhas):
        if linha.strip().startswith(f"def {nome_funcao}("):
            inicio = i
            break
    if inicio is None:
        return None
    base = len(linhas[inicio]) - len(linhas[inicio].lstrip())
    fim = len(linhas)
    for j in range(inicio + 1, len(linhas)):
        if not linhas[j].strip():
            continue
        nivel = len(linhas[j]) - len(linhas[j].lstrip())
        if nivel <= base and linhas[j].strip().startswith(("def ", "class ")):
            fim = j
            break
    return "\n".join(linhas[inicio:fim])


def _cabeca_e_cauda(texto: str, quota: int) -> str:
    """Começo + fim do texto, cortando sempre em fronteiras de linha."""
    if len(texto) <= quota:
        return texto
    linhas = texto.splitlines()
    metade = quota // 2
    cabeca, g1 = [], 0
    for l in linhas:
        if g1 + len(l) + 1 > metade:
            break
        cabeca.append(l)
        g1 += len(l) + 1
    cauda, g2 = [], 0
    for l in reversed(linhas):
        if g2 + len(l) + 1 > metade:
            break
        cauda.append(l)
        g2 += len(l) + 1
    return ("\n".join(cabeca) + "\n\n# ...[trecho omitido]...\n\n"
            + "\n".join(reversed(cauda)))


def _montar_conteudos(alvos: dict) -> dict:
    """{arquivo: [funções]} → {arquivo: contexto}, dentro de MAX_CHARS_CONTEXTO.
    Sem função mapeada: arquivo INTEIRO se couber (a função alvo pode estar
    no meio — cabeça+cauda cortava exatamente ela); senão, cabeça+cauda."""
    quota = MAX_CHARS_CONTEXTO // max(len(alvos), 1)
    conteudos = {}
    for nome, funcoes in alvos.items():
        texto = _ler_arquivo(_caminho_seguro(nome)) or ""
        if not funcoes:
            if len(texto) <= quota:
                conteudos[nome] = texto          # inteiro — sem risco de cortar o meio
            else:
                conteudos[nome] = _cabeca_e_cauda(texto, quota)
            continue
        partes, gastos = [], 0
        for fn in funcoes:
            bloco = _extrair_bloco_funcao(texto, fn)
            if not bloco:
                continue
            if gastos + len(bloco) <= quota:
                partes.append(bloco)
                gastos += len(bloco)
            elif not partes:
                bloco = _cabeca_e_cauda(bloco, quota)
                partes.append(bloco)
                gastos = len(bloco)
        if not partes:
            partes.append(_cabeca_e_cauda(texto, quota))
        conteudos[nome] = "\n\n".join(partes)
    return conteudos

# -----------------------------------------------------------------------
# PARSER DA RESPOSTA (sem regex — só split/strip)
# -----------------------------------------------------------------------

def _separar(texto: str, marcador: str) -> tuple:
    """Extrai blocos 'marcador ... ===FIM===' e devolve (blocos, texto restante)."""
    blocos = []
    while marcador in texto:
        antes, resto = texto.split(marcador, 1)
        if "===FIM===" not in resto:
            break
        meio, fim = resto.split("===FIM===", 1)
        blocos.append(meio.strip("\n"))
        texto = antes + "\n" + fim
    return blocos, texto


def _limpar_fences(texto: str) -> str:
    """Remove cercas markdown (```) que a IA às vezes insere."""
    return "\n".join(l for l in texto.splitlines() if not l.strip().startswith("```"))


def _parsear_resposta(resposta: str) -> tuple:
    """Retorna (blocos, resumo). Bloco: criar (arquivo inteiro) ou editar (pares)."""
    resposta = resposta.replace("===RESUMO===", "===RESUMO:")   # normaliza formato
    resumos, resposta = _separar(resposta.strip(), "===RESUMO:")
    resumo = resumos[0].strip() if resumos else ""

    blocos = []
    novos, resposta = _separar(resposta, "===ARQUIVO NOVO:")
    for seg in novos:
        cabec, _, corpo = seg.partition("\n")
        nome = cabec.split("===")[0].strip()
        if nome:
            blocos.append({"tipo": "criar", "arquivo": nome, "conteudo": corpo.strip("\n")})

    edits, resposta = _separar(resposta, "===ARQUIVO:")
    for seg in edits:
        cabec, _, corpo = seg.partition("\n")
        nome = cabec.split("===")[0].strip()
        pares = []
        for parte in corpo.split("===BUSCAR===")[1:]:
            pedacos = parte.split("===SUBSTITUIR===")
            if len(pedacos) == 2:
                pares.append((pedacos[0].strip("\n"), pedacos[1].strip("\n")))
        if nome and pares:
            blocos.append({"tipo": "editar", "arquivo": nome, "pares": pares})
    return blocos, resumo

# -----------------------------------------------------------------------
# CHAMADAS À IA
# -----------------------------------------------------------------------

# -----------------------------------------------------------------------
# SELEÇÃO DE ARQUIVOS — 3 camadas, nunca desiste
# IA → heurística por palavra-chave → módulos padrão
# -----------------------------------------------------------------------

ARQUIVOS_PADRAO = ["brain.py", "utilities.py"]

# (palavras do pedido) → módulos prováveis — 1ª linha que casar vence
_HEURISTICA = [
    (("voz", "voice", "falar", "fala", "tts"),                 ["voice.py", "brain.py"]),
    (("escut", "ouvir", "wake", "microfone", "stt"),           ["listen.py", "brain.py"]),
    (("esquiva", "esquiv", "janela", "orb", "orbe", "escala"), ["window.py", "brain.py"]),
    (("volume", "menor", "maior", "visual"),                   ["window.py", "brain.py"]),
    (("gesto", "mouse", "camera", "câmera", "mão", "mao"),     ["main.py", "gestures.py", "brain.py"]),
    (("arquivo", "pasta", "buscar"),                           ["file_manager.py", "brain.py"]),
    (("nota", "anota", "lembrete"),                            ["notes.py", "brain.py"]),
    (("memoria", "memória", "conversa", "histórico"),          ["memory.py", "brain.py"]),
    (("timer", "segundos", "minutos", "espera", "ficar"),      ["utilities.py", "brain.py"]),
    (("clima", "previs", "temperatura"),                       ["utilities.py"]),
    (("imagem", "desenhar"),                                   ["image_gen.py", "brain.py"]),
    (("humor", "emoc"),                                        ["emotions.py", "brain.py"]),    
]


def _selecao_heuristica(pedido: str) -> list:
    p = pedido.lower()
    for palavras, arquivos in _HEURISTICA:
        if any(palavra in p for palavra in palavras):
            return list(arquivos)
    return list(ARQUIVOS_PADRAO)


def _mapa_funcoes(inventario: list) -> dict:
    """{arquivo: [funções]} reconstruído da descrição do inventário."""
    mapa = {}
    for nome, desc in inventario:
        if "funcoes: " in desc:
            mapa[nome] = [f.strip() for f in desc.split("funcoes: ", 1)[1].split(",") if f.strip()]
        else:
            mapa[nome] = []
    return mapa


def _extrair_alvo(texto: str, inventario: list) -> dict:
    """Resposta da Groq#1 (formato tolerado) → {'arquivo.py': ['funcao', ...]}.
    Token a token: nome de arquivo muda o alvo corrente; identificador
    conhecido do mapa vira função dele. Sem regex."""
    validos = {nome.lower(): nome for nome, _ in inventario}
    funcoes_por_arquivo = _mapa_funcoes(inventario)
    alvo, atual = {}, None
    for bruto in (texto or "").replace("\n", " ").replace(",", " ") \
                              .replace(";", " ").replace(":", " ").split():
        token = bruto.strip("*`.-•'\"[]()").strip().lower()
        if not token:
            continue
        chave = token if token.endswith(".py") else token + ".py"
        if chave in validos:
            atual = validos[chave]
            alvo.setdefault(atual, [])
            continue
        if atual and token in funcoes_por_arquivo.get(atual, []) \
                and token not in alvo[atual]:
            alvo[atual].append(token)
    return alvo


def _escolher_arquivos(pedido: str, inventario: list) -> dict:
    """GROQ#1 — LISTA X + pedido → {'arquivo.py': [funções a ler]}.
    Nunca retorna vazio: IA → heurística → padrão."""
    lista = "\n".join(f"- {nome} :: {desc}" for nome, desc in inventario)
    prompt = (
        "Voce e o agente de codigo do JARVIS. Dado o pedido e a lista completa de "
        "arquivos (com descricao e funcoes de cada um), escolha onde a mudanca "
        "acontece.\n\n"
        f"PEDIDO: {pedido}\n\nLISTA DE ARQUIVOS:\n{lista}\n\n"
        "Arquitetura: decisao/logica em brain.py, audio em listen.py, helpers em "
        "utilities.py, janela/visual em window.py, orbes em orbs.py, voz em voice.py, "
        "humor em emotions.py, gestos/camera em main.py.\n"
        f"Responda no maximo {MAX_ARQUIVOS_LER} linhas, no formato exato:\n"
        "arquivo.py: funcao1, funcao2\n"
        "(funcoes que PRECISAM ser lidas; vazio se nenhuma). Nada alem dessas linhas."
    )
    try:
        _respeitar_tpm(_estimar_tokens(prompt) + 300)
        cliente = _get_groq_client()
        r = _chamada(cliente, model=GROQ_MODELO,
                     messages=[{"role": "user", "content": prompt}],
                     temperature=0.0, max_tokens=300)
        _registrar_uso(r)
        msg = r.choices[0].message
        texto = (msg.content or "") + " " + (getattr(msg, "reasoning", "") or "")
        alvos = _extrair_alvo(texto, inventario)
        if alvos:
            print(f"[DEV_AGENT] GROQ#1 julgou: { {k: v for k, v in alvos.items()} }")
            return alvos
        print("[DEV_AGENT] GROQ#1 sem nomes validos — heuristica.")
    except Exception as e:
        print(f"[DEV_AGENT] GROQ#1 falhou ({e}) — heuristica.")
    heuristicos = _selecao_heuristica(pedido)
    print(f"[DEV_AGENT] Selecao heuristica: {', '.join(heuristicos)}")
    return {nome: [] for nome in heuristicos}

def _gerar_codigo(pedido: str, conteudos: dict, erro_anterior: str = "") -> str:
    contexto = "\n".join(f"----- {nome} -----\n{texto}" for nome, texto in conteudos.items())
    feedback = ""
    if erro_anterior:
        feedback = (
            f"\n\n## TENTATIVA ANTERIOR FALHOU AO APLICAR\n{erro_anterior}\n"
            "Refaça os blocos: o BUSCAR precisa casar UMA vez, caractere a "
            "caractere (incluindo indentação), com o conteudo atual dos arquivos acima."
        )
    user = (f"## ARQUIVOS ATUAIS (trechos reais)\n{contexto}\n\n"
            f"## PEDIDO\n{pedido}{feedback}\n\n"
            "Responda somente com os blocos no formato definido (e ===RESUMO=== no final).")
    _respeitar_tpm(_estimar_tokens(PROMPT_SISTEMA + user) + MAX_TOKENS_CODIGO)
    cliente = _get_groq_client()
    r = _chamada(cliente, model=GROQ_MODELO,
                 messages=[{"role": "system", "content": PROMPT_SISTEMA},
                           {"role": "user", "content": user}],
                 temperature=TEMP_CODIGO, max_tokens=MAX_TOKENS_CODIGO)
    _registrar_uso(r)
    return r.choices[0].message.content.strip()


def _revisar(resposta: str) -> str | None:
    """2ª revisão obrigatória do prompt-padrão. None = blocos aprovados."""
    _respeitar_tpm(_estimar_tokens(resposta) + 1500)
    cliente = _get_groq_client()
    r = _chamada(cliente, model=GROQ_MODELO,
                 messages=[{"role": "user", "content": (
                     "2a revisao obrigatoria: releia os blocos abaixo procurando regex, "
                     "codigo redundante, bug de logica ou trecho BUSCAR que nao casaria "
                     "exatamente com o arquivo. Se estiver tudo certo, responda exatamente "
                     "OK. Se houver correcao, devolva os blocos completos corrigidos no "
                     "mesmo formato.\n\n" + resposta)}],
                 temperature=0.1, max_tokens=MAX_TOKENS_CODIGO)
    _registrar_uso(r)
    texto = r.choices[0].message.content.strip()
    return None if texto.upper().startswith("OK") else texto

# -----------------------------------------------------------------------
# BACKUP E APLICAÇÃO
# -----------------------------------------------------------------------

_backups_sessao: list = []   # (arquivo_backup, caminho_original)
_criados_sessao: list = []


def _backup(caminho: str):
    os.makedirs(PASTA_BACKUP, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = os.path.join(PASTA_BACKUP, f"{carimbo}_{os.path.basename(caminho)}")
    shutil.copy2(caminho, destino)
    _backups_sessao.append((destino, caminho))


def _restaurar():
    for backup, original in _backups_sessao:
        try:
            shutil.copy2(backup, original)
        except Exception as e:
            print(f"[DEV_AGENT] Falha ao restaurar {original}: {e}")
    for criado in _criados_sessao:
        try:
            if os.path.exists(criado):
                os.remove(criado)
        except Exception as e:
            print(f"[DEV_AGENT] Falha ao remover {criado}: {e}")
    _backups_sessao.clear()
    _criados_sessao.clear()


def _aplicar(blocos: list) -> tuple:
    """
    Monta os textos finais em memória, valida sintaxe e só então grava
    (com backup). Qualquer erro = nada é gravado.
    Retorna (ok, arquivos_gravados, erros).
    """
    finais, erros = {}, []
    for b in blocos:
        caminho = _caminho_seguro(b["arquivo"])
        if not caminho:
            erros.append(f"caminho invalido: {b['arquivo']}")
            continue
        if b["tipo"] == "criar":
            if os.path.exists(caminho):
                erros.append(f"{b['arquivo']} ja existe")
                continue
            finais[caminho] = b["conteudo"]
            continue
        texto = _ler_arquivo(caminho)
        if texto is None:
            erros.append(f"{b['arquivo']} nao existe")
            continue
        for buscar, substituir in b["pares"]:
            atual = finais.get(caminho, texto)
            ocorrencias = atual.count(buscar)
            if ocorrencias != 1:
                erros.append(f"{b['arquivo']}: BUSCAR casou {ocorrencias}x")
                continue
            atual = atual.replace(buscar, substituir)
            finais[caminho] = atual
    if erros:
        return False, [], erros

    # validação de sintaxe — compile nativo, sem subprocesso
    for caminho, texto in finais.items():
        try:
            compile(texto, os.path.basename(caminho), "exec")
        except SyntaxError as e:
            erros.append(f"{os.path.basename(caminho)}: sintaxe (linha {e.lineno})")
    if erros:
        return False, [], erros

    gravados = []
    for caminho, texto in finais.items():
        if os.path.exists(caminho):
            _backup(caminho)
        else:
            _criados_sessao.append(caminho)
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                f.write(texto)
            gravados.append(caminho)
        except OSError as e:
            erros.append(f"gravar {os.path.basename(caminho)}: {e}")
    if erros:
        _restaurar()
        return False, [], erros
    return True, gravados, []

# -----------------------------------------------------------------------
# AMBIENTE DE TESTE (instância separada — subprocesso com JARVIS_TEST=1)
# -----------------------------------------------------------------------

def _testar(gravados: list) -> str | None:
    if not TESTE_IMPORT:
        return None
    env = dict(os.environ, JARVIS_TEST="1")
    for caminho in gravados:
        nome = os.path.splitext(os.path.basename(caminho))[0]
        if nome in ("__init__", "config"):
            continue
        try:
            r = subprocess.run(
                [sys.executable, "-c", f"import {nome}"],
                cwd=PASTA_PROJETO, env=env,
                capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return f"import {nome}: timeout no ambiente de teste"
        if r.returncode != 0:
            linhas = (r.stderr or "").strip().splitlines()
            return f"import {nome}: {linhas[-1] if linhas else 'falhou'}"
    return None

# -----------------------------------------------------------------------
# APROVAÇÃO (voz via brain + texto via terminal)
# -----------------------------------------------------------------------

_aguardando = False
_resposta   = None


def aguardando_aprovacao() -> bool:
    return _aguardando


def responder_aprovacao(valor: bool):
    global _resposta
    _resposta = valor


def _canal_texto():
    """[DESATIVADO] o teste roda em janela própria — o 's/n' por voz
    continua; o input() daqui disputava o stdin do terminal principal."""
    return

def _aguardar_aprovacao() -> bool | None:
    """True=sim, False=não, None=timeout. (voz/texto — fluxo antigo, fallback)"""
    global _aguardando, _resposta
    _aguardando, _resposta = True, None
    threading.Thread(target=_canal_texto, daemon=True).start()
    fim = time.time() + TIMEOUT_APROVACAO
    while time.time() < fim and _resposta is None:
        time.sleep(0.25)
    _aguardando = False
    return _resposta


_subproc = None


def _testar_interativo() -> bool | None:
    """
    Abre o JARVIS de teste (jarvis_test.py). O usuário testa digitando e
    decide lá ('aprovado'/'rejeitado') — ou fala sim/não para ESTA instância.
    True=aprovado | False=rejeitado/fechado | None=sem teste (erro/timeout).
    """
    global _aguardando, _resposta, _subproc
    _aguardando, _resposta = True, None
    resultado = {}

    def _rodar_sub():
        global _subproc
        try:
            # [FIX-JANELA] janela de TERMINAL DEDICADA pro teste: stdin
            # próprio (não disputa com o prompt do JARVIS) e VISÍVEL —
            # antes o teste rodava no mesmo terminal e o input() dele
            # nunca recebia as teclas (parecia 'não abriu nada').
            term = None
            for cand in ("gnome-terminal", "xfce4-terminal", "konsole", "xterm"):
                if shutil.which(cand):
                    term = cand
                    break
            if term == "xterm":
                cmd = ["xterm", "-title", "JARVIS TESTE", "-e",
                       f"{sys.executable} jarvis_test.py --ja-janela"]
            elif term:
                cmd = [term, "--title", "JARVIS TESTE", "--",
                       sys.executable, "jarvis_test.py", "--ja-janela"]
            else:
                cmd = [sys.executable, "jarvis_test.py"]   # sem emulador: terminal atual
            _subproc = subprocess.Popen(
                cmd, cwd=PASTA_PROJETO, start_new_session=True,
                env=dict(os.environ, JARVIS_TEST="1", PYTHONUNBUFFERED="1"))
            resultado["code"] = _subproc.wait(timeout=TIMEOUT_TESTE_INTERATIVO)
        except subprocess.TimeoutExpired:
            try:
                _subproc.terminate()
            except Exception:
                pass
            resultado["erro"] = "timeout"
        except Exception as e:
            resultado["erro"] = str(e)

    threading.Thread(target=_rodar_sub, daemon=True).start()
    fim = time.time() + TIMEOUT_TESTE_INTERATIVO + 60
    while time.time() < fim:
        if _resposta is not None:              # decisão por VOZ (principal)
            _aguardando = False
            try:
                if _subproc and _subproc.poll() is None:
                    _subproc.terminate()
            except Exception:
                pass
            return _resposta
        if "code" in resultado:                # decisão no TERMINAL do teste
            _aguardando = False
            return resultado["code"] == 0
        if "erro" in resultado:                # teste nem abriu (ou expirou) → fallback voz
            _aguardando = False
            return None
        time.sleep(0.3)
    _aguardando = False
    return None
# -----------------------------------------------------------------------
# REINÍCIO
# -----------------------------------------------------------------------

def _reiniciar():
    """Fecha esta instância e sobe outra com o código novo (bash desanexado)."""
    os.makedirs(PASTA_BACKUP, exist_ok=True)
    python_bin = sys.executable or "python3"
    comando = (f"cd '{PASTA_PROJETO}' && sleep {ATRASO_REINICIO} && "
               f"nohup '{python_bin}' main.py >> .dev_backups/restart.log 2>&1 &")
    try:
        subprocess.Popen(["bash", "-c", comando], start_new_session=True)
    except Exception as e:
        print(f"[DEV_AGENT] Falha ao agendar reinicio: {e}")
    time.sleep(1.0)
    os._exit(0)

# -----------------------------------------------------------------------
# FLUXO PRINCIPAL
# -----------------------------------------------------------------------

def _mem_log(texto: str):
    """Registra o passo na memória do JARVIS (tipo='dev_agent')."""
    try:
        _memory.registrar(texto, tipo="dev_agent")
    except Exception as e:
        print(f"[DEV_AGENT] Falha ao registrar na memoria: {e}")


_ocupado = False


def criar_codigo(pedido: str):
    """Entrada pública (chamada pelo brain). Roda em thread — nada trava."""
    global _ocupado
    if _ocupado:
        jarvis_voice.falar("Já tenho uma obra em andamento, chefe. Espera terminar.")
        return
    _ocupado = True
    threading.Thread(target=_executar, args=(pedido,), daemon=True).start()


def _executar(pedido: str):
    global _ocupado
    try:
        _rodar(pedido)
    except Exception as e:
        print(f"[DEV_AGENT] ERRO: {type(e).__name__}: {e}")
        _restaurar()
        try:
            jarvis_voice.falar("O agente de código falhou. Nada foi alterado, chefe.")
            _mem_log(f"dev_agent falhou: {type(e).__name__}: {e}")
        except Exception:
            pass
    finally:
        _ocupado = False


def _rodar(pedido: str):
    if not _GROQ_OK:
        jarvis_voice.falar("Sem cliente de IA disponível pro agente de código.")
        return
    _mem_log(f"Pedido de código recebido: {pedido}")

    inventario = _inventario()
    if not inventario:
        jarvis_voice.falar(f"Não achei o projeto em {PASTA_PROJETO}, chefe.")
        return

    alvos = _escolher_arquivos(pedido, inventario)
    print(f"[DEV_AGENT] Alvos: { {k: v for k, v in alvos.items()} }")

    jarvis_voice.falar("Lendo os arquivos e forjando o código.")
    conteudos = _montar_conteudos(alvos)

    # [NARRATIVA] o processo é longo e mudo — cada fase fala, pra você
    # saber que não travou (i3 + Groq + fila = até 90s de silêncio antes)
    jarvis_voice.falar("Contexto montado. Pedindo o código à IA — isso pode demorar.")

    # geração + aplicação com retry — o erro da tentativa anterior volta à IA
    ok, gravados, erros, blocos, resumo = False, [], [], [], ""

    resposta = ""
    for _ in range(MAX_TENTATIVAS_GERAR):
        resposta = _gerar_codigo(pedido, conteudos, erro_anterior=" | ".join(erros))
        jarvis_voice.falar("Resposta recebida. Conferindo os blocos.")
        blocos, resumo = _parsear_resposta(_limpar_fences(resposta))
        if blocos and REVISAO_AUTO:
            jarvis_voice.falar("Revisão dupla da IA em andamento.")
            revisada = _revisar(resposta)
            if revisada:
                b2, r2 = _parsear_resposta(_limpar_fences(revisada))
                if b2:
                    blocos, resumo = b2, (r2 or resumo)
        if not blocos:
            break
        ok, gravados, erros = _aplicar(blocos)
        if ok:
            break
        jarvis_voice.falar("A aplicação rejeitou um trecho. Ajustando com a IA.")
        print(f"[DEV_AGENT] Aplicacao falhou ({erros}) — tentando de novo.")

    # IA respondeu em texto (sem código) — fala a explicação e encerra
    if not blocos:
        texto = (resumo or resposta).strip()
        _mem_log(f"Resposta da IA (sem código): {texto}")
        jarvis_voice.falar(texto[:350] or "A IA não devolveu código.")
        return

    if not ok:
        _mem_log("Falha ao aplicar: " + " | ".join(erros))
        jarvis_voice.falar("Não consegui aplicar as mudanças, nada foi tocado. "
                           f"Motivo: {erros[0]}")
        return

    nomes_gravados = [os.path.basename(c) for c in gravados]
    _mem_log(f"Blocos aplicados em {', '.join(nomes_gravados)}. Resumo: {resumo or 'n/a'}")

    jarvis_voice.falar("Validação de sintaxe e import — a parte silenciosa, já vai.")
    falha = _testar(gravados)
    if falha:
        _restaurar()
        _mem_log(f"Teste falhou — revertido: {falha}")
        jarvis_voice.falar("O teste falhou, reverti tudo. Seguimos como antes. "
                           f"Detalhe: {falha[:120]}")
        return

    jarvis_voice.falar("Código aplicado. Abrindo o JARVIS de teste — teste "
                       "digitando e decida lá, ou me diga sim ou não.")
    decisao = _testar_interativo()
    if decisao is None:                        # teste indisponível → voz pura
        jarvis_voice.falar("Teste interativo indisponível. Aprova por voz? Sim ou não.")
        decisao = _aguardar_aprovacao()

    if decisao is True:
        _mem_log(f"APROVADO. Gravados: {', '.join(nomes_gravados)}. Resumo: {resumo or 'n/a'}")
        jarvis_voice.falar("Confirmado. Reiniciando com o código novo. Já volto.")
        _reiniciar()

    motivo = "Você rejeitou." if decisao is False else "Tempo esgotado."
    _restaurar()
    _mem_log(f"REVERTIDO — {motivo} Arquivos: {', '.join(nomes_gravados)}")
    jarvis_voice.falar(f"{motivo} Reverti tudo, chefe.")
