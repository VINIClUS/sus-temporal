"""Catálogos e origem dos dados congelados contra os da config de agora (T14); SINTETICO.

O manifesto guarda o SHA-256 de cada catálogo da config e o do catálogo de regras. A diferença é
observação (o conteúdo refeito decide o resultado): os catálogos que mudaram, sumiram ou que só um
dos lados tem, e o catálogo de regras. A origem dos dados da config tem de ser a dos conjuntos
congelados; senão há um item inconclusivo.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts.base import OrigemDados
from sustemporal.evaluation.freeze import hash_das_regras
from sustemporal.hashing import sha256_arquivo
from sustemporal.reporting.reproduce_catalogos import (
    item_da_origem,
    observacoes_dos_catalogos,
    origens_do_relatorio,
)
from sustemporal.reporting.reproduce_comparacao import Comparacao, Situacao
from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.protocolo_insumos import conjunto_sintetico

if TYPE_CHECKING:
    from sustemporal.contracts.records import DatasetRef
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


def _conjunto(origem: OrigemDados, versao: str = "a") -> DatasetRef:
    return conjunto_sintetico("sia_pa.v1", versao).model_copy(update={"origem_dados": origem})


def _item(esperado: str, obtido: str) -> Comparacao:
    detalhe = "origem_dados_diferente_do_congelado"
    return Comparacao("origem_dados", Situacao.INCONCLUSIVO, esperado, obtido, detalhe)


def test_origem_igual_a_dos_conjuntos_congelados_nao_gera_item() -> None:
    assert item_da_origem(OrigemDados.SINTETICO, [_conjunto(OrigemDados.SINTETICO)]) == []
    assert item_da_origem(OrigemDados.REAL, [_conjunto(OrigemDados.REAL)]) == []


def test_origem_diferente_da_congelada_e_inconclusiva() -> None:
    itens = item_da_origem(OrigemDados.REAL, [_conjunto(OrigemDados.SINTETICO)])
    assert itens == [_item("SINTETICO", "REAL")]


def test_config_sem_origem_dos_dados_vale_a_sintetica() -> None:
    assert item_da_origem(None, [_conjunto(OrigemDados.SINTETICO)]) == []
    assert item_da_origem(None, [_conjunto(OrigemDados.REAL)]) == [_item("REAL", "SINTETICO")]


def test_conjuntos_de_origens_diferentes_nunca_conferem_com_uma_so() -> None:
    conjuntos = [_conjunto(OrigemDados.SINTETICO), _conjunto(OrigemDados.REAL, "b")]
    assert item_da_origem(OrigemDados.SINTETICO, conjuntos) == [
        _item("REAL,SINTETICO", "SINTETICO")
    ]


def test_conjuntos_repetidos_da_mesma_origem_contam_uma_vez() -> None:
    conjuntos = [_conjunto(OrigemDados.REAL), _conjunto(OrigemDados.REAL, "b")]
    assert item_da_origem(OrigemDados.REAL, conjuntos) == []


def test_o_topo_do_relatorio_traz_a_origem_dos_conjuntos_congelados_e_a_declarada_a_parte() -> None:
    origens = origens_do_relatorio(OrigemDados.REAL, [_conjunto(OrigemDados.SINTETICO)])
    assert origens == {"origem_dados": "SINTETICO", "origem_dados_config": "REAL"}


def test_config_sem_origem_vale_sintetico_na_declarada_e_a_dos_conjuntos_fica_a_deles() -> None:
    sintetico = origens_do_relatorio(None, [_conjunto(OrigemDados.SINTETICO)])
    assert sintetico == {"origem_dados": "SINTETICO", "origem_dados_config": "SINTETICO"}
    real = origens_do_relatorio(None, [_conjunto(OrigemDados.REAL)])
    assert real == {"origem_dados": "REAL", "origem_dados_config": "SINTETICO"}


def test_conjuntos_de_mais_de_uma_origem_saem_em_ordem_sem_repetir() -> None:
    conjuntos = [
        _conjunto(OrigemDados.SINTETICO, "a"),
        _conjunto(OrigemDados.REAL, "b"),
        _conjunto(OrigemDados.SINTETICO, "c"),
    ]
    assert origens_do_relatorio(None, conjuntos)["origem_dados"] == "REAL,SINTETICO"


def test_sem_conjuntos_congelados_o_topo_nao_tem_origem_e_a_declarada_segue() -> None:
    origens = origens_do_relatorio(OrigemDados.REAL, [])
    assert origens == {"origem_dados": None, "origem_dados_config": "REAL"}
