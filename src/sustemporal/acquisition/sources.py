"""Catálogo de fontes e plano de requisições em duas passadas."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Annotated, Literal
from urllib.parse import quote, urlsplit

from pydantic import StringConstraints, ValidationError, model_validator

from sustemporal.contracts.artifacts import (
    ChaveArtefato,
    FormatoArquivo,
    MotivoRequisicao,
    SourceRequest,
    TipoConteudo,
)
from sustemporal.contracts.base import (
    Booleano,
    CanalPublicacao,
    Confirmacao,
    ContratoBase,
    FamiliaFonte,
    Identificador,
    InteiroNaoNegativo,
    Proveniencia,
)
from sustemporal.contracts.temporal import CompetenciaArquivo
from sustemporal.errors import ConfigInvalida
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from sustemporal.contracts.temporal import CompetenciaAtendimento, CompetenciaProcessamento

__all__ = [
    "CatalogoFontes",
    "DocumentoCatalogo",
    "FonteCatalogo",
    "carregar_catalogo",
    "competencias_auxiliares",
    "requisicao_listagem",
    "requisicoes_da_listagem",
    "requisicoes_documentos",
]

logger = logging.getLogger(__name__)

TAMANHO_MAXIMO_LISTAGEM = 16 * 1024 * 1024
_TAMANHO_MAXIMO_DOCUMENTO = 64 * 1024 * 1024
_MARCADORES = ("{uf}", "{aamm}", "{aaaamm}")


class FonteCatalogo(ContratoBase):
    fonte: FamiliaFonte
    diretorio: Annotated[str, StringConstraints(pattern=r"^(ftp|https|file)://\S+/$")]
    padrao_nome: str
    formato: FormatoArquivo
    canal: CanalPublicacao
    multipartes: Booleano = False
    tamanho_maximo_bytes: InteiroNaoNegativo
    proveniencia: Proveniencia
    confirmacao: Confirmacao
    referencias: tuple[str, ...] = ()
    observacao: str | None = None

    @model_validator(mode="after")
    def _padrao(self) -> FonteCatalogo:
        try:
            re.compile(self._substituir("SP", "201801"))
        except re.error as erro:
            raise ValueError(f"padrao_nome_invalido fonte={self.fonte} erro={erro}") from erro
        if "{aamm}" not in self.padrao_nome and "{aaaamm}" not in self.padrao_nome:
            raise ValueError(f"padrao_nome_sem_competencia fonte={self.fonte}")
        return self

    @property
    def por_uf(self) -> bool:
        return "{uf}" in self.padrao_nome

    def _substituir(self, uf: str, competencia: str) -> str:
        valores = (re.escape(uf), re.escape(competencia[2:]), re.escape(competencia))
        padrao = self.padrao_nome
        for marcador, valor in zip(_MARCADORES, valores, strict=True):
            padrao = padrao.replace(marcador, valor)
        return padrao

    def expressao(self, uf: str, competencia: CompetenciaArquivo) -> re.Pattern[str]:
        return re.compile(self._substituir(uf, competencia.valor), re.IGNORECASE)


class DocumentoCatalogo(ContratoBase):
    doc_id: Identificador
    fonte: Literal[FamiliaFonte.DOCUMENTO, FamiliaFonte.TERRITORIO_DRS]
    titulo: str
    localizador: str
    formato: FormatoArquivo
    proveniencia: Proveniencia
    confirmacao: Confirmacao = Confirmacao.A_CONFIRMAR


class CatalogoFontes(ContratoBase):
    versao: Literal["1"]
    fontes: tuple[FonteCatalogo, ...]
    documentos: tuple[DocumentoCatalogo, ...] = ()

    @model_validator(mode="after")
    def _unicas(self) -> CatalogoFontes:
        familias = [f.fonte for f in self.fontes]
        if len(familias) != len(set(familias)):
            raise ValueError("catalogo_fonte_repetida")
        return self

    def fonte(self, familia: FamiliaFonte) -> FonteCatalogo:
        for item in self.fontes:
            if item.fonte is familia:
                return item
        raise ConfigInvalida(f"fonte_fora_do_catalogo fonte={familia}")


def carregar_catalogo(caminho: Path) -> CatalogoFontes:
    """Lê `catalog/sources.yaml` com escalares só texto.

    Raises:
        ConfigInvalida: arquivo ilegível ou fora do modelo.
    """
    try:
        return CatalogoFontes.model_validate(carregar_yaml(caminho))
    except (OSError, ValueError, ValidationError) as erro:
        raise ConfigInvalida(f"catalogo_fontes_invalido caminho={caminho} erro={erro}") from erro


def _ultimo_segmento(localizador: str) -> str:
    segmentos = [s for s in urlsplit(localizador).path.split("/") if s]
    return segmentos[-1] if segmentos else "raiz"


def requisicao_listagem(
    catalogo: CatalogoFontes,
    fonte: FamiliaFonte,
    *,
    motivo: MotivoRequisicao = MotivoRequisicao.PRIMARIA,
) -> SourceRequest:
    """Requisição da listagem do diretório da fonte; o resultado é uma observação própria."""
    item = catalogo.fonte(fonte)
    chave = ChaveArtefato(
        fonte=fonte,
        canal=item.canal,
        nome_original=_ultimo_segmento(item.diretorio),
        tipo_conteudo=TipoConteudo.LISTAGEM_DIRETORIO,
    )
    return SourceRequest(
        chave=chave,
        localizador=item.diretorio,
        formato_esperado=FormatoArquivo.TXT,
        tamanho_maximo_bytes=TAMANHO_MAXIMO_LISTAGEM,
        motivo=motivo,
    )


def _requisicao_do_nome(
    item: FonteCatalogo,
    achado: re.Match[str],
    uf: str | None,
    competencia: CompetenciaArquivo,
    motivo: MotivoRequisicao,
) -> SourceRequest:
    grupos = achado.groupdict()
    parte = grupos.get("parte")
    chave = ChaveArtefato(
        fonte=item.fonte,
        uf=uf,
        competencia_arquivo=competencia,
        parte=parte.lower() if parte else None,
        canal=item.canal,
        nome_original=achado.string,
        versao_publicacao=grupos.get("versao"),
    )
    return SourceRequest(
        chave=chave,
        localizador=f"{item.diretorio}{quote(achado.string)}",
        formato_esperado=item.formato,
        tamanho_maximo_bytes=item.tamanho_maximo_bytes,
        motivo=motivo,
    )


def requisicoes_da_listagem(
    catalogo: CatalogoFontes,
    fonte: FamiliaFonte,
    uf: str,
    competencias: Iterable[CompetenciaArquivo],
    nomes: Iterable[str],
    *,
    motivo: MotivoRequisicao = MotivoRequisicao.PRIMARIA,
) -> list[SourceRequest]:
    """Uma requisição por arquivo listado que casa exatamente com a competência pedida.

    Competência sem arquivo listado não gera requisição (nunca o mês vizinho); fica no log e a
    própria listagem registra a ausência naquele instante.
    """
    item = catalogo.fonte(fonte)
    uf_chave = uf if item.por_uf else None
    listados = sorted(set(nomes))
    requisicoes: list[SourceRequest] = []
    for competencia in sorted(set(competencias)):
        expressao = item.expressao(uf, competencia)
        achados = [a for nome in listados if (a := expressao.fullmatch(nome))]
        if not achados:
            logger.warning(
                "competencia_sem_arquivo_na_listagem fonte=%s competencia=%s", fonte, competencia
            )
        requisicoes += [
            _requisicao_do_nome(item, a, uf_chave, competencia, motivo) for a in achados
        ]
    return requisicoes


def competencias_auxiliares(
    atendimento: Iterable[CompetenciaAtendimento],
    processamento: Iterable[CompetenciaProcessamento],
) -> tuple[CompetenciaArquivo, ...]:
    """Competências de CNES/SIGTAP a obter: as observadas nos registros, sem vizinhas.

    Atendimento e processamento são consultados por políticas diferentes (B_ATEND, B_PROC);
    a união é o que alguma política pode exigir, nunca um mês presumido.
    """
    valores = {c.valor for c in atendimento} | {c.valor for c in processamento}
    return tuple(CompetenciaArquivo(v) for v in sorted(valores))


def requisicoes_documentos(catalogo: CatalogoFontes) -> list[SourceRequest]:
    return [
        SourceRequest(
            chave=ChaveArtefato(
                fonte=documento.fonte,
                canal=CanalPublicacao.ATUAL,
                nome_original=documento.doc_id,
                documento_id=documento.doc_id,
            ),
            localizador=documento.localizador,
            formato_esperado=documento.formato,
            tamanho_maximo_bytes=_TAMANHO_MAXIMO_DOCUMENTO,
            motivo=MotivoRequisicao.DOCUMENTO,
        )
        for documento in catalogo.documentos
    ]
