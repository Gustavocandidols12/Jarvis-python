# JARVIS em Python - Open Source

Um assistente virtual pessoal feito em Python, inspirado no JARVIS. Ele utiliza reconhecimento de voz contínuo, integração de LLM via Groq, reconhecimento facial e de gestos manuais via MediaPipe/OpenCV, e fornece uma interface de controle completa do computador através de comandos de voz e gestos.

Todo o código está comentado detalhadamente para facilitar a compreensão e contribuição de outros desenvolvedores. As credenciais confidenciais foram isoladas, e o sistema é flexível para usar seus próprios provedores de IA.

## Recursos Principais
- **Controle por voz**: Wake Word ("Jarvis") integrada e transcrição local contínua via Faster-Whisper.
- **Controle por gestos**: Modo mouse (controle da seta na tela com a mão, usando a câmera).
- **Integração com LLMs**: Utiliza Groq (Llama-3) para responder perguntas quase em tempo real (via streaming).
- **Síntese de voz rápida**: Integração ao Microsoft Azure TTS via pacote `edge-tts` emitindo fala natural.
- **Integração com o sistema operativo**: Capacidade de criar timers, consultar anotações, aumentar volume, e abrir o navegador em sistemas Linux.

## Arquitetura (Módulos)
- **`main.py`**: Ponto de entrada. Gerencia a captura de vídeo, processamento da mão (gestos visuais) e cordenação das threads principais.
- **`brain.py`**: Motor cognitivo. Interpreta intenções derivadas da voz e de gestos e transforma-as em funções (como tocar no YouTube, responder perguntas ou desligar o PC).
- **`listen.py`**: Módulo de audição. Processa captura do microfone utilizando STT local.
- **`voice.py`**: Módulo de fala. Converte texto gerado pelo Cérebro/LLM em fala humana rápida usando edge-tts e mpv.
- **`utilities.py`**: Utilitários. Consulta clima na internet, interage com a Groq API, opera timers e muito mais.
- **`config.py`**: Configuração central (onde ficam mapeadas variáveis de ambiente, cores e conjuntos de vocabulários).

---

## 🛠 Pré-requisitos e Instalação (Ex: Linux Mint XFCE)

Como cada ambiente é único, as instruções abaixo cobrem especificamente a configuração baseada em uma distribuição Ubuntu/Mint (como o **Linux Mint XFCE**).

### 1. Dependências do Sistema

Antes de tudo, garanta que você tem o Python 3 instalado e as ferramentas necessárias de sistema para trabalhar com aúdio e vídeo:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pyaudio pulse-audio mpv xdg-utils
```

### 2. Preparando o Ambiente (VENV)

É sempre recomendado criar um Ambiente Virtual de Python (venv) dentro da pasta do projeto para evitar conflito com as dependências do sistema:

```bash
# Entre na pasta onde você clonou este repositório
cd jarvis-python-refactor

# Crie o ambiente virtual
python3 -m venv venv

# Ative o ambiente virtual
source venv/bin/activate
```

### 3. Instalando as Bibliotecas Python

Com o `venv` ativado, instale os requerimentos do projeto:

```bash
pip install -r requirements.txt
```

*(O arquivo `requirements.txt` contém todos os pacotes chave como `opencv-python`, `mediapipe`, `faster-whisper`, `groq`, `pvporcupine`, entre outros).*

### 4. Configuração das Chaves de API

O JARVIS depende de dois serviços externos gratuitos para poder funcionar em potência total. Você deverá criar suas próprias contas para obter suas Chaves de API:

1. **Groq (Respostas do Jarvis)** - Pegue a chave no [Groq Console](https://console.groq.com)
2. **Picovoice / Porcupine (Palavra de Despertar)** - Pegue em [Picovoice Console](https://console.picovoice.ai/)

**Como adicionar suas chaves no projeto:**
Este projeto acompanha um arquivo de exemplo `.env.example`. Você deve renomeá-lo ou copiar para `.env` e adicionar suas chaves ali. O `config.py` puxará as variáveis automaticamente usando a lib `python-dotenv`:

```bash
cp .env.example .env
```
Edite o arquivo `.env`:
```env
GROQ_API_KEY="sua_chave_groq_aqui"
PORCUPINE_ACCESS_KEY="sua_chave_picovoice_aqui"
GEMINI_API_KEY="sua_chave_gemini_aqui_opcional"
```

### 5. Execução Fácil usando Alias no `.bashrc`

Para não ter que entrar nas pastas e usar os comandos toda hora, você pode criar um **alias** (um atalho no seu terminal) e abrir o JARVIS de qualquer lugar do terminal apenas digitando a palavra `jarvis`:

```bash
# Abra seu bashrc em um editor de texto (pode ser nano, vim ou mousepad)
nano ~/.bashrc

# Adicione a seguinte linha no final do arquivo (substitua o caminho_da_pasta pelo caminho real onde clonou o seu JARVIS)
alias jarvis='cd /caminho_da_pasta_do_seu_jarvis && source venv/bin/activate && python3 main.py'

# Salve o arquivo (Ctrl+O, Enter, Ctrl+X no Nano) e atualize as variáveis
source ~/.bashrc
```

---

## 🚀 Como Usar

Agora que configurou o alias, simplesmente abra de qualquer terminal:
```bash
jarvis
```
Se preferir a forma manual:
```bash
cd /caminho_da_pasta_do_projeto
source venv/bin/activate
python3 main.py
```

O programa iniciará a câmera e ativará os serviços.
Diga: **"Jarvis"**
Você ouvirá um Bip `(Beep)`. Em seguida, dê o seu comando:

> *"Jarvis, qual a previsão do tempo para hoje?"*
> *"Jarvis, que horas são?"*
> *"Jarvis, abra o youtube."*
> *"Jarvis, crie um timer de 15 minutos para tirar o bolo do forno."*

Se os retornos das APIs falharem, acesse o terminal onde rodou o jarvis e visualize os **logs** textuais.

Caso necessite aprender gestos detalhados ou incluir respostas específicas, dê uma olhada no **`config.py`** e nas intenções mapeadas detalhadamente dentro do **`listen.py`**.
