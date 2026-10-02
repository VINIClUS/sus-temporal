"""Download verificável e promoção atômica de artefatos (T02)."""

from __future__ import annotations

import contextlib
import io
import logging
import os
import secrets
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from sustemporal.acquisition.manifest import Manifesto, ManifestoCorrompido
from sustemporal.acquisition.transport import (
    ErroTransporte,
    LimiteExcedido,
    Recebimento,
    RecursoNaoEncontrado,
    TransferenciaInterrompida,
    transportes_padrao,
)
from sustemporal.acquisition.validation import Veredito, validar_conteudo
from sustemporal.contracts.artifacts import (
    ArtifactObservation,
    ArtifactVersion,
    EstadoIntegridade,
    FormatoArquivo,
    MetadadosRemotos,
    ResultadoTentativa,
    SourceRequest,
    TipoConteudo,
    calcular_artifact_id,
)
from sustemporal.errors import FalhaOperacionalErro, RedeProibida
from sustemporal.hashing import sha256_arquivo
from sustemporal.store import caminho_conteudo, promover_sem_sobrescrever

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from typing import BinaryIO

    from sustemporal.acquisition.transport import Transporte

__all__ = ["AREA_QUARENTENA", "NOME_MANIFESTO", "agora_utc", "fetch_source", "nomes_listados"]

logger = logging.getLogger(__name__)

NOME_MANIFESTO = "manifesto.jsonl"
AREA_QUARENTENA = "quarentena"
_ESQUEMAS_DE_REDE = {"ftp", "https"}
_EXTENSOES = {
    FormatoArquivo.DBC: "dbc",
    FormatoArquivo.DBF: "dbf",
    FormatoArquivo.ZIP: "zip",
    FormatoArquivo.TXT: "txt",
    FormatoArquivo.CSV: "csv",
    FormatoArquivo.PDF: "pdf",
    FormatoArquivo.HTML: "html",
    FormatoArquivo.YAML: "yaml",
    FormatoArquivo.OUTRO: "bin",
}


def agora_utc() -> datetime:
    return datetime.now(UTC)


def _ferramenta(esquema: str) -> str:
    try:
        versao = metadata.version("sustemporal")
    except metadata.PackageNotFoundError:
        versao = "desconhecida"
    return f"sustemporal/{versao} transporte={esquema}"


@dataclass(frozen=True)
class _Tentativa:
    request: SourceRequest
    store: Path
    manifesto: Manifesto
    relogio: Callable[[], datetime]
    esquema: str

    def registrar(
        self,
        resultado: ResultadoTentativa,
        versao: ArtifactVersion | None = None,
        **campos: Any,
    ) -> ArtifactObservation:
        observacao = ArtifactObservation(
            observation_id=f"obs_{secrets.token_hex(16)}",
            chave=self.request.chave,
            request_sha256=self.request.sha256(),
            observado_em=self.relogio(),
            resultado=resultado,
            ferramenta=_ferramenta(self.esquema),
            localizador=self.request.localizador,
            **campos,
        )
        self.manifesto.registrar(observacao, versao)
        return observacao


class FalhaDestinoLocal(Exception):
    """Falha de E/S no temporário local; não é falha do transporte nem da fonte."""


class _DestinoLocal:
    """Envolve o temporário: OSError de escrita local vira `FalhaDestinoLocal`.

    Não herda de OSError, então os transportes não a confundem com erro de rede.
    """

    def __init__(self, arquivo: BinaryIO) -> None:
        self._arquivo = arquivo

    def _local(self, operacao: str, erro: OSError) -> FalhaDestinoLocal:
        return FalhaDestinoLocal(f"temporario_falhou operacao={operacao} erro={erro}")

    def write(self, dados: bytes) -> int:
        try:
            return self._arquivo.write(dados)
        except OSError as erro:
            raise self._local("write", erro) from erro

    def sincronizar(self) -> None:
        try:
            self._arquivo.flush()
            os.fsync(self._arquivo.fileno())
        except OSError as erro:
            raise self._local("fsync", erro) from erro
        except io.UnsupportedOperation:
            return


def _abrir_temporario(caminho: Path) -> BinaryIO:
    return caminho.open("wb")


@contextlib.contextmanager
def _temporario_local(caminho: Path) -> Iterator[_DestinoLocal]:
    """Abre e fecha o temporário tratando qualquer OSError local como falha de armazenamento."""
    try:
        arquivo = _abrir_temporario(caminho)
    except OSError as erro:
        raise FalhaDestinoLocal(f"temporario_falhou operacao=open erro={erro}") from erro
    try:
        yield _DestinoLocal(arquivo)
    finally:
        try:
            arquivo.close()
        except OSError as erro:
            raise FalhaDestinoLocal(f"temporario_falhou operacao=close erro={erro}") from erro


def _receber(tentativa: _Tentativa, transporte: Transporte, temporario: Path) -> Recebimento:
    request = tentativa.request
    limite = request.tamanho_maximo_bytes
    with _temporario_local(temporario) as destino:
        if request.chave.tipo_conteudo is TipoConteudo.LISTAGEM_DIRETORIO:
            nomes = transporte.listar(request.localizador)
            conteudo = "".join(f"{nome}\n" for nome in sorted(nomes)).encode("utf-8")
            if len(conteudo) > limite:
                raise LimiteExcedido(f"tamanho_maximo_excedido limite={limite}")
            destino.write(conteudo)
            recebimento = Recebimento(len(conteudo), None, {"entradas": str(len(nomes))})
        else:
            recebimento = transporte.baixar(request.localizador, destino, limite)
        destino.sincronizar()
    return recebimento


def _resultado_do_erro(erro: Exception) -> ResultadoTentativa:
    if isinstance(erro, RecursoNaoEncontrado):
        return ResultadoTentativa.NAO_ENCONTRADO
    if isinstance(erro, LimiteExcedido):
        return ResultadoTentativa.CONTEUDO_INVALIDO
    recebidos = getattr(erro, "recebidos", 0)
    if isinstance(erro, TransferenciaInterrompida) or recebidos:
        return ResultadoTentativa.INTERROMPIDO
    return ResultadoTentativa.FALHA_TRANSPORTE


def _registrar_falha(tentativa: _Tentativa, erro: Exception) -> ArtifactObservation:
    resultado = _resultado_do_erro(erro)
    sem_bytes = resultado is ResultadoTentativa.NAO_ENCONTRADO
    recebidos = 0 if sem_bytes else int(getattr(erro, "recebidos", 0))
    logger.info("aquisicao_falhou resultado=%s erro=%s", resultado, erro)
    return tentativa.registrar(resultado, bytes_recebidos=recebidos, erro=str(erro) or repr(erro))


def _promover(tentativa: _Tentativa, temporario: Path, area: Path, sha256: str) -> Path:
    extensao = _EXTENSOES[tentativa.request.formato_esperado]
    destino = caminho_conteudo(area, sha256, extensao)
    promover_sem_sobrescrever(temporario, destino)
    return destino


def _versao(
    tentativa: _Tentativa, sha256: str, tamanho: int, veredito: Veredito, destino: Path
) -> ArtifactVersion:
    request = tentativa.request
    return ArtifactVersion(
        artifact_id=calcular_artifact_id(request.chave, sha256),
        chave=request.chave,
        localizador=request.localizador,
        sha256=sha256,
        tamanho_bytes=tamanho,
        formato=request.formato_esperado,
        caminho_conteudo=destino.relative_to(tentativa.store).as_posix(),
        integridade=veredito.integridade,
        membros=veredito.membros,
    )


def _guardar(
    tentativa: _Tentativa, temporario: Path, recebimento: Recebimento
) -> ArtifactObservation:
    """Hash, validação, promoção e versão; qualquer falha inesperada ainda vira observação."""
    try:
        return _guardar_validado(tentativa, temporario, recebimento)
    except ManifestoCorrompido:
        raise
    except Exception as erro:
        mensagem = f"guarda_falhou erro={type(erro).__name__}: {erro}"
        logger.error("aquisicao_guarda_falhou erro=%s", mensagem)
        return tentativa.registrar(
            ResultadoTentativa.FALHA_ARMAZENAMENTO,
            bytes_recebidos=recebimento.bytes_recebidos,
            erro=mensagem,
        )


def _guardar_validado(
    tentativa: _Tentativa, temporario: Path, recebimento: Recebimento
) -> ArtifactObservation:
    request = tentativa.request
    sha256 = sha256_arquivo(temporario)
    campos: dict[str, Any] = {
        "sha256_obtido": sha256,
        "bytes_recebidos": recebimento.bytes_recebidos,
        "metadados_remotos": MetadadosRemotos(brutos=recebimento.metadados),
    }
    quarentena = tentativa.store / AREA_QUARENTENA
    esperado = request.sha256_esperado
    try:
        if esperado is not None and sha256 != esperado:
            _promover(tentativa, temporario, quarentena, sha256)
            erro = f"checksum_divergente esperado={esperado} obtido={sha256}"
            return tentativa.registrar(
                ResultadoTentativa.CONTEUDO_INVALIDO,
                erro=erro,
                integridade=EstadoIntegridade.QUARENTENA_CHECKSUM,
                formato=request.formato_esperado,
                **campos,
            )
        veredito = validar_conteudo(temporario, request.formato_esperado)
        area = quarentena if veredito.em_quarentena else tentativa.store
        destino = _promover(tentativa, temporario, area, sha256)
    except FalhaOperacionalErro as falha:
        logger.error("aquisicao_armazenamento_falhou erro=%s", falha)
        return tentativa.registrar(
            ResultadoTentativa.FALHA_ARMAZENAMENTO, erro=str(falha), **campos
        )
    versao = _versao(tentativa, sha256, recebimento.bytes_recebidos, veredito, destino)
    resultado = (
        ResultadoTentativa.CONTEUDO_INVALIDO
        if veredito.em_quarentena
        else ResultadoTentativa.OBTIDO
    )
    return tentativa.registrar(
        resultado,
        versao,
        artifact_id=versao.artifact_id,
        erro=veredito.motivo,
        integridade=veredito.integridade,
        formato=request.formato_esperado,
        **campos,
    )


def _executar(
    tentativa: _Tentativa, transporte: Transporte, temporario: Path
) -> ArtifactObservation:
    try:
        recebimento = _receber(tentativa, transporte, temporario)
    except FalhaDestinoLocal as local:
        logger.error("aquisicao_temporario_falhou erro=%s", local)
        return tentativa.registrar(ResultadoTentativa.FALHA_ARMAZENAMENTO, erro=str(local))
    except Exception as erro:
        return _registrar_falha(tentativa, erro)
    anunciado = recebimento.tamanho_anunciado
    if anunciado is not None and anunciado != recebimento.bytes_recebidos:
        divergente = TransferenciaInterrompida(
            f"tamanho_divergente_do_anunciado anunciado={anunciado} "
            f"recebido={recebimento.bytes_recebidos}",
            recebimento.bytes_recebidos,
        )
        return _registrar_falha(tentativa, divergente)
    return _guardar(tentativa, temporario, recebimento)


def _recusar_offline(tentativa: _Tentativa) -> RedeProibida:
    mensagem = f"rede_proibida localizador={tentativa.request.localizador}"
    tentativa.registrar(ResultadoTentativa.RECUSADO_OFFLINE, erro=mensagem)
    return RedeProibida(mensagem)


def _novo_temporario(store: Path) -> Path:
    pasta = store / "tmp"
    pasta.mkdir(parents=True, exist_ok=True)
    descritor, nome = tempfile.mkstemp(prefix="baixando_", dir=pasta)
    os.close(descritor)
    return Path(nome)


def fetch_source(
    request: SourceRequest,
    store: Path,
    *,
    rede_permitida: bool = False,
    relogio: Callable[[], datetime] = agora_utc,
    transportes: Mapping[str, Transporte] | None = None,
    manifesto: Path | None = None,
) -> ArtifactObservation:
    """Obtém uma fonte e registra a observação da tentativa, inclusive quando falha.

    O instante observado vem do relógio ao fim da tentativa; metadados remotos ficam brutos.

    Raises:
        RedeProibida: ftp/https com `rede_permitida` falso (a recusa fica registrada).
        ManifestoCorrompido: o manifesto existente não passa na verificação.
    """
    esquema = urlsplit(request.localizador).scheme
    caminho_manifesto = manifesto or store / NOME_MANIFESTO
    tentativa = _Tentativa(request, store, Manifesto(caminho_manifesto), relogio, esquema)
    tentativa.manifesto.preparar()
    if esquema in _ESQUEMAS_DE_REDE and not rede_permitida:
        raise _recusar_offline(tentativa)
    transporte = (transportes_padrao() if transportes is None else transportes).get(esquema)
    if transporte is None:
        ausente = ErroTransporte(f"transporte_ausente esquema={esquema}")
        return _registrar_falha(tentativa, ausente)
    try:
        temporario = _novo_temporario(store)
    except OSError as erro:
        mensagem = f"temporario_falhou erro={erro}"
        return tentativa.registrar(ResultadoTentativa.FALHA_ARMAZENAMENTO, erro=mensagem)
    try:
        return _executar(tentativa, transporte, temporario)
    except (KeyboardInterrupt, SystemExit) as interrupcao:
        recebidos = temporario.stat().st_size if temporario.exists() else 0
        sinal = type(interrupcao).__name__
        _registrar_falha(
            tentativa, TransferenciaInterrompida(f"interrompido sinal={sinal}", recebidos)
        )
        raise
    finally:
        temporario.unlink(missing_ok=True)


def nomes_listados(store: Path, observacao: ArtifactObservation) -> list[str]:
    """Nomes de uma listagem de diretório obtida, lidos dos bytes guardados e conferidos.

    Raises:
        ValueError: a observação não é uma listagem obtida.
        FalhaOperacionalErro: os bytes guardados não conferem com o hash observado.
    """
    listagem = observacao.chave.tipo_conteudo is TipoConteudo.LISTAGEM_DIRETORIO
    obtida = observacao.resultado is ResultadoTentativa.OBTIDO
    if not (listagem and obtida and observacao.sha256_obtido):
        raise ValueError(f"observacao_nao_e_listagem_obtida id={observacao.observation_id}")
    caminho = caminho_conteudo(store, observacao.sha256_obtido, _EXTENSOES[FormatoArquivo.TXT])
    if sha256_arquivo(caminho) != observacao.sha256_obtido:
        raise FalhaOperacionalErro(f"listagem_divergente caminho={caminho}")
    return caminho.read_text(encoding="utf-8").splitlines()
