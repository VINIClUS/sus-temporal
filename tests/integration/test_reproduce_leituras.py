"""Varredura das leituras do `reproduce`: cada arquivo que a cadeia abre, estragado (T14).

`LEITURAS` (a tabela da seção 5.5 do runbook) diz que arquivos a cadeia abre e o resultado
documentado de cada dano: diretório no lugar do arquivo, sem permissão e bytes que não decodificam
ou truncados. Aqui cada leitura é estragada de verdade no mundo temporário (o catálogo do clone
só falha na abertura: o teste não o toca) e o `reproduce` roda; nenhum dano dá traceback,
`DIVERGENTE` ou `IGUAL` sem justificativa, e o resultado é o da tabela. Os arquivos independentes
que só pesam no fim da reprodução saem estragados juntos, numa reprodução só; os que a param cedo
rodam um por vez. Uma auditoria das aberturas de uma reprodução sem estrago falha se a cadeia abre
arquivo que a tabela não tem, e um cenário a mais é exigido para cada leitura que a tabela estraga.
O que não se estraga no mundo temporário (o destino da reprodução, o código) está na tabela com o
motivo. Nada aqui é resultado empírico.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.reproducao_estragos import aberturas, estragado, estragado_na_abertura
from tests.fixtures.reproducao_fluxo import (
    Fluxo,
    Reproducao,
    adquirir_e_ingerir,
    artefatos_do_sia_pa,
    congelar_e_avaliar,
    derivar,
    iniciar,
    reproduzir,
    validar_janelas,
    yaml_em_memoria,
)
from tests.fixtures.reproducao_mundo import DRS_XI, JANELAS, RAIZ, escrever_config

from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts import FamiliaFonte
from sustemporal.errors import ExitCode
from sustemporal.evaluation.freeze_registro import ler_registro
from sustemporal.reporting.reproduce_leituras import (
    LEITURAS,
    Dano,
    Leitura,
    Raiz,
    Resultado,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

pytestmark = pytest.mark.slow

COMPETENCIA = "202401"
BINARIOS = {".parquet", ".dbc", ".zip"}
CHAVE_VALOR = re.compile(r"^[a-z][a-z0-9_]* \w+=")
ERRO_DO_CLI = re.compile(
    r"ERROR sustemporal\.cli (?:comando_falhou|config_invalida) .*? erro=(.*)$"
)
DO_INTERPRETADOR = (
    sys.prefix,
    sys.base_prefix,
    sys.exec_prefix,
    "/usr",
    "/proc",
    "/sys",
    "/dev",
    "/etc",
    "/lib",
    "/opt",
)
SEM_ORIGINAL = {"original_ausente", "original_ilegivel"}
COM_COPIA = ("territorio", "leiaute_sia_pa")


@dataclass(frozen=True)
class Alvo:
    """Um arquivo a estragar; `no_clone` é o do repositório, que só falha na abertura."""

    caminho: Path
    binario: bool = False
    no_clone: bool = False


@dataclass(frozen=True)
class Cenario:
    """Leituras estragadas juntas numa reprodução e os danos em que isso vale.

    `itens` troca os itens que a tabela dá a uma leitura quando o grupo precisa do método.
    """

    nome: str
    linhas: tuple[str, ...]
    danos: tuple[Dano, ...] = tuple(Dano)
    itens: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def pares(self) -> list[tuple[Cenario, Dano]]:
        return [
            (self, d) for d in self.danos if all(d in LEITURAS[c].estragos for c in self.linhas)
        ]


DA_COMPARACAO = ("relatorio", "execucao_original", "saidas_originais")
DOS_METODOS = {
    "execucao_original": ("saida:M_TEMP:*",),
    "saidas_originais": ("saida:B_ATEND:*",),
}
CENARIOS = (
    Cenario(
        "originais_da_comparacao", DA_COMPARACAO, (Dano.DIRETORIO, Dano.PERMISSAO), DOS_METODOS
    ),
    Cenario(
        "originais_da_comparacao_e_conjuntos",
        (*DA_COMPARACAO, "conjuntos_originais"),
        (Dano.BYTES,),
        DOS_METODOS,
    ),
    Cenario(
        "registro_e_conjuntos",
        ("registro", "conjuntos_originais"),
        (Dano.DIRETORIO, Dano.PERMISSAO),
    ),
    Cenario("registro_adulterado", ("registro",), (Dano.BYTES,)),
    *(
        Cenario(chave, (chave,))
        for chave, leitura in LEITURAS.items()
        if leitura.estragos and chave not in {*DA_COMPARACAO, "conjuntos_originais", "registro"}
    ),
)


@pytest.fixture(scope="module", autouse=True)
def _catalogos_em_memoria() -> Iterator[None]:
    with yaml_em_memoria():
        yield


@pytest.fixture(scope="module")
def fluxo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Fluxo]:
    with pytest.MonkeyPatch.context() as mp:
        estado = iniciar(tmp_path_factory.mktemp("leituras"), mp)
        adquirir_e_ingerir(estado)
        validar_janelas(estado)
        derivar(estado, inspecionados=artefatos_do_sia_pa(estado, "dev"))
        congelar_e_avaliar(estado)
        yield estado


@pytest.fixture(scope="module")
def configs_com_copia(fluxo: Fluxo) -> dict[str, Path]:
    """A config do congelamento com o arquivo da leitura em cópia, que o teste pode estragar.

    O território e o leiaute do SIA-PA vêm do repositório; a cópia, com o mesmo conteúdo, entra
    pela config (`piloto.territorio` e `catalogos.leiaute_sia_pa`).
    """
    mundo = fluxo.mundo
    territorio = mundo.raiz / "territorio_copia.yaml"
    territorio.write_bytes(DRS_XI.read_bytes())
    texto = fluxo.configs["teste"].read_text(encoding="utf-8")
    config_territorio = mundo.raiz / "config_territorio.yaml"
    config_territorio.write_text(texto.replace(str(DRS_XI), str(territorio)), encoding="utf-8")
    leiaute = mundo.raiz / "leiaute_sia_pa_copia.yaml"
    leiaute.write_bytes((RAIZ / "catalog" / "layouts" / "sia_pa.yaml").read_bytes())
    config_leiaute = escrever_config(
        mundo, "leiaute", JANELAS["teste"], extras_de_catalogo={"leiaute_sia_pa": leiaute}
    )
    return {"territorio": config_territorio, "leiaute_sia_pa": config_leiaute}


def _raizes(fluxo: Fluxo, destino: Path) -> dict[Raiz, Path]:
    mundo = fluxo.mundo
    return {
        Raiz.CONFIG: fluxo.configs["teste"],
        Raiz.CONGELAMENTOS: mundo.congelamentos,
        Raiz.MANIFESTOS: mundo.raiz / "manifestos",
        Raiz.SAIDAS: mundo.saidas,
        Raiz.DADOS: mundo.raiz / "dados",
        Raiz.FONTES: mundo.fontes,
        Raiz.TERRITORIO: DRS_XI,
        Raiz.CATALOGO: RAIZ / "catalog",
        Raiz.TRABALHO: mundo.raiz,
        Raiz.DESTINO: destino,
        Raiz.CODIGO: RAIZ,
        Raiz.TEMPORARIO: Path(tempfile.gettempdir()),
    }


def _linhas_do_arquivo(caminho: str, raizes: Mapping[Raiz, Path]) -> list[str]:
    """As chaves de `LEITURAS` que casam com o arquivo, pela raiz mais específica dele."""
    arquivo = Path(caminho)
    candidatas = [
        (r, base) for r, base in raizes.items() if arquivo == base or base in arquivo.parents
    ]
    if not candidatas:
        return []
    raiz, base = max(candidatas, key=lambda candidata: len(candidata[1].parts))
    relativo = "." if arquivo == base else arquivo.relative_to(base).as_posix()
    return [chave for chave, leitura in LEITURAS.items() if leitura.casa(raiz, relativo)]


def _do_interpretador(caminho: str) -> bool:
    return any(caminho == base or caminho.startswith(f"{base}/") for base in DO_INTERPRETADOR)


def test_toda_abertura_da_reproducao_tem_uma_linha_na_varredura(fluxo: Fluxo) -> None:
    destino = fluxo.mundo.raiz / "reproducao_auditada"
    with aberturas() as lidas:
        feita = reproduzir(fluxo, fluxo.configs["teste"], destino)
    assert feita.codigo == ExitCode.OK
    raizes = _raizes(fluxo, destino)
    abertas = {caminho for caminho, _ in lidas if not _do_interpretador(caminho)}
    achadas = {caminho: _linhas_do_arquivo(caminho, raizes) for caminho in sorted(abertas)}
    assert {c: ls for c, ls in achadas.items() if not ls} == {}
    assert {c: ls for c, ls in achadas.items() if len(ls) > 1} == {}
    lidas_da_tabela = {chave for linhas in achadas.values() for chave in linhas}
    sem_abertura = {c for c, leitura in LEITURAS.items() if leitura.estragos} - lidas_da_tabela
    assert sem_abertura == set()


def test_toda_leitura_que_a_tabela_estraga_tem_um_cenario_para_cada_dano() -> None:
    cobertos = {
        (chave, dano)
        for cenario in CENARIOS
        for _, dano in cenario.pares()
        for chave in cenario.linhas
    }
    esperados = {(c, d) for c, leitura in LEITURAS.items() for d in leitura.estragos}
    assert esperados - cobertos == set()


def test_cenario_com_mais_de_uma_leitura_so_junta_resultados_que_nao_se_mascaram() -> None:
    juntaveis = {Resultado.INCONCLUSIVO, Resultado.IGUAL_PELO_DECLARADO}
    for cenario in CENARIOS:
        for _, dano in cenario.pares():
            resultados = {LEITURAS[c].estragos[dano].resultado for c in cenario.linhas}
            assert len(cenario.linhas) == 1 or resultados <= juntaveis, cenario.nome


def _arquivo_bruto(fluxo: Fluxo, familia: FamiliaFonte) -> Path:
    estado = Manifesto(fluxo.mundo.raiz / "manifestos" / "aquisicao.jsonl").ler()
    (versao,) = (
        v
        for v in estado.versoes.values()
        if v.chave.fonte is familia and str(v.chave.competencia_arquivo) == COMPETENCIA
    )
    return fluxo.mundo.raiz / "dados" / "raw" / versao.caminho_conteudo


def _runs_registrados(fluxo: Fluxo) -> dict[str, Path]:
    """A pasta de cada execução da rodada registrada, por método."""
    registro = ler_registro(fluxo.mundo.congelamentos / "registro_execucoes.jsonl")
    entrada = [e for e in registro if e["freeze_id"] == fluxo.freeze_id][-1]
    pastas = {}
    for run_id in entrada["runs"]:
        pasta = fluxo.mundo.saidas / "runs" / run_id
        metodo = json.loads((pasta / "run_result.json").read_text(encoding="utf-8"))["metodo"]
        pastas[metodo] = pasta
    return pastas


def _arquivos(raiz: Path, leitura: Leitura) -> list[Path]:
    if leitura.padroes == (".",):
        return [raiz]
    return [arquivo for padrao in leitura.padroes for arquivo in sorted(raiz.glob(padrao))]


def _alvos_do_mundo(fluxo: Fluxo, chave: str, raiz: Path) -> list[Path]:
    especiais = {
        "execucao_original": lambda: [_runs_registrados(fluxo)["M_TEMP"] / "run_result.json"],
        "saidas_originais": lambda: sorted(_runs_registrados(fluxo)["B_ATEND"].glob("*.parquet")),
        "territorio": lambda: [fluxo.mundo.raiz / "territorio_copia.yaml"],
        "leiaute_sia_pa": lambda: [fluxo.mundo.raiz / "leiaute_sia_pa_copia.yaml"],
        "brutos_dbc": lambda: [
            _arquivo_bruto(fluxo, familia)
            for familia in (FamiliaFonte.SIA_PA, FamiliaFonte.CNES_PF, FamiliaFonte.CNES_ST)
        ],
        "brutos_zip": lambda: [_arquivo_bruto(fluxo, FamiliaFonte.SIGTAP)],
        "insumos": lambda: _arquivos(raiz, LEITURAS[chave]),
        "conjuntos_originais": lambda: _arquivos(raiz, LEITURAS[chave]),
    }
    if chave in especiais:
        return especiais[chave]()
    return _arquivos(raiz, LEITURAS[chave])[:1]


def _alvos(fluxo: Fluxo, chave: str) -> list[Alvo]:
    leitura = LEITURAS[chave]
    raiz = _raizes(fluxo, fluxo.mundo.raiz)[leitura.raiz]
    no_clone = leitura.raiz is Raiz.CATALOGO and chave not in COM_COPIA
    return [
        Alvo(caminho, caminho.suffix in BINARIOS, no_clone)
        for caminho in _alvos_do_mundo(fluxo, chave, raiz)
    ]


def _a_mensagem_do_cli(erro: str) -> str:
    """O texto depois de `erro=` da última linha de erro do CLI, ou vazio."""
    achadas = [m.group(1) for linha in erro.splitlines() if (m := ERRO_DO_CLI.search(linha))]
    return achadas[-1] if achadas else ""


def _rodar(
    fluxo: Fluxo, config: Path, cenario: Cenario, dano: Dano, capsys: pytest.CaptureFixture[str]
) -> tuple[Reproducao, str]:
    destino = fluxo.mundo.raiz / f"reproducao_{cenario.nome}_{dano.value.lower()}"
    alvos = [alvo for chave in cenario.linhas for alvo in _alvos(fluxo, chave)]
    capsys.readouterr()
    with ExitStack() as pilha:
        for alvo in alvos:
            if alvo.no_clone:
                pilha.enter_context(estragado_na_abertura(alvo.caminho, dano))
            else:
                pilha.enter_context(estragado(alvo.caminho, dano, binario=alvo.binario))
        feita = reproduzir(fluxo, config, destino)
    return feita, _a_mensagem_do_cli(capsys.readouterr().err)


def _confere_a_recusa(feita: Reproducao, mensagem: str, codigo: ExitCode) -> None:
    assert feita.codigo == codigo
    assert feita.conteudo == {}
    assert CHAVE_VALOR.match(mensagem), mensagem


def _explicado(item: str, padroes: Sequence[str]) -> bool:
    return any(fnmatchcase(item, padrao) for padrao in padroes)


def _confere_os_itens(
    feita: Reproducao, cenario: Cenario, dano: Dano, esperados: Mapping[str, Sequence[str]]
) -> None:
    situacoes, itens = feita.situacoes, feita.itens
    assert "DIVERGENTE" not in situacoes.values()
    for chave in cenario.linhas:
        estrago = LEITURAS[chave].estragos[dano]
        casados = [i for i in situacoes if _explicado(i, esperados[chave])]
        if estrago.resultado is Resultado.INCONCLUSIVO:
            assert {situacoes[i] for i in casados} >= {"INCONCLUSIVO"}, (chave, situacoes)
        else:
            detalhes = {itens[i]["detalhe"] for i in casados if situacoes[i] == "IGUAL"}
            assert detalhes & SEM_ORIGINAL, (chave, detalhes)
        if estrago.observacao:
            assert any(estrago.observacao in o for o in feita.conteudo["observacoes"]), chave
    explicados = [padrao for padroes in esperados.values() for padrao in padroes]
    fora = {i: s for i, s in situacoes.items() if s != "IGUAL" and not _explicado(i, explicados)}
    assert fora == {}


def _confere_o_cenario(feita: Reproducao, mensagem: str, cenario: Cenario, dano: Dano) -> None:
    estragos = {chave: LEITURAS[chave].estragos[dano] for chave in cenario.linhas}
    resultados = {estrago.resultado for estrago in estragos.values()}
    if resultados == {Resultado.CONFIG_INVALIDA}:
        _confere_a_recusa(feita, mensagem, ExitCode.CONFIG_INVALIDA)
    elif resultados == {Resultado.FALHA}:
        _confere_a_recusa(feita, mensagem, ExitCode.FALHA_OPERACIONAL)
    else:
        inconclusivo = Resultado.INCONCLUSIVO in resultados
        assert feita.codigo == (ExitCode.FALHA_OPERACIONAL if inconclusivo else ExitCode.OK)
        assert feita.conteudo["resultado"] == ("INCONCLUSIVO" if inconclusivo else "IGUAL")
        esperados = {c: cenario.itens.get(c, e.itens) for c, e in estragos.items()}
        _confere_os_itens(feita, cenario, dano, esperados)


PARES = [
    pytest.param(c, d, id=f"{c.nome}-{d.value.lower()}") for k in CENARIOS for c, d in k.pares()
]


@pytest.mark.parametrize(("cenario", "dano"), PARES)
def test_arquivo_estragado_tem_o_resultado_documentado_e_nunca_traceback(
    fluxo: Fluxo,
    configs_com_copia: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    cenario: Cenario,
    dano: Dano,
) -> None:
    config = next(
        (configs_com_copia[chave] for chave in cenario.linhas if chave in COM_COPIA),
        fluxo.configs["teste"],
    )
    feita, mensagem = _rodar(fluxo, config, cenario, dano, capsys)
    _confere_o_cenario(feita, mensagem, cenario, dano)
