"""
FILE: jarvis_test.py
DESCRIPTION: Instância de TESTE do JARVIS — sem câmera, sem Whisper, sem
             wake word. Roda o brain REAL com entrada por TEXTO, numa
             JANELA DE TERMINAL PRÓPRIA (aberta pelo dev_agent via
             gnome-terminal/xterm) — stdin exclusivo, nada disputa com o
             terminal do JARVIS principal.

             Sai com código 0 (aprovado) ou 1 (rejeitado / sem decisão).
             Ctrl+C = rejeitar (seguro por padrão).

USO:
    lançado pelo dev_agent (janela própria), ou manual:
    python3 jarvis_test.py
"""
import sys
import os

# -----------------------------------------------------------------------
# DETECÇÃO DE JANELA — se chamado sem terminal (ex: dev_agent direto),
# RE-EXECUTA a si mesmo dentro de uma janela de terminal dedicada.
# É isso que garante: stdin próprio + VISIBILIDADE (você VÊ o teste abrir).
# -----------------------------------------------------------------------
def _garantir_janela():
    if sys.stdout.isatty():
        return False                      # já tem terminal → segue normal
    for term in ("gnome-terminal", "xfce4-terminal", "konsole", "xterm"):
        caminho = shutil_which(term)
        if caminho:
            try:
                if term == "xterm":
                    cmd = [caminho, "-title", "JARVIS TESTE",
                           "-e", f"{sys.executable} {os.path.abspath(__file__)} --ja-janela"]
                else:
                    cmd = [caminho, "--title", "JARVIS TESTE", "--",
                           sys.executable, os.path.abspath(__file__), "--ja-janela"]
                subprocess.Popen(cmd, start_new_session=True)
                sys.exit(0)               # este processo se retira; o da janela segue
            except Exception:
                continue
    return False                          # sem emulador → segue no terminal atual


def shutil_which(nome):
    for pasta in os.environ.get("PATH", "").split(os.pathsep):
        cam = os.path.join(pasta, nome)
        if os.path.isfile(cam) and os.access(cam, os.X_OK):
            return cam
    return None


if "--ja-janela" not in sys.argv:
    import subprocess
    _garantir_janela()

# -----------------------------------------------------------------------
# IMPORTS DO SISTEMA REAL — depois da garantia de janela
# -----------------------------------------------------------------------
from listen import _normalizar_texto, _INTENCOES_COMPILADAS
from brain import jarvis_brain
from voice import jarvis_voice

LIMITE_INTENCAO = 0.5   # mais rígido que o listen (0.40) — teste não chuta

PALAVRAS_APROVAR = ("aprovado", "aprovada", "aprovo", "ok aprovar", "s")
PALAVRAS_REJEITAR = ("rejeitado", "rejeitada", "rejeito", "reverter",
                     "desfazer", "n")


def _intencao_de(texto: str) -> tuple:
    """Espelha o matching do listen: sobreposição de palavras por variação."""
    norm = _normalizar_texto(texto)
    palavras = set(norm.split())
    melhor, score_melhor = "", 0.0
    for intencao, variacoes in _INTENCOES_COMPILADAS:
        for palavras_var, _frase in variacoes:
            score = len(palavras & palavras_var) / max(len(palavras_var), 1)
            if score > score_melhor:
                melhor, score_melhor = intencao, score
    return (melhor, score_melhor) if score_melhor >= LIMITE_INTENCAO else ("", score_melhor)


def main():
    # fala do JARVIS também vira print — feedback garantido mesmo sem TTS
    _falar_original = jarvis_voice.falar
    def _falar_com_print(texto, *a, **k):
        print(f"\n   [JASPER]: {texto}\n")
        try:
            return _falar_original(texto, *a, **k)
        except Exception:
            pass   # TTS pode falhar no ambiente de teste — o print já garantiu
    jarvis_voice.falar = _falar_com_print

    # ---------------- BANNER VISUAL — impossível não perceber ----------------
    print()
    print("╔" + "═" * 60 + "╗")
    print("║  J A R V I S   D E   T E S T E  —  ALTERAÇÃO EM VALIDAÇÃO  ║")
    print("╚" + "═" * 60 + "╝")
    print()
    print("  Este terminal é o JARVIS de TESTE (brain real, entrada por texto).")
    print("  Teste o que foi alterado digitando comandos como se fosse voz.")
    print()
    print("  DECISÃO:")
    print("    aprovado  (ou s)  → aplica e o JARVIS reinicia com o código novo")
    print("    rejeitado (ou n)  → reverte a alteração")
    print("    Ctrl+C            → idem rejeitado (seguro por padrão)")
    print()
    print("  Experimente: 'que horas são', 'status do celular', 'oi jasper'")
    print("─" * 62)

    while True:
        try:
            linha = input("\n[TESTE] comando> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[TESTE] Sem decisão → a alteração será REVERTIDA.")
            sys.exit(1)

        if not linha:
            continue
        baixo = linha.lower()
        if baixo in PALAVRAS_APROVAR:
            print("\n[TESTE] ★ APROVADO — o JARVIS vai reiniciar com o código novo.")
            sys.exit(0)
        if baixo in PALAVRAS_REJEITAR:
            print("\n[TESTE] ✖ REJEITADO — a alteração será revertida.")
            sys.exit(1)

        intencao, score = _intencao_de(linha)
        if not intencao:
            print(f"[TESTE] Sem intenção clara (score={score:.2f}). Reformule ou "
                  f"digite 'aprovado'/'rejeitado'.")
            continue

        print(f"[TESTE] Intenção: '{intencao}' (score={score:.2f})")
        try:
            jarvis_brain.execute_voice_command(intencao, linha)
        except Exception as e:
            print(f"[TESTE] ERRO NA EXECUÇÃO: {type(e).__name__}: {e}")
            print("        ↑ Se isso apareceu, a alteração tem bug — rejeite.")


if __name__ == "__main__":
    main()
