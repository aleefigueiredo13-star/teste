# AGENTS.md — Pixel Legal Office

Este arquivo orienta futuras sessões de Codex e qualquer agente de desenvolvimento que trabalhe neste repositório.

## 1. Objetivo do projeto

Pixel Legal Office é um escritório jurídico virtual local-first. A interface pixelada é uma visualização do trabalho real de agentes de IA; ela não é o núcleo do sistema.

Prioridade permanente:

1. execução real;
2. rastreabilidade;
3. anti-hallucination;
4. simplicidade;
5. aparência.

Nunca inverta essa ordem.

## 2. Filosofia de arquitetura

Mantenha o projeto pequeno, modular e inspecionável.

- Python 3.12+.
- Filesystem primeiro; SQLite somente se surgir necessidade concreta.
- Sem PostgreSQL, Redis, filas, microserviços ou frontend web por padrão.
- Poucas dependências.
- Configuração legível.
- Prompts/instruções longas pertencem a `SKILL.md`, não a strings Python gigantes.
- O código executa ferramentas; os Markdown definem papel, critérios e comportamento.
- `python office.py` continua sendo o comando normal de inicialização.

Uma alteração que exija infraestrutura pesada precisa demonstrar uma necessidade que o filesystem/local runtime não resolve.

## 3. Componentes

### `agents/*/SKILL.md`

Fonte declarativa de comportamento dos agentes. O front matter contém pelo menos `name`, `model_env` e `tools`. O corpo contém função, responsabilidades, limites, qualidade, escalonamento e saída.

Ao alterar um agente:

- edite primeiro o `SKILL.md`;
- não replique o mesmo prompt em Python;
- se conceder nova ferramenta, adicione-a explicitamente no front matter e implemente a permissão correspondente no runtime;
- preserve `FONTE > CONCLUSÃO`.

### `orchestrator/router.py`

Transforma uma tarefa em plano mínimo. O Orquestrador não deve mandar toda tarefa aos três agentes por reflexo.

### `orchestrator/workflow.py`

Motor do fluxo. É responsável por tool calling, handoffs, estados reais, uso/custo, rejeição e revision loop. Não introduza progresso fictício neste arquivo.

### `orchestrator/handoff.py`

Schemas dos Structured Outputs. Mudanças de schema devem ser compatíveis com os consumidores e acompanhadas de testes.

### `tools/documents.py`

Parsing/indexação local. Não envie documentos completos para serviços remotos sem necessidade explícita. Preserve página de PDF e nome de arquivo.

### `tools/web_search.py`

Pesquisa web real via Responses API. URLs devem vir das fontes retornadas pelo tool call, nunca apenas do texto gerado pelo modelo.

### `tools/legal_search.py`

Interface separada para pesquisa jurídica. Pode ganhar integrações específicas no futuro sem mudar os agentes.

### `tools/filesystem.py`

Persistência, logs, task state e custo. Escritas estruturadas importantes devem ser atômicas quando possível.

### `ui/*`

Visualização local. A UI lê `task.json` e `activity.jsonl`. Não crie timers/setTimeout/sleeps para fingir atividade. Uma animação só pode ser disparada por evento real já gravado.

## 4. Segurança e privacidade

Documentos jurídicos podem conter dados sensíveis.

Nunca:

- registrar `OPENAI_API_KEY`;
- copiar conteúdo integral de documentos para `activity.jsonl`;
- adicionar telemetria externa sem solicitação explícita;
- apagar ou sobrescrever documento original automaticamente;
- enviar e-mail, mensagem ou protocolo por iniciativa do agente;
- adicionar ferramenta de mutação externa sem human approval explícita.

As chamadas de modelo devem continuar usando `store=False` enquanto a arquitetura for local-first/stateless.

## 5. Anti-hallucination

Regra fundamental: **FONTE > CONCLUSÃO**.

- Fato documental sem fonte não deve ser afirmado como fato.
- PDF: citar arquivo e página quando disponível.
- Informação ausente: `NÃO LOCALIZADO.`
- Jurisprudência sem fonte/URL real não pode ser citada como confirmada.
- Inferência deve permanecer identificada como inferência.
- Senior review deve validar a aderência da tese aos autos.

Não flexibilize essas regras para produzir texto "mais completo".

## 6. Chain-of-thought

Não exponha chain-of-thought na UI, nos arquivos ou nos logs. Armazene somente:

- atividade observável;
- ferramenta usada;
- fonte consultada;
- resultado estruturado;
- problema identificado;
- justificativa/conclusão final necessária.

## 7. Estados reais

Estados permitidos:

`IDLE`, `READING`, `RESEARCHING`, `WRITING`, `REVIEWING`, `WAITING`, `REVISING`, `DONE`, `ERROR`.

Um estado de trabalho só pode ser gravado quando a etapa correspondente estiver realmente acontecendo. Não use sleeps para fabricar transições.

## 8. Senior rejection

O Sênior não é um rubber stamp.

Se `approved=false` e houver resultado do Júnior:

1. gravar a rejeição;
2. mudar Júnior para `REVISING`;
3. executar nova chamada real do Júnior com as instruções;
4. gravar nova entrega;
5. executar nova chamada real do Sênior.

Respeitar `MAX_REVISION_CYCLES`. Ao esgotar, marcar `needs_human_review`; nunca forçar aprovação.

## 9. Modelos e custos

Modelos vêm do `.env` por papel. Não fixe um único modelo no código.

Custos são estimativas baseadas em `pricing.json`. Se não houver tarifa cadastrada, retorne `null`. Nunca invente tarifa.

Ao adicionar chamadas auxiliares de modelo, inclua seu uso no custo/tokens do agente responsável.

## 10. Testes

Antes de considerar uma alteração concluída:

```bash
python -m compileall -q .
python -m pytest -q
```

A suíte deve continuar cobrindo:

- document parsing;
- task creation;
- agent execution;
- handoff;
- senior rejection;
- revision loop;
- final approval;
- workspace isolation.

Testes podem usar clientes determinísticos/fakes para não gastar API e para validar controle de fluxo. O aplicativo de produção não pode substituir agentes reais por esses fakes.

## 11. O que não pode ser simulado

No runtime de produção, é proibido:

- responder com textos hardcoded fingindo modelo;
- usar timer/sleep para fingir leitura, pesquisa ou escrita;
- marcar `DONE` antes de existir resultado gravado;
- inventar resultado de web/legal search;
- inserir jurisprudência fictícia;
- gerar arquivos "placeholder" como se fossem entrega concluída.

## 12. Definição de done

Uma mudança está pronta quando:

- executa no fluxo real;
- deixa artefatos inspecionáveis no filesystem;
- registra eventos observáveis sem conteúdo sensível desnecessário;
- falha de forma explícita, sem inventar saída;
- preserva human approval para ações externas;
- passa `compileall` e testes;
- mantém `python office.py` como entrada normal;
- não aumenta a arquitetura sem necessidade real.

Para o MVP jurídico principal, "done" significa: anexar sentença → Estagiário analisa → Júnior elabora → Sênior revisa → pode rejeitar → Júnior corrige → Sênior aprova → versão final e histórico permanecem no workspace após reinício.
