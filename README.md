# sus-temporal

Validação temporal e explicável de dados administrativos do SUS: modelo de restrições
versionadas que integra CNES, SIGTAP e SIA-PA, preserva referências temporais e produz explicações
verificáveis. Aplicação local de pesquisa, orientada a lotes (Python, DuckDB, Parquet).

## Estado
Em construção, pré-G0. Nenhum dado real foi processado aqui; os testes usam fixtures sintéticas.
Nenhum resultado empírico é afirmado por este repositório.

## Uso rápido
```bash
uv sync --locked
bash scripts/ci.sh
```

## Documentação
- Plano de implementação: `docs/plan/`
- Especificação-base e manifesto de preservação: `docs/spec/`
- Guia para contribuidores e agentes: `AGENTS.md`
- Processo multi-sessão, revisão e propriedade de arquivos: `docs/process/`
- Decisões de arquitetura: `docs/decisions/`
- Fontes e inventário preliminar de campos: `docs/references/`
