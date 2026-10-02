# AGENTS.md — sus-temporal

Guia obrigatório para humanos e agentes que alteram este repositório. Fonte de verdade do
trabalho: `docs/plan/Plano_Implementacao_Validacao_Temporal_SUS.md` (cópia preservada, hash em
`docs/spec/manifest.yaml`). O esboço (`docs/spec/esboco_original.pdf`, ainda PENDENTE) prevalece
sobre o plano quanto ao escopo científico.

## Estado do projeto
- Pré-G0. Nenhum dado real foi processado neste repositório. Tudo que roda no CI usa fixtures
  sintéticas e é exploratório. Não existe resultado empírico a relatar.
- Decisões G0/G1/G2 são humanas (`experiments/decisions/`). Agentes nunca as criam ou alteram.
- Famílias de regras implementadas antes do G0 têm estado `CANDIDATA_PRE_G0`.

## Restrições globais (do plano; invioláveis)
- Recorte inicial: municípios do DRS XI (Presidente Prudente), 2018–2025; teste de escala em SP.
- Sem bases municipais restritas; nunca identificar pacientes.
- Falta de campo ou arquivo necessário = verificação **inconclusiva**, nunca violação.
- BPA consolidado: verificação cadastral no nível estabelecimento–CBO, sem inferir vínculo de um
  profissional específico.
- O classificador não recebe rótulo, campos de erro nem quantidades/valores aprovados.
- Data de coleta ≠ data de registro/publicação; histórico nunca é substituído pelo cadastro atual.
- Não afirmar que alteração atual modifica competência encerrada, que contrafactual assegura
  aprovação, nem que valor de tabela não aprovado é perda financeira.
- Separar exploração, decisões congeladas e resultados confirmatórios; registrar toda alteração
  posterior à abertura do teste.

## Foco de revisão (do plano)
| Condição crítica | Comportamento exigido |
|---|---|
| Arquivo ausente, truncado ou com leiaute incompatível | Quarentena/inconclusão; conjunto vazio nunca vira ausência cadastral |
| Mesmo arquivo coletado de novo ou conteúdo antigo reaparecendo | Nova observação; não nova versão de conteúdo; histórico preservado |
| Atendimento e processamento em competências diferentes (inclusive borda de 2018) | Resolver as dependências realmente necessárias; nunca escolher automaticamente o mês vizinho |
| Linhas repetidas, agregadas ou sem identificador longitudinal | Preservar multiplicidades; não inventar paciente, reapresentação ou vínculo entre competências |
| Contrafactual remove uma violação e cria outra, ou depende de informação local | Revalidar o conjunto afetado; declarar condições pendentes e limite de minimalidade |

## Engenharia
- Python 3.12, uv (`uv sync --locked`), pacote em `src/sustemporal/`, CLI `sustemporal`.
- Contratos em `sustemporal.contracts` (pydantic v2, `frozen`, `extra="forbid"`; pydantic v2 não
  converte número em texto). Campo novo em contrato com id derivado do conteúdo tem default
  `None`, assim ids já emitidos continuam válidos. Use os tipos de `contracts/base.py` (`Inteiro`,
  `DecimalExato`, `ValorMonetario`, `Booleano`, `InstanteUTC`, códigos com padrão) em vez de
  `int`/`float`/`bool` crus: eles recusam float, bool disfarçado e instantes sem UTC.
- Limites: função ≤ 50 linhas, complexidade ≤ 10, aninhamento ≤ 3, arquivo ≤ 500 linhas, linha
  ≤ 100 colunas, ≤ 5 parâmetros posicionais (extras só keyword-only com default). Verificados por
  `tests/unit/test_limites_codigo.py` e ruff; supressões (`# ruff: noqa`, `noqa: C901/PLR09`,
  `# mypy: ignore-errors`, `# type: ignore` sem código) são proibidas, e arquivos de configuração de
  ferramentas (`ruff.toml`, `pytest.ini`, `conftest.py` novo, `setup.cfg`…) são só do orquestrador.
- Códigos sempre texto, com zeros à esquerda (CNES 7 dígitos, procedimento 10, CBO `[0-9A-Z]{6}`,
  município 6 ou 7 dígitos como tipos distintos). Nunca `int()` em código.
- Dinheiro em `Decimal`/DECIMAL; nunca float em somatório monetário.
- Instantes sempre UTC conscientes de fuso. Competência é texto `AAAAMM` com tipo próprio.
- YAML de catálogo/config carregado com escalares só texto (helper `sustemporal.yamlio`).
- DBF decodificado em latin-1 (bijetivo) com o byte de driver registrado; nunca `errors="replace"`.
- SQL só parametrizado; identificadores apenas de allowlist derivada dos esquemas.
- Logging `logger.info("acao chave=%s", valor)`, uma linha por evento; sem `print`.
- Mensagens de erro no formato `chave=valor`. Sem comentários óbvios; docstrings curtas.
- Termos genéricos em inglês; termos do domínio SUS em português; valores de enum exatamente
  como no plano (`CONFORME`, `VIOLACAO`, `INCONCLUSIVO`, `NAO_APLICAVEL`, …).
- Nada de LLM para atribuir causas, criar rótulos ou redigir texto de explicação.

## Proveniência
Todo leiaute, código, vigência ou trecho normativo carrega `Proveniencia` (`OFICIAL_DOCUMENTO`,
`OFICIAL_ARQUIVO`, `OFICIAL_VISTO_EM_BUSCA`, `SECUNDARIA`, `INFERIDA`, `INFERIDA_PILOTO`) e
`Confirmacao` (`CONFIRMADO` ou `A_CONFIRMAR`). Fatos observados pelo CnesData (rótulo
`EMPIRICA_CNESDATA` nos docs) contam como `SECUNDARIA` nos catálogos. Fontes secundárias e
inferências nunca são apresentadas como oficiais. Registro de fontes: `docs/references/`.

## Testes
- TDD: commit `test(...)` com vermelho pertinente (falha de asserção ou `NotImplementedError`,
  nunca erro de import ou sintaxe) → commit `feat(...)` mínimo → verde → refatorar.
- Nomes em português descrevendo comportamento (`test_rejeita_cbo_com_espaco`), exceto os nomes
  fixados pelo plano.
- Sem rede: pytest-socket só permite loopback. Marcadores `network`, `real_data`, `perf` ficam
  fora do CI. Dados reais só via `SUSTEMPORAL_REAL_DATA_DIR`, nunca no Git.
- Fixtures sintéticas pequenas (≤ 200 KB), geradas por código em `tests/fixtures/`.
- Mock só na fronteira (rede, sistema de arquivos remoto, relógio). Relógio injetado.
- Teste diferencial e avaliadores de referência não importam o código de produção comparado.

## Comandos
```bash
uv sync --locked
bash scripts/ci.sh                      # ruff, format, mypy, propriedade, pytest (perfil Hypothesis ci)
uv run pytest tests/unit -q             # recorte
uv run python ...                       # sempre via uv (python3 do sistema é 3.11)
uv run sustemporal --help               # CLI
```

## Git e PRs
- Branch por sessão `claude/sN-<slug>` (definido pelo orquestrador ao criar a sessão); orquestrador
  em `claude/determined-ritchie-b9o2qg` ou `claude/orq-*`. Branch `claude/*` sem dono no mapa de
  propriedade reprova no CI. Commits `<tipo>(<escopo>): <descrição>`.
- Push forçado, remoção de branch e qualquer push para `main` são bloqueados por hook.
- Nunca force-push, rebase de commits publicados, commit direto em `main` ou merge de PR por
  sessões-filhas. Atualizar com `git fetch origin && git merge --no-edit origin/main`.
- PR em rascunho até ficar pronto (rascunho não roda CI); corpo segue
  `.github/pull_request_template.md`.
- Propriedade de arquivos: `docs/process/propriedade.yaml` (checada no CI).
- Dependências: só o orquestrador altera `pyproject.toml`/`uv.lock`.
- Pendências humanas ou de dados reais: `docs/pendencias/TNN.md`.

## Mapa
- `docs/plan/` plano; `docs/spec/` esboço e manifesto; `docs/process/` protocolo, revisão e
  propriedade; `docs/decisions/` ADRs; `docs/references/` fontes e inventário de campos;
  `docs/method/` semântica e métodos; `docs/runbooks/` execução na máquina do pesquisador.
- `catalog/` fontes, leiautes, rótulos, esquemas, regras, políticas e operações.
- `config/` configurações de piloto, coorte, partições e execução.
