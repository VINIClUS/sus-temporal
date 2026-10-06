"""Varredura do que a cadeia do `reproduce` lê e compara: cada campo e cada comparação (T14).

A reprodução tem de refazer o que foi registrado, e o que ela não consegue conferir sai
INCONCLUSIVO. Cada campo do `FreezeManifest` e da config (inclusive os de `runtime` e `piloto`)
tem aqui o tratamento: a fonte da verdade, como a diferença aparece e o efeito. O mesmo vale para
os campos que as comparações projetam ou deixam de fora (`DatasetRef`, `SplitManifest` e
`EvaluationReport`), e `COMPARACOES` diz o que cada comparação confere antes de projetar. Um
teste percorre os campos dos contratos e falha se um campo novo ficar sem tratamento, como em
`freeze_conferencia.CAMPOS_DO_MANIFESTO`; campo lido e não conferido é limite declarado (T14-16),
com efeito conservador: divergência ou inconclusão, nunca reprodução falsa. `LEITURAS` (em
`reproduce_leituras`, por causa do limite de tamanho do arquivo, e reexportada daqui) lista os
arquivos que a cadeia abre e o resultado de cada um que não abre.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sustemporal.reporting.reproduce_leituras import (
    LEITURAS,
    Dano,
    Estrago,
    Leitura,
    Origem,
    Raiz,
    Resultado,
)

__all__ = [
    "CAMPOS_DA_CONFIG",
    "CAMPOS_DA_REFERENCIA",
    "CAMPOS_DO_CONGELAMENTO",
    "CAMPOS_DO_RELATORIO",
    "CAMPOS_DO_SPLIT",
    "COMPARACOES",
    "LEITURAS",
    "Conferencia",
    "Conferido",
    "Dano",
    "Estrago",
    "Fonte",
    "Leitura",
    "Origem",
    "Raiz",
    "Resultado",
    "Tratamento",
]


class Fonte(StrEnum):
    """De onde vem o valor que a reprodução usa."""

    CONGELAMENTO = "CONGELAMENTO"
    REGISTRO = "REGISTRO"
    ORIGINAL = "ORIGINAL"
    CODIGO = "CODIGO"
    CONFIG = "CONFIG"
    NENHUMA = "NENHUMA"


class Conferencia(StrEnum):
    """Como a diferença aparece no `reproducao.json`."""

    ITEM = "ITEM"
    OBSERVACAO = "OBSERVACAO"
    INDIRETA = "INDIRETA"
    RECUSA = "RECUSA"
    NENHUMA = "NENHUMA"


@dataclass(frozen=True)
class Tratamento:
    fonte: Fonte
    conferencia: Conferencia
    efeito: str


@dataclass(frozen=True)
class Conferido:
    """O que uma comparação confere antes de projetar, filtrar ou ignorar, e o que deixa de fora."""

    antes: str
    fora: str


def _t(fonte: Fonte, conferencia: Conferencia, efeito: str) -> Tratamento:
    return Tratamento(fonte, conferencia, efeito)


F, C = Fonte, Conferencia

CAMPOS_DO_CONGELAMENTO: dict[str, Tratamento] = {
    "freeze_id": _t(
        F.CONGELAMENTO, C.RECUSA, "recomputado do conteúdo; adulterado ou de outro id sai 2"
    ),
    "criado_em": _t(F.NENHUMA, C.NENHUMA, "informativo; já não decide o manifesto de aquisição"),
    "config_hash": _t(
        F.CONGELAMENTO, C.OBSERVACAO, "`config_diferente_da_congelada`; o conteúdo decide"
    ),
    "codigo": _t(
        F.CONGELAMENTO, C.OBSERVACAO, "`codigo_diferente_do_congelado`; o conteúdo decide"
    ),
    "ambiente": _t(
        F.CONGELAMENTO, C.OBSERVACAO, "`pacotes_diferentes_do_congelado`; o conteúdo decide"
    ),
    "catalogos_sha256": _t(F.CONGELAMENTO, C.OBSERVACAO, "`catalogos_diferentes_do_congelado`"),
    "datasets": _t(
        F.CONGELAMENTO, C.ITEM, "`conjunto:*` por hash lógico; acha o ingest e a origem"
    ),
    "split": _t(F.CONGELAMENTO, C.ITEM, "`split:*`; a `spec` e os inspecionados vêm dele"),
    "features": _t(F.NENHUMA, C.NENHUMA, "a avaliação por regras não usa features"),
    "bootstrap": _t(F.CONGELAMENTO, C.INDIRETA, "o do manifesto vale; `metricas` e `notas`"),
    "metricas": _t(F.CODIGO, C.INDIRETA, "constante do código; `metricas` do relatório registrado"),
    "comparacoes_primarias": _t(F.CODIGO, C.INDIRETA, "constante do código; `notas` do relatório"),
    "margens": _t(F.NENHUMA, C.NENHUMA, "a avaliação não usa margens (T11 #2)"),
    "decisao_g0": _t(F.NENHUMA, C.NENHUMA, "só autoriza congelar"),
    "catalogo_regras_sha256": _t(
        F.CONGELAMENTO, C.OBSERVACAO, "`catalogo_de_regras_diferente_do_congelado`"
    ),
    "politicas_sha256": _t(
        F.CONGELAMENTO, C.ITEM, "a política refeita é a congelada; senão `insumos:*` inconclusivo"
    ),
    "entradas_validacao": _t(
        F.CONGELAMENTO, C.ITEM, "`insumos:*`: entrada original e identidade campo a campo"
    ),
}

CAMPOS_DA_CONFIG: dict[str, Tratamento] = {
    "versao": _t(F.NENHUMA, C.NENHUMA, "não lido pela cadeia"),
    "modo": _t(F.REGISTRO, C.RECUSA, "só o exploratório; a rodada é a do modo no registro"),
    "origem_dados": _t(
        F.CONGELAMENTO, C.ITEM, "`origem_dados` inconclusivo se difere dos conjuntos"
    ),
    "runtime.duckdb_memoria": _t(F.NENHUMA, C.NENHUMA, "desempenho; o conteúdo não depende"),
    "runtime.duckdb_threads": _t(
        F.NENHUMA, C.NENHUMA, "desempenho; 1 e 4 threads dão o mesmo conteúdo"
    ),
    "runtime.raiz_dados": _t(
        F.ORIGINAL, C.ITEM, "SHA-256 do bruto conferido pelo ingest; quarentena inconclusiva"
    ),
    "runtime.raiz_manifestos": _t(
        F.ORIGINAL, C.ITEM, "só até a posição que o ingest leu (`manifesto:aquisicao`)"
    ),
    "runtime.raiz_saidas": _t(
        F.ORIGINAL, C.ITEM, "ingest, `split/insumos`, relatório e execuções originais"
    ),
    "runtime.dir_congelamentos": _t(
        F.CONGELAMENTO, C.RECUSA, "manifesto com id recomputado e registro encadeado"
    ),
    "runtime.rede_permitida": _t(F.NENHUMA, C.RECUSA, "recusado (saída 6)"),
    "runtime.verificacao_fidelidade": _t(
        F.NENHUMA, C.NENHUMA, "limite: o ingest original não registra o modo"
    ),
    "piloto.uf": _t(F.ORIGINAL, C.ITEM, "`configuracao_ingest.json`: `manifesto:aquisicao`"),
    "piloto.competencias_processamento": _t(
        F.CONGELAMENTO, C.INDIRETA, "a janela vem da partição; a cobertura na identidade"
    ),
    "piloto.territorio": _t(
        F.CONGELAMENTO, C.ITEM, "`recorte_territorial` na identidade dos insumos"
    ),
    "piloto.familias_fontes": _t(
        F.ORIGINAL, C.ITEM, "`configuracao_ingest.json`: `manifesto:aquisicao`"
    ),
    "vigilancia": _t(F.NENHUMA, C.NENHUMA, "não lido: o piloto é exigido"),
    "coorte": _t(F.CONFIG, C.INDIRETA, "o `split_id` leva a coorte; diferente diverge"),
    "particoes": _t(
        F.CONGELAMENTO, C.NENHUMA, "a `spec` do manifesto vale; a da config é ignorada"
    ),
    "bootstrap": _t(F.CONGELAMENTO, C.NENHUMA, "o do manifesto vale; o da config é ignorado"),
    "metodos": _t(F.CODIGO, C.INDIRETA, "refaz os três métodos; método sem registro diverge"),
    "politica_id": _t(F.CONGELAMENTO, C.ITEM, "cada método refaz com a política congelada dele"),
    "semente": _t(F.NENHUMA, C.NENHUMA, "não lida pela cadeia (o bootstrap tem a do manifesto)"),
    "contrafactual": _t(F.NENHUMA, C.NENHUMA, "não lido pela cadeia"),
    "corte_observacao": _t(
        F.ORIGINAL, C.ITEM, "`configuracao_ingest.json` e `snapshots` dos insumos"
    ),
    "freeze_id": _t(F.CONGELAMENTO, C.RECUSA, "o da CLI; config com outro sai 2"),
    "catalogos": _t(
        F.CONGELAMENTO, C.ITEM, "fontes e leiaute pelo ingest original; os demais, observação"
    ),
}

CAMPOS_DA_REFERENCIA: dict[str, Tratamento] = {
    "dataset_id": _t(
        F.ORIGINAL,
        C.INDIRETA,
        "deriva de esquema, hash lógico e artefatos; o das saídas leva o `run_id`",
    ),
    "schema_id": _t(
        F.ORIGINAL, C.ITEM, "pareia o item e dá o leiaute esperado: `esquema_divergente`"
    ),
    "caminho": _t(F.NENHUMA, C.NENHUMA, "onde o arquivo está; o conteúdo decide"),
    "hash_logico": _t(F.ORIGINAL, C.ITEM, "recalculado do arquivo, nunca lido da referência"),
    "linhas": _t(F.ORIGINAL, C.ITEM, "recontada do arquivo: `refeito_diverge`"),
    "artifact_ids": _t(F.ORIGINAL, C.ITEM, "multiconjunto de artefatos: `linhagem_diverge`"),
    "origem_dados": _t(F.CONGELAMENTO, C.ITEM, "item `origem_dados`, antes de refazer"),
    "produzido_por": _t(
        F.NENHUMA, C.NENHUMA, "rótulo do código que gravou; o código diferente é observação"
    ),
    "reconciliacao": _t(
        F.ORIGINAL, C.INDIRETA, "contagem derivada do conteúdo; o hash lógico cobre as linhas"
    ),
    "multiplicidade": _t(
        F.ORIGINAL, C.INDIRETA, "contagem derivada do conteúdo; o hash lógico conta a repetição"
    ),
}

CAMPOS_DO_SPLIT: dict[str, Tratamento] = {
    "split_id": _t(F.CONGELAMENTO, C.ITEM, "`split:split_id`"),
    "spec": _t(F.CONGELAMENTO, C.ITEM, "`split:campos`; a do manifesto é a que refaz"),
    "dataset_hash": _t(F.CONGELAMENTO, C.ITEM, "`split:campos`"),
    "linhas_por_particao": _t(F.CONGELAMENTO, C.ITEM, "`split:campos`"),
    "hash_por_particao": _t(F.CONGELAMENTO, C.ITEM, "`split:campos`"),
    "artefatos_inspecionados": _t(
        F.CONGELAMENTO, C.ITEM, "`split:campos`; vêm do manifesto e entram no `split_id`"
    ),
    "artefatos_teste": _t(F.CONGELAMENTO, C.ITEM, "`split:campos`"),
    "cohort_id": _t(F.CONGELAMENTO, C.ITEM, "`split:campos`"),
    "particoes": _t(
        F.CONGELAMENTO, C.ITEM, "`split:particao:*`, pela união das chaves das duas pontas"
    ),
    "exclusoes": _t(F.CONGELAMENTO, C.ITEM, "`split:campos`"),
    "limites": _t(F.CONGELAMENTO, C.ITEM, "`split:campos`"),
    "rotulos_por_particao": _t(
        F.CONGELAMENTO, C.ITEM, "`split:rotulos:*`, pela união das chaves das duas pontas"
    ),
}

CAMPOS_DO_RELATORIO: dict[str, Tratamento] = {
    "report_id": _t(
        F.REGISTRO,
        C.INDIRETA,
        "o original só vale se bate com o registro; o refeito deriva do caminho",
    ),
    "modo": _t(F.REGISTRO, C.ITEM, "`relatorio:campos`"),
    "origem_dados": _t(F.REGISTRO, C.ITEM, "`relatorio:campos`"),
    "freeze_id": _t(F.REGISTRO, C.ITEM, "`relatorio:campos`"),
    "decisao_g2": _t(F.ORIGINAL, C.ITEM, "`relatorio:campos`"),
    "runs": _t(
        F.REGISTRO, C.ITEM, "`relatorio:campos` só pela quantidade; os ids derivam do caminho"
    ),
    "metricas": _t(F.ORIGINAL, C.ITEM, "`metricas`: multiconjunto por nome, estrato e valor"),
    "tabelas": _t(F.ORIGINAL, C.ITEM, "`relatorio:campos`: esquema, linhas e hash lógico"),
    "notas": _t(F.ORIGINAL, C.ITEM, "`notas`: multiconjunto"),
    "criado_em": _t(F.NENHUMA, C.NENHUMA, "instante da execução; o conteúdo decide"),
}

COMPARACOES: dict[str, Conferido] = {
    "conjunto:*": Conferido(
        "o leiaute (nomes, ordem e tipos) do refeito, do original e entre os dois; os esquemas "
        "pela união do manifesto e dos refeitos (`sem_etapa`, `conjunto_nao_congelado`); linhas, "
        "hash lógico e linhagem",
        "`caminho` e `produzido_por`",
    ),
    "split:split_id": Conferido(
        "o id, que leva a especificação, a coorte, as fontes, os rótulos e os artefatos "
        "inspecionados",
        "nada",
    ),
    "split:campos": Conferido(
        "todos os campos do manifesto do split, menos o id e as referências; campo novo do "
        "contrato entra sozinho",
        "nada",
    ),
    "split:particao:*": Conferido(
        "as partições da população pela união das chaves (`particao_ausente`, "
        "`particao_sem_original`, `particao_nao_congelada`) e, em cada uma, o leiaute, o hash "
        "lógico e a linhagem",
        "`caminho` e `produzido_por`",
    ),
    "split:rotulos:*": Conferido(
        "as partições dos rótulos, como `split:particao:*`",
        "`caminho` e `produzido_por`",
    ),
    "saida:*": Conferido(
        "o leiaute completo dos dois lados, inclusive a coluna `run_id`; os esquemas e os métodos "
        "pela união; a saída repetida (`<esquema>#2`); o hash lógico e a linhagem",
        "os valores de `run_id`, que derivam do caminho, e só depois do leiaute",
    ),
    "insumos:*": Conferido(
        "a união dos campos da identidade da entrada: o campo só do congelamento, ou só da "
        "entrada refeita, é divergência",
        "nada",
    ),
    "metricas": Conferido(
        "o multiconjunto de (nome, estrato, valor): a métrica repetida conta cada vez", "nada"
    ),
    "notas": Conferido("o multiconjunto das notas: a nota repetida conta cada vez", "nada"),
    "relatorio:campos": Conferido(
        "`modo`, `origem_dados`, `freeze_id`, `decisao_g2`, a quantidade de execuções e as tabelas "
        "(esquema, linhas e hash lógico); campo novo do contrato entra sozinho",
        "`report_id`, `criado_em` e os ids das execuções (derivam do caminho e do relógio); "
        "`metricas` e `notas` têm item próprio",
    ),
}
