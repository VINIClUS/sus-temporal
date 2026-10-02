"""Aquisição verificável e manifesto (T02); todo conteúdo é SINTETICO."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.aquisicao_dados import (
    HTML_DE_ERRO,
    Relogio,
    TransporteFalso,
    dbc_sintetico,
    dbf_sintetico,
    servidor_ftp,
    zip_sintetico,
)

from sustemporal.acquisition.fetch import fetch_source, nomes_listados
from sustemporal.acquisition.manifest import EstadoManifesto, Manifesto, ManifestoCorrompido
from sustemporal.acquisition.transport import (
    LimiteExcedido,
    RecursoNaoEncontrado,
    TransferenciaInterrompida,
    TransporteArquivo,
    TransporteFTP,
)
from sustemporal.contracts.artifacts import (
    ChaveArtefato,
    EstadoIntegridade,
    FormatoArquivo,
    MotivoRequisicao,
    ResultadoTentativa,
    SourceRequest,
    TipoConteudo,
)
from sustemporal.contracts.base import CanalPublicacao, FamiliaFonte
from sustemporal.errors import RedeProibida
from sustemporal.hashing import sha256_arquivo

if TYPE_CHECKING:
    from pathlib import Path

_LIMITE = 10_000_000


def _requisicao(
    localizador: str,
    formato: FormatoArquivo = FormatoArquivo.DBC,
    **campos: object,
) -> SourceRequest:
    chave = ChaveArtefato(
        fonte=FamiliaFonte.SIA_PA,
        uf="SP",
        competencia_arquivo="201801",
        parte="a",
        canal=CanalPublicacao.ATUAL,
        nome_original=localizador.rsplit("/", 1)[-1] or "raiz",
    )
    base: dict[str, object] = {
        "chave": chave,
        "localizador": localizador,
        "formato_esperado": formato,
        "tamanho_maximo_bytes": _LIMITE,
        "motivo": MotivoRequisicao.PRIMARIA,
    }
    return SourceRequest.model_validate(base | campos)


def _publicar(origem: Path, conteudo: bytes, nome: str = "PASP1801a.dbc") -> SourceRequest:
    origem.mkdir(parents=True, exist_ok=True)
    (origem / nome).write_bytes(conteudo)
    formato = {"zip": FormatoArquivo.ZIP, "dbf": FormatoArquivo.DBF}.get(
        nome.rsplit(".", 1)[-1], FormatoArquivo.DBC
    )
    return _requisicao((origem / nome).as_uri(), formato)


def _estado(store: Path) -> EstadoManifesto:
    return Manifesto(store / "manifesto.jsonl").ler()


def _arquivos_de_conteudo(store: Path, area: str = "sha256") -> list[Path]:
    return sorted(p for p in (store / area).rglob("*") if p.is_file())


def _sem_temporarios(store: Path) -> bool:
    return not any(p.is_file() for p in (store / "tmp").rglob("*"))


def test_conteudo_repetido_gera_duas_observacoes_e_uma_versao(tmp_path: Path) -> None:
    requisicao = _publicar(tmp_path / "origem", dbc_sintetico())
    store = tmp_path / "store"
    primeira = fetch_source(requisicao, store, relogio=Relogio())
    segunda = fetch_source(requisicao, store, relogio=Relogio())
    estado = _estado(store)
    assert [o.resultado for o in estado.observacoes] == [ResultadoTentativa.OBTIDO] * 2
    assert primeira.observation_id != segunda.observation_id
    assert primeira.artifact_id == segunda.artifact_id
    assert list(estado.versoes) == [primeira.artifact_id]
    assert [x.tipo.value for x in estado.linhas] == ["VERSAO", "OBSERVACAO", "OBSERVACAO"]
    assert len(_arquivos_de_conteudo(store)) == 1


def test_a_b_a_preserva_tres_observacoes_e_duas_versoes(tmp_path: Path) -> None:
    store = tmp_path / "store"
    relogio = Relogio()
    ids = []
    for valor in ("A", "B", "A"):
        requisicao = _publicar(tmp_path / "origem", dbc_sintetico(valor))
        ids.append(fetch_source(requisicao, store, relogio=relogio).artifact_id)
    estado = _estado(store)
    assert ids[0] == ids[2] != ids[1]
    assert [o.artifact_id for o in estado.observacoes] == ids
    assert [o.observado_em for o in estado.observacoes] == relogio.leituras
    assert set(estado.versoes) == set(ids)
    tipos = [x.tipo.value for x in estado.linhas]
    assert tipos == ["VERSAO", "OBSERVACAO", "VERSAO", "OBSERVACAO", "OBSERVACAO"]
    assert len(_arquivos_de_conteudo(store)) == 2


def test_download_interrompido_nao_promove_e_registra_observacao(tmp_path: Path) -> None:
    store = tmp_path / "store"
    falso = TransporteFalso(conteudo=b"\x03parcial", erro=TransferenciaInterrompida("eof", 8))
    requisicao = _requisicao("ftp://ftp.exemplo.invalid/PASP1801a.dbc")
    observacao = fetch_source(
        requisicao, store, rede_permitida=True, relogio=Relogio(), transportes={"ftp": falso}
    )
    assert observacao.resultado is ResultadoTentativa.INTERROMPIDO
    assert observacao.artifact_id is None
    assert observacao.bytes_recebidos == 8
    assert not (store / "sha256").exists()
    assert _sem_temporarios(store)
    assert _estado(store).observacoes == (observacao,)


def test_tamanho_anunciado_maior_que_o_recebido_e_interrupcao(tmp_path: Path) -> None:
    store = tmp_path / "store"
    conteudo = dbc_sintetico()
    falso = TransporteFalso(conteudo=conteudo, anunciado=len(conteudo) + 10)
    observacao = fetch_source(
        _requisicao("ftp://ftp.exemplo.invalid/PASP1801a.dbc"),
        store,
        rede_permitida=True,
        transportes={"ftp": falso},
    )
    assert observacao.resultado is ResultadoTentativa.INTERROMPIDO
    assert not (store / "sha256").exists()


def test_interrupcao_pelo_usuario_registra_observacao_e_repropaga(tmp_path: Path) -> None:
    store = tmp_path / "store"
    falso = TransporteFalso(conteudo=b"abc", erro=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        fetch_source(
            _requisicao("ftp://ftp.exemplo.invalid/PASP1801a.dbc"),
            store,
            rede_permitida=True,
            transportes={"ftp": falso},
        )
    (observacao,) = _estado(store).observacoes
    assert observacao.resultado is ResultadoTentativa.INTERROMPIDO
    assert _sem_temporarios(store)


def test_checksum_divergente_vai_para_quarentena_sem_versao(tmp_path: Path) -> None:
    store = tmp_path / "store"
    base = _publicar(tmp_path / "origem", dbc_sintetico())
    requisicao = base.model_copy(update={"sha256_esperado": "0" * 64})
    observacao = fetch_source(requisicao, store)
    assert observacao.resultado is ResultadoTentativa.CONTEUDO_INVALIDO
    assert observacao.artifact_id is None
    assert observacao.erro is not None
    assert observacao.erro.startswith("checksum_divergente")
    assert observacao.sha256_obtido is not None
    assert not _arquivos_de_conteudo(store)
    (guardado,) = _arquivos_de_conteudo(store, "quarentena")
    assert sha256_arquivo(guardado) == observacao.sha256_obtido
    assert _estado(store).versoes == {}


def test_checksum_esperado_que_confere_obtem(tmp_path: Path) -> None:
    store = tmp_path / "store"
    base = _publicar(tmp_path / "origem", dbc_sintetico())
    esperado = sha256_arquivo(tmp_path / "origem" / "PASP1801a.dbc")
    observacao = fetch_source(base.model_copy(update={"sha256_esperado": esperado}), store)
    assert observacao.resultado is ResultadoTentativa.OBTIDO


@pytest.mark.parametrize("formato", ["DBC", "DBF", "ZIP", "PDF"])
def test_html_no_lugar_de_dados_fica_em_quarentena(tmp_path: Path, formato: str) -> None:
    store = tmp_path / "store"
    (tmp_path / "pagina").write_bytes(HTML_DE_ERRO)
    requisicao = _requisicao((tmp_path / "pagina").as_uri(), FormatoArquivo(formato))
    observacao = fetch_source(requisicao, store)
    assert observacao.resultado is ResultadoTentativa.CONTEUDO_INVALIDO
    versao = _estado(store).versoes[str(observacao.artifact_id)]
    assert versao.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert versao.caminho_conteudo.startswith("quarentena/")
    assert not _arquivos_de_conteudo(store)


@pytest.mark.parametrize(
    ("membros", "links"),
    [
        ({"../fora.txt": b"x"}, None),
        ({"/etc/abs.txt": b"x"}, None),
        ({"dir/../../fora.txt": b"x"}, None),
        ({"c:/windows.txt": b"x"}, None),
        ({"dir\\..\\fora.txt": b"x"}, None),
        ({"ok.txt": b"x"}, {"link": "/etc/passwd"}),
    ],
)
def test_caminho_inseguro_em_arquivo_compactado_fica_em_quarentena(
    tmp_path: Path, membros: dict[str, bytes], links: dict[str, str] | None
) -> None:
    store = tmp_path / "store"
    requisicao = _publicar(tmp_path / "origem", zip_sintetico(membros, links=links), "t.zip")
    observacao = fetch_source(requisicao, store)
    assert observacao.resultado is ResultadoTentativa.CONTEUDO_INVALIDO
    versao = _estado(store).versoes[str(observacao.artifact_id)]
    assert versao.integridade is EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO
    assert any(not membro.seguro for membro in versao.membros)
    assert not (tmp_path / "fora.txt").exists()
    assert not (store / "fora.txt").exists()


def test_zip_integro_e_listado_sem_extrair(tmp_path: Path) -> None:
    store = tmp_path / "store"
    conteudo = zip_sintetico({"tb_procedimento.txt": b"0101010010", "leia/me.txt": b"x"})
    observacao = fetch_source(_publicar(tmp_path / "origem", conteudo, "t.zip"), store)
    versao = _estado(store).versoes[str(observacao.artifact_id)]
    assert versao.integridade is EstadoIntegridade.OK
    assert sorted(m.nome for m in versao.membros) == ["leia/me.txt", "tb_procedimento.txt"]
    assert [p.suffix for p in store.rglob("*") if p.is_file()].count(".txt") == 0


@pytest.mark.parametrize(
    ("conteudo", "estado"),
    [
        (b"", EstadoIntegridade.QUARENTENA_TRUNCADO),
        (dbf_sintetico(truncar_bytes=3), EstadoIntegridade.QUARENTENA_TRUNCADO),
        (b"PK\x03\x04truncado", EstadoIntegridade.QUARENTENA_TRUNCADO),
        (b"MZ\x90\x00executavel", EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO),
    ],
    ids=["vazio", "dbf_truncado", "zip_sem_diretorio", "executavel"],
)
def test_conteudo_truncado_ou_inesperado_fica_em_quarentena(
    tmp_path: Path, conteudo: bytes, estado: EstadoIntegridade
) -> None:
    nome = "t.zip" if conteudo.startswith(b"PK") else "t.dbf"
    store = tmp_path / "store"
    observacao = fetch_source(_publicar(tmp_path / "origem", conteudo, nome), store)
    assert observacao.resultado is ResultadoTentativa.CONTEUDO_INVALIDO
    assert _estado(store).versoes[str(observacao.artifact_id)].integridade is estado


def test_reexecucao_idempotente_nao_reescreve_conteudo(tmp_path: Path) -> None:
    store = tmp_path / "store"
    requisicao = _publicar(tmp_path / "origem", dbc_sintetico())
    fetch_source(requisicao, store)
    (guardado,) = _arquivos_de_conteudo(store)
    antes = guardado.stat()
    fetch_source(requisicao, store)
    depois = guardado.stat()
    assert (antes.st_ino, antes.st_mtime_ns) == (depois.st_ino, depois.st_mtime_ns)
    assert len(_estado(store).versoes) == 1


def test_recuperacao_nao_sobrescreve_original_divergente(tmp_path: Path) -> None:
    store = tmp_path / "store"
    requisicao = _publicar(tmp_path / "origem", dbc_sintetico())
    fetch_source(requisicao, store)
    (guardado,) = _arquivos_de_conteudo(store)
    guardado.chmod(0o644)
    guardado.write_bytes(b"adulterado")
    observacao = fetch_source(requisicao, store)
    assert observacao.resultado is ResultadoTentativa.FALHA_ARMAZENAMENTO
    assert observacao.artifact_id is None
    assert guardado.read_bytes() == b"adulterado"
    assert _sem_temporarios(store)
    assert len(_estado(store).observacoes) == 2


def test_recuperacao_restaura_conteudo_removido(tmp_path: Path) -> None:
    store = tmp_path / "store"
    requisicao = _publicar(tmp_path / "origem", dbc_sintetico())
    primeira = fetch_source(requisicao, store)
    (guardado,) = _arquivos_de_conteudo(store)
    guardado.unlink()
    segunda = fetch_source(requisicao, store)
    assert segunda.artifact_id == primeira.artifact_id
    assert sha256_arquivo(guardado) == primeira.sha256_obtido


def test_temporario_abandonado_nao_afeta_nova_aquisicao(tmp_path: Path) -> None:
    store = tmp_path / "store"
    (store / "tmp").mkdir(parents=True)
    (store / "tmp" / "baixando_antigo").write_bytes(b"lixo de uma queda")
    observacao = fetch_source(_publicar(tmp_path / "origem", dbc_sintetico()), store)
    assert observacao.resultado is ResultadoTentativa.OBTIDO
    assert (store / "tmp" / "baixando_antigo").read_bytes() == b"lixo de uma queda"


def _manifesto_com_tres_linhas(tmp_path: Path) -> Path:
    store = tmp_path / "store"
    relogio = Relogio()
    for valor in ("A", "B"):
        fetch_source(_publicar(tmp_path / "origem", dbc_sintetico(valor)), store, relogio=relogio)
    return store / "manifesto.jsonl"


def test_manifesto_encadeia_e_detecta_reescrita(tmp_path: Path) -> None:
    caminho = _manifesto_com_tres_linhas(tmp_path)
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 4
    linhas[1] = linhas[1].replace("2026-09-01T12:00:00", "2026-09-01T11:00:00")
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    with pytest.raises(ManifestoCorrompido, match="cadeia"):
        Manifesto(caminho).ler()


@pytest.mark.parametrize("operacao", ["remover", "trocar", "truncar"])
def test_manifesto_detecta_remocao_reordenacao_e_truncamento(tmp_path: Path, operacao: str) -> None:
    caminho = _manifesto_com_tres_linhas(tmp_path)
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    if operacao == "remover":
        del linhas[1]
    elif operacao == "trocar":
        linhas[1], linhas[2] = linhas[2], linhas[1]
    else:
        linhas[-1] = linhas[-1][:20]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    with pytest.raises(ManifestoCorrompido):
        Manifesto(caminho).ler()


def test_manifesto_corrompido_impede_novo_registro(tmp_path: Path) -> None:
    caminho = _manifesto_com_tres_linhas(tmp_path)
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    caminho.write_text("\n".join(linhas[1:]) + "\n", encoding="utf-8")
    with pytest.raises(ManifestoCorrompido):
        fetch_source(_publicar(tmp_path / "origem", dbc_sintetico("C")), caminho.parent)


def test_metadados_remotos_nunca_viram_competencia_nem_instante(tmp_path: Path) -> None:
    requisicao = _publicar(tmp_path / "origem", dbc_sintetico())
    antigo = datetime(2019, 3, 15, tzinfo=UTC).timestamp()
    os.utime(tmp_path / "origem" / "PASP1801a.dbc", (antigo, antigo))
    relogio = Relogio()
    observacao = fetch_source(requisicao, tmp_path / "store", relogio=relogio)
    assert observacao.chave.competencia_arquivo == requisicao.chave.competencia_arquivo
    assert observacao.observado_em == relogio.leituras[-1]
    assert "2019-03-15" in observacao.metadados_remotos.brutos["mtime"]
    assert observacao.metadados_remotos.interpretado_como_registro_oficial is False


def test_recusa_offline_registra_observacao_e_nao_toca_a_rede(tmp_path: Path) -> None:
    store = tmp_path / "store"
    falso = TransporteFalso(conteudo=dbc_sintetico())
    with pytest.raises(RedeProibida):
        fetch_source(
            _requisicao("ftp://ftp.exemplo.invalid/PASP1801a.dbc"),
            store,
            transportes={"ftp": falso},
        )
    assert falso.chamadas == 0
    (observacao,) = _estado(store).observacoes
    assert observacao.resultado is ResultadoTentativa.RECUSADO_OFFLINE
    assert observacao.bytes_recebidos == 0


def test_arquivo_local_ausente_e_nao_encontrado(tmp_path: Path) -> None:
    requisicao = _requisicao((tmp_path / "nao_existe.dbc").as_uri())
    observacao = fetch_source(requisicao, tmp_path / "store")
    assert observacao.resultado is ResultadoTentativa.NAO_ENCONTRADO


def test_limite_de_tamanho_excedido_nao_guarda_conteudo(tmp_path: Path) -> None:
    base = _publicar(tmp_path / "origem", dbc_sintetico())
    requisicao = base.model_copy(update={"tamanho_maximo_bytes": 10})
    observacao = fetch_source(requisicao, tmp_path / "store")
    assert observacao.resultado is ResultadoTentativa.CONTEUDO_INVALIDO
    assert observacao.artifact_id is None
    assert observacao.sha256_obtido is None
    assert observacao.erro is not None
    assert observacao.erro.startswith("tamanho_maximo_excedido")
    assert not (tmp_path / "store" / "sha256").exists()


@pytest.mark.parametrize(
    ("erro", "resultado"),
    [
        (RecursoNaoEncontrado("550"), ResultadoTentativa.NAO_ENCONTRADO),
        (LimiteExcedido("grande", 11), ResultadoTentativa.CONTEUDO_INVALIDO),
        (OSError("conexao recusada"), ResultadoTentativa.FALHA_TRANSPORTE),
    ],
)
def test_erros_do_transporte_viram_observacao(
    tmp_path: Path, erro: Exception, resultado: ResultadoTentativa
) -> None:
    falso = TransporteFalso(erro=erro)
    observacao = fetch_source(
        _requisicao("ftp://ftp.exemplo.invalid/PASP1801a.dbc"),
        tmp_path / "store",
        rede_permitida=True,
        transportes={"ftp": falso},
    )
    assert observacao.resultado is resultado
    assert observacao.artifact_id is None


def _requisicao_listagem(localizador: str) -> SourceRequest:
    chave = ChaveArtefato(
        fonte=FamiliaFonte.SIA_PA,
        canal=CanalPublicacao.ATUAL,
        nome_original="Dados",
        tipo_conteudo=TipoConteudo.LISTAGEM_DIRETORIO,
    )
    return SourceRequest(
        chave=chave,
        localizador=localizador,
        formato_esperado=FormatoArquivo.TXT,
        tamanho_maximo_bytes=1_000_000,
        motivo=MotivoRequisicao.PRIMARIA,
    )


def test_ftp_local_baixa_e_lista_diretorio_como_observacao(tmp_path: Path) -> None:
    dados = tmp_path / "ftp" / "Dados"
    dados.mkdir(parents=True)
    for nome in ("PASP1801a.dbc", "PASP1801b.dbc", "PAPE1801.dbc"):
        (dados / nome).write_bytes(dbc_sintetico(nome[-5]))
    store = tmp_path / "store"
    transportes = {"ftp": TransporteFTP(timeout=5)}
    with servidor_ftp(tmp_path / "ftp") as porta:
        raiz = f"ftp://127.0.0.1:{porta}/Dados/"
        listagem = fetch_source(
            _requisicao_listagem(raiz), store, rede_permitida=True, transportes=transportes
        )
        arquivo = fetch_source(
            _requisicao(f"{raiz}PASP1801a.dbc"), store, rede_permitida=True, transportes=transportes
        )
    assert listagem.resultado is ResultadoTentativa.OBTIDO
    assert nomes_listados(store, listagem) == ["PAPE1801.dbc", "PASP1801a.dbc", "PASP1801b.dbc"]
    assert arquivo.resultado is ResultadoTentativa.OBTIDO
    assert arquivo.sha256_obtido == sha256_arquivo(dados / "PASP1801a.dbc")
    assert "tamanho" in arquivo.metadados_remotos.brutos


def test_ftp_local_arquivo_ausente_e_nao_encontrado(tmp_path: Path) -> None:
    (tmp_path / "ftp").mkdir()
    with servidor_ftp(tmp_path / "ftp") as porta:
        observacao = fetch_source(
            _requisicao(f"ftp://127.0.0.1:{porta}/PASP1801a.dbc"),
            tmp_path / "store",
            rede_permitida=True,
            transportes={"ftp": TransporteFTP(timeout=5)},
        )
    assert observacao.resultado is ResultadoTentativa.NAO_ENCONTRADO


def test_listagem_de_diretorio_local(tmp_path: Path) -> None:
    (tmp_path / "origem").mkdir()
    for nome in ("b.dbc", "a.dbc"):
        (tmp_path / "origem" / nome).write_bytes(b"x")
    assert TransporteArquivo().listar((tmp_path / "origem").as_uri() + "/") == ["a.dbc", "b.dbc"]
