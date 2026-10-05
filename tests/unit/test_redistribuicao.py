"""Auditoria de redistribuição sobre os arquivos rastreados pelo git (T14).

Nenhum arquivo em `data/` ou `outputs/`; nenhum .dbc, .dbf, .parquet, .zip ou .pdf; nenhum
arquivo acima de 200 KB, salvo allowlist justificada. O PDF do esboço só entra com o SHA-256
registrado em `docs/spec/manifest.yaml`. As mesmas regras valem para o histórico publicado
(`origin/main`): o que entrou e saiu continua redistribuído com a história.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

RAIZ = Path(__file__).resolve().parents[2]
MANIFESTO = RAIZ / "docs" / "spec" / "manifest.yaml"
LIMITE_BYTES = 200 * 1024
DIRETORIOS_PROIBIDOS = ("data/", "outputs/")
EXTENSOES_PROIBIDAS = (".dbc", ".dbf", ".parquet", ".zip", ".pdf")
PDF_DO_ESBOCO = "docs/spec/esboco_original.pdf"

FORMATOS_JUSTIFICADOS: dict[str, str] = {}
GRANDES_JUSTIFICADOS: dict[str, str] = {}


@dataclass(frozen=True)
class Rastreado:
    caminho: str
    tamanho: int
    blob: str


_AMBIENTE_GIT = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
_GITLINK = "160000"
_AUSENTE = "000000"


def _git(raiz: Path, *argumentos: str, entrada: bytes | None = None) -> bytes:
    ambiente = {k: v for k, v in os.environ.items() if k not in _AMBIENTE_GIT}
    identidade = ["-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@t"]
    return subprocess.run(
        ["git", *identidade, *argumentos],
        cwd=raiz,
        env=ambiente,
        input=entrada,
        check=True,
        capture_output=True,
    ).stdout


def _tamanhos(raiz: Path, blobs: Iterable[str]) -> dict[str, int]:
    nomes = sorted(set(blobs))
    if not nomes:
        return {}
    formato = "--batch-check=%(objectname) %(objectsize)"
    saida = _git(raiz, "cat-file", formato, entrada="\n".join(nomes).encode() + b"\n")
    tamanhos: dict[str, int] = {}
    for linha in saida.decode("utf-8").splitlines():
        nome, _, tamanho = linha.partition(" ")
        if not tamanho.isdigit():
            raise AssertionError(f"objeto_ilegivel blob={nome}")
        tamanhos[nome] = int(tamanho)
    return tamanhos


def _com_tamanho(raiz: Path, pares: Iterable[tuple[str, str]]) -> list[Rastreado]:
    ordenados = sorted(set(pares))
    tamanhos = _tamanhos(raiz, (blob for _, blob in ordenados))
    return [Rastreado(caminho, tamanhos[blob], blob) for caminho, blob in ordenados]


def listar_rastreados(raiz: Path) -> list[Rastreado]:
    """Arquivos do índice do git, com o tamanho do blob e não o do arquivo no disco."""
    pares = []
    for campo in _git(raiz, "ls-files", "--stage", "-z").decode("utf-8").split("\0"):
        meta, _, caminho = campo.partition("\t")
        modo, _, resto = meta.partition(" ")
        if caminho and modo != _GITLINK:
            pares.append((caminho, resto.split(" ")[0]))
    return _com_tamanho(raiz, pares)


def _par_do_cabecalho(cabecalho: str, caminho: str) -> tuple[str, str] | None:
    _modo_antigo, modo, _blob_antigo, blob, status = cabecalho[1:].split(" ")
    if status.startswith("D") or modo in (_GITLINK, _AUSENTE):
        return None
    return caminho, blob


def listar_historico(raiz: Path, ref: str) -> list[Rastreado]:
    """Cada par (caminho, blob) gravado em algum commit alcançável de `ref`."""
    argumentos = ("log", "--raw", "--no-abbrev", "--no-renames", "-m", "--format=", "-z", ref)
    campos = _git(raiz, *argumentos).decode("utf-8").split("\0")
    pares = []
    indice = 0
    while indice < len(campos) - 1:
        if campos[indice].startswith(":"):
            par = _par_do_cabecalho(campos[indice], campos[indice + 1])
            pares.extend([par] if par else [])
            indice += 2
        else:
            indice += 1
    return _com_tamanho(raiz, pares)


def sha256_do_esboco(manifesto: Path) -> str | None:
    """SHA-256 do esboço no manifesto; None enquanto o documento está PENDENTE."""
    if not manifesto.is_file():
        return None
    conteudo = yaml.safe_load(manifesto.read_text(encoding="utf-8"))
    for documento in conteudo.get("documentos", []):
        if documento.get("id") == "esboco_original" and documento.get("estado") == "PRESERVADO":
            return str(documento["sha256"]) if documento.get("sha256") else None
    return None


def _motivo_do_formato(
    arquivo: Rastreado,
    esboco_sha256: str | None,
    ler_blob: Callable[[str], bytes],
    formatos: Mapping[str, str],
) -> str | None:
    if arquivo.caminho in formatos:
        return None
    if arquivo.caminho != PDF_DO_ESBOCO:
        return "formato_proibido"
    if esboco_sha256 is None:
        return "esboco_sem_hash_no_manifesto"
    if hashlib.sha256(ler_blob(arquivo.blob)).hexdigest() != esboco_sha256:
        return "esboco_com_hash_divergente"
    return None


def auditar(
    arquivos: Iterable[Rastreado],
    *,
    esboco_sha256: str | None,
    ler_blob: Callable[[str], bytes],
    formatos: Mapping[str, str] | None = None,
    grandes: Mapping[str, str] | None = None,
) -> list[str]:
    """Mensagens `chave=valor` das violações; lista vazia quando a redistribuição está limpa."""
    formatos = FORMATOS_JUSTIFICADOS if formatos is None else formatos
    grandes = GRANDES_JUSTIFICADOS if grandes is None else grandes
    problemas = []
    for arquivo in arquivos:
        caminho = arquivo.caminho
        if caminho.lower().startswith(DIRETORIOS_PROIBIDOS):
            problemas.append(f"arquivo_em_diretorio_proibido caminho={caminho}")
        if caminho.lower().endswith(EXTENSOES_PROIBIDAS):
            motivo = _motivo_do_formato(arquivo, esboco_sha256, ler_blob, formatos)
            problemas.extend([f"{motivo} caminho={caminho}"] if motivo else [])
        if arquivo.tamanho > LIMITE_BYTES and caminho not in grandes:
            problemas.append(f"arquivo_grande caminho={caminho} bytes={arquivo.tamanho}")
    return problemas


def _auditar_repositorio(raiz: Path, arquivos: Sequence[Rastreado]) -> list[str]:
    return auditar(
        arquivos,
        esboco_sha256=sha256_do_esboco(raiz / "docs" / "spec" / "manifest.yaml"),
        ler_blob=lambda blob: _git(raiz, "cat-file", "blob", blob),
    )


@pytest.fixture
def raiz_git() -> Path:
    if shutil.which("git") is None:
        pytest.skip("git_indisponivel")
    try:
        dentro = _git(RAIZ, "rev-parse", "--is-inside-work-tree").strip()
    except subprocess.CalledProcessError:
        pytest.skip("sem_repositorio_git")
    if dentro != b"true":
        pytest.skip("sem_repositorio_git")
    return RAIZ


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git_indisponivel")
    _git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


def _gravar(repo: Path, caminho: str, conteudo: bytes = b"x\n") -> None:
    alvo = repo / caminho
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(conteudo)


def _arquivo(caminho: str, tamanho: int = 10, blob: str = "b" * 40) -> Rastreado:
    return Rastreado(caminho, tamanho, blob)


def _leitura(conteudo: bytes) -> Callable[[str], bytes]:
    return lambda _blob: conteudo


def _auditar(
    *arquivos: Rastreado,
    esboco_sha256: str | None = None,
    ler_blob: Callable[[str], bytes] = lambda _blob: b"",
    formatos: Mapping[str, str] | None = None,
    grandes: Mapping[str, str] | None = None,
) -> list[str]:
    return auditar(
        arquivos,
        esboco_sha256=esboco_sha256,
        ler_blob=ler_blob,
        formatos=formatos,
        grandes=grandes,
    )


def test_arquivos_rastreados_respeitam_a_redistribuicao(raiz_git: Path) -> None:
    assert _auditar_repositorio(raiz_git, listar_rastreados(raiz_git)) == []


def test_historico_publicado_respeita_a_redistribuicao(raiz_git: Path) -> None:
    try:
        _git(raiz_git, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main")
    except subprocess.CalledProcessError:
        pytest.skip("sem_origin_main")
    historico = listar_historico(raiz_git, "origin/main")
    assert historico
    assert _auditar_repositorio(raiz_git, historico) == []


def test_allowlists_sao_justificadas_e_ainda_necessarias(raiz_git: Path) -> None:
    rastreados = {arquivo.caminho: arquivo for arquivo in listar_rastreados(raiz_git)}
    for caminho, justificativa in {**FORMATOS_JUSTIFICADOS, **GRANDES_JUSTIFICADOS}.items():
        assert len(justificativa.split()) >= 6, f"allowlist_sem_justificativa caminho={caminho}"
        assert caminho in rastreados, f"allowlist_obsoleta caminho={caminho}"
    for caminho in FORMATOS_JUSTIFICADOS:
        assert caminho.lower().endswith(EXTENSOES_PROIBIDAS), (
            f"allowlist_sem_efeito caminho={caminho}"
        )
        assert caminho != PDF_DO_ESBOCO, (
            f"allowlist_sem_efeito caminho={caminho} motivo=manifesto_decide"
        )
    for caminho in GRANDES_JUSTIFICADOS:
        assert rastreados[caminho].tamanho > LIMITE_BYTES, f"allowlist_sem_efeito caminho={caminho}"


def test_arquivo_em_data_ou_outputs_reprova_ate_o_readme() -> None:
    problemas = _auditar(
        _arquivo("data/raw/PASP1801.txt"),
        _arquivo("outputs/pilot/relatorio.json"),
        _arquivo("data/README.md"),
        _arquivo("docs/data/README.md"),
    )
    assert problemas == [
        "arquivo_em_diretorio_proibido caminho=data/raw/PASP1801.txt",
        "arquivo_em_diretorio_proibido caminho=outputs/pilot/relatorio.json",
        "arquivo_em_diretorio_proibido caminho=data/README.md",
    ]


@pytest.mark.parametrize(
    "caminho",
    ["x/PASP1801.dbc", "x/PFSP1801.DBF", "x/dados.parquet", "x/PA.ZIP", "x/manual.Pdf", "x/.dbc"],
)
def test_formato_de_dados_ou_documento_oficial_reprova_sem_justificativa(caminho: str) -> None:
    assert _auditar(_arquivo(caminho)) == [f"formato_proibido caminho={caminho}"]


def test_formato_com_justificativa_e_aceito_so_no_caminho_justificado() -> None:
    liberado = {"tests/fixtures/amostra.zip": "fixture sintética gerada por código, 3 KB"}
    assert _auditar(_arquivo("tests/fixtures/amostra.zip"), formatos=liberado) == []
    outro = _auditar(_arquivo("tests/fixtures/outra.zip"), formatos=liberado)
    assert outro == ["formato_proibido caminho=tests/fixtures/outra.zip"]


def test_limite_de_tamanho_aceita_200_kb_e_reprova_um_byte_a_mais() -> None:
    assert _auditar(_arquivo("docs/a.md", 204_800)) == []
    esperado = ["arquivo_grande caminho=docs/b.md bytes=204801"]
    assert _auditar(_arquivo("docs/b.md", 204_801)) == esperado


def test_arquivo_grande_com_justificativa_e_aceito() -> None:
    liberado = {"uv.lock": "trava de dependências gerada pelo uv, só do orquestrador"}
    assert _auditar(_arquivo("uv.lock", LIMITE_BYTES * 2), grandes=liberado) == []


def test_pdf_do_esboco_sem_hash_no_manifesto_reprova() -> None:
    problemas = _auditar(_arquivo(PDF_DO_ESBOCO), ler_blob=_leitura(b"%PDF"))
    assert problemas == [f"esboco_sem_hash_no_manifesto caminho={PDF_DO_ESBOCO}"]


def test_pdf_do_esboco_com_hash_do_manifesto_e_aceito_e_com_outro_hash_reprova() -> None:
    conteudo = b"%PDF-esboco"
    hash_certo = hashlib.sha256(conteudo).hexdigest()
    leitura = _leitura(conteudo)
    assert _auditar(_arquivo(PDF_DO_ESBOCO), esboco_sha256=hash_certo, ler_blob=leitura) == []
    divergente = _auditar(_arquivo(PDF_DO_ESBOCO), esboco_sha256="0" * 64, ler_blob=leitura)
    assert divergente == [f"esboco_com_hash_divergente caminho={PDF_DO_ESBOCO}"]


def test_pdf_do_esboco_na_allowlist_de_formatos_ainda_passa_pelo_manifesto() -> None:
    conteudo = b"%PDF-esboco"
    liberado = {
        PDF_DO_ESBOCO: "documento oficial preservado, sem licença própria de redistribuição"
    }
    leitura = _leitura(conteudo)
    arquivo = _arquivo(PDF_DO_ESBOCO)
    sem_hash = _auditar(arquivo, ler_blob=leitura, formatos=liberado)
    assert sem_hash == [f"esboco_sem_hash_no_manifesto caminho={PDF_DO_ESBOCO}"]
    divergente = _auditar(arquivo, esboco_sha256="0" * 64, ler_blob=leitura, formatos=liberado)
    assert divergente == [f"esboco_com_hash_divergente caminho={PDF_DO_ESBOCO}"]
    hash_certo = hashlib.sha256(conteudo).hexdigest()
    conferido = _auditar(arquivo, esboco_sha256=hash_certo, ler_blob=leitura, formatos=liberado)
    assert conferido == []


def test_hash_do_manifesto_nao_libera_outro_pdf() -> None:
    conteudo = b"%PDF-esboco"
    hash_certo = hashlib.sha256(conteudo).hexdigest()
    problemas = _auditar(
        _arquivo("docs/spec/copia.pdf"), esboco_sha256=hash_certo, ler_blob=_leitura(conteudo)
    )
    assert problemas == ["formato_proibido caminho=docs/spec/copia.pdf"]


def test_hash_do_esboco_vem_do_manifesto_so_quando_preservado(tmp_path: Path) -> None:
    pendente = "documentos:\n  - id: esboco_original\n    estado: PENDENTE\n    sha256: null\n"
    preservado = pendente.replace("PENDENTE", "PRESERVADO").replace("null", "a" * 64)
    (tmp_path / "pendente.yaml").write_text(pendente, encoding="utf-8")
    (tmp_path / "preservado.yaml").write_text(preservado, encoding="utf-8")
    assert sha256_do_esboco(tmp_path / "pendente.yaml") is None
    assert sha256_do_esboco(tmp_path / "preservado.yaml") == "a" * 64


def test_esboco_do_repositorio_segue_pendente_sem_hash() -> None:
    assert sha256_do_esboco(MANIFESTO) is None


def test_listagem_do_indice_traz_o_tamanho_do_blob_com_acentos_e_espacos(repo: Path) -> None:
    _gravar(repo, "docs/nota explicativa.md", b"abc")
    _gravar(repo, "docs/relatório.md", b"abcd")
    _gravar(repo, "grande.bin", bytes(LIMITE_BYTES + 1))
    _git(repo, "add", "-A")
    (repo / "grande.bin").unlink()
    tamanhos = {arquivo.caminho: arquivo.tamanho for arquivo in listar_rastreados(repo)}
    assert tamanhos == {
        "docs/nota explicativa.md": 3,
        "docs/relatório.md": 4,
        "grande.bin": LIMITE_BYTES + 1,
    }


def test_arquivo_adicionado_ao_indice_em_data_e_acusado(repo: Path) -> None:
    _gravar(repo, "data/raw/PASP1801.dbc", b"dados")
    _gravar(repo, "src/ok.py")
    _git(repo, "add", "-A")
    problemas = _auditar_repositorio(repo, listar_rastreados(repo))
    assert problemas == [
        "arquivo_em_diretorio_proibido caminho=data/raw/PASP1801.dbc",
        "formato_proibido caminho=data/raw/PASP1801.dbc",
    ]


def test_historico_enxerga_o_arquivo_removido_depois_do_commit(repo: Path) -> None:
    _gravar(repo, "outputs/relatorio.parquet", b"dados")
    _gravar(repo, "src/ok.py")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "com saída")
    _git(repo, "rm", "-q", "outputs/relatorio.parquet")
    _git(repo, "commit", "-q", "-m", "sem saída")
    assert _auditar_repositorio(repo, listar_rastreados(repo)) == []
    historico = _auditar_repositorio(repo, listar_historico(repo, "HEAD"))
    assert historico == [
        "arquivo_em_diretorio_proibido caminho=outputs/relatorio.parquet",
        "formato_proibido caminho=outputs/relatorio.parquet",
    ]
