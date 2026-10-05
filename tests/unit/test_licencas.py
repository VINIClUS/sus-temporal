"""Auditoria offline das licenças do runtime (T14, direitos de redistribuição).

Lê os metadados instalados (`importlib.metadata`) das dependências de `[project].dependencies` e
do fecho transitivo delas; dependências só de dev não entram. Vale a licença declarada nos
metadados. Bibliotecas embarcadas dentro das wheels não são inspecionadas
(`docs/pendencias/T14.md`).
"""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from packaging.requirements import Requirement

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from os import PathLike

RAIZ = Path(__file__).resolve().parents[2]
PYPROJECT = RAIZ / "pyproject.toml"

PERMISSIVAS: dict[str, str] = {}
EXCECOES: dict[str, str] = {}

_CLASSIFICADORES = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: BSD License": "BSD",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: zlib/libpng License": "Zlib",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
}
_ROTULOS = {"mit license": "MIT", "bsd license": "BSD", "apache 2.0": "Apache-2.0"}
_COPYLEFT = re.compile(r"(?i)(?<![a-z])[al]?gpl|general public licen[cs]e")
_TEXTO_CURTO = 60


def _normalizar(nome: str) -> str:
    return re.sub(r"[-_.]+", "-", nome).lower()


def requisitos_declarados(pyproject: Path) -> list[Requirement]:
    dados = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return [Requirement(texto) for texto in dados["project"]["dependencies"]]


def _instalada(nome: str, obter: Callable[[str], metadata.Distribution]) -> metadata.Distribution:
    try:
        return obter(nome)
    except metadata.PackageNotFoundError as erro:
        raise AssertionError(f"dependencia_nao_instalada pacote={nome}") from erro


def _dependencias(dist: metadata.Distribution, extras: Iterable[str]) -> list[Requirement]:
    ambientes = [{"extra": ""}, *({"extra": extra} for extra in extras)]
    requisitos = [Requirement(linha) for linha in dist.requires or []]
    return [
        requisito
        for requisito in requisitos
        if requisito.marker is None
        or any(requisito.marker.evaluate(ambiente) for ambiente in ambientes)
    ]


def fechamento_de_runtime(
    declarados: Iterable[Requirement],
    obter: Callable[[str], metadata.Distribution] = metadata.distribution,
) -> dict[str, metadata.Distribution]:
    """Distribuições instaladas alcançáveis pelas dependências de runtime declaradas."""
    encontrados: dict[str, metadata.Distribution] = {}
    visitados: set[tuple[str, frozenset[str]]] = set()
    fila = list(declarados)
    while fila:
        requisito = fila.pop()
        nome = _normalizar(requisito.name)
        chave = (nome, frozenset(requisito.extras))
        if chave in visitados:
            continue
        visitados.add(chave)
        if nome not in encontrados:
            encontrados[nome] = _instalada(requisito.name, obter)
        fila.extend(_dependencias(encontrados[nome], requisito.extras))
    return encontrados


def _identificadores(expressao: str) -> list[str]:
    sem_excecoes = re.sub(r"\s+WITH\s+\S+", "", expressao, flags=re.IGNORECASE)
    partes = re.split(r"\s+(?:AND|OR)\s+|[()]", sem_excecoes, flags=re.IGNORECASE)
    return [
        _ROTULOS.get(parte.strip().casefold(), parte.strip()) for parte in partes if parte.strip()
    ]


def _texto_da_licenca(dist: metadata.Distribution) -> str:
    return " ".join((dist.metadata.get("License") or "").split())


def licencas_declaradas(dist: metadata.Distribution) -> list[str]:
    """Identificadores declarados: expressão SPDX, senão classificadores e texto curto."""
    expressao = (dist.metadata.get("License-Expression") or "").strip()
    if expressao:
        return _identificadores(expressao)
    declaradas = [
        _CLASSIFICADORES.get(classificador, classificador)
        for classificador in dist.metadata.get_all("Classifier", [])
        if classificador.startswith("License ::")
    ]
    texto = _texto_da_licenca(dist)
    if texto and len(texto) <= _TEXTO_CURTO:
        declaradas.extend(_identificadores(texto))
    return declaradas


def avaliar(
    nome: str,
    dist: metadata.Distribution,
    permissivas: Mapping[str, str],
    excecoes: Mapping[str, str],
) -> str | None:
    """Mensagem `chave=valor` da reprovação, ou None se a licença é aceita."""
    if nome in excecoes:
        return None
    declaradas = licencas_declaradas(dist)
    copyleft = [licenca for licenca in declaradas if _COPYLEFT.search(licenca)]
    if copyleft:
        return f"licenca_copyleft pacote={nome} licenca={', '.join(copyleft)}"
    fora = [licenca for licenca in declaradas if licenca not in permissivas]
    if fora or not declaradas:
        mostrada = ", ".join(fora) or _texto_da_licenca(dist)[:_TEXTO_CURTO] or "NENHUMA"
        return f"licenca_desconhecida pacote={nome} licenca={mostrada}"
    return None


FECHAMENTO = fechamento_de_runtime(requisitos_declarados(PYPROJECT))


@pytest.mark.parametrize("nome", sorted(FECHAMENTO))
def test_licenca_do_runtime_e_permissiva(nome: str) -> None:
    assert avaliar(nome, FECHAMENTO[nome], PERMISSIVAS, EXCECOES) is None


def test_fechamento_cobre_as_dependencias_declaradas_e_as_transitivas() -> None:
    declarados = {_normalizar(requisito.name) for requisito in requisitos_declarados(PYPROJECT)}
    assert declarados <= set(FECHAMENTO)
    assert len(FECHAMENTO) > len(declarados)


def test_toda_licenca_permissiva_tem_justificativa() -> None:
    assert PERMISSIVAS
    assert all(justificativa.strip() for justificativa in PERMISSIVAS.values())
    assert not [licenca for licenca in PERMISSIVAS if _COPYLEFT.search(licenca)]


def test_toda_excecao_e_do_runtime_e_justificada() -> None:
    for pacote, justificativa in EXCECOES.items():
        assert _normalizar(pacote) in FECHAMENTO, f"excecao_fora_do_runtime pacote={pacote}"
        assert len(justificativa.split()) >= 6, f"excecao_sem_justificativa pacote={pacote}"


class _Distribuicao(metadata.Distribution):
    """Distribuição em memória, só com o texto do METADATA."""

    def __init__(self, texto: str) -> None:
        self._texto = texto

    def read_text(self, filename: str) -> str | None:
        return self._texto if filename == "METADATA" else None

    def locate_file(self, path: str | PathLike[str]) -> PathLike[str]:
        raise NotImplementedError


def _falsa(nome: str, *cabecalhos: str) -> metadata.Distribution:
    linhas = ["Metadata-Version: 2.4", f"Name: {nome}", "Version: 1.0", *cabecalhos]
    return _Distribuicao("\n".join(linhas) + "\n")


def _resolvedor(*distribuicoes: metadata.Distribution) -> Callable[[str], metadata.Distribution]:
    indice = {_normalizar(dist.metadata["Name"]): dist for dist in distribuicoes}

    def obter(nome: str) -> metadata.Distribution:
        if _normalizar(nome) not in indice:
            raise metadata.PackageNotFoundError(nome)
        return indice[_normalizar(nome)]

    return obter


_PERMITIDAS = {"MIT": "teste", "BSD-3-Clause": "teste", "BSD": "teste", "Zlib": "teste"}


def _avaliar(dist: metadata.Distribution) -> str | None:
    return avaliar(dist.metadata["Name"], dist, _PERMITIDAS, {})


def test_licenca_gpl_no_runtime_reprova() -> None:
    dist = _falsa("leitor", "License-Expression: GPL-3.0-only")
    assert _avaliar(dist) == "licenca_copyleft pacote=leitor licenca=GPL-3.0-only"


def test_licenca_agpl_por_classificador_reprova() -> None:
    classificador = "License :: OSI Approved :: GNU Affero General Public License v3 (AGPLv3)"
    dist = _falsa("leitor", f"Classifier: {classificador}")
    assert _avaliar(dist) == f"licenca_copyleft pacote=leitor licenca={classificador}"


def test_licenca_lgpl_no_campo_license_reprova() -> None:
    dist = _falsa("leitor", "License: LGPL-2.1-or-later")
    assert _avaliar(dist) == "licenca_copyleft pacote=leitor licenca=LGPL-2.1-or-later"


def test_licenca_desconhecida_reprova_com_a_mensagem_do_cartao() -> None:
    dist = _falsa("leitor", "License-Expression: LicenseRef-Proprietaria")
    esperado = "licenca_desconhecida pacote=leitor licenca=LicenseRef-Proprietaria"
    assert _avaliar(dist) == esperado


def test_pacote_sem_licenca_declarada_reprova_como_desconhecido() -> None:
    assert _avaliar(_falsa("leitor")) == "licenca_desconhecida pacote=leitor licenca=NENHUMA"


def test_expressao_composta_so_passa_com_todas_as_licencas_permissivas() -> None:
    permissiva = _falsa("a", "License-Expression: MIT AND (BSD-3-Clause OR Zlib)")
    assert _avaliar(permissiva) is None
    copyleft = _falsa("b", "License-Expression: MIT AND GPL-2.0-only")
    assert _avaliar(copyleft) == "licenca_copyleft pacote=b licenca=GPL-2.0-only"
    alternativa = _falsa("c", "License-Expression: MIT OR GPL-3.0-or-later")
    assert str(_avaliar(alternativa)).startswith("licenca_copyleft pacote=c")
    desconhecida = _falsa("d", "License-Expression: MIT AND LicenseRef-X")
    assert _avaliar(desconhecida) == "licenca_desconhecida pacote=d licenca=LicenseRef-X"


def test_excecao_de_compilador_nao_torna_copyleft_uma_licenca_permissiva() -> None:
    assert licencas_declaradas(_falsa("a", "License-Expression: MIT WITH LLVM-exception")) == [
        "MIT"
    ]
    dist = _falsa("b", "License-Expression: GPL-2.0-only WITH Classpath-exception-2.0")
    assert _avaliar(dist) == "licenca_copyleft pacote=b licenca=GPL-2.0-only"


def test_classificadores_genericos_e_rotulos_curtos_sao_mapeados() -> None:
    bsd = _falsa("a", "Classifier: License :: OSI Approved :: BSD License")
    mit = _falsa("b", "License: MIT License")
    assert (licencas_declaradas(bsd), licencas_declaradas(mit)) == (["BSD"], ["MIT"])
    assert _avaliar(bsd) is None
    assert _avaliar(mit) is None


def test_texto_longo_no_campo_license_nao_e_interpretado_com_classificador_permissivo() -> None:
    texto = "License: Texto agregado com GNU General Public License de componentes embarcados"
    dist = _falsa("a", texto, "Classifier: License :: OSI Approved :: BSD License")
    assert _avaliar(dist) is None


def test_texto_longo_sem_classificador_reprova_como_desconhecido() -> None:
    texto = "Texto agregado com licenças de componentes embarcados, sem identificador SPDX"
    mensagem = _avaliar(_falsa("a", f"License: {texto}"))
    assert mensagem == f"licenca_desconhecida pacote=a licenca={texto[:_TEXTO_CURTO]}"


def test_excecao_justificada_dispensa_o_pacote() -> None:
    dist = _falsa("leitor", "License-Expression: LGPL-3.0-only")
    justificativa = {"leitor": "licença conferida à mão no arquivo LICENSE do pacote"}
    assert avaliar("leitor", dist, _PERMITIDAS, justificativa) is None


def test_fechamento_segue_as_dependencias_transitivas() -> None:
    a = _falsa("a", "Requires-Dist: b>=1")
    b = _falsa("b", "Requires-Dist: Sub_C")
    c = _falsa("sub-c")
    fechamento = fechamento_de_runtime([Requirement("a")], _resolvedor(a, b, c))
    assert set(fechamento) == {"a", "b", "sub-c"}


def test_fechamento_ignora_extras_e_marcadores_falsos() -> None:
    a = _falsa(
        "a",
        'Requires-Dist: so-de-teste; extra == "dev"',
        'Requires-Dist: so-do-windows; sys_platform == "plataforma-inexistente"',
        "Requires-Dist: comum",
    )
    resolvedor = _resolvedor(a, _falsa("comum"), _falsa("so-de-teste"), _falsa("so-do-windows"))
    assert set(fechamento_de_runtime([Requirement("a")], resolvedor)) == {"a", "comum"}


def test_fechamento_inclui_o_extra_pedido_pelo_requisito() -> None:
    a = _falsa("a", 'Requires-Dist: opcional; extra == "x"')
    resolvedor = _resolvedor(a, _falsa("opcional"))
    assert set(fechamento_de_runtime([Requirement("a[x]")], resolvedor)) == {"a", "opcional"}


def test_fechamento_tolera_ciclos() -> None:
    a = _falsa("a", "Requires-Dist: b")
    b = _falsa("b", "Requires-Dist: a")
    assert set(fechamento_de_runtime([Requirement("a")], _resolvedor(a, b))) == {"a", "b"}


def test_fechamento_recusa_dependencia_declarada_e_nao_instalada() -> None:
    a = _falsa("a", "Requires-Dist: ausente")
    with pytest.raises(AssertionError, match="dependencia_nao_instalada pacote=ausente"):
        fechamento_de_runtime([Requirement("a")], _resolvedor(a))
