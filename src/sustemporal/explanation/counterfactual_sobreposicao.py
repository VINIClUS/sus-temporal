"""Sobreposição isolada dos cadastros CNES e revalidação pelo motor de regras (T09).

Todos os insumos da execução são copiados para um diretório temporário; as operações alteram só
tabelas em memória, gravadas como novos parquet nessa cópia. Os arquivos originais são apenas
lidos uma vez, para a cópia e a conferência de conteúdo.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.contracts.records import DatasetRef, TipoCanonico, calcular_dataset_id
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.hashing import hash_logico_relacao
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo
from sustemporal.rules.engine import evaluate_rules

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import RuleSpec, RunConfig
    from sustemporal.explanation.counterfactual_contexto import ContextoContrafactual

__all__ = ["InsumoCadastralInvalido", "RevalidacaoFalhou", "Sobreposicao"]

logger = logging.getLogger(__name__)

_PF = "cnes_estab_cbo.v1"
_ST = "cnes_estabelecimento.v1"
_TABELAS = {_PF: "sobreposicao_pf", _ST: "sobreposicao_st"}
_INTEIROS_FISICOS = frozenset(
    {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT"}
)


def _tipo_compativel(tipo: TipoCanonico, fisico: str | None) -> bool:
    """Mesma regra do motor (`rules/preparo.py`): inteiro de qualquer largura; texto VARCHAR."""
    if tipo is TipoCanonico.INTEIRO:
        return fisico in _INTEIROS_FISICOS
    return tipo is TipoCanonico.TEXTO and fisico == "VARCHAR"


class InsumoCadastralInvalido(ValueError):
    """Cadastro CNES ilegível ou com conteúdo divergente do `DatasetRef` (falha operacional)."""


class RevalidacaoFalhou(ValueError):
    """O motor não concluiu a avaliação da sobreposição (falha operacional, não inconclusão)."""


@dataclass(frozen=True)
class _Editavel:
    original: DatasetRef
    tabela: str
    colunas: tuple[str, ...]
    artefato: str
    integro: bool


def _copiar(ref: DatasetRef, destino: Path) -> DatasetRef:
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / f"{ref.dataset_id}.parquet"
    shutil.copyfile(ref.caminho, alvo)
    return ref.model_copy(update={"caminho": str(alvo)})


class Sobreposicao:
    """Estado hipotético dos cadastros na competência `competencia`, isolado em `raiz`."""

    def __init__(
        self,
        contexto: ContextoContrafactual,
        config: RunConfig,
        raiz: Path,
        *,
        competencia: str | None,
        artefatos: dict[str, tuple[str, ...]],
    ) -> None:
        self._contexto = contexto
        self._config = config
        self._raiz = raiz
        self.competencia = competencia
        self._con = conectar(config.runtime, temporario=raiz / "duckdb")
        self._alterados: set[str] = set()
        self._avaliacoes = 0
        try:
            self._isolar(artefatos)
        except BaseException:
            self._con.close()
            raise

    def _isolar(self, artefatos: dict[str, tuple[str, ...]]) -> None:
        contexto = self._contexto
        entrada = self._raiz / "entrada"
        insumos = contexto.insumos
        self._dataset = _copiar(contexto.dataset, entrada)
        self._insumos = replace(
            insumos,
            auxiliares=tuple(_copiar(d, entrada) for d in insumos.auxiliares),
            selecoes=_copiar(insumos.selecoes, entrada) if insumos.selecoes else None,
            cobertura=_copiar(insumos.cobertura, entrada) if insumos.cobertura else None,
        )
        cadastros = [_copiar(d, entrada) for d in contexto.cadastros]
        self._editaveis = self._preparar_editaveis(
            [*self._insumos.auxiliares, *cadastros], artefatos
        )
        for editavel in self._editaveis.values():
            projecao = ", ".join(
                identificador_seguro(c, editavel.colunas) for c in editavel.colunas
            )
            self._con.execute(
                f"CREATE TEMP TABLE {editavel.tabela}_observada AS "  # noqa: S608
                f"SELECT {projecao} FROM read_parquet($c)",
                {"c": editavel.original.caminho},
            )

    def fechar(self) -> None:
        self._con.close()

    def __enter__(self) -> Sobreposicao:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()

    def _preparar_editaveis(
        self, conjuntos: list[DatasetRef], artefatos: dict[str, tuple[str, ...]]
    ) -> dict[str, _Editavel]:
        editaveis: dict[str, _Editavel] = {}
        for schema_id, tabela in _TABELAS.items():
            refs = [d for d in conjuntos if d.schema_id == schema_id]
            if len({d.dataset_id for d in refs}) != 1 or self.competencia is None:
                continue
            editavel = self._editavel(refs[0], tabela, artefatos.get(schema_id, ()))
            if editavel is not None:
                editaveis[schema_id] = editavel
        return editaveis

    def _editavel(
        self, ref: DatasetRef, tabela: str, selecionados: tuple[str, ...]
    ) -> _Editavel | None:
        fisicos = self._conferir(ref)
        esquema = carregar_esquema(ref.schema_id)
        colunas = tuple(c.nome for c in esquema.colunas)
        if not all(_tipo_compativel(c.tipo, fisicos.get(c.nome)) for c in esquema.colunas):
            logger.warning("sobreposicao_leiaute_incompativel schema=%s", ref.schema_id)
            return None
        artefato = self._artefato(ref, selecionados)
        if artefato is None:
            logger.warning("sobreposicao_sem_versao_unica schema=%s", ref.schema_id)
            return None
        estado = self._contexto.insumos.integridade.get(artefato, EstadoIntegridade.NAO_VERIFICADO)
        if estado.value.startswith("QUARENTENA_"):
            logger.warning("sobreposicao_versao_em_quarentena schema=%s", ref.schema_id)
            return None
        integro = estado is EstadoIntegridade.OK
        return _Editavel(ref, tabela, colunas, artefato, integro)

    def _conferir(self, ref: DatasetRef) -> dict[str, str]:
        """Conteúdo contra o `DatasetRef` e tipos físicos; ilegível é falha operacional."""
        try:
            verificar_conteudo(self._con, ref)
            descricao = self._con.execute(
                "DESCRIBE SELECT * FROM read_parquet($c)", {"c": ref.caminho}
            ).fetchall()
        except (ConteudoDivergente, duckdb.Error) as erro:
            raise InsumoCadastralInvalido(
                f"contrafactual_cadastro_invalido schema={ref.schema_id} erro={erro}"
            ) from erro
        return {str(linha[0]): str(linha[1]) for linha in descricao}

    def _artefato(self, ref: DatasetRef, selecionados: tuple[str, ...]) -> str | None:
        candidatos = set(selecionados)
        if not candidatos:
            linhas = self._con.execute(
                "SELECT DISTINCT artifact_id FROM read_parquet($c) "
                "WHERE competencia_arquivo = $competencia",
                {"c": ref.caminho, "competencia": self.competencia},
            ).fetchall()
            candidatos = {str(linha[0]) for linha in linhas}
        if len(candidatos) != 1 or not candidatos <= set(ref.artifact_ids):
            return None
        return candidatos.pop()

    def editavel(self, schema_id: str) -> bool:
        return schema_id in self._editaveis

    def reiniciar(self) -> None:
        """Volta ao estado observado (tabela carregada uma vez da cópia, colunas do esquema)."""
        for editavel in self._editaveis.values():
            self._con.execute(
                f"CREATE OR REPLACE TEMP TABLE {editavel.tabela} AS "  # noqa: S608
                f"SELECT * FROM {editavel.tabela}_observada"
            )
        self._alterados.clear()

    def _escopo(self, schema_id: str) -> tuple[_Editavel, dict[str, str]]:
        editavel = self._editaveis[schema_id]
        filtro = {"competencia": str(self.competencia), "artefato": editavel.artefato}
        return editavel, filtro

    def contagem_pf(self, cnes: str, cbo: str) -> int:
        if not self.editavel(_PF):
            return 0
        editavel, filtro = self._escopo(_PF)
        linhas = self._con.execute(
            f"SELECT coalesce(sum(n_vinculos), 0) FROM {editavel.tabela} "  # noqa: S608
            "WHERE competencia_arquivo = $competencia AND artifact_id = $artefato "
            "AND cnes = $cnes AND cbo = $cbo",
            filtro | {"cnes": cnes, "cbo": cbo},
        ).fetchall()
        return int(linhas[0][0])

    def cbos_com_vinculo(self, cnes: str) -> list[str]:
        if not self.editavel(_PF):
            return []
        editavel, filtro = self._escopo(_PF)
        linhas = self._con.execute(
            f"SELECT DISTINCT cbo FROM {editavel.tabela} "  # noqa: S608
            "WHERE competencia_arquivo = $competencia AND artifact_id = $artefato "
            "AND cnes = $cnes AND n_vinculos > 0 ORDER BY cbo",
            filtro | {"cnes": cnes},
        ).fetchall()
        return [str(linha[0]) for linha in linhas]

    def estabelecimento_no_st(self, cnes: str) -> bool | None:
        """Presença observada; ausência só com versão `OK`; senão `None` (indeterminado)."""
        if not self.editavel(_ST):
            return None
        editavel, filtro = self._escopo(_ST)
        linhas = self._con.execute(
            f"SELECT count(*) FROM {editavel.tabela} "  # noqa: S608
            "WHERE competencia_arquivo = $competencia AND artifact_id = $artefato "
            "AND cnes = $cnes",
            filtro | {"cnes": cnes},
        ).fetchall()
        if int(linhas[0][0]) > 0:
            return True
        return False if editavel.integro else None

    def somar_pf(self, cnes: str, cbo: str, delta: int) -> None:
        """Aplica `delta` ao total do par (linhas repetidas viram uma linha com o total)."""
        editavel, filtro = self._escopo(_PF)
        chave = filtro | {"cnes": cnes, "cbo": cbo}
        total = self.contagem_pf(cnes, cbo) + delta
        self._con.execute(
            f"DELETE FROM {editavel.tabela} WHERE competencia_arquivo = $competencia "  # noqa: S608
            "AND artifact_id = $artefato AND cnes = $cnes AND cbo = $cbo",
            chave,
        )
        if total > 0:
            self._con.execute(
                f"INSERT INTO {editavel.tabela} (competencia_arquivo, cnes, cbo, artifact_id, "  # noqa: S608
                "n_vinculos) VALUES ($competencia, $cnes, $cbo, $artefato, $total)",
                chave | {"total": total},
            )
        self._alterados.add(_PF)

    def incluir_st(self, cnes: str) -> None:
        editavel, filtro = self._escopo(_ST)
        self._con.execute(
            f"INSERT INTO {editavel.tabela} (competencia_arquivo, cnes, artifact_id) "  # noqa: S608
            "VALUES ($competencia, $cnes, $artefato)",
            filtro | {"cnes": cnes},
        )
        self._alterados.add(_ST)

    def _materializar(self, schema_id: str, destino: Path) -> DatasetRef:
        editavel = self._editaveis[schema_id]
        projecao = ", ".join(identificador_seguro(c, editavel.colunas) for c in editavel.colunas)
        caminho = destino / f"{editavel.tabela}.parquet"
        self._con.sql(
            f"SELECT {projecao} FROM {editavel.tabela} ORDER BY ALL"  # noqa: S608
        ).write_parquet(str(caminho))
        hash_logico = hash_logico_relacao(self._con, editavel.tabela, editavel.colunas)
        linhas = self._con.execute(f"SELECT count(*) FROM {editavel.tabela}").fetchall()  # noqa: S608
        original = editavel.original
        dados = original.model_dump(mode="json") | {
            "dataset_id": calcular_dataset_id(schema_id, hash_logico, original.artifact_ids),
            "caminho": str(caminho),
            "hash_logico": hash_logico,
            "linhas": int(linhas[0][0]),
            "produzido_por": "contrafactual_sobreposicao",
            "reconciliacao": None,
            "multiplicidade": None,
        }
        ref = DatasetRef.model_validate(dados)
        verificar_conteudo(self._con, ref)
        return ref

    def avaliar(self, regras: list[RuleSpec]) -> dict[tuple[str, str], str]:
        """Grava as tabelas alteradas e reavalia `regras` em todos os registros pelo motor.

        Raises:
            RevalidacaoFalhou: execução do motor com falha operacional.
        """
        self._avaliacoes += 1
        destino = self._raiz / f"avaliacao_{self._avaliacoes:06d}"
        destino.mkdir(parents=True)
        novos = {s: self._materializar(s, destino) for s in sorted(self._alterados)}
        auxiliares = tuple(novos.get(d.schema_id, d) for d in self._insumos.auxiliares)
        resultado = evaluate_rules(
            self._dataset,
            self._contexto.snapshots,
            regras,
            self._config,
            destino / "saida",
            insumos=replace(self._insumos, auxiliares=auxiliares),
            relogio=self._contexto.relogio,
        )
        if resultado.estado is not EstadoExecucao.CONCLUIDA:
            raise RevalidacaoFalhou(
                f"contrafactual_revalidacao_falhou run={resultado.run_id} "
                f"estado={resultado.estado} falhas={resultado.falhas}"
            )
        caminho = next(r.caminho for r in resultado.saidas if r.schema_id == "avaliacoes.v1")
        linhas = self._con.execute(
            "SELECT row_id, rule_id, estado FROM read_parquet($c)", {"c": caminho}
        ).fetchall()
        shutil.rmtree(destino)
        return {(str(row), str(rule)): str(estado) for row, rule, estado in linhas}
