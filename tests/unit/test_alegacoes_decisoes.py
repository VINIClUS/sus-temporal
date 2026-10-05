"""Estado de cada alegação × decisão humana que a cita (T14).

Mudar o estado de uma alegação exige decisão humana específica: o id e o mesmo estado em
`experiments/decisions/alegacoes/<AAAA-MM-DD>.yaml`, caminho só de humanos no mapa de propriedade e
conferido pelo CI de propriedade. CONFIRMADA e NAO_CONFIRMADA exigem também a decisão de cada
portão de que a alegação depende. As decisões de teste ficam em diretório temporário.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts.check_ownership import carregar_especificacao, encontrar_violacoes

from sustemporal.contracts.experiment import Portao
from sustemporal.gates import carregar_decisoes
from tests.unit.test_alegacoes import RAIZ, _bloco, _validar

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_FREEZE = f"frz_{'a' * 64}"
_G0 = (
    "portao: G0\ndecisao: {}\ndata: 2025-01-15\nresponsaveis: [orientacao]\n"
    "registrado_por_humano: true\n"
)
_G2 = (
    "portao: G2\ndecisao: ABRIR_TESTE\ndata: 2025-06-01\nresponsaveis: [orientacao]\n"
    f"registrado_por_humano: true\nfreeze_id: {_FREEZE}\n"
)
_DECISAO = (
    "data: {data}\nresponsaveis: [orientacao]\nregistrado_por_humano: true\n"
    "evidencias: [relatorio.json]\nalegacoes:\n{itens}"
)
_VALIDA = _DECISAO.format(data="2027-03-01", itens="  AL-01: CONFIRMADA\n")
_SEM_DECISAO = "estado_sem_decisao_da_alegacao id=AL-01 estado={}"
_SEM_PORTAO = "alegacao_sem_decisao_humana id=AL-01 estado={} portao={}"
_DIVERGE = "estado_diverge_da_decisao id=AL-01 estado={} decidido={}"


def _registrar(diretorio: Path, nome: str, conteudo: str) -> None:
    diretorio.mkdir(parents=True, exist_ok=True)
    (diretorio / nome).write_text(conteudo, encoding="utf-8")


def _g0_aberto(diretorio: Path) -> None:
    _registrar(diretorio, "G0_2025-01-15.yaml", _G0.format("CONTINUAR"))


def _decidir(
    diretorio: Path,
    alegacoes: Mapping[str, str],
    *,
    nome: str = "2027-03-01.yaml",
    data: str = "2027-03-01",
) -> None:
    itens = "".join(f"  {id_}: {estado}\n" for id_, estado in alegacoes.items())
    _registrar(diretorio / "alegacoes", nome, _DECISAO.format(data=data, itens=itens))


@pytest.mark.parametrize("estado", ["CONFIRMADA", "NAO_CONFIRMADA"])
def test_alegacao_com_resultado_sem_decisao_de_portao_reprova(estado: str, tmp_path: Path) -> None:
    _decidir(tmp_path, {"AL-01": estado})
    problemas = _validar(_bloco(estado=estado, depende="G0, DADOS_REAIS"), tmp_path)
    assert problemas == [_SEM_PORTAO.format(estado, "G0")]


def test_modelo_de_decisao_de_portao_nao_libera_alegacao(tmp_path: Path) -> None:
    _registrar(tmp_path, "MODELO_G0.yaml", _G0.format("CONTINUAR"))
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"})
    problemas = _validar(_bloco(estado="CONFIRMADA"), tmp_path)
    assert problemas == [_SEM_PORTAO.format("CONFIRMADA", "G0")]


def test_decisao_g0_que_nao_libera_o_portao_nao_basta(tmp_path: Path) -> None:
    _registrar(tmp_path, "G0_2025-01-15.yaml", _G0.format("REFORMULAR"))
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"})
    problemas = _validar(_bloco(estado="CONFIRMADA"), tmp_path)
    assert problemas == [_SEM_PORTAO.format("CONFIRMADA", "G0")]


def test_decisao_humana_de_teste_em_diretorio_temporario_libera_g0(tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"})
    assert _validar(_bloco(estado="CONFIRMADA"), tmp_path) == []


def test_alegacao_confirmatoria_exige_a_decisao_g2_do_congelamento(tmp_path: Path) -> None:
    texto = _bloco(estado="CONFIRMADA", natureza="CONFIRMATORIA", depende="G2, DADOS_REAIS")
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"})
    assert _validar(texto, tmp_path) == [_SEM_PORTAO.format("CONFIRMADA", "G2")]
    _registrar(tmp_path, "G2_2025-06-01.yaml", _G2)
    assert _validar(texto, tmp_path) == []


def test_esboco_pendente_impede_alegacao_que_depende_dele(tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"})
    texto = _bloco(estado="CONFIRMADA", depende="G0, DADOS_REAIS, ESBOCO")
    assert _validar(texto, tmp_path, esboco=False) == [
        "alegacao_sobre_esboco_pendente id=AL-01 estado=CONFIRMADA"
    ]
    assert _validar(texto, tmp_path, esboco=True) == []


def test_alegacao_pendente_sem_decisao_e_aceita(tmp_path: Path) -> None:
    assert _validar(_bloco(estado="PENDENTE"), tmp_path) == []


def test_alegacao_exploratoria_exige_a_decisao_da_alegacao_mas_nao_a_do_portao(
    tmp_path: Path,
) -> None:
    texto = _bloco(estado="EXPLORATORIA", depende="G2, DADOS_REAIS")
    assert _validar(texto, tmp_path) == [_SEM_DECISAO.format("EXPLORATORIA")]
    _decidir(tmp_path, {"AL-01": "EXPLORATORIA"})
    assert _validar(texto, tmp_path) == []


@pytest.mark.parametrize("estado", ["EXPLORATORIA", "CONFIRMADA", "NAO_CONFIRMADA"])
def test_estado_sem_decisao_que_cite_a_alegacao_reprova(estado: str, tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    problemas = _validar(_bloco(estado=estado), tmp_path)
    assert problemas == [_SEM_DECISAO.format(estado)]


def test_decisao_de_portao_aberto_nao_substitui_a_decisao_da_alegacao(tmp_path: Path) -> None:
    _registrar(tmp_path, "G2_2025-06-01.yaml", _G2)
    texto = _bloco(estado="CONFIRMADA", natureza="CONFIRMATORIA", depende="G2, DADOS_REAIS")
    assert _validar(texto, tmp_path) == [_SEM_DECISAO.format("CONFIRMADA")]


def test_decisao_que_cita_outra_alegacao_nao_basta(tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    _decidir(tmp_path, {"AL-02": "CONFIRMADA"})
    texto = _bloco(1, estado="CONFIRMADA") + "\n" + _bloco(2, estado="CONFIRMADA")
    assert _validar(texto, tmp_path) == [_SEM_DECISAO.format("CONFIRMADA")]


def test_decisao_que_cita_a_alegacao_com_o_mesmo_estado_libera(tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"})
    assert _validar(_bloco(estado="CONFIRMADA"), tmp_path) == []


def test_decisao_em_arquivo_yml_tambem_vale(tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"}, nome="2027-03-01.yml")
    assert _validar(_bloco(estado="CONFIRMADA"), tmp_path) == []


def test_estado_diferente_do_decidido_reprova(tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    _decidir(tmp_path, {"AL-01": "NAO_CONFIRMADA"})
    problemas = _validar(_bloco(estado="CONFIRMADA"), tmp_path)
    assert problemas == [_DIVERGE.format("CONFIRMADA", "NAO_CONFIRMADA")]


def test_alegacao_pendente_com_decisao_de_outro_estado_reprova(tmp_path: Path) -> None:
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"})
    problemas = _validar(_bloco(estado="PENDENTE"), tmp_path)
    assert problemas == [_DIVERGE.format("PENDENTE", "CONFIRMADA")]


def test_decisao_em_arquivo_de_modelo_nao_conta(tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"}, nome="MODELO_ALEGACOES.yaml")
    problemas = _validar(_bloco(estado="CONFIRMADA"), tmp_path)
    assert problemas == [_SEM_DECISAO.format("CONFIRMADA")]


def test_decisao_fora_do_subdiretorio_das_alegacoes_nao_conta(tmp_path: Path) -> None:
    _registrar(tmp_path, "2027-03-01.yaml", _VALIDA)
    problemas = _validar(_bloco(estado="EXPLORATORIA"), tmp_path)
    assert problemas == [_SEM_DECISAO.format("EXPLORATORIA")]


def test_a_decisao_mais_recente_da_alegacao_prevalece_pela_data_e_nao_pelo_nome(
    tmp_path: Path,
) -> None:
    _g0_aberto(tmp_path)
    _decidir(tmp_path, {"AL-01": "NAO_CONFIRMADA"}, nome="a.yaml", data="2027-06-01")
    _decidir(tmp_path, {"AL-01": "EXPLORATORIA"}, nome="b.yaml", data="2027-01-10")
    assert _validar(_bloco(estado="NAO_CONFIRMADA"), tmp_path) == []
    antiga = _validar(_bloco(estado="EXPLORATORIA"), tmp_path)
    assert antiga == [_DIVERGE.format("EXPLORATORIA", "NAO_CONFIRMADA")]


def test_decisoes_da_mesma_data_com_estados_diferentes_reprovam(tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"}, nome="a.yaml")
    _decidir(tmp_path, {"AL-01": "NAO_CONFIRMADA"}, nome="b.yaml")
    problemas = _validar(_bloco(estado="CONFIRMADA"), tmp_path)
    assert problemas == ["decisoes_de_alegacao_empatadas id=AL-01 data=2027-03-01"]


def test_decisao_que_cita_alegacao_inexistente_reprova(tmp_path: Path) -> None:
    _decidir(tmp_path, {"AL-09": "CONFIRMADA"})
    problemas = _validar(_bloco(estado="PENDENTE"), tmp_path)
    assert problemas == ["decisao_cita_alegacao_inexistente id=AL-09"]


def test_decisao_de_referencia_e_valida(tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    _registrar(tmp_path / "alegacoes", "2027-03-01.yaml", _VALIDA)
    assert _validar(_bloco(estado="CONFIRMADA"), tmp_path) == []


@pytest.mark.parametrize(
    "conteudo",
    [
        _VALIDA.replace("registrado_por_humano: true", "registrado_por_humano: false"),
        _VALIDA.replace("[orientacao]", "[]"),
        _VALIDA.replace("[relatorio.json]", "[]"),
        _VALIDA.replace("[orientacao]", '[" "]'),
        _VALIDA.replace("[relatorio.json]", '[""]'),
        _VALIDA.replace("evidencias: [relatorio.json]\n", ""),
        _VALIDA.replace("AL-01: CONFIRMADA", "AL-01: OK"),
        _VALIDA.replace("AL-01:", "AL-1:"),
        _VALIDA.replace("2027-03-01", "ontem"),
        _VALIDA + "observacao_solta: x\n",
        "alegacoes: [",
    ],
    ids=[
        "nao_registrada_por_humano",
        "sem_responsavel",
        "evidencia_vazia",
        "responsavel_em_branco",
        "evidencia_em_branco",
        "sem_evidencia",
        "estado_fora_do_vocabulario",
        "id_mal_formado",
        "data_invalida",
        "campo_desconhecido",
        "yaml_ilegivel",
    ],
)
def test_decisao_de_alegacao_invalida_reprova_e_nao_libera(conteudo: str, tmp_path: Path) -> None:
    _g0_aberto(tmp_path)
    _registrar(tmp_path / "alegacoes", "2027-03-01.yaml", conteudo)
    problemas = _validar(_bloco(estado="CONFIRMADA"), tmp_path)
    assert problemas == [
        "decisao_de_alegacao_invalida arquivo=2027-03-01.yaml",
        _SEM_DECISAO.format("CONFIRMADA"),
    ]


def test_decisoes_de_alegacao_ficam_fora_do_carregamento_dos_portoes(tmp_path: Path) -> None:
    _decidir(tmp_path, {"AL-01": "CONFIRMADA"})
    assert carregar_decisoes(tmp_path, Portao.G0) == []
    _g0_aberto(tmp_path)
    assert len(carregar_decisoes(tmp_path, Portao.G0)) == 1


def test_diretorio_das_decisoes_de_alegacao_e_so_de_humanos_no_mapa_de_propriedade() -> None:
    especificacao = carregar_especificacao(RAIZ / "docs" / "process" / "propriedade.yaml")
    caminho = "experiments/decisions/alegacoes/2027-03-01.yaml"
    assert especificacao.donos
    for dono in especificacao.donos:
        assert encontrar_violacoes([caminho], dono, especificacao) == [caminho], dono
