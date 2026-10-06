"""Catálogos congelados contra os de agora (T14); SINTETICO.

O manifesto guarda o SHA-256 de cada catálogo da config e o do catálogo de regras. A diferença é
observação (o conteúdo refeito decide o resultado): os catálogos que mudaram, sumiram ou que só um
dos lados tem, e o catálogo de regras.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.evaluation.freeze import hash_das_regras
from sustemporal.hashing import sha256_arquivo
from sustemporal.reporting.reproduce_catalogos import observacoes_dos_catalogos
from sustemporal.rules.catalog import carregar_regras

if TYPE_CHECKING:
    from sustemporal.contracts.rules import RuleSpec

SEM_REGRAS = None
CATALOGOS = "catalogos_diferentes_do_congelado catalogos="
REGRAS_DIFERENTES = "catalogo_de_regras_diferente_do_congelado"


@cache
def _regras() -> list[RuleSpec]:
    return carregar_regras()


def _catalogo(tmp_path: Path, nome: str, texto: str) -> str:
    caminho = tmp_path / f"{nome}.yaml"
    caminho.write_text(texto, encoding="utf-8")
    return str(caminho)


def _congelar(catalogos: dict[str, str]) -> dict[str, str]:
    return {nome: sha256_arquivo(Path(caminho)) for nome, caminho in catalogos.items()}


def _observar(
    congelados: dict[str, str],
    catalogos: dict[str, str],
    regras_congeladas: str | None = SEM_REGRAS,
) -> list[str]:
    return observacoes_dos_catalogos(congelados, catalogos, regras_congeladas, _regras())


def test_catalogos_e_regras_iguais_aos_congelados_nao_geram_observacao(tmp_path: Path) -> None:
    catalogos = {"fontes": _catalogo(tmp_path, "fontes", "a: 1\n")}
    assert _observar(_congelar(catalogos), catalogos, hash_das_regras(_regras())) == []


def test_catalogo_cujo_arquivo_mudou_depois_do_congelamento_e_nomeado(tmp_path: Path) -> None:
    catalogos = {
        "fontes": _catalogo(tmp_path, "fontes", "a: 1\n"),
        "outro": _catalogo(tmp_path, "outro", "b: 2\n"),
    }
    congelados = _congelar(catalogos)
    _catalogo(tmp_path, "fontes", "a: 2\n")
    assert _observar(congelados, catalogos) == [f"{CATALOGOS}fontes"]


def test_catalogo_ausente_ou_ilegivel_conta_como_diferente(tmp_path: Path) -> None:
    catalogos = {"fontes": _catalogo(tmp_path, "fontes", "a: 1\n")}
    congelados = _congelar(catalogos)
    sumiu = {"fontes": str(tmp_path / "nao_existe.yaml")}
    assert _observar(congelados, sumiu) == [f"{CATALOGOS}fontes"]
    pasta = {"fontes": str(tmp_path)}
    assert _observar(congelados, pasta) == [f"{CATALOGOS}fontes"]


def test_catalogo_que_so_um_dos_lados_tem_conta_como_diferente(tmp_path: Path) -> None:
    so_na_config = {"b": _catalogo(tmp_path, "b", "b: 2\n")}
    so_no_manifesto = {"a": _catalogo(tmp_path, "a", "a: 1\n")}
    assert _observar(_congelar(so_no_manifesto), so_na_config) == [f"{CATALOGOS}a,b"]


def test_catalogos_diferentes_saem_em_ordem_alfabetica(tmp_path: Path) -> None:
    catalogos = {nome: _catalogo(tmp_path, nome, f"{nome}: 1\n") for nome in ("z", "a", "m")}
    congelados = _congelar(catalogos)
    for nome in catalogos:
        _catalogo(tmp_path, nome, f"{nome}: 2\n")
    assert _observar(congelados, catalogos) == [f"{CATALOGOS}a,m,z"]


def test_catalogo_de_regras_diferente_do_congelado_e_observado() -> None:
    assert _observar({}, {}, "f" * 64) == [REGRAS_DIFERENTES]


def test_manifesto_sem_o_catalogo_de_regras_nao_confere_as_regras() -> None:
    assert _observar({}, {}, SEM_REGRAS) == []


def test_catalogos_vem_antes_das_regras(tmp_path: Path) -> None:
    catalogos = {"fontes": _catalogo(tmp_path, "fontes", "a: 1\n")}
    congelados = {"fontes": "0" * 64}
    assert _observar(congelados, catalogos, "f" * 64) == [f"{CATALOGOS}fontes", REGRAS_DIFERENTES]
