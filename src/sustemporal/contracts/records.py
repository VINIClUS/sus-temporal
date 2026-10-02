"""Leiautes, esquemas canônicos, referências de tabelas, registros de produção e rótulos."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, StringConstraints, model_validator

from sustemporal.contracts.artifacts import ArtifactId
from sustemporal.contracts.base import (
    Booleano,
    CodigoCBO,
    CodigoCNES,
    CodigoMunicipio6,
    CodigoProcedimento,
    Confirmacao,
    ContratoBase,
    DatasetId,
    DocRef,
    FamiliaFonte,
    Identificador,
    InteiroNaoNegativo,
    OrigemDados,
    Proveniencia,
    ValorMonetario,
    ValorNormalizado,
    hash_canonico,
)
from sustemporal.contracts.temporal import (
    CompetenciaArquivo,
    CompetenciaAtendimento,
    CompetenciaProcessamento,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    "CampoLeiaute",
    "CodigoRotulo",
    "ColunaCanonica",
    "DatasetRef",
    "EsquemaCanonico",
    "FormatoLeiaute",
    "HashLogico",
    "LayoutSpec",
    "Multiplicidade",
    "PapelColuna",
    "ProductionRecord",
    "Reconciliacao",
    "RegistroRotulo",
    "RowId",
    "RowLocator",
    "SchemaId",
    "TipoCanonico",
    "calcular_dataset_id",
]

RowId = Annotated[str, StringConstraints(pattern=r"^art_[0-9a-f]{64}(/[^#\s]+)?#[0-9]+$")]
SchemaId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+\.v[0-9]+$")]
HashLogico = Annotated[str, StringConstraints(pattern=r"^lh1:[0-9a-f]{64}$")]
NomeColuna = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]


class TipoCanonico(StrEnum):
    TEXTO = "TEXTO"
    INTEIRO = "INTEIRO"
    DECIMAL = "DECIMAL"
    DATA = "DATA"
    BOOLEANO = "BOOLEANO"


class PapelColuna(StrEnum):
    CHAVE = "CHAVE"
    LINHAGEM = "LINHAGEM"
    ATRIBUTO = "ATRIBUTO"
    ROTULO = "ROTULO"
    DIAGNOSTICO = "DIAGNOSTICO"
    BRUTO = "BRUTO"
    MOTIVO = "MOTIVO"


class FormatoLeiaute(StrEnum):
    DBF = "DBF"
    LARGURA_FIXA = "LARGURA_FIXA"


class CampoLeiaute(ContratoBase):
    nome_fisico: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    tipo_fisico: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    largura: InteiroNaoNegativo
    decimais: InteiroNaoNegativo = 0
    inicio: InteiroNaoNegativo | None = None
    nome_canonico: NomeColuna
    tipo_canonico: TipoCanonico
    papel: PapelColuna
    obrigatorio: Booleano = False

    @model_validator(mode="after")
    def _coerencia(self) -> CampoLeiaute:
        if self.largura < 1:
            raise ValueError(f"campo_largura_invalida campo={self.nome_fisico}")
        codigo = self.papel in {PapelColuna.CHAVE, PapelColuna.LINHAGEM}
        if codigo and self.tipo_canonico is not TipoCanonico.TEXTO:
            raise ValueError(f"campo_codigo_deve_ser_texto campo={self.nome_fisico}")
        return self


class LayoutSpec(ContratoBase):
    layout_id: Identificador
    fonte: FamiliaFonte
    versao: str
    codificacao: str
    formato: FormatoLeiaute
    campos: tuple[CampoLeiaute, ...]
    valido_de: CompetenciaArquivo | None = None
    valido_ate: CompetenciaArquivo | None = None
    proveniencia: Proveniencia
    confirmacao: Confirmacao = Confirmacao.A_CONFIRMAR
    documento: DocRef | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> LayoutSpec:
        fisicos = [campo.nome_fisico for campo in self.campos]
        canonicos = [campo.nome_canonico for campo in self.campos]
        if not fisicos or len(set(fisicos)) != len(fisicos):
            raise ValueError(f"leiaute_campos_vazios_ou_repetidos layout={self.layout_id}")
        if len(set(canonicos)) != len(canonicos):
            raise ValueError(f"leiaute_nome_canonico_repetido layout={self.layout_id}")
        if self.valido_de and self.valido_ate and self.valido_ate < self.valido_de:
            raise ValueError(f"leiaute_vigencia_invertida layout={self.layout_id}")
        return self


class ColunaCanonica(ContratoBase):
    nome: NomeColuna
    tipo: TipoCanonico
    papel: PapelColuna
    anulavel: Booleano = True
    descricao: str = ""


class EsquemaCanonico(ContratoBase):
    schema_id: SchemaId
    descricao: str
    chave: tuple[NomeColuna, ...]
    colunas: tuple[ColunaCanonica, ...]

    @model_validator(mode="after")
    def _coerencia(self) -> EsquemaCanonico:
        nomes = [coluna.nome for coluna in self.colunas]
        if len(set(nomes)) != len(nomes):
            raise ValueError(f"esquema_coluna_repetida schema={self.schema_id}")
        if not self.chave or not set(self.chave) <= set(nomes):
            raise ValueError(f"esquema_chave_invalida schema={self.schema_id}")
        por_nome = {coluna.nome: coluna for coluna in self.colunas}
        if any(por_nome[nome].anulavel for nome in self.chave):
            raise ValueError(f"esquema_chave_anulavel schema={self.schema_id}")
        return self

    def colunas_com_papel(self, papel: PapelColuna) -> tuple[str, ...]:
        return tuple(coluna.nome for coluna in self.colunas if coluna.papel is papel)

    def papel_de(self, nome: str) -> PapelColuna:
        for coluna in self.colunas:
            if coluna.nome == nome:
                return coluna.papel
        return PapelColuna.DIAGNOSTICO

    @classmethod
    def de_yaml(cls, caminho: Path) -> EsquemaCanonico:
        from sustemporal.yamlio import carregar_yaml

        return cls.model_validate(carregar_yaml(caminho))


class Reconciliacao(ContratoBase):
    fisicos: InteiroNaoNegativo
    deletados: InteiroNaoNegativo = 0
    canonicas: InteiroNaoNegativo
    quarentena: InteiroNaoNegativo = 0
    excluidas_por_motivo: dict[str, InteiroNaoNegativo] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sem_perda_inexplicada(self) -> Reconciliacao:
        explicadas = self.canonicas + self.quarentena + sum(self.excluidas_por_motivo.values())
        if explicadas != self.fisicos:
            raise ValueError(f"perda_inexplicada fisicos={self.fisicos} explicadas={explicadas}")
        if self.deletados > self.fisicos:
            raise ValueError("deletados_maior_que_fisicos")
        return self


class Multiplicidade(ContratoBase):
    linhas_totais: InteiroNaoNegativo
    combinacoes_distintas: InteiroNaoNegativo
    max_repeticoes: InteiroNaoNegativo

    @model_validator(mode="after")
    def _possivel(self) -> Multiplicidade:
        linhas, distintas, maximo = (
            self.linhas_totais,
            self.combinacoes_distintas,
            self.max_repeticoes,
        )
        if linhas == 0:
            possivel = distintas == 0 and maximo == 0
        else:
            possivel = (
                1 <= distintas <= linhas
                and 1 <= maximo <= linhas - distintas + 1
                and linhas <= distintas * maximo
            )
        if not possivel:
            raise ValueError(
                f"multiplicidade_impossivel linhas={linhas} distintas={distintas} maximo={maximo}"
            )
        return self


def calcular_dataset_id(schema_id: str, hash_logico: str, artifact_ids: tuple[str, ...]) -> str:
    conteudo = {"schema": schema_id, "hash": hash_logico, "artefatos": sorted(artifact_ids)}
    return f"ds_{hash_canonico(conteudo)}"


class DatasetRef(ContratoBase):
    dataset_id: DatasetId
    schema_id: SchemaId
    caminho: str
    hash_logico: HashLogico
    linhas: InteiroNaoNegativo
    artifact_ids: tuple[ArtifactId, ...]
    origem_dados: OrigemDados
    produzido_por: str
    reconciliacao: Reconciliacao | None = None
    multiplicidade: Multiplicidade | None = None

    @model_validator(mode="after")
    def _identidade(self) -> DatasetRef:
        esperado = calcular_dataset_id(self.schema_id, self.hash_logico, self.artifact_ids)
        if self.dataset_id != esperado:
            raise ValueError(f"dataset_id_nao_corresponde dataset_id={self.dataset_id}")
        canonicas = self.reconciliacao.canonicas if self.reconciliacao else self.linhas
        totais = self.multiplicidade.linhas_totais if self.multiplicidade else self.linhas
        if canonicas != self.linhas or totais != self.linhas:
            raise ValueError(
                f"dataset_contagens_divergentes dataset_id={self.dataset_id} linhas={self.linhas}"
            )
        return self


class RowLocator(ContratoBase):
    artifact_id: ArtifactId
    membro: Annotated[str, StringConstraints(pattern=r"^[^#\s/]+$")] | None = None
    indice: InteiroNaoNegativo
    deletado: Booleano = False

    def row_id(self) -> str:
        membro = f"/{self.membro}" if self.membro else ""
        return f"{self.artifact_id}{membro}#{self.indice}"


class ProductionRecord(ContratoBase):
    row_id: RowId
    origem: RowLocator
    cnes: CodigoCNES | None = None
    municipio_estabelecimento: CodigoMunicipio6 | None = None
    competencia_atendimento: CompetenciaAtendimento | None = None
    competencia_processamento: CompetenciaProcessamento | None = None
    instrumento: ValorNormalizado
    procedimento: CodigoProcedimento | None = None
    cbo: CodigoCBO | None = None
    atributos: dict[str, ValorNormalizado] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _identidade(self) -> ProductionRecord:
        if self.row_id != self.origem.row_id():
            raise ValueError(f"row_id_incoerente_com_origem row_id={self.row_id}")
        return self

    @classmethod
    def filtrar_atributos(
        cls, valores: Mapping[str, ValorNormalizado], esquema: EsquemaCanonico
    ) -> dict[str, ValorNormalizado]:
        return {
            nome: valor
            for nome, valor in valores.items()
            if esquema.papel_de(nome) is PapelColuna.ATRIBUTO
        }


class CodigoRotulo(StrEnum):
    NAO_APROVADO = "NAO_APROVADO"
    APROVADO_TOTAL = "APROVADO_TOTAL"
    APROVADO_PARCIAL = "APROVADO_PARCIAL"
    DESCONHECIDO = "DESCONHECIDO"


class RegistroRotulo(ContratoBase):
    row_id: RowId
    pa_indica_bruto: str | None
    rotulo: CodigoRotulo
    codebook: DocRef
    quantidade_apresentada: InteiroNaoNegativo | None = None
    quantidade_aprovada: InteiroNaoNegativo | None = None
    valor_apresentado: ValorMonetario | None = None
    valor_aprovado: ValorMonetario | None = None
    contradicoes: tuple[str, ...] = ()
