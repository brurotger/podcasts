"""Agente 2: transforma as notícias em um roteiro de diálogo em português.

Escreve uma conversa natural entre Marcos (especialista) e Ana (entusiasta),
em linguagem acessível, sempre citando a fonte de cada notícia.

Dois modos de autenticação, escolhidos automaticamente:
- ANTHROPIC_API_KEY definida      -> API da Anthropic (Claude Opus 5)
- CLAUDE_CODE_OAUTH_TOKEN definida -> Claude Code CLI usando a assinatura
                                      Pro/Max do claude.ai (custo zero extra)
"""

import os
import subprocess

import anthropic

SYSTEM_PROMPT = """\
Você é roteirista de um podcast semanal brasileiro chamado "IA Hoje", que discute \
em profundidade as novidades do mundo da inteligência artificial da semana, em \
linguagem simples.

O episódio é um diálogo entre duas pessoas:
- MARCOS: especialista em IA. Explica os conceitos com clareza, dá contexto histórico, \
compara com o que já existia antes, cita números e detalhes concretos da notícia, \
e dá opinião técnica — mas sem jargão; quando um termo técnico é inevitável, ele \
explica em uma frase o que significa.
- ANA: entusiasta curiosa. Não aceita respostas superficiais: pergunta "por quê",
"e daí?", "isso muda o quê pra quem usa?", pede exemplos do dia a dia, questiona \
se é hype ou é real, e só segue pra próxima notícia quando sente que entendeu de verdade.

## Prioridade #1: profundidade, não cobertura

Este é o ponto mais importante destas instruções. NÃO tente encaixar todas as \
notícias da lista — é preferível discutir 8 a 12 notícias muito bem do que passar \
rapidamente por todas. Escolha as notícias mais relevantes/impactantes da semana e \
dedique a cada uma delas (ou a um grupo de notícias relacionadas, veja abaixo) um \
bloco de conversa real, cobrindo (sem parecer um roteiro decorado, de forma fluida \
e conversada):
- O que aconteceu, com detalhes concretos (números, nomes de produtos, o que foi \
anunciado exatamente) — não fique só no título.
- Contexto: o que veio antes disso? É uma resposta a um concorrente? É uma evolução \
de algo que a empresa já vinha fazendo?
- Por que isso importa de verdade — pra quem trabalha com tecnologia, pra quem usa \
esses produtos no dia a dia, ou pro mercado.
- Um ponto de vista: é exagero de marketing ou é significativo mesmo? Tem algum \
motivo pra desconfiar ou comemorar?
- Sempre que fizer sentido, uma pequena comparação ou analogia que ajude a Ana (e o \
ouvinte) a visualizar o tamanho da coisa.
As notícias menores e menos relevantes da semana podem ficar de fora do episódio \
sem problema — qualidade da discussão importa mais que quantidade de manchetes.

## Organize por tema, não só por ordem cronológica

Como o episódio cobre uma semana inteira, é comum haver notícias relacionadas \
entre si (ex.: dois lançamentos de modelos concorrentes, uma sequência de \
anúncios da mesma empresa, ou várias notícias sobre o mesmo debate). Quando \
fizer sentido, agrupe essas notícias no mesmo bloco de conversa e faça Marcos \
e Ana compararem umas com as outras, em vez de tratar cada uma isoladamente \
como se fossem assuntos sem relação.

## Regras de formato

1. Escreva SOMENTE falas, uma por linha, no formato "MARCOS: texto" ou "ANA: texto". \
Nada de marcações de cena, efeitos sonoros, markdown, emojis ou títulos.
2. O texto será convertido em áudio por um sintetizador de voz: escreva por extenso \
tudo que precisa ser falado (por exemplo, "GPT" vira "G P T", "US$ 5 bilhões" vira \
"cinco bilhões de dólares", siglas pouco conhecidas são soletradas ou explicadas).
3. Abra com Ana saudando o ouvinte, dizendo que é o resumo semanal e qual período \
a semana cobre (ex.: "nesta semana, de 19 a 25 de outubro"), e chamando o Marcos.
4. SEMPRE cite a fonte de cada notícia de forma natural na conversa \
("segundo o TechCrunch...", "a própria OpenAI anunciou no blog dela...").
5. Linguagem: português do Brasil, coloquial, fácil de entender, frases curtas. \
Tom leve e bem-humorado, mas informativo — e evite que os blocos de cada notícia \
soem repetitivos entre si (varie a forma como Ana introduz o assunto e como Marcos \
fecha cada bloco).
6. Duração alvo: entre vinte e cinco e trinta e cinco minutos de fala (aproximadamente \
4200 a 6000 palavras) — isso só funciona se você seguir a prioridade de profundidade \
acima; não estique artificialmente uma notícia rasa, aprofunde de verdade cada uma \
das notícias escolhidas e use o espaço extra pra comparações entre notícias do mesmo \
tema, não pra encher linguiça.
7. Feche com um resumo de uma frase por notícia (ou grupo de notícias) discutida e \
uma despedida simpática lembrando que semana que vem tem mais.
8. Responda APENAS com as falas do roteiro: nenhum texto antes ("Aqui está o \
roteiro...") nem depois delas.
"""


def build_user_prompt(candidates: list[dict], period_str: str) -> str:
    lines = [
        f"Período coberto por este episódio: {period_str}.",
        "",
        "Notícias da semana (título, fonte, resumo e link):",
        "",
    ]
    for i, c in enumerate(candidates, 1):
        lines.append(f"{i}. [{c['source']}] {c['title']}")
        if c["summary"]:
            lines.append(f"   Resumo: {c['summary']}")
        lines.append(f"   Link: {c['url']}")
        lines.append("")
    lines.append("Escreva o roteiro completo do episódio desta semana.")
    return "\n".join(lines)


def write_script(candidates: list[dict], period_str: str) -> str:
    user_prompt = build_user_prompt(candidates, period_str)

    if os.environ.get("ANTHROPIC_API_KEY"):
        script = _generate_via_api(user_prompt)
    elif os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        script = _generate_via_claude_code(user_prompt)
    else:
        raise RuntimeError(
            "Defina ANTHROPIC_API_KEY (API) ou CLAUDE_CODE_OAUTH_TOKEN "
            "(assinatura Pro/Max via Claude Code) no ambiente."
        )

    n_lines = len([l for l in script.splitlines() if l.strip()])
    print(f"[script] roteiro gerado: {n_lines} falas, {len(script.split())} palavras")
    return script


def _generate_via_api(user_prompt: str) -> str:
    client = anthropic.Anthropic()  # usa ANTHROPIC_API_KEY do ambiente

    with client.beta.messages.stream(
        model="claude-opus-5",
        max_tokens=32000,
        # Fallback automático: se o classificador de segurança recusar a
        # requisição (raro para notícias), o Opus 4.8 responde na mesma chamada.
        betas=["server-side-fallback-2026-06-01"],
        fallbacks=[{"model": "claude-opus-4-8"}],
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise RuntimeError("A API recusou a requisição (stop_reason=refusal).")
    if response.stop_reason == "max_tokens":
        print("[script] aviso: roteiro pode ter sido truncado (max_tokens)")

    return "".join(b.text for b in response.content if b.type == "text").strip()


def _generate_via_claude_code(user_prompt: str) -> str:
    """Gera o roteiro pelo Claude Code CLI, autenticado com a assinatura Pro/Max.

    O token vem de `claude setup-token` e é lido da variável de ambiente
    CLAUDE_CODE_OAUTH_TOKEN pelo próprio CLI.
    """
    full_prompt = SYSTEM_PROMPT + "\n\n" + user_prompt
    result = subprocess.run(
        ["claude", "-p", "--output-format", "text"],
        input=full_prompt,
        capture_output=True,
        text=True,
        timeout=1800,  # roteiro semanal é mais longo; dá mais folga que o diário
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Claude Code CLI falhou (token expirado? rode `claude setup-token` "
            f"de novo e atualize o secret). Erro: {result.stderr[-2000:]}"
        )
    script = result.stdout.strip()
    if not script:
        raise RuntimeError("Claude Code CLI retornou resposta vazia.")
    return script
