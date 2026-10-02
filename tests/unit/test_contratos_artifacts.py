from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sustemporal.contracts.artifacts import (
    ArtifactObservation,
    ArtifactVersion,
    ChaveArtefato,
    EstadoIntegridade,
    FormatoArquivo,
    LinhaManifesto,
    MembroArquivo,
    MetadadosRemotos,
    MotivoRequisicao,
    ResultadoTentativa,
    SourceRequest,
    TipoLinhaManifesto,
    calcular_artifact_id,
)
from sustemporal.contracts.base import CanalPublicacao, FamiliaFonte

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_HEX64 = st.from_regex(r"[0-9a-f]{64}", fullmatch=True)
_SEM_CONTEUDO = [
    ResultadoTentativa.NAO_ENCONTRADO,
    ResultadoTentativa.FALHA_TRANSPORTE,
    ResultadoTentativa.INTERROMPIDO,
    ResultadoTentativa.RECUSADO_OFFLINE,
]


def _chave(**campos: object) -> ChaveArtefato:
    base = {
        "fonte": FamiliaFonte.SIA_PA,
        "uf": "SP",
        "competencia_arquivo": "201801",
        "canal": CanalPublicacao.ATUAL,
        "nome_original": "PASP1801.dbc",
    }
    return ChaveArtefato.model_validate(base | campos)


def _versao(sha256: str = _SHA_A, **campos: object) -> ArtifactVersion:
    chave = campos.pop("chave", _chave())
    base = {
        "artifact_id": calcular_artifact_id(chave, sha256),
        "chave": chave,
        "localizador": "ftp://ftp.datasus.gov.br/dissemin/publicos/SIASUS/PASP1801.dbc",
        "sha256": sha256,
        "tamanho_bytes": 1024,
        "formato": FormatoArquivo.DBC,
        "caminho_conteudo": f"data/raw/{sha256}",
        "integridade": EstadoIntegridade.OK,
    }
    return ArtifactVersion.model_validate(base | campos)


def _observacao(**campos: object) -> ArtifactObservation:
    base = {
        "observation_id": f"obs_{'1' * 32}",
        "chave": _chave(),
        "request_sha256": "c" * 64,
        "observado_em": datetime(2026, 9, 1, 12, tzinfo=UTC),
        "resultado": ResultadoTentativa.OBTIDO,
        "artifact_id": calcular_artifact_id(_chave(), _SHA_A),
        "sha256_obtido": _SHA_A,
        "bytes_recebidos": 1024,
        "ferramenta": "sustemporal-0.1.0",
    }
    return ArtifactObservation.model_validate(base | campos)


def _sem_artefato(resultado: ResultadoTentativa, **campos: object) -> ArtifactObservation:
    return _observacao(resultado=resultado, artifact_id=None, sha256_obtido=None, **campos)


def _requisicao(localizador: str) -> SourceRequest:
    return SourceRequest(
        chave=_chave(),
        localizador=localizador,
        formato_esperado=FormatoArquivo.DBC,
        tamanho_maximo_bytes=50_000_000,
        motivo=MotivoRequisicao.PRIMARIA,
    )


def _linha(sequencia: int = 1, **campos: object) -> LinhaManifesto:
    base = {
        "sequencia": sequencia,
        "tipo": TipoLinhaManifesto.OBSERVACAO,
        "observacao": _observacao(),
        "anterior_sha256": None if sequencia == 1 else "d" * 64,
    }
    return LinhaManifesto.model_validate(base | campos)


def test_artifact_id_e_derivado_da_chave_e_do_sha256() -> None:
    versao = _versao()
    assert versao.artifact_id == calcular_artifact_id(_chave(), _SHA_A)
    assert versao.artifact_id.startswith("art_")
    assert len(versao.artifact_id) == len("art_") + 64


@pytest.mark.parametrize(
    "artifact_id",
    [calcular_artifact_id(_chave(), _SHA_B), calcular_artifact_id(_chave(uf="PR"), _SHA_A)],
)
def test_versao_rejeita_artifact_id_que_nao_corresponde(artifact_id: str) -> None:
    with pytest.raises(ValidationError, match="artifact_id_nao_corresponde"):
        _versao(artifact_id=artifact_id)


@pytest.mark.parametrize(
    "alteracao",
    [
        {"canal": CanalPublicacao.PRELIMINAR},
        {"competencia_arquivo": "201802"},
        {"uf": "PR"},
        {"nome_original": "PASP1801A.dbc"},
        {"parte": "a"},
        {"versao_publicacao": "2"},
    ],
)
@given(sha256=_HEX64)
def test_mesmo_conteudo_com_chave_diferente_gera_id_diferente(
    alteracao: dict[str, object], sha256: str
) -> None:
    assert calcular_artifact_id(_chave(**alteracao), sha256) != calcular_artifact_id(
        _chave(), sha256
    )


@given(primeiro=_HEX64, segundo=_HEX64)
def test_mesma_chave_gera_mesmo_id_sse_mesmo_conteudo(primeiro: str, segundo: str) -> None:
    mesmo_id = calcular_artifact_id(_chave(), primeiro) == calcular_artifact_id(_chave(), segundo)
    assert mesmo_id is (primeiro == segundo)


@pytest.mark.parametrize("modelo", [ArtifactVersion, ChaveArtefato])
def test_identidade_da_versao_nao_tem_campo_de_instante(modelo: type) -> None:
    anotacoes = " ".join(str(campo.annotation) for campo in modelo.model_fields.values())
    assert "datetime" not in anotacoes


def test_versao_de_artefato_rejeita_instante_de_observacao() -> None:
    for campo in ("observado_em", "coletado_em", "first_seen", "last_seen"):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            _versao(**{campo: "2026-09-01T00:00:00Z"})


def test_recoleta_do_mesmo_conteudo_gera_nova_observacao_e_mesma_versao() -> None:
    primeira = _observacao()
    segunda = _observacao(
        observation_id=f"obs_{'2' * 32}", observado_em=datetime(2026, 9, 30, tzinfo=UTC)
    )
    assert primeira.observation_id != segunda.observation_id
    assert primeira.artifact_id == segunda.artifact_id == _versao().artifact_id
    assert _versao() == _versao()


def test_conteudo_antigo_reaparecendo_preserva_as_tres_observacoes() -> None:
    sequencia = [(_SHA_A, "1"), (_SHA_B, "2"), (_SHA_A, "3")]
    observacoes = [
        _observacao(
            observation_id=f"obs_{marca * 32}",
            artifact_id=calcular_artifact_id(_chave(), sha256),
            sha256_obtido=sha256,
        )
        for sha256, marca in sequencia
    ]
    artefatos = [observacao.artifact_id for observacao in observacoes]
    assert len({observacao.observation_id for observacao in observacoes}) == 3
    assert artefatos[0] == artefatos[2] != artefatos[1]


def test_zip_integro_exige_membros_seguros() -> None:
    seguro = MembroArquivo(nome="PASP1801.dbf", tamanho_bytes=10, seguro=True)
    inseguro = MembroArquivo(nome="../etc/passwd", tamanho_bytes=10, seguro=False)
    zip_ok = {"formato": FormatoArquivo.ZIP, "integridade": EstadoIntegridade.OK}
    assert _versao(membros=(seguro,), **zip_ok).membros == (seguro,)
    for membros in ((), (seguro, inseguro)):
        with pytest.raises(ValidationError, match="zip_integro_exige_membros_seguros"):
            _versao(membros=membros, **zip_ok)
    quarentena = _versao(
        formato=FormatoArquivo.ZIP,
        integridade=EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO,
        membros=(inseguro,),
    )
    assert quarentena.integridade is EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO


def test_observacao_obtida_exige_artefato() -> None:
    with pytest.raises(ValidationError, match="observacao_obtida_sem_artefato"):
        _sem_artefato(ResultadoTentativa.OBTIDO)


@pytest.mark.parametrize("resultado", _SEM_CONTEUDO)
def test_falha_de_coleta_nao_pode_apontar_artefato(resultado: ResultadoTentativa) -> None:
    with pytest.raises(ValidationError, match="observacao_sem_conteudo_com_artefato"):
        _observacao(resultado=resultado)


@pytest.mark.parametrize("resultado", _SEM_CONTEUDO)
def test_falha_de_coleta_e_registrada_como_observacao_sem_artefato(
    resultado: ResultadoTentativa,
) -> None:
    observacao = _sem_artefato(resultado, bytes_recebidos=0, erro="timeout")
    assert observacao.artifact_id is None


def test_observacao_com_artefato_exige_hash_obtido() -> None:
    with pytest.raises(ValidationError, match="observacao_artefato_sem_hash"):
        _observacao(sha256_obtido=None)


def test_conteudo_invalido_pode_apontar_artefato_em_quarentena() -> None:
    observacao = _observacao(resultado=ResultadoTentativa.CONTEUDO_INVALIDO)
    assert observacao.artifact_id == calcular_artifact_id(_chave(), _SHA_A)


@pytest.mark.parametrize("instante", ["2026-09-01T12:00:00", "2026-09-01T09:00:00-03:00"])
def test_observacao_exige_instante_utc(instante: str) -> None:
    with pytest.raises(ValidationError, match="instante_deve_ser_utc"):
        _observacao(observado_em=instante)


def test_observacao_rejeita_artefato_que_nao_deriva_do_hash_obtido() -> None:
    with pytest.raises(ValidationError):
        _observacao(artifact_id=calcular_artifact_id(_chave(), _SHA_B), sha256_obtido=_SHA_A)


@pytest.mark.parametrize("valor", [True, "true"])
def test_metadados_remotos_nunca_sao_registro_oficial(valor: object) -> None:
    with pytest.raises(ValidationError):
        MetadadosRemotos(interpretado_como_registro_oficial=valor)


def test_metadados_remotos_ficam_brutos_e_nao_oficiais() -> None:
    metadados = MetadadosRemotos(brutos={"Last-Modified": "Tue, 01 Sep 2026 00:00:00 GMT"})
    assert metadados.interpretado_como_registro_oficial is False
    assert _observacao().metadados_remotos.interpretado_como_registro_oficial is False
    with pytest.raises(ValidationError):
        MetadadosRemotos(brutos={"Content-Length": 1024})


@pytest.mark.parametrize(
    "localizador",
    [
        "ftp://usuario:senha@ftp.datasus.gov.br/PASP1801.dbc",
        "https://token@datasus.saude.gov.br/PASP1801.dbc",
    ],
)
def test_requisicao_rejeita_credenciais_no_localizador(localizador: str) -> None:
    with pytest.raises(ValidationError, match="localizador_com_credencial_ou_espaco"):
        _requisicao(localizador)


@pytest.mark.parametrize(
    "localizador",
    [
        "http://ftp.datasus.gov.br/PASP1801.dbc",
        "s3://balde/PASP1801.dbc",
        "sftp://ftp.datasus.gov.br/PASP1801.dbc",
        "data:text/plain,abc",
        "dados/PASP1801.dbc",
        "C:\\dados\\PASP1801.dbc",
    ],
)
def test_requisicao_rejeita_esquema_nao_permitido(localizador: str) -> None:
    with pytest.raises(ValidationError, match="esquema_nao_permitido"):
        _requisicao(localizador)


@pytest.mark.parametrize(
    "localizador", ["https://host/PA SP1801.dbc", "https://host/PASP1801.dbc\n"]
)
def test_requisicao_rejeita_espaco_no_localizador(localizador: str) -> None:
    with pytest.raises(ValidationError, match="localizador_com_credencial_ou_espaco"):
        _requisicao(localizador)


@pytest.mark.parametrize(
    "localizador",
    [
        "ftp://ftp.datasus.gov.br/dissemin/publicos/SIASUS/200801_/Dados/PASP1801.dbc",
        "https://datasus.saude.gov.br/PASP1801.dbc",
        "file:///importacao/PASP1801.dbc",
    ],
)
def test_requisicao_aceita_ftp_https_e_file(localizador: str) -> None:
    requisicao = _requisicao(localizador)
    assert requisicao.sha256() == _requisicao(localizador).sha256()
    assert requisicao.sha256() != _requisicao(f"{localizador}.bak").sha256()


def test_primeira_linha_do_manifesto_nao_tem_anterior() -> None:
    assert _linha(1).anterior_sha256 is None
    with pytest.raises(ValidationError, match="linha_manifesto_cadeia_incoerente"):
        _linha(1, anterior_sha256="d" * 64)


def test_linha_seguinte_do_manifesto_exige_hash_anterior() -> None:
    with pytest.raises(ValidationError, match="linha_manifesto_cadeia_incoerente"):
        _linha(2, anterior_sha256=None)


def test_linha_do_manifesto_rejeita_sequencia_zero() -> None:
    with pytest.raises(ValidationError, match="linha_manifesto_sequencia_invalida"):
        _linha(0, anterior_sha256="d" * 64)


@pytest.mark.parametrize(
    "campos",
    [
        {"tipo": TipoLinhaManifesto.OBSERVACAO, "observacao": None, "versao": _versao()},
        {"tipo": TipoLinhaManifesto.OBSERVACAO, "versao": _versao()},
        {"tipo": TipoLinhaManifesto.VERSAO},
        {"tipo": TipoLinhaManifesto.VERSAO, "observacao": None},
    ],
)
def test_tipo_da_linha_do_manifesto_corresponde_ao_conteudo(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="linha_manifesto_tipo_incoerente"):
        _linha(**campos)


def test_hash_da_linha_encadeia_a_seguinte() -> None:
    primeira = _linha(1)
    segunda = _linha(
        2,
        tipo=TipoLinhaManifesto.VERSAO,
        observacao=None,
        versao=_versao(),
        anterior_sha256=primeira.sha256(),
    )
    assert segunda.anterior_sha256 == _linha(1).sha256()
    assert primeira.sha256() != segunda.sha256()
