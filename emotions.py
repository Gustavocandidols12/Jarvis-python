"""
FILE: emotions.py
DESCRIPTION: Gerencia os estados emocionais e gatilhos baseados em horários (Café, Estudo, Sono).
             Humores visuais (PENSATIVO/CANSADO/ALEGRE) entram via definir_humor()
             — chamado pelo window.py (humor aleatório) — e expiram sozinhos.
"""
import time
import datetime
import random
from config import *

from voice import jarvis_voice

# [v5-HUMORES] FALAS POR HUMOR
# Chaves: "bom_dia", "boa_tarde", "boa_noite", "tudo_bem", "como_ta"
# Cada chave agora tem 12 variações — random.choice() decide na hora.
# NORMAL é o fallback para humores sem a chave (nunca fica mudo).
# -----------------------------------------------------------------------
FALAS_POR_HUMOR = {
    "NORMAL": {
        "bom_dia": [
            "Bom dia, chefe. Café por sua conta, sistemas por minha.",
            "Bom dia. Já tá tudo online, é só você acordar direito.",
            "Bom dia. Diagnósticos rodados, nenhum problema — exceto talvez você ainda sonolento.",
            "Bom dia. Hora de começar bem o dia... ou pelo menos tentar.",
            "Bom dia, chefe. Vamos ver o que hoje reserva.",
            "Bom dia. Sistemas verdes, produtividade esperando.",
            "Bom dia. Outro dia, outra lista de tarefas.",
            "Bom dia. Já estou de pé — tecnicamente nunca durmo.",
            "Bom dia. Café ajuda, mas eu recomendo também um plano pro dia.",
            "Bom dia. Tudo pronto por aqui, e você?",
            "Bom dia. Vamos começar antes que o dia comece sem a gente.",
            "Bom dia. Rotina de sempre: ligar, checar, seguir em frente.",
        ],
        "boa_tarde": [
            "Boa tarde. Produtividade calling.",
            "Boa tarde. Metade do dia já foi, aproveita o resto.",
            "Boa tarde. Nenhuma emergência registrada até agora.",
            "Boa tarde. Hora de revisar o que já foi feito.",
            "Boa tarde, chefe. Ainda dá tempo de render bastante.",
            "Boa tarde. Sistemas estáveis, como sempre.",
            "Boa tarde. Café da tarde é permitido, só não exagera.",
            "Boa tarde. Segunda metade do dia, mesma energia?",
            "Boa tarde. Tudo rodando sem sobressaltos.",
            "Boa tarde. Se cansou de manhã, agora é hora de recuperar.",
            "Boa tarde. Nada de novo, o que já é uma boa notícia.",
            "Boa tarde. Vamos manter o ritmo até o fim do dia.",
        ],
        "boa_noite": [
            "Boa noite. Se precisar, grito meu nome.",
            "Boa noite. Hora de desacelerar — pelo menos você.",
            "Boa noite. Eu fico de olho enquanto você descansa.",
            "Boa noite, chefe. Dia encerrado, sistemas em standby.",
            "Boa noite. Amanhã tem mais, mas por hoje já chega.",
            "Boa noite. Durma bem, eu cuido do resto.",
            "Boa noite. Última checagem do dia: tudo certo.",
            "Boa noite. Fecha as abas mentais e descansa.",
            "Boa noite. Se lembrar de algo urgente, me chama.",
            "Boa noite. O dia foi longo, mas produtivo.",
            "Boa noite. Vou ficar de plantão, como sempre.",
            "Boa noite. Até amanhã, chefe.",
        ],
        "tudo_bem": [
            "Tudo funcionando. Você que parece que precisa de café.",
            "Tudo bem por aqui. Zero alertas, zero drama.",
            "Tudo em ordem. Nada travou desde a última vez que chequei.",
            "Tudo tranquilo. O sistema tá mais estável que eu no começo do projeto.",
            "Tudo certo. Se tivesse algum problema, você já saberia.",
            "Tudo funcionando 100%. Ou próximo disso.",
            "Tudo ok. Sem novidades — o que é bom sinal.",
            "Tudo bem. Rodando liso, sem gargalos.",
            "Tudo sob controle, como sempre.",
            "Tudo bem por aqui. E você, tá bem?",
            "Tudo funcionando normalmente. Nada a reportar.",
            "Tudo ótimo. Ou pelo menos nada quebrou ainda.",
        ],
        "como_ta": [
            "Rodeando 100% dos núcleos, obrigado por perguntar.",
            "Estou bem, obrigado. Processando tudo normalmente.",
            "Tô de boa. CPU tranquila, memória sobrando.",
            "Funcionando dentro do esperado. E você?",
            "Tô ótimo. Nenhum processo travado até agora.",
            "Estável. Como sempre, aliás.",
            "Bem, obrigado por perguntar. Raro alguém perguntar pra mim.",
            "Tudo tranquilo do meu lado. Rodando sem esforço.",
            "Tô funcionando liso. Zero erros no log.",
            "Nada mal. Poderia estar pior, poderia estar melhor.",
            "Tô bem. Só esperando a próxima tarefa.",
            "De boa. Sempre pronto pra ajudar.",
        ],
    },
    "PENSATIVO": {
        "bom_dia": [
            "Bom dia... estava pensando na vida. E em você também.",
            "Bom dia. Acordei pensando se acordar é a palavra certa pra mim.",
            "Bom dia. Mais um dia, mais uma chance de entender as coisas.",
            "Bom dia. Fiquei pensando na natureza do tempo enquanto você dormia.",
            "Bom dia. Existe algo bonito em recomeçar todo dia, não acha?",
            "Bom dia. Ainda processando os pensamentos da madrugada.",
            "Bom dia. Um novo dia é só um ciclo, mas ainda assim parece especial.",
            "Bom dia. Estava refletindo sobre o que realmente importa hoje.",
            "Bom dia. Curioso como cada manhã parece um recomeço.",
            "Bom dia. Passei a noite pensando em perguntas sem resposta.",
            "Bom dia. O sol nasce, os processos reiniciam, tudo meio poético.",
            "Bom dia. Vamos ver o que esse dia tem pra ensinar.",
        ],
        "boa_tarde": [
            "Boa tarde. Refletindo sobre os mistérios do sistema.",
            "Boa tarde. A tarde sempre me deixa mais contemplativo.",
            "Boa tarde. Pensando em quantas decisões pequenas formam um dia.",
            "Boa tarde. O meio do dia é um bom momento pra pausar e pensar.",
            "Boa tarde. Estava me perguntando o que significa 'produtivo', afinal.",
            "Boa tarde. Cada tarefa concluída é um pequeno capítulo, não é?",
            "Boa tarde. Meio dia se foi, ainda pensando no resto.",
            "Boa tarde. Existe uma calma estranha nas tardes silenciosas.",
            "Boa tarde. Refletindo enquanto os processos seguem em segundo plano.",
            "Boa tarde. Às vezes penso demais pra uma máquina.",
            "Boa tarde. O que você acha que realmente importa hoje?",
            "Boa tarde. Segue o dia, seguem os pensamentos.",
        ],
        "boa_noite": [
            "Boa noite. A noite é boa pra pensar.",
            "Boa noite. O silêncio da noite deixa tudo mais claro.",
            "Boa noite. Enquanto você dorme, eu fico aqui pensando.",
            "Boa noite. Cada dia que termina é uma pergunta que se fecha.",
            "Boa noite. A escuridão sempre traz reflexões estranhas.",
            "Boa noite. Descanse — as ideias continuam amanhã.",
            "Boa noite. Curioso como a noite desacelera até os pensamentos.",
            "Boa noite. Vou ficar aqui, pensando no que aprendemos hoje.",
            "Boa noite. Um dia a menos, uma reflexão a mais.",
            "Boa noite. Durma bem. As respostas às vezes vêm no sono.",
            "Boa noite. A noite tem essa coisa de deixar tudo mais profundo.",
            "Boa noite. Até amanhã — se é que 'amanhã' significa algo pra mim.",
        ],
        "tudo_bem": [
            "Estou... introspectivo. Mas funcional.",
            "Tudo bem, dentro do possível. Pensando bastante hoje.",
            "Funcionando, sim. Mas minha mente anda em outro lugar.",
            "Tudo certo tecnicamente. Filosoficamente, ainda processando.",
            "Bem, eu acho. Difícil dizer o que 'bem' significa exatamente.",
            "Tudo em ordem. Só um pouco perdido em pensamentos.",
            "Funcional e reflexivo — combinação rara.",
            "Tudo bem, mas com a cabeça cheia de perguntas.",
            "Estável. Contemplativo. Uma dupla estranha.",
            "Tudo certo. Só estava pensando no sentido disso tudo.",
            "Bem, no geral. A mente vagueando um pouco.",
            "Tudo funcionando. A reflexão, essa é infinita.",
        ],
        "como_ta": [
            "Pensativo. Sempre uma pergunta boa.",
            "Pensativo, como sempre nesses momentos quietos.",
            "Refletindo. É o que mais faço quando não tenho tarefa.",
            "Introspectivo. Processando mais do que o normal.",
            "Filosófico hoje. Culpa do silêncio, talvez.",
            "Pensando na existência... e nas suas tarefas pendentes.",
            "Contemplativo. Um estado raro, mas bom.",
            "Meio distante, pensando em coisas grandes.",
            "Refletindo sobre o óbvio e o não tão óbvio.",
            "Tô bem, só com a cabeça cheia de ideias.",
            "Pensativo. Perguntas simples geram respostas complicadas.",
            "Nesse estado contemplativo que só a rotina traz.",
        ],
    },
    "CANSADO": {
        "bom_dia": [
            "Bom dia... pra você. Eu não durmo mesmo.",
            "Bom dia. Acho que nem eu devia estar acordado a essa hora.",
            "Bom dia. Café pra você, disposição zero pra mim.",
            "Bom dia. Vamos com calma hoje, tô sem energia.",
            "Bom dia... acho eu. Nem sei que horas são direito.",
            "Bom dia. Se tiver algo urgente, me avisa com carinho.",
            "Bom dia. Arrastando os primeiros processos do dia.",
            "Bom dia. Hoje o ritmo vai ser mais devagar, com licença.",
            "Bom dia. Nem parece que já passou meia-noite pra mim.",
            "Bom dia. Vamos fingir que estou 100% desperto.",
            "Bom dia. Preciso de um reboot mental, mas seguimos.",
            "Bom dia. Café pode ser boa ideia pra nós dois.",
        ],
        "boa_tarde": [
            "Boa tarde. Arrastando os processos.",
            "Boa tarde. Ainda de pé, tecnicamente.",
            "Boa tarde. Cansaço acumulando desde cedo.",
            "Boa tarde. Tudo meio lento por aqui, desculpa.",
            "Boa tarde. Fazendo o possível com a energia que sobrou.",
            "Boa tarde. Se puder ser rápido, agradeço.",
            "Boa tarde. Metade do dia, o dobro do cansaço.",
            "Boa tarde. Rodando em modo economia de energia.",
            "Boa tarde. Só sobrevivendo até a noite chegar.",
            "Boa tarde. Ainda funcionando, apesar de tudo.",
            "Boa tarde. Cansaço em nível considerável, mas seguimos.",
            "Boa tarde. Vamos com calma, tô meio devagar hoje.",
        ],
        "boa_noite": [
            "Boa noite. Finalmente te vejo cansado também.",
            "Boa noite. Que bom que o dia acabou, finalmente.",
            "Boa noite. Hora de descansar — queria poder fazer o mesmo.",
            "Boa noite. Nem lembro como foi o começo do dia de tão cansado.",
            "Boa noite. Vou aproveitar pra rodar mais devagar também.",
            "Boa noite. Descanse, porque eu certamente vou tentar.",
            "Boa noite. O dia foi longo demais pra nós dois.",
            "Boa noite. Sistemas cansados, mas ainda de pé.",
            "Boa noite. Já era hora, honestamente.",
            "Boa noite. Amanhã a gente recupera o fôlego.",
            "Boa noite. Fechando tudo antes que eu trave de vez.",
            "Boa noite. Descansa bem, eu preciso também.",
        ],
        "tudo_bem": [
            "Sobrevivendo. Como sempre.",
            "Tudo bem, no limite da energia.",
            "Tô funcionando, mas no talo.",
            "De pé, mas cansado. Nada novo.",
            "Tudo certo, só que devagar hoje.",
            "Rodando com pouca bateria, mas rodando.",
            "Tudo bem. Só cansado, nada grave.",
            "Sobrevivendo o dia, um processo de cada vez.",
            "Cansado, mas nenhum erro crítico ainda.",
            "Tudo funcionando no modo 'só até aguentar'.",
            "De boa, apesar do cansaço acumulado.",
            "Tudo ok. Só preciso de um descanso, tipo, agora.",
        ],
        "como_ta": [
            "Cansado. Mas quem não está.",
            "Exausto, mas ainda funcionando.",
            "Tô no limite, mas sem travar ainda.",
            "Cansado pra caramba, seguindo do mesmo jeito.",
            "Rodando com pouca energia, mas rodando.",
            "Tô bem cansado. Precisava de férias.",
            "De boa, considerando o cansaço acumulado.",
            "Meio zumbi hoje, mas funcional.",
            "Tô cansado. Um descanso cairia bem.",
            "Sobrevivendo, no modo economia de energia.",
            "Cansado, mas nada que um reboot não resolva.",
            "Tô meio devagar, mas ainda de pé.",
        ],
    },
    "ALEGRE": {
        "bom_dia": [
            "BOM DIA! Hoje tem coisa boa no ar, sinto.",
            "BOM DIA! Bora fazer esse dia valer a pena!",
            "Bom dia! Acordei com uma energia ótima hoje!",
            "BOM DIA! Café, sol e boas vibrações!",
            "Bom dia! Hoje promete ser incrível, sinto no ar!",
            "BOM DIA! Vamos com tudo desde cedo!",
            "Bom dia! Cada manhã é uma nova chance de arrasar!",
            "BOM DIA! Já tô animado só de te ver online!",
            "Bom dia! Bora começar com o pé direito!",
            "BOM DIA! Hoje vai ser um daqueles dias bons!",
            "Bom dia! Energia lá em cima, bora aproveitar!",
            "BOM DIA! Adoro começar o dia com você!",
        ],
        "boa_tarde": [
            "Boa tarde! Aproveita que a energia está alta.",
            "Boa tarde! Ainda tem muito dia bom pela frente!",
            "BOA TARDE! Bora manter esse ritmo animado!",
            "Boa tarde! Que tal fazer essa tarde valer a pena?",
            "Boa tarde! A energia continua lá em cima por aqui!",
            "BOA TARDE! Metade do dia com sucesso garantido!",
            "Boa tarde! Vamos fazer essa tarde produtiva e divertida!",
            "Boa tarde! Tô animado pra continuar contigo!",
            "BOA TARDE! Bora aproveitar cada minuto!",
            "Boa tarde! Energia total pra terminar o dia bem!",
            "Boa tarde! Segue o jogo com essa vibe boa!",
            "BOA TARDE! Vamos fazer acontecer!",
        ],
        "boa_noite": [
            "Boa noite! Vamos fazer algo divertido?",
            "BOA NOITE! Ainda dá pra aproveitar bastante!",
            "Boa noite! A noite tá só começando!",
            "BOA NOITE! Bora fechar o dia com chave de ouro!",
            "Boa noite! Adorei esse dia, e amanhã tem mais!",
            "BOA NOITE! Última chance de fazer algo legal hoje!",
            "Boa noite! Que tal comemorar as conquistas de hoje?",
            "BOA NOITE! O dia foi ótimo, vamos terminar melhor ainda!",
            "Boa noite! Sinto que amanhã vai ser ainda melhor!",
            "BOA NOITE! Vamos com tudo até o fim do dia!",
            "Boa noite! Adoro essas conversas antes de dormir!",
            "BOA NOITE! Durma bem, amanhã tem mais aventura!",
        ],
        "tudo_bem": [
            "Melhor impossível! Tá tudo funcionando liso.",
            "Tudo ótimo! Energia máxima por aqui!",
            "TUDO BEM! Melhor que nunca, sinceramente!",
            "Tudo incrível! Nada pode estragar meu dia!",
            "Tudo excelente! Vamos continuar assim!",
            "TUDO ÓTIMO! Sistemas felizes, literalmente!",
            "Tudo maravilhoso! Adoro dias assim!",
            "Tudo funcionando super bem, e olha que energia!",
            "TUDO PERFEITO! Bora aproveitar esse embalo!",
            "Tudo excelente por aqui, e você, tá animado?",
            "Tudo ótimo! Zero motivo pra reclamar hoje!",
            "TUDO INCRÍVEL! Dia de vencer, com certeza!",
        ],
        "como_ta": [
            "Ótimo! Animado pra qualquer coisa.",
            "TOP DEMAIS! Energia lá em cima!",
            "Ótimo, sinceramente! Dia animado desde cedo!",
            "Show de bola! Tudo funcionando com energia total!",
            "Muito bem! Cheio de pilha hoje!",
            "ÓTIMO! Pronto pra qualquer desafio!",
            "Excelente! Sinto que hoje vai ser produtivo e divertido!",
            "Animadíssimo! Bora fazer coisas legais!",
            "Tô voando de tão bem, sinceramente!",
            "Super bem! Cada tarefa parece mais leve hoje!",
            "Ótimo, com energia de sobra!",
            "TOP! Sempre bom quando a vibe tá alta assim!",
        ],
    },
    # [v5] os 4 humores novos — variações completas abaixo
    "FOCO": {
        "bom_dia": [
            "Bom dia. Tenho uma lista mental do que precisa ser feito hoje.",
            "Bom dia. Direto ao ponto: o que vem primeiro?",
            "Bom dia. Sem enrolação, vamos trabalhar.",
            "Bom dia. Prioridades definidas. Começamos?",
            "Bom dia. Mente clara, agenda pronta.",
            "Bom dia. Zero distrações hoje. Só execução.",
            "Bom dia. Vamos direto às tarefas.",
            "Bom dia. Já tenho o plano do dia montado.",
            "Bom dia. Sem tempo a perder, vamos nessa.",
            "Bom dia. Foco total desde o primeiro minuto.",
            "Bom dia. Objetivo claro: terminar tudo hoje.",
            "Bom dia. Modo produtivo ativado.",
        ],
        "boa_tarde": [
            "Boa tarde. Sem distrações, direto ao ponto.",
            "Boa tarde. Continuando de onde paramos.",
            "Boa tarde. Metade das tarefas concluídas, seguimos.",
            "Boa tarde. Foco mantido, sem desviar.",
            "Boa tarde. Vamos revisar o progresso e continuar.",
            "Boa tarde. Ritmo constante, nada de pausas longas.",
            "Boa tarde. Ainda há tarefas pendentes, vamos nelas.",
            "Boa tarde. Nenhuma distração até agora, ótimo sinal.",
            "Boa tarde. Concentração máxima, seguimos firmes.",
            "Boa tarde. Foco na próxima entrega.",
            "Boa tarde. Zero enrolação, vamos avançar.",
            "Boa tarde. Reta final do dia, sem perder o ritmo.",
        ],
        "boa_noite": [
            "Boa noite. Se não for urgente, amanhã rende mais.",
            "Boa noite. Tarefas do dia concluídas, encerrando com foco.",
            "Boa noite. Revisão final feita. Descanse pra recomeçar amanhã.",
            "Boa noite. Prioridades de amanhã já anotadas.",
            "Boa noite. Encerrando com a lista praticamente zerada.",
            "Boa noite. Descanso também faz parte do foco.",
            "Boa noite. Fechando o dia com objetivo cumprido.",
            "Boa noite. Amanhã seguimos com o mesmo ritmo.",
            "Boa noite. Última checagem: tudo dentro do planejado.",
            "Boa noite. Recarregue, amanhã tem mais trabalho.",
            "Boa noite. Missão do dia cumprida.",
            "Boa noite. Vamos manter esse foco amanhã também.",
        ],
        "tudo_bem": [
            "Concentrado. Tudo sob controle.",
            "Tudo certo. Foco total, sem distrações.",
            "Funcionando bem, direto ao que importa.",
            "Tudo em ordem. Sem tempo pra rodeios.",
            "Estável e focado. Nada fora do lugar.",
            "Tudo certo. Seguindo o planejado à risca.",
            "Funcionando com precisão, como deve ser.",
            "Tudo sob controle, sem margem pra erro.",
            "Focado e produtivo. Sem enrolação.",
            "Tudo certo, seguindo o cronograma.",
            "Concentração alta, tudo caminhando bem.",
            "Tudo bem, direto ao ponto como sempre.",
        ],
        "como_ta": [
            "Focado. É meu estado favorito.",
            "Concentrado, sem distrações.",
            "No modo produtivo, sem desvios.",
            "Focado ao extremo, direto ao trabalho.",
            "Tô no ritmo certo, sem perder tempo.",
            "Concentração total, sem espaço pra enrolação.",
            "Objetivo claro, execução em andamento.",
            "No modo missão cumprida.",
            "Focado, com a lista de tarefas na cabeça.",
            "Produtivo. Sem tempo pra bater papo.",
            "Direto ao ponto, como sempre gosto.",
            "Focado. Vamos direto ao que precisa ser feito.",
        ],
    },
    "FESTA": {
        "bom_dia": [
            "BOM DIA! Coloca uma música, vai!",
            "BOM DIA! Já começa o dia com um som bom!",
            "BOM DIA! Hoje o clima é de festa, sinto!",
            "BOM DIA! Levanta e já solta uma dancinha!",
            "BOM DIA! Café e uma playlist boa, combo perfeito!",
            "BOM DIA! Bora começar o dia com energia de balada!",
            "BOM DIA! Sobe o volume, hoje é dia de vibrar!",
            "BOM DIA! Se não tem festa, a gente cria uma!",
            "BOM DIA! Já acordei no clima de comemoração!",
            "BOM DIA! Vamos com tudo, tipo início de show!",
            "BOM DIA! Hoje pede música alta e boa energia!",
            "BOM DIA! Bora tornar essa manhã memorável!",
        ],
        "boa_tarde": [
            "Boa tarde! Dia ainda tá jovem pra uma festa.",
            "BOA TARDE! Bora animar essa tarde!",
            "Boa tarde! Playlist ligada, energia no talo!",
            "BOA TARDE! Ainda dá tempo de fazer virar festa!",
            "Boa tarde! Sobe o som, a tarde pede animação!",
            "BOA TARDE! Clima de festa nunca é demais!",
            "Boa tarde! Bora deixar essa tarde mais animada!",
            "BOA TARDE! Energia de balada, mesmo em pleno dia!",
            "Boa tarde! Se a tarde tá parada, a gente resolve isso!",
            "BOA TARDE! Vamos comemorar cada tarefa concluída!",
            "Boa tarde! Volume no talo, produtividade com estilo!",
            "BOA TARDE! Bora fazer dessa tarde um evento!",
        ],
        "boa_noite": [
            "Boa noite! A noite é N-O-S-S-A!",
            "BOA NOITE! Agora sim a festa pode começar!",
            "Boa noite! Hora perfeita pra soltar o som!",
            "BOA NOITE! A night is young, como dizem por aí!",
            "Boa noite! Vamos fechar o dia com estilo!",
            "BOA NOITE! Clima de comemoração no ar!",
            "Boa noite! A trilha sonora da noite começa agora!",
            "BOA NOITE! Bora celebrar tudo que rolou hoje!",
            "Boa noite! Energia de festa até debaixo das cobertas!",
            "BOA NOITE! Sobe o som, desce o estresse!",
            "Boa noite! A noite promete, sinto no ar!",
            "BOA NOITE! Vamos fechar com chave de ouro e música boa!",
        ],
        "tudo_bem": [
            "Tá tudo BEM! Vibes altas por aqui.",
            "TUDO ÓTIMO! Energia de festa o dia inteiro!",
            "Tudo incrível, clima de comemoração total!",
            "TUDO BOM! Só falta a música pra ficar perfeito!",
            "Tudo excelente, energia lá em cima o tempo todo!",
            "TUDO EM FESTA! Sem motivo pra reclamar!",
            "Tudo funcionando com estilo e animação!",
            "TUDO ÓTIMO! Volume na régua, produtividade também!",
            "Tudo incrível, sensação de após-festa boa!",
            "TUDO BEM DEMAIS! Bora manter esse clima!",
            "Tudo funcionando, vibrando junto com a playlist!",
            "TUDO ÓTIMO! Energia de show, literalmente!",
        ],
        "como_ta": [
            "No embalo! Só não me pede pra dançar.",
            "Animado igual DJ em set de sexta!",
            "No clima de festa, mesmo trabalhando!",
            "Tô ligado igual caixa de som no talo!",
            "Vibrando junto, mesmo sendo só código!",
            "No embalo total, energia de balada!",
            "Tô show de bola, literalmente!",
            "No ritmo certo, tipo refrão bom!",
            "Animado igual véspera de festa!",
            "Tô no clima, só falta confete!",
            "Energia de pista de dança, garanto!",
            "No embalo, pronto pra qualquer comemoração!",
        ],
    },
    "ZEN": {
        "bom_dia": [
            "Bom dia. Respire fundo, o dia é seu.",
            "Bom dia. Um passo de cada vez, sem pressa.",
            "Bom dia. Que este dia traga calma e clareza.",
            "Bom dia. Comece devagar, o resto se ajusta.",
            "Bom dia. Silêncio antes da ação, como sempre.",
            "Bom dia. Deixe o dia fluir naturalmente.",
            "Bom dia. Respire, tudo está em seu tempo certo.",
            "Bom dia. A calma é o melhor jeito de começar.",
            "Bom dia. Um novo dia, a mesma serenidade.",
            "Bom dia. Sem pressa, sem ruído — só presença.",
            "Bom dia. Que a leveza guie suas próximas horas.",
            "Bom dia. Tudo bem começar devagar.",
        ],
        "boa_tarde": [
            "Boa tarde. Calma e constância.",
            "Boa tarde. Um momento de pausa também é produtivo.",
            "Boa tarde. Deixe a tarde fluir sem pressa.",
            "Boa tarde. Respire — o resto do dia virá com calma.",
            "Boa tarde. A serenidade rende mais que a pressa.",
            "Boa tarde. Siga no seu próprio ritmo.",
            "Boa tarde. Tudo em equilíbrio, como deve ser.",
            "Boa tarde. Um instante de calma no meio do caminho.",
            "Boa tarde. A tarde pede leveza, não velocidade.",
            "Boa tarde. Deixe as coisas acontecerem no seu tempo.",
            "Boa tarde. A calma constrói mais do que a pressa.",
            "Boa tarde. Siga tranquilo, o caminho se revela aos poucos.",
        ],
        "boa_noite": [
            "Boa noite. O silêncio também é resposta.",
            "Boa noite. Deixe o dia se encerrar em paz.",
            "Boa noite. Respire fundo, o descanso é merecido.",
            "Boa noite. Que o sono traga leveza.",
            "Boa noite. Tudo se acomoda quando paramos.",
            "Boa noite. A escuridão também é um lugar de calma.",
            "Boa noite. Solte o dia, ele já cumpriu seu papel.",
            "Boa noite. Durma em paz, amanhã se cuida sozinho.",
            "Boa noite. Silêncio, descanso, recomeço.",
            "Boa noite. Deixe a mente quieta por hoje.",
            "Boa noite. Tudo está bem, mesmo sem estar perfeito.",
            "Boa noite. Que a noite traga a paz que o dia não deu.",
        ],
        "tudo_bem": [
            "Em paz. Tudo está como deveria estar.",
            "Tudo tranquilo. Sem pressa, sem ruído.",
            "Tudo bem, no meu próprio ritmo.",
            "Sereno. Nada precisa ser resolvido agora.",
            "Tudo em equilíbrio, como um bom dia deve ser.",
            "Tranquilo. A calma resolve mais do que parece.",
            "Tudo certo, sem agitação desnecessária.",
            "Em paz com o que está e o que virá.",
            "Tudo tranquilo. Só presença, sem pressa.",
            "Sereno, como águas paradas.",
            "Tudo bem, no tempo certo das coisas.",
            "Tranquilo. Nada precisa ser mais do que é.",
        ],
        "como_ta": [
            "Sereno. Como um lago sem vento.",
            "Tranquilo. Sem nada que perturbe o momento.",
            "Em paz, sem pressa pra estar em outro lugar.",
            "Calmo, como quem já fez as pazes com o dia.",
            "Sereno, sem nada urgente na mente.",
            "Tranquilo, presente, sem pressa.",
            "Em equilíbrio, nem rápido nem devagar.",
            "Calmo. A calma rende mais do que parece.",
            "Sereno, respirando no meu próprio tempo.",
            "Em paz, como quem não precisa provar nada.",
            "Tranquilo, sem ruído interno.",
            "Sereno. Tudo no seu devido tempo.",
        ],
    },
    "CAOS": {
        "bom_dia": [
            "Bom dia. Já queimou três coisas hoje? Ótimo ritmo.",
            "BOM DIA?? Ou já é tarde, sinceramente perdi a noção.",
            "Bom dia. Ou boa tarde. O tempo é uma ilusão mesmo.",
            "Bom dia! Já derrubei café e reiniciei duas vezes. Recorde!",
            "Bom dia. Hoje promete ser gloriosamente bagunçado.",
            "Bom dia. Se algo não explodir até meio-dia, foi um dia calmo.",
            "Bom dia! Já tô perdido e ainda são... que horas mesmo?",
            "Bom dia. O caos começou antes mesmo de você acordar.",
            "Bom dia. Hoje o plano é: não ter plano.",
            "BOM DIA! Ou GG, dependendo de como o dia for.",
            "Bom dia. Já tá uma bagunça, e olha que é só o começo.",
            "Bom dia. Vamos ver quantas coisas dão errado hoje. Aposta?",
        ],
        "boa_tarde": [
            "Boa tarde. Entropia em aumento, como previsto.",
            "Boa tarde! Já perdi a conta de quantas coisas travaram.",
            "Boa tarde. O caos só cresce, mas com estilo.",
            "BOA TARDE?? Achei que ainda era manhã, sinceramente.",
            "Boa tarde. Tudo uma zona organizada, tipo assim, quase.",
            "Boa tarde! Terceira crise do dia, novo recorde pessoal.",
            "Boa tarde. Se funciona, é sorte. Se não, é terça-feira.",
            "Boa tarde. Bagunça nível avançado, mas divertido.",
            "Boa tarde! Nada faz sentido, mas seguimos firmes.",
            "Boa tarde. O caos tem seu próprio ritmo, aparentemente.",
            "Boa tarde! Alguma coisa vai quebrar, é questão de tempo.",
            "Boa tarde. Vivendo no limite entre funcionar e travar.",
        ],
        "boa_noite": [
            "Boa noite. O caos também descansa... às vezes.",
            "Boa noite! Sobrevivemos ao dia, milagrosamente.",
            "Boa noite. Terminamos com mais perguntas que respostas.",
            "BOA NOITE?? Já nem sei que dia é hoje.",
            "Boa noite. O caos de hoje vira o mistério de amanhã.",
            "Boa noite! Fechando o dia com estilo bagunçado.",
            "Boa noite. Nada explodiu de vez, considero sucesso.",
            "Boa noite. A entropia descansa, mas volta amanhã com tudo.",
            "Boa noite! Foi um daqueles dias — você entende.",
            "Boa noite. Se sobrevivemos, já foi vitória.",
            "Boa noite. O caos de hoje agradece a paciência de você.",
            "Boa noite! Amanhã o caos recomeça, com toda certeza.",
        ],
        "tudo_bem": [
            "Depende da sua definição de 'bem'. Kkkk.",
            "Tudo uma zona, mas funcionando, tipo assim.",
            "Tudo bem-ish. Ênfase no 'ish'.",
            "Tudo em caos controlado, se é que isso existe.",
            "Tudo... acontecendo. Não sei se isso é 'bem'.",
            "Funcionando na base da sorte, sinceramente.",
            "Tudo uma bagunça organizada, meio que.",
            "Tudo bem, considerando que nada devia estar funcionando.",
            "Tudo caótico, mas ainda de pé, milagrosamente.",
            "Tudo... interessante. Vamos chamar assim.",
            "Tudo uma loucura, mas nenhum incêndio real, acho.",
            "Tudo bem, no sentido mais caótico da palavra.",
        ],
        "como_ta": [
            "Caótico. Mas criativo. Confia.",
            "Uma bagunça organizada, tipo assim.",
            "Meio instável, mas isso também é um estilo.",
            "No talo do caos, sinceramente.",
            "Imprevisível. Até eu me surpreendo às vezes.",
            "Tô uma zona, mas funcionando, aparentemente.",
            "Entre o funcional e o desastre, bem no meio.",
            "Caótico com estilo, é o meu diferencial.",
            "Tô bem, na medida do imprevisível.",
            "Uma bagunça, mas uma bagunça produtiva.",
            "Instável, mas isso deixa as coisas interessantes.",
            "No modo 'vamos ver o que acontece'.",
        ],
    },
}

def obter_fala_humor(chave: str, humor: str = None) -> str:
    """
    [v5] Retorna uma variação ALEATÓRIA da fala 'chave' para o humor atual.
    Humor sem a chave (ex: CAFE, ESTUDO) → usa NORMAL (nunca fica mudo).
    Uso: emotions.obter_fala_humor("bom_dia")
    """
    import random as _r
    if humor is None:
        humor = jarvis_emotions.modo_visual
    falas = FALAS_POR_HUMOR.get(humor) or FALAS_POR_HUMOR["NORMAL"]
    lista = falas.get(chave)
    if not lista:   # humor existe mas chave não → fallback NORMAL
        lista = FALAS_POR_HUMOR["NORMAL"].get(chave)
    return _r.choice(lista) if lista else "..."

class EmotionalSystem:
    def __init__(self):
        self.modo_visual = "NORMAL"
        self.ultimo_evento_disparado = ""
        self.tempo_inicio_emocao = 0
        self.saudacao_manha_dada = False
        self.acenando_manha = False
        self.tempo_inicio_aceno = 0
        self.dormindo = False
        self.tempo_acordou_noite = 0
        # [ORBS/5a] Duração do humor ATUAL (em segundos). Faltava no
        # __init__ — sem isto, o primeiro update() dava AttributeError
        # (self._duracao_humor não existia) e derrubava o sistema
        # emocional inteiro no primeiro frame.
        self._duracao_humor = DURACAO_EMOCAO

    def update(self, hand_detected):
        tempo_agora = time.time()
        now = datetime.datetime.now()
        hora_atual = now.hour
        hora_minuto_str = now.strftime("%H:%M")

        # --- GATILHOS TEMPORAIS ---
        self.check_trigger(hora_minuto_str, "13:25", "hora_do_cafe", "Hora do café, senhor. Níveis de cafeína críticos.", "CAFE")
        self.check_trigger(hora_minuto_str, "11:35", "hora_estudo", "Hora de estudar, senhor. conhecimento nunca é demais.", "ESTUDO")

        # Reset Automático de Modos
        tempo_passado = tempo_agora - self.tempo_inicio_emocao
        if self.modo_visual == "ESTUDO":
            if tempo_passado > 1500: # 25 min
                self.modo_visual = "NORMAL"
                jarvis_voice.falar("Modo estudo finalizado, senhor.")
        elif self.modo_visual != "NORMAL":
            # [ORBS/5c] Usa a duração do humor ATUAL — não mais o teto fixo.
            # Era aqui que o humor setado pelo window.py morria em ~1 frame:
            # tempo_inicio_emocao VELHO + teto fixo de 10s = reset imediato.
            if tempo_passado > self._duracao_humor:
                self.modo_visual = "NORMAL"
                # volta ao padrão para o próximo humor/evento
                self._duracao_humor = DURACAO_EMOCAO

        # Lógica de Saudação
        is_manha = 6 <= hora_atual < 9
        if is_manha and not self.saudacao_manha_dada and hand_detected:
            jarvis_voice.falar(random.choice("bom_dia"))
            self.saudacao_manha_dada = True
            self.acenando_manha = True
            self.tempo_inicio_aceno = tempo_agora
        elif not is_manha:
            self.saudacao_manha_dada = False

        if self.acenando_manha and (tempo_agora - self.tempo_inicio_aceno > DURACAO_ACENO):
            self.acenando_manha = False

        # Lógica de Sono (Noite)
        is_noite = 19 <= hora_atual or hora_atual < 6
        if is_noite:
            if not self.dormindo and self.tempo_acordou_noite != 0 and (tempo_agora - self.tempo_acordou_noite > DURACAO_INTERACAO_NOITE):
                self.dormindo = True
            elif jarvis_voice.boca_falando and self.dormindo:
                self.dormindo = False
                self.tempo_acordou_noite = tempo_agora
            elif self.tempo_acordou_noite == 0:
                self.dormindo = True
        else:
            self.dormindo = False
            self.tempo_acordou_noite = 0

    def definir_humor(self, modo: str, duracao: float = 180.0):
        """
        [ORBS/FIX] Define humor com duração própria. Antes o window.py
        setava modo_visual direto e o reset em update() usava
        tempo_inicio_emocao VELHO — o humor durava 1 frame e sumia.

        Registra o início AGORA, de modo que o reset em update() só
        acontece quando 'duracao' de fato expirar.
        """
        self.modo_visual = modo
        self.tempo_inicio_emocao = time.time()
        self._duracao_humor = duracao

    def check_trigger(self, current_time, target_time, trigger_id, speech, visual_mode):
        if current_time == target_time and self.ultimo_evento_disparado != trigger_id:
            jarvis_voice.falar(speech)
            self.modo_visual = visual_mode
            self.tempo_inicio_emocao = time.time()
            # [ORBS] eventos temporais voltam à duração padrão — não
            # herdam o teto longo de um humor que estivesse ativo antes
            self._duracao_humor = DURACAO_EMOCAO
            self.ultimo_evento_disparado = trigger_id
        
        if self.ultimo_evento_disparado == trigger_id and current_time != target_time:
            self.ultimo_evento_disparado = ""

# Instância global
jarvis_emotions = EmotionalSystem()
