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


def listar_rastreados(raiz: Path) -> list[Rastreado]:
    raise NotImplementedError


def listar_historico(raiz: Path, ref: str) -> list[Rastreado]:
    raise NotImplementedError


def sha256_do_esboco(manifesto: Path) -> str | None:
    raise NotImplementedError


def auditar(
    arquivos: Iterable[Rastreado],
    *,
    esboco_sha256: str | None,
    ler_blob: Callable[[str], bytes],
    formatos: Mapping[str, str] | None = None,
    grandes: Mapping[str, str] | None = None,
) -> list[str]:
    raise NotImplementedError


_AMBIENTE_GIT = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


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
        assert caminho.lower().endswith(EXTENSOES_PROIBIDAS), f"allowlist_sem_efeito {caminho}"
    for caminho in GRANDES_JUSTIFICADOS:
        assert rastreados[caminho].tamanho > LIMITE_BYTES, f"allowlist_sem_efeito {caminho}"


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
    assert _auditar(_arquivo("docs/a.md", LIMITE_BYTES)) == []
    esperado = [f"arquivo_grande caminho=docs/b.md bytes={LIMITE_BYTES + 1}"]
    assert _auditar(_arquivo("docs/b.md", LIMITE_BYTES + 1)) == esperado


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
