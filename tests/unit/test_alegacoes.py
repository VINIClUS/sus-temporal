"""Auditoria de `docs/method/claims.md`: cada alegação com evidência exigida e estado (T14).

Cada alegação é um bloco `### AL-NN — título` com campos `- **Campo:** valor`. Nenhuma pode
estar CONFIRMADA (ou NAO_CONFIRMADA) sem decisão humana registrada em `experiments/decisions/`
para cada portão de que depende, e o texto não traz a linguagem proibida pelo AGENTS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Sequence

RAIZ = Path(__file__).resolve().parents[2]
CLAIMS = RAIZ / "docs" / "method" / "claims.md"
DECISOES = RAIZ / "experiments" / "decisions"
MANIFESTO = RAIZ / "docs" / "spec" / "manifest.yaml"

CAMPOS_OBRIGATORIOS = (
    "Conclusão possível",
    "Natureza",
    "Evidência exigida",
    "Depende de",
    "Estado",
    "Limites",
)
ESTADOS = ("PENDENTE", "EXPLORATORIA", "CONFIRMADA", "NAO_CONFIRMADA")
ESTADOS_COM_RESULTADO = ("CONFIRMADA", "NAO_CONFIRMADA")
NATUREZAS = ("DESCRITIVA", "EXPLORATORIA", "CONFIRMATORIA")
PORTOES = ("G0", "G1", "G2")
DEPENDENCIAS = (
    *PORTOES,
    "DADOS_REAIS",
    "DOCUMENTO_OFICIAL",
    "ESPECIALISTA",
    "AVALIADORES",
    "ORIENTACAO",
    "ESBOCO",
)
PROIBIDAS = {
    "garante aprovação": r"garant\w*\s+(?:a\s+|de\s+)?aprovacao|aprovacao\s+garantid[ao]s?",
    "assegura aprovação": r"assegur\w*\s+(?:a\s+|de\s+)?aprovacao",
    "perda financeira": r"perdas?\s+financeiras?",
    "causa oficial": r"causas?\s+oficia(?:l|is)",
    "demonstramos": r"demonstramos|comprovamos|provamos",
    "o método funciona": r"\bo\s+metodo\s+funciona",
}


@dataclass(frozen=True)
class Alegacao:
    id: str
    titulo: str
    campos: dict[str, str]
    repetidos: tuple[str, ...] = field(default=())


def ler_alegacoes(texto: str) -> list[Alegacao]:
    raise NotImplementedError


def termos_proibidos(texto: str) -> list[str]:
    raise NotImplementedError


def validar_alegacoes(
    alegacoes: Sequence[Alegacao], *, decisoes: Path, esboco_preservado: bool
) -> list[str]:
    raise NotImplementedError


def _esboco_preservado() -> bool:
    conteudo = yaml.safe_load(MANIFESTO.read_text(encoding="utf-8"))
    estados = {doc["id"]: doc["estado"] for doc in conteudo["documentos"]}
    return estados["esboco_original"] == "PRESERVADO"


def _texto_do_registro() -> str:
    assert CLAIMS.is_file(), "claims_ausente caminho=docs/method/claims.md"
    return CLAIMS.read_text(encoding="utf-8")


def _problemas_do_registro(*prefixos: str) -> list[str]:
    alegacoes = ler_alegacoes(_texto_do_registro())
    problemas = validar_alegacoes(
        alegacoes, decisoes=DECISOES, esboco_preservado=_esboco_preservado()
    )
    return [p for p in problemas if not prefixos or p.startswith(prefixos)]


def test_registro_traz_alegacoes_com_ids_unicos_e_sequenciais() -> None:
    alegacoes = ler_alegacoes(_texto_do_registro())
    ids = [alegacao.id for alegacao in alegacoes]
    assert ids, "claims_sem_alegacoes"
    assert ids == [f"AL-{n:02d}" for n in range(1, len(ids) + 1)]


def test_toda_alegacao_tem_evidencia_exigida_e_estado() -> None:
    assert _problemas_do_registro("alegacao_sem_campo", "campo_repetido", "estado_invalido") == []


def test_toda_alegacao_declara_natureza_e_portao_ou_dado_real() -> None:
    prefixos = ("natureza_invalida", "dependencia_invalida", "alegacao_sem_portao_nem_dado_real")
    assert _problemas_do_registro(*prefixos) == []


def test_alegacao_confirmatoria_depende_de_g2_e_de_dados_reais() -> None:
    assert _problemas_do_registro("confirmatoria_sem_g2_e_dados_reais") == []


def test_nenhuma_alegacao_confirmada_sem_decisao_humana_em_experiments_decisions() -> None:
    assert _problemas_do_registro("alegacao_sem_decisao_humana", "alegacao_sobre_esboco") == []


def test_registro_nao_traz_linguagem_proibida() -> None:
    assert termos_proibidos(_texto_do_registro()) == []


def test_registro_declara_que_teste_de_software_nao_e_confirmacao_empirica() -> None:
    texto = " ".join(_texto_do_registro().split())
    assert "Nenhum teste de software" in texto
    assert "SINTETICO" in texto


def test_registro_inteiro_passa_na_validacao() -> None:
    assert _problemas_do_registro() == []


def _bloco(
    n: int = 1,
    *,
    estado: str = "PENDENTE",
    natureza: str = "DESCRITIVA",
    depende: str = "G0, DADOS_REAIS",
    retirar: tuple[str, ...] = (),
) -> str:
    campos = {
        "Conclusão possível": "As fontes são recuperáveis.",
        "Natureza": natureza,
        "Evidência exigida": "Manifesto de aquisição real.",
        "Depende de": depende,
        "Estado": estado,
        "Limites": "Nada além do recorte.",
    }
    linhas = [f"- **{nome}:** {valor}" for nome, valor in campos.items() if nome not in retirar]
    return f"### AL-{n:02d} — Título {n}\n\n" + "\n".join(linhas) + "\n"


def _registrar(diretorio: Path, nome: str, conteudo: str) -> None:
    diretorio.mkdir(parents=True, exist_ok=True)
    (diretorio / nome).write_text(conteudo, encoding="utf-8")


_FREEZE = f"frz_{'a' * 64}"
_G0 = (
    "portao: G0\ndecisao: {}\ndata: 2025-01-15\nresponsaveis: [orientacao]\n"
    "registrado_por_humano: true\n"
)
_G2 = (
    "portao: G2\ndecisao: ABRIR_TESTE\ndata: 2025-06-01\nresponsaveis: [orientacao]\n"
    f"registrado_por_humano: true\nfreeze_id: {_FREEZE}\n"
)


def _validar(texto: str, decisoes: Path, *, esboco: bool = True) -> list[str]:
    return validar_alegacoes(ler_alegacoes(texto), decisoes=decisoes, esboco_preservado=esboco)


def test_leitor_separa_campos_continuacoes_e_ignora_texto_fora_dos_blocos() -> None:
    texto = (
        "# Título\n\nTexto solto com - **Campo:** falso.\n\n"
        "### AL-01 — Primeira\n\n- **Estado:** PENDENTE\n- **Limites:** linha um\n"
        "  e continuação\n\n## Outra seção\n\n- **Estado:** CONFIRMADA\n"
    )
    (alegacao,) = ler_alegacoes(texto)
    assert (alegacao.id, alegacao.titulo) == ("AL-01", "Primeira")
    assert alegacao.campos == {"Estado": "PENDENTE", "Limites": "linha um e continuação"}


def test_leitor_registra_campo_repetido_e_cabecalho_fora_do_formato() -> None:
    (alegacao,) = ler_alegacoes("### AL-01 — A\n- **Estado:** PENDENTE\n- **Estado:** CONFIRMADA\n")
    assert alegacao.repetidos == ("Estado",)
    problemas = _validar("### AL-1 — sem dois dígitos\n", Path("inexistente"))
    assert problemas == ["cabecalho_invalido linha=### AL-1 — sem dois dígitos"]


def test_alegacao_sem_evidencia_exigida_ou_sem_estado_reprova(tmp_path: Path) -> None:
    sem_evidencia = _validar(_bloco(retirar=("Evidência exigida",)), tmp_path)
    assert sem_evidencia == ["alegacao_sem_campo id=AL-01 campo=Evidência exigida"]
    sem_estado = _validar(_bloco(retirar=("Estado",)), tmp_path)
    assert sem_estado == ["alegacao_sem_campo id=AL-01 campo=Estado"]


def test_estado_natureza_e_dependencia_fora_do_vocabulario_reprovam(tmp_path: Path) -> None:
    texto = _bloco(estado="OK", natureza="MAGICA", depende="G0, TALVEZ")
    assert _validar(texto, tmp_path) == [
        "natureza_invalida id=AL-01 valor=MAGICA",
        "estado_invalido id=AL-01 valor=OK",
        "dependencia_invalida id=AL-01 valor=TALVEZ",
    ]


def test_alegacao_sem_portao_nem_dado_real_reprova(tmp_path: Path) -> None:
    texto = _bloco(depende="ORIENTACAO, ESBOCO")
    assert _validar(texto, tmp_path) == ["alegacao_sem_portao_nem_dado_real id=AL-01"]


def test_alegacao_confirmatoria_sem_g2_ou_sem_dados_reais_reprova(tmp_path: Path) -> None:
    sem_g2 = _bloco(natureza="CONFIRMATORIA", depende="G1, DADOS_REAIS")
    sem_dados = _bloco(natureza="CONFIRMATORIA", depende="G2")
    completa = _bloco(natureza="CONFIRMATORIA", depende="G2, DADOS_REAIS")
    esperado = ["confirmatoria_sem_g2_e_dados_reais id=AL-01"]
    assert _validar(sem_g2, tmp_path) == esperado
    assert _validar(sem_dados, tmp_path) == esperado
    assert _validar(completa, tmp_path) == []


@pytest.mark.parametrize("estado", ["CONFIRMADA", "NAO_CONFIRMADA"])
def test_alegacao_com_resultado_sem_decisao_humana_reprova(estado: str, tmp_path: Path) -> None:
    problemas = _validar(_bloco(estado=estado, depende="G0, DADOS_REAIS"), tmp_path / "vazio")
    assert problemas == [f"alegacao_sem_decisao_humana id=AL-01 estado={estado} portao=G0"]


def test_modelo_de_decisao_nao_libera_alegacao(tmp_path: Path) -> None:
    _registrar(tmp_path, "MODELO_G0.yaml", _G0.format("CONTINUAR"))
    problemas = _validar(_bloco(estado="CONFIRMADA"), tmp_path)
    assert problemas == ["alegacao_sem_decisao_humana id=AL-01 estado=CONFIRMADA portao=G0"]


def test_decisao_g0_que_nao_libera_o_portao_nao_basta(tmp_path: Path) -> None:
    _registrar(tmp_path, "G0_2025-01-15.yaml", _G0.format("REFORMULAR"))
    problemas = _validar(_bloco(estado="CONFIRMADA"), tmp_path)
    assert problemas == ["alegacao_sem_decisao_humana id=AL-01 estado=CONFIRMADA portao=G0"]


def test_decisao_humana_de_teste_em_diretorio_temporario_libera_g0(tmp_path: Path) -> None:
    _registrar(tmp_path, "G0_2025-01-15.yaml", _G0.format("CONTINUAR"))
    assert _validar(_bloco(estado="CONFIRMADA"), tmp_path) == []


def test_alegacao_confirmatoria_exige_a_decisao_g2_do_congelamento(tmp_path: Path) -> None:
    texto = _bloco(estado="CONFIRMADA", natureza="CONFIRMATORIA", depende="G2, DADOS_REAIS")
    esperado = ["alegacao_sem_decisao_humana id=AL-01 estado=CONFIRMADA portao=G2"]
    assert _validar(texto, tmp_path) == esperado
    _registrar(tmp_path, "G2_2025-06-01.yaml", _G2)
    assert _validar(texto, tmp_path) == []


def test_alegacao_pendente_ou_exploratoria_nao_exige_decisao(tmp_path: Path) -> None:
    assert _validar(_bloco(estado="PENDENTE"), tmp_path) == []
    assert _validar(_bloco(estado="EXPLORATORIA", depende="G2, DADOS_REAIS"), tmp_path) == []


def test_esboco_pendente_impede_alegacao_que_depende_dele(tmp_path: Path) -> None:
    _registrar(tmp_path, "G0_2025-01-15.yaml", _G0.format("CONTINUAR"))
    texto = _bloco(estado="CONFIRMADA", depende="G0, DADOS_REAIS, ESBOCO")
    assert _validar(texto, tmp_path, esboco=False) == [
        "alegacao_sobre_esboco_pendente id=AL-01 estado=CONFIRMADA"
    ]
    assert _validar(texto, tmp_path, esboco=True) == []


@pytest.mark.parametrize(
    "frase",
    [
        "O contrafactual garante aprovação do registro.",
        "A alteração garante a aprovação.",
        "Há garantia de aprovação após a correção.",
        "O motor assegura aprovação.",
        "A aprovação garantida resulta da simulação.",
        "O valor é perda financeira do município.",
        "As perdas financeiras somam o total.",
        "A regra é a causa oficial da rejeição.",
        "Demonstramos o ganho do M_TEMP.",
        "Concluímos que o método funciona.",
        "O  MÉTODO\nFUNCIONA.",
    ],
)
def test_linguagem_proibida_e_detectada_com_acento_caixa_e_quebra_de_linha(frase: str) -> None:
    assert termos_proibidos(frase) != []


@pytest.mark.parametrize(
    "frase",
    [
        "A explicação não atribui o motivo registrado pelo sistema oficial.",
        "Valor de tabela não aprovado não equivale a dinheiro perdido.",
        "Nenhum teste de software é confirmação empírica.",
        "A aprovação do registro continua dependendo do processamento.",
    ],
)
def test_redacao_alternativa_nao_e_confundida_com_linguagem_proibida(frase: str) -> None:
    assert termos_proibidos(frase) == []
