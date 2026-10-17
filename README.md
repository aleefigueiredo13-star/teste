# Pixel Legal Office

Pixel Legal Office é um escritório jurídico virtual local-first em Python. Os personagens da interface representam agentes reais: Estagiário, Advogado Júnior e Advogado Sênior. O progresso visual vem do workflow e dos logs gravados no disco; não existem timers simulando trabalho de IA.

## O que o MVP faz

- cria processos e tarefas em pastas locais inspecionáveis;
- anexa PDF, DOCX, TXT e Markdown;
- indexa documentos localmente e busca apenas trechos relevantes;
- executa agentes reais pela OpenAI Responses API;
- permite function calling para busca documental, web search e pesquisa jurídica;
- usa Structured Outputs para planos, handoffs e revisão;
- executa Estagiário → Júnior → Sênior quando o Orquestrador considerar necessário;
- permite `REJECT` do Sênior, revisão do Júnior e nova análise, com limite de ciclos;
- salva JSON e Markdown de todas as entregas;
- registra atividade real em `logs/activity.jsonl`;
- registra tokens, cached tokens, modelo e estimativa de custo;
- mantém o estado no filesystem para que reiniciar o programa não apague a tarefa;
- permite conversar diretamente com cada funcionário sobre a tarefa selecionada.

## Instalação

```bash
git clone https://github.com/aleefigueiredo13-star/teste.git legal-pixel-office
cd legal-pixel-office
python -m venv .venv
```

Ative o ambiente virtual e instale as dependências:

```bash
pip install -r requirements.txt
cp .env.example .env
```

No Windows PowerShell, use `Copy-Item .env.example .env` se `cp` não estiver disponível.

Abra `.env`, informe `OPENAI_API_KEY` e ajuste os modelos se desejar.

Depois, para uso normal:

```bash
python office.py
```

## Configuração de modelos

```env
ORCHESTRATOR_MODEL=gpt-6-luna
INTERN_MODEL=gpt-6-luna
JUNIOR_MODEL=gpt-6.1-sol
SENIOR_MODEL=gpt-6.1-sol
WEB_SEARCH_MODEL=gpt-6-luna
```

Nenhum modelo está hardcoded como única opção. Os valores acima são apenas defaults editáveis.

## Arquitetura

```text
legal-pixel-office/
├── AGENTS.md
├── README.md
├── .env.example
├── requirements.txt
├── pricing.json
├── office.py
├── agents/
│   ├── orchestrator/SKILL.md
│   ├── estagiario/SKILL.md
│   ├── junior/SKILL.md
│   └── senior/SKILL.md
├── orchestrator/
│   ├── router.py
│   ├── workflow.py
│   └── handoff.py
├── tools/
│   ├── documents.py
│   ├── web_search.py
│   ├── legal_search.py
│   └── filesystem.py
├── workspace/
│   ├── processos/
│   ├── tarefas/
│   └── outputs/
├── ui/
│   ├── app.py
│   ├── office.py
│   ├── sprites/palette.json
│   └── components/panels.py
├── logs/
└── tests/
```

A pasta realmente importante é `workspace/processos/<processo>/`. Ela contém `case.json`, documentos, tarefas, pesquisas e outputs. O sistema deve continuar compreensível mesmo sem abrir a interface.

## Fluxo de uma tarefa

Exemplo:

```text
workspace/processos/0101234-56.2026.5.01.0001/
├── case.json
├── documents/
│   └── sentenca.pdf
├── research/
│   ├── document_index.json
│   └── web_search.jsonl
├── tasks/
│   └── task-001/
│       ├── task.json
│       ├── plan.json
│       ├── estagiario/
│       │   ├── result.json
│       │   └── result.md
│       ├── junior/
│       │   ├── result.json
│       │   └── minuta.md
│       ├── senior/
│       │   ├── review.json
│       │   └── final.md
│       └── versao_final.md
└── outputs/
    └── task-001-versao_final.md
```

Quando houver rejeição, o Júnior e o Sênior também ganham arquivos versionados, como `minuta-rev-01.md` e `review-01.json`.

## Documentos e privacidade

O MVP não cria um vector database remoto. PDF/DOCX/TXT/MD são processados localmente. A busca documental é local e retorna trechos com nome de arquivo e, em PDFs, número da página. Apenas o contexto necessário para a tarefa é enviado ao modelo.

As chamadas à Responses API usam `store=False`. Não há telemetria externa própria. A chave da API não é escrita nos logs. Os documentos originais não são apagados nem alterados.

PDFs digitalizados sem camada de texto ainda não têm OCR no MVP. Nesses casos, o agente deve tratar conteúdo não encontrado como `NÃO LOCALIZADO.` em vez de inventar.

## Pesquisa web e jurídica

`web_search` usa a ferramenta oficial `web_search` da Responses API. O runtime conserva URLs realmente retornadas pelas fontes da busca. `legal_search` é separado propositalmente e hoje restringe a pesquisa a fontes oficiais selecionadas (TST, TRTs, STF, STJ e Planalto), deixando a porta aberta para integrações futuras.

A aplicação não cria precedente jurídico fictício. Se uma URL verificável não for obtida, o resultado não deve ser tratado como jurisprudência confirmada.

## Aprovação humana

O sistema pode ler, pesquisar, analisar, criar arquivos e revisar. Não há ferramenta para enviar e-mail, protocolar peça, enviar mensagem, apagar original ou alterar sistema externo. Essas ações ficam fora do MVP e exigirão aprovação humana explícita se forem adicionadas no futuro.

## Custo

Cada agente registra no `task.json`:

- `input_tokens`;
- `output_tokens`;
- `cached_tokens`;
- `model`;
- `estimated_cost`;
- chamadas auxiliares de web/legal search, quando existirem.

`pricing.json` é um arquivo legível e atualizável. Se o modelo não estiver cadastrado, o custo estimado fica `null` em vez de ser inventado.

## Testes

```bash
python -m pytest -q
```

A suíte cobre parsing, criação de tarefas, execução com tool calling, handoff, rejeição do Sênior, revision loop, aprovação final e isolamento de workspaces.

## Escolhas da API OpenAI

O MVP usa a SDK oficial Python e a Responses API. Para tools próprias, segue o loop oficial de function calling. Como `store=False`, os itens retornados pela resposta — inclusive reasoning items criptografados — são preservados e reenviados durante a mesma execução. Structured Outputs usa `text.format` com JSON Schema.

Referências oficiais consultadas na implementação:

- https://developers.openai.com/api/docs/guides/function-calling
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/tools-file-search
- https://developers.openai.com/api/docs/guides/conversation-state
- https://developers.openai.com/api/docs/pricing

O hosted File Search da OpenAI existe, mas não é o default deste MVP porque o requisito central é local-first e documentos jurídicos podem ser sensíveis. A camada `tools/documents.py` pode ser substituída ou complementada depois sem mudar a interface dos agentes.
