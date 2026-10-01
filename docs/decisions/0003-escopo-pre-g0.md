# 0003 — Escopo pré-G0 com portões em tempo de execução

- Estado: aceita (2026-10-01), por decisão do pesquisador.

## Contexto
O plano (§10) recomenda autorizar primeiro só T01–T05 e decidir o restante depois da decisão G0,
porque o primeiro sucesso procurado é uma amostra auditável, não um motor completo. O pesquisador
decidiu implementar agora o software de T01–T14, testado com fixtures sintéticas, mantendo como
pendências tudo o que depende de dados reais ou de decisão humana. O ambiente de desenvolvimento
não alcança fontes oficiais (gov.br e FTP do DATASUS bloqueados).

## Decisão
- Todo o software de T01–T14 é construído e testado com dados **sintéticos**, marcados com
  `origem_dados = SINTETICO`; execuções sintéticas são sempre exploratórias.
- As quatro famílias do primeiro incremento (procedimento–CBO, estabelecimento–CBO, instrumento de
  registro, vigência do procedimento) entram com estado `CANDIDATA_PRE_G0`; escolher as duas
  primeiras famílias observáveis continua sendo decisão do G0.
- Portões em tempo de execução: congelamento exige registro humano de G0; avaliação confirmatória
  exige G2, congelamento e dados reais; políticas `DOCUMENTADA` com documento pendente só valem em
  modo exploratório. Registros de decisão (`experiments/decisions/`) são feitos só por humanos.
- Leiautes, códigos e trechos normativos vindos de fontes secundárias ficam `A_CONFIRMAR` até a
  conferência com fontes oficiais preservadas na máquina do pesquisador.

## Consequências
- Parte do código pode precisar de ajuste depois do piloto (G0); o custo é aceito para ter a
  cadeia completa pronta e testada.
- Nenhum relatório deste repositório afirma resultado empírico antes de G0/G2.
