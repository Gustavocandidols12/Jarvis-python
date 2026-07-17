"""
FILE: file_manager.py
DESCRIPTION: Módulo de gerenciamento de arquivos do JARVIS.
             Localiza arquivos em qualquer lugar do sistema pelo nome
             (com fuzzy matching, não precisa ser exato) e abre-os com
             a aplicação apropriada.

FLUXO:
    brain.py → file_manager.buscar_arquivo(nome)  [quando "onde está X"]
    brain.py → file_manager.abrir_arquivo(nome)   [quando "abrir X"]

DEPENDÊNCIAS:
    difflib → já presente no Python stdlib, usado para fuzzy matching.
    os, subprocess → ambos stdlib, já usados em todo o projeto.

FUZZY MATCHING:
    Ao procurar "arquivo X", não precisa ser exatamente "arquivo X" —
    busca em todo o filesystem por arquivos com nomes similares usando
    SequenceMatcher.ratio() (mesmo padrão já bem-testado em listen.py
    para intenções). Se encontrar múltiplos matches, retorna o com melhor score.
"""

import os
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from voice import jarvis_voice

try:
    import personality as _personality  # [NOVO] respostas humanizadas
except ImportError:
    _personality = None

try:
    from groq import Groq
    from config import GROQ_API_KEY, GROQ_MODELO
    _GROQ_OK = True
except Exception:
    _GROQ_OK = False

# -----------------------------------------------------------------------
# CONFIGURAÇÕES
# -----------------------------------------------------------------------

# Pastas raiz para busca — começa do home do usuário para desempenho
# (buscar desde / pode levar minutos). Para encontrar arquivos globais
# mesmo em /etc, /usr, etc., o usuário precisaria de permissões + paciência.
PASTA_RAIZ_BUSCA = os.path.expanduser("~")

# Mínimo de similaridade para considerar um match válido (0.0 a 1.0).
# Muito baixo = false positives (acha "xd.txt" pra "arquivo.txt").
# Muito alto = falsos negativos (não acha "arquivo_importante.txt" pra "arquivo").
# 0.6 é um bom ponto de equilíbrio empiricamente.
SCORE_MINIMO = 0.6

# Máximo de resultados a considerar (se houver 1000 "documento.txt"...)
LIMITE_RESULTADOS = 50

# Aplicações padrão para abrir tipos de arquivo em Linux
APPS_PADRAO = {
    ".pdf": "xdg-open",
    ".txt": "xdg-open",
    ".md": "xdg-open",
    ".doc": "libreoffice",
    ".docx": "libreoffice",
    ".xls": "libreoffice",
    ".xlsx": "libreoffice",
    ".ppt": "libreoffice",
    ".pptx": "libreoffice",
    ".png": "eog",  # Eye of GNOME
    ".jpg": "eog",
    ".jpeg": "eog",
    ".gif": "eog",
    ".mp4": "vlc",
    ".avi": "vlc",
    ".mkv": "vlc",
    ".mp3": "vlc",
    ".wav": "vlc",
    ".zip": "xdg-open",
    ".tar": "xdg-open",
    ".gz": "xdg-open",
    ".7z": "xdg-open",
    ".exe": "wine",  # Wine para executáveis Windows
    ".sh": "bash",
    ".py": "python3",
}

# -----------------------------------------------------------------------
# BUSCA E FUZZY MATCHING
# -----------------------------------------------------------------------

def _score_similaridade(nome_procurado: str, nome_arquivo: str) -> float:
    """
    Calcula similaridade entre o nome procurado e o nome do arquivo,
    normalizando para lowercase e ignorando extensões para melhor match.
    Retorna valor 0.0 a 1.0.
    """
    # Compara nome do arquivo (sem extensão) contra o procurado
    nome_arquivo_base = os.path.splitext(os.path.basename(nome_arquivo))[0]
    procurado_lower = nome_procurado.lower()
    arquivo_lower = nome_arquivo_base.lower()

    # Score principal: SequenceMatcher (mesmo usado em listen.py)
    score = SequenceMatcher(None, procurado_lower, arquivo_lower).ratio()

    # Bônus se o nome procurado é substring exata (case-insensitive)
    if procurado_lower in arquivo_lower:
        score = min(score + 0.15, 1.0)

    return score


def _buscar_recursivo(diretorio: str, nome_procurado: str, resultados: list) -> None:
    """
    Caminha recursivamente pelo filesystem procurando por arquivos com
    nomes similares. Usa DFS (recursão) pra simplicidade, com limite
    de resultados pra evitar demora infinita.
    """
    if len(resultados) >= LIMITE_RESULTADOS:
        return

    try:
        for entrada in os.listdir(diretorio):
            if len(resultados) >= LIMITE_RESULTADOS:
                return

            caminho_completo = os.path.join(diretorio, entrada)

            # Se é arquivo, calcula score
            if os.path.isfile(caminho_completo):
                score = _score_similaridade(nome_procurado, entrada)
                if score >= SCORE_MINIMO:
                    resultados.append((caminho_completo, score))

            # Se é pasta, desce recursivamente (com proteção contra loops)
            elif os.path.isdir(caminho_completo):
                # Pula pastas que normalmente têm bilhões de arquivos ou
                # requerem permissões especiais
                if entrada.startswith("."):
                    continue
                if entrada in ["node_modules", "__pycache__", ".git", ".venv", "venv"]:
                    continue

                _buscar_recursivo(caminho_completo, nome_procurado, resultados)

    except PermissionError:
        # Pastas onde não temos permissão são silenciosamente puladas
        pass
    except Exception:
        # Qualquer outro erro (symlink quebrado, etc.) também pula
        pass


def buscar_arquivo(nome_procurado: str) -> str:
    """
    Localiza arquivo em qualquer lugar do filesystem (abaixo de ~/) com
    nome similar ao procurado, usando fuzzy matching.

    Parâmetros:
        nome_procurado — nome ou parte do nome do arquivo (ex: "documento",
            "documento.txt", "doc importante")

    Retorna:
        String pronta para o JARVIS falar, contendo o caminho do arquivo
        encontrado ou uma mensagem de não encontrado.
    """
    if not nome_procurado or not nome_procurado.strip():
        return "Qual arquivo você está procurando, senhor?"

    nome_procurado = nome_procurado.strip()
    resultados = []

    print(f"[FILE_MANAGER] Buscando arquivo: {nome_procurado}")
    _buscar_recursivo(PASTA_RAIZ_BUSCA, nome_procurado, resultados)

    if not resultados:
        # [ALTERADO] Antes: resposta fixa e robótica
        # Agora: resposta criativa via personality — sarcasmo sobre arquivo desaparecido
        if _personality:
            resposta = _personality.gerar_resposta(
                categoria="nao_encontrado",
                contexto={"tipo": "arquivo", "nome": nome_procurado}
            )
        else:
            resposta = f"Não encontrei arquivo com nome parecido com '{nome_procurado}', senhor."
        return resposta

    # Ordena por score (melhor match primeiro)
    resultados.sort(key=lambda x: x[1], reverse=True)
    caminho_melhor = resultados[0][0]

    # [ALTERADO] Resposta de sucesso — antes era genérica "Arquivo encontrado: ..."
    # Agora: personalizada via Groq, celebrando a "vitória" de achar o arquivo
    if _personality:
        resposta = _personality.gerar_resposta(
            categoria="sucesso",
            contexto={"acao": "localizar_arquivo", "nome": nome_procurado, "caminho": caminho_melhor}
        )
        # Adiciona o caminho no final (informação essencial não pode ser omitida)
        resposta += f" {caminho_melhor}"
    else:
        resposta = f"Arquivo encontrado: {caminho_melhor}"
    
    print(f"[FILE_MANAGER] {resposta}")
    return resposta


# -----------------------------------------------------------------------
# ABERTURA DE ARQUIVO
# -----------------------------------------------------------------------

def _detectar_app_abertura(caminho_arquivo: str) -> str | None:
    """
    Detecta qual aplicação usar para abrir o arquivo com base na extensão
    e na disponibilidade de binários no sistema.
    """
    _, extensao = os.path.splitext(caminho_arquivo)
    extensao = extensao.lower()

    app = APPS_PADRAO.get(extensao, "xdg-open")

    # Verifica se a app está disponível no sistema
    if app == "xdg-open":
        return app  # Sempre disponível em Linux com Freedesktop

    resultado = subprocess.run(["which", app], capture_output=True)
    if resultado.returncode == 0:
        return app

    # Fallback: usa xdg-open se a app específica não está disponível
    return "xdg-open"


def abrir_arquivo(nome_arquivo: str) -> str:
    """
    Localiza e abre um arquivo com a aplicação apropriada.
    Suporta .exe (via wine), documentos, imagens, vídeos, etc.

    Parâmetros:
        nome_arquivo — nome ou parte do nome do arquivo a abrir

    Retorna:
        String pronta para o JARVIS falar, confirmando abertura ou erro.
    """
    if not nome_arquivo or not nome_arquivo.strip():
        return "Qual arquivo você quer abrir, senhor?"

    nome_arquivo = nome_arquivo.strip()

    # Primeiro tenta buscar o arquivo
    resultado_busca = buscar_arquivo(nome_arquivo)

    # Se não encontrou (resposta via personality também vai ter "Não encontrei" ou similar)
    # Verifica se a busca falhou
    if "Não encontrei" in resultado_busca or "não encontr" in resultado_busca.lower():
        return resultado_busca

    # [ALTERADO] Agora buscar_arquivo retorna uma resposta criativa que pode ter
    # múltiplas frases. Precisamos extrair o caminho de um jeito mais robusto.
    # A última linha da resposta should contain "/caminho/arquivo"
    linhas = resultado_busca.split("\n")
    caminho = None
    for linha in linhas:
        if "/" in linha and os.path.exists(linha.strip()):
            caminho = linha.strip()
            break
    
    if not caminho:
        # Fallback: tenta procurar por "/" em qualquer parte
        import re
        match = re.search(r'/[^\s"\']*', resultado_busca)
        if match:
            caminho = match.group(0)
    
    if not caminho or not os.path.exists(caminho):
        # [ALTERADO] Resposta de erro mais criativa
        if _personality:
            resposta = _personality.gerar_resposta(
                categoria="erro",
                contexto={"acao": "abrir_arquivo", "problema": "caminho_inválido"}
            )
        else:
            resposta = "Não consegui extrair o caminho do arquivo, senhor."
        return resposta

    app = _detectar_app_abertura(caminho)

    try:
        print(f"[FILE_MANAGER] Abrindo com {app}: {caminho}")

        # Trata .exe e .sh de forma especial (via terminal/wine)
        _, extensao = os.path.splitext(caminho)
        if extensao.lower() == ".exe":
            # Abre .exe via wine no diretório do arquivo
            diretorio = os.path.dirname(caminho)
            nome_exe = os.path.basename(caminho)
            subprocess.Popen(["wine", nome_exe], cwd=diretorio, 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif extensao.lower() == ".sh":
            # Abre script bash via terminal
            subprocess.Popen(["bash", caminho], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif extensao.lower() == ".py":
            # Abre Python script em novo terminal
            subprocess.Popen(["python3", caminho], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Usa aplicação padrão para outros tipos
            subprocess.Popen([app, caminho], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # [ALTERADO] Resposta de sucesso — antes: genérica "Abrindo arquivo, senhor."
        # Agora: criativa via personality
        if _personality:
            resposta = _personality.gerar_resposta(
                categoria="sucesso",
                contexto={"acao": "abrir_arquivo", "tipo": extensao}
            )
        else:
            resposta = "Abrindo arquivo, senhor."
        
        return resposta

    except Exception as e:
        print(f"[FILE_MANAGER] Erro ao abrir: {e}")
        # [ALTERADO] Resposta de erro — antes: genérica
        # Agora: criativa via personality (sim, mesmo em caso de erro)
        if _personality:
            resposta = _personality.gerar_resposta(
                categoria="erro",
                contexto={"acao": "abrir_arquivo", "erro": str(type(e).__name__)}
            )
        else:
            resposta = f"Erro ao abrir arquivo: {e}, senhor."
        return resposta


# -----------------------------------------------------------------------
# LISTAGEM DE ARQUIVOS COM RESUMO VIA GROQ
# -----------------------------------------------------------------------

def _categorizar_arquivos(arquivos: list) -> dict:
    """
    Categoriza arquivos por tipo (documentos, imagens, vídeos, áudio, etc.).
    Retorna dict com formato: {"documentos": [...], "imagens": [...], ...}
    """
    categorias = {
        "documentos": [".pdf", ".txt", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".md"],
        "imagens": [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico"],
        "vídeos": [".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm"],
        "áudio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"],
        "compactados": [".zip", ".tar", ".gz", ".7z", ".rar", ".bz2"],
        "código": [".py", ".js", ".java", ".cpp", ".c", ".html", ".css", ".php", ".go", ".rs"],
        "outros": [],
    }

    arquivos_categorizados = {cat: [] for cat in categorias}

    for arquivo in arquivos:
        _, ext = os.path.splitext(arquivo)
        ext = ext.lower()
        
        encontrado = False
        for categoria, extensoes in categorias.items():
            if categoria != "outros" and ext in extensoes:
                arquivos_categorizados[categoria].append(arquivo)
                encontrado = True
                break
        
        if not encontrado:
            arquivos_categorizados["outros"].append(arquivo)

    return {k: v for k, v in arquivos_categorizados.items() if v}  # Remove categorias vazias


def _resumir_arquivos_com_groq(arquivos_por_categoria: dict, caminho_pasta: str) -> str:
    """
    Envia descrição dos arquivos pra Groq para gerar resumo conversado e breve.
    Retorna o resumo da IA ou fallback se não conseguir.
    """
    if not _GROQ_OK:
        # Fallback: simplesmente descreve as categorias sem IA
        total = sum(len(v) for v in arquivos_por_categoria.values())
        descricao = f"Encontrei {total} arquivos nessa pasta: "
        partes = [f"{len(v)} {cat}" for cat, v in arquivos_por_categoria.items()]
        return descricao + ", ".join(partes) + "."

    # Monta descrição textual dos arquivos para enviar à Groq
    descricao_arquivos = "Pasta: " + caminho_pasta + "\n\n"
    for categoria, arquivos in arquivos_por_categoria.items():
        descricao_arquivos += f"{categoria.upper()} ({len(arquivos)}): {', '.join(arquivos[:5])}"
        if len(arquivos) > 5:
            descricao_arquivos += f" ... e mais {len(arquivos) - 5}"
        descricao_arquivos += "\n"

    total_arquivos = sum(len(v) for v in arquivos_por_categoria.values())

    prompt = (
        f"O usuário tem essa pasta:\n\n{descricao_arquivos}\n\n"
        f"Total: {total_arquivos} arquivos.\n\n"
        f"Resuma o conteúdo dessa pasta de forma conversada e natural, como se estivesse "
        f"descrevendo para o usuário o que ele tem lá. Máximo 4 frases. Sem markdown. "
        f"Em português brasileiro. Mencione as categorias principais e a quantidade total."
    )

    try:
        cliente = Groq(api_key=GROQ_API_KEY)
        resposta = cliente.chat.completions.create(
            model=GROQ_MODELO,
            messages=[
                {
                    "role": "system",
                    "content": "Você é JARVIS. Resuma conteúdo de pastas de forma concisa e conversada."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=150,
        )
        return resposta.choices[0].message.content.strip()
    except Exception as e:
        print(f"[FILE_MANAGER] Erro ao chamar Groq: {e}")
        # Fallback: descrição manual
        partes = [f"{len(v)} {cat}" for cat, v in arquivos_por_categoria.items()]
        return f"Encontrei arquivos nessa pasta: {', '.join(partes)}."


def _salvar_lista_completa(arquivos: list, caminho_pasta: str) -> str | None:
    """
    Salva lista completa de arquivos num arquivo .txt na pasta do usuário.
    Retorna o caminho do arquivo ou None se falhar.
    """
    try:
        pasta_listas = os.path.join(os.path.expanduser("~"), ".jarvis_listas")
        os.makedirs(pasta_listas, exist_ok=True)

        timestamp = __import__('datetime').datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_pasta = os.path.basename(caminho_pasta.rstrip("/"))
        caminho_lista = os.path.join(pasta_listas, f"lista_{nome_pasta}_{timestamp}.txt")

        with open(caminho_lista, "w", encoding="utf-8") as f:
            f.write(f"Arquivos em: {caminho_pasta}\n")
            f.write(f"Total: {len(arquivos)}\n")
            f.write(f"Gerado em: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            for arquivo in sorted(arquivos):
                f.write(arquivo + "\n")

        return caminho_lista
    except Exception as e:
        print(f"[FILE_MANAGER] Erro ao salvar lista: {e}")
        return None


def listar_arquivos_pasta(nome_pasta: str) -> str:
    """
    Lista arquivos de uma pasta pelo nome (com fuzzy matching, igual a buscar_arquivo).
    Categoriza por tipo, resume via Groq de forma conversada, e oferece download
    da lista completa se houver muitos arquivos.

    Parâmetros:
        nome_pasta — nome ou parte do nome da pasta (ex: "documentos", "meus docs")

    Retorna:
        String pronta para o JARVIS falar.
    """
    if not nome_pasta or not nome_pasta.strip():
        return "Qual pasta você quer listar, senhor?"

    nome_pasta = nome_pasta.strip()

    # Tenta buscar a pasta (usa a mesma lógica de fuzzy matching de arquivos,
    # mas filtra só diretórios)
    print(f"[FILE_MANAGER] Procurando pasta: {nome_pasta}")

    resultados_pastas = []
    try:
        for entrada in os.walk(PASTA_RAIZ_BUSCA):
            caminho_dir = entrada[0]
            nome_dir_base = os.path.basename(caminho_dir)
            
            score = _score_similaridade(nome_pasta, nome_dir_base)
            if score >= SCORE_MINIMO:
                resultados_pastas.append((caminho_dir, score))
            
            if len(resultados_pastas) >= LIMITE_RESULTADOS:
                break
    except PermissionError:
        pass

    if not resultados_pastas:
        return f"Não encontrei pasta parecida com '{nome_pasta}', senhor."

    # Pega a pasta com melhor score
    resultados_pastas.sort(key=lambda x: x[1], reverse=True)
    caminho_pasta = resultados_pastas[0][0]

    # Lista arquivos dentro da pasta
    try:
        arquivos = []
        for entrada in os.listdir(caminho_pasta):
            caminho_completo = os.path.join(caminho_pasta, entrada)
            if os.path.isfile(caminho_completo):
                arquivos.append(entrada)

        if not arquivos:
            return f"A pasta '{os.path.basename(caminho_pasta)}' está vazia, senhor."

        # Categoriza
        arquivos_categorizados = _categorizar_arquivos(arquivos)

        # Resumo via Groq
        resumo = _resumir_arquivos_com_groq(arquivos_categorizados, caminho_pasta)

        # Se muitos arquivos, oferece salvar lista completa
        if len(arquivos) > 50:
            caminho_lista = _salvar_lista_completa(arquivos, caminho_pasta)
            if caminho_lista:
                resumo += f" Salvei a lista completa em {caminho_lista}, senhor."

        print(f"[FILE_MANAGER] Listagem de {len(arquivos)} arquivos em {caminho_pasta}")
        return resumo

    except Exception as e:
        print(f"[FILE_MANAGER] Erro ao listar pasta: {e}")
        return f"Erro ao listar a pasta: {e}, senhor."
