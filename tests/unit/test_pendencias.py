"""Consolidação de `docs/pendencias/T*.md` em `docs/PENDENCIAS.md` (T14): nada se perde.

Cada item dos arquivos de pendências tem uma chave (`T04-19`, `T13-b1`, `T07-i3`; ver
`itens_de`) e precisa aparecer no campo `Itens` de uma ação de `docs/PENDENCIAS.md`. A base da
consolidação registra, por arquivo, as chaves e o SHA-256 consolidados: enquanto o arquivo for o
mesmo, os itens dele precisam ser exatamente os da base; arquivo editado depois (por outras
sessões) só gera aviso, para a consolidação ser refeita sem travar quem editou.
"""

from __future__ import annotations

import hashlib
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
PENDENCIAS = RAIZ / "docs" / "PENDENCIAS.md"
ORIGENS = RAIZ / "docs" / "pendencias"
ARQUIVOS = (
    "T01",
    "T02",
    "T03",
    "T04",
    "T05",
    "T06",
    "T07",
    "T08",
    "T09",
    "T10",
    "T12",
    "T13",
    "T14",
)
MARCADOR_DA_BASE = "## Base da consolidação"
DONOS_HUMANOS = ("PQ", "OR", "AV")
ITENS_DO_ORQUESTRADOR = 22
CAMPOS_DA_ACAO = ("Itens", "Ferramenta pronta", "Runbook", "Estado")


_SEPARADOR = re.compile(r"^\|[\s:|-]+\|$")
_NUMERADO = re.compile(r"^(\d+)\. ")
_CHAVE = re.compile(r"\bT(\d{2})-([bi]?\d+)\b")
_FAIXA = re.compile(r"^([bi]?)(\d+)(?:-([bi]?)(\d+))?$")
_ACAO = re.compile(r"^### ((?:PQ|OR|AV|EN|FE)-\d{2}) — (.+)$")
_CAMPO = re.compile(r"^- \*\*([^*:]+):\*\*\s*(.*)$")
_SECAO = re.compile(r"^#{1,3} ")


def itens_de(texto: str) -> list[str]:
    """Chaves dos itens de um arquivo de pendências, de cima para baixo.

    Linha de tabela com coluna `#` vale pelo número (`14`, `b1`); lista numerada no primeiro nível
    vale pelo número; ponto de lista no primeiro nível e linha de tabela sem coluna `#` valem por
    `i<k>`, o k-ésimo item sem número do arquivo.
    """
    linhas = texto.splitlines()
    chaves: list[str] = []
    sem_numero = 0
    numerada = False
    for indice, linha in enumerate(linhas):
        proxima = linhas[indice + 1] if indice + 1 < len(linhas) else ""
        numero = _NUMERADO.match(linha)
        if linha.startswith("|") and not _SEPARADOR.match(linha):
            celulas = [celula.strip() for celula in linha.strip().strip("|").split("|")]
            if _SEPARADOR.match(proxima):
                numerada = celulas[0] == "#"
            elif numerada:
                chaves.append(celulas[0])
            else:
                sem_numero += 1
                chaves.append(f"i{sem_numero}")
        elif numero:
            chaves.append(numero.group(1))
        elif linha.startswith("- "):
            sem_numero += 1
            chaves.append(f"i{sem_numero}")
    return chaves


def expandir(especificacao: str) -> list[str]:
    """`1-3, i1-i2, 8` vira `1 2 3 i1 i2 8`; faixas só dentro do mesmo prefixo."""
    chaves: list[str] = []
    for parte in (p.strip() for p in especificacao.split(",") if p.strip()):
        casamento = _FAIXA.match(parte)
        assert casamento, f"faixa_invalida valor={parte}"
        prefixo, inicio, prefixo_fim, fim = casamento.groups()
        assert prefixo_fim in (None, prefixo), f"faixa_com_prefixos_diferentes valor={parte}"
        ultimo = int(fim) if fim else int(inicio)
        chaves += [f"{prefixo}{n}" for n in range(int(inicio), ultimo + 1)]
    return chaves


@dataclass(frozen=True)
class Base:
    itens: str
    total: int
    sha256: str


def ler_base(texto: str) -> dict[str, Base]:
    """Linhas `| TNN | itens | total | sha256 |` da seção da base da consolidação."""
    base: dict[str, Base] = {}
    for linha in texto.partition(MARCADOR_DA_BASE)[2].splitlines():
        celulas = [celula.strip() for celula in linha.strip().strip("|").split("|")]
        if linha.startswith("| T") and len(celulas) == 4:
            base[celulas[0]] = Base(celulas[1], int(celulas[2]), celulas[3])
    return base


@dataclass(frozen=True)
class Acao:
    id: str
    titulo: str
    campos: dict[str, str]


def ler_acoes(texto: str) -> list[Acao]:
    """Blocos `### XX-NN — título` com campos `- **Campo:** valor` antes da base."""
    corpo = texto.partition(MARCADOR_DA_BASE)[0]
    acoes: list[Acao] = []
    atual: dict[str, str] | None = None
    ultimo = ""
    for linha in corpo.splitlines():
        cabecalho = _ACAO.match(linha)
        campo = _CAMPO.match(linha)
        if cabecalho:
            atual = {}
            acoes.append(Acao(cabecalho[1], cabecalho[2], atual))
        elif _SECAO.match(linha):
            atual = None
        elif atual is not None and campo:
            ultimo = campo[1].strip()
            atual[ultimo] = campo[2].strip()
        elif atual is not None and linha.startswith("  ") and linha.strip() and ultimo:
            atual[ultimo] = f"{atual[ultimo]} {linha.strip()}".strip()
    return acoes


def chaves_das_acoes(acoes: list[Acao]) -> set[str]:
    return {
        f"T{numero}-{chave}"
        for acao in acoes
        for numero, chave in _CHAVE.findall(acao.campos.get("Itens", ""))
    }


def linhas_do_orquestrador(texto: str) -> list[list[str]]:
    """Células das linhas `| ORQ-NN | tarefa | PR | pendência | ferramenta | runbook |`."""
    corpo = texto.partition(MARCADOR_DA_BASE)[0]
    return [
        [celula.strip() for celula in linha.strip().strip("|").split("|")]
        for linha in corpo.splitlines()
        if linha.startswith("| ORQ-")
    ]


def _texto() -> str:
    assert PENDENCIAS.is_file(), "pendencias_ausente caminho=docs/PENDENCIAS.md"
    return PENDENCIAS.read_text(encoding="utf-8")


def _chaves_da_base(texto: str) -> set[str]:
    return {
        f"{arquivo}-{chave}"
        for arquivo, base in ler_base(texto).items()
        for chave in expandir(base.itens)
    }


def test_originais_continuam_no_repositorio_sem_apagar() -> None:
    apagados = [arquivo for arquivo in ARQUIVOS if not (ORIGENS / f"{arquivo}.md").is_file()]
    assert apagados == [], f"pendencia_original_apagada arquivos={apagados}"


def test_base_da_consolidacao_lista_todos_os_arquivos() -> None:
    assert set(ARQUIVOS) <= set(ler_base(_texto()))


def test_toda_chave_da_base_esta_em_alguma_acao() -> None:
    texto = _texto()
    perdidas = sorted(_chaves_da_base(texto) - chaves_das_acoes(ler_acoes(texto)))
    assert perdidas == [], f"pendencia_perdida chaves={perdidas}"


def test_nenhuma_acao_cita_chave_fora_da_base() -> None:
    texto = _texto()
    extras = sorted(chaves_das_acoes(ler_acoes(texto)) - _chaves_da_base(texto))
    assert extras == [], f"chave_fora_da_base chaves={extras}"


def test_total_declarado_confere_com_as_chaves_da_base() -> None:
    divergentes = [
        f"{arquivo} declarado={base.total} chaves={len(expandir(base.itens))}"
        for arquivo, base in ler_base(_texto()).items()
        if base.total != len(expandir(base.itens))
    ]
    assert divergentes == [], f"total_divergente {divergentes}"


def test_arquivo_inalterado_desde_a_consolidacao_tem_exatamente_os_itens_da_base() -> None:
    for arquivo, base in ler_base(_texto()).items():
        conteudo = (ORIGENS / f"{arquivo}.md").read_bytes()
        if hashlib.sha256(conteudo).hexdigest() != base.sha256:
            warnings.warn(f"pendencia_nao_reconsolidada arquivo={arquivo}.md", stacklevel=1)
            continue
        itens = sorted(itens_de(conteudo.decode("utf-8")))
        assert itens == sorted(expandir(base.itens)), f"itens_da_base_divergem arquivo={arquivo}"


def test_toda_acao_tem_itens_ferramenta_runbook_e_estado() -> None:
    acoes = ler_acoes(_texto())
    assert acoes, "pendencias_sem_acoes"
    problemas = [
        f"acao_sem_campo id={acao.id} campo={campo}"
        for acao in acoes
        for campo in CAMPOS_DA_ACAO
        if not acao.campos.get(campo)
    ]
    assert problemas == []


def test_ids_das_acoes_sao_unicos() -> None:
    ids = [acao.id for acao in ler_acoes(_texto())]
    assert len(ids) == len(set(ids)), (
        f"acao_repetida ids={sorted(i for i in ids if ids.count(i) > 1)}"
    )


def test_acao_dos_donos_humanos_cita_runbook_existente() -> None:
    for acao in ler_acoes(_texto()):
        if not acao.id.startswith(DONOS_HUMANOS):
            continue
        caminhos = re.findall(r"`(docs/runbooks/[\w.]+\.md)`", acao.campos.get("Runbook", ""))
        assert caminhos, f"acao_sem_runbook id={acao.id}"
        for caminho in caminhos:
            assert (RAIZ / caminho).is_file(), f"runbook_inexistente id={acao.id} {caminho}"


def test_secao_do_orquestrador_traz_todos_os_itens_com_tarefa_e_pr_de_origem() -> None:
    linhas = linhas_do_orquestrador(_texto())
    assert [linha[0] for linha in linhas] == [
        f"ORQ-{n:02d}" for n in range(1, ITENS_DO_ORQUESTRADOR + 1)
    ]
    for identificador, tarefa, pr, pendencia, ferramenta, runbook in linhas:
        assert re.fullmatch(r"T\d{2}[a-z]?(?:/T\d{2}[a-z]?)*", tarefa), f"tarefa {identificador}"
        assert re.search(r"#\d+", pr), f"pr_de_origem {identificador}"
        assert pendencia, f"celula_vazia {identificador} campo=pendencia"
        assert ferramenta, f"celula_vazia {identificador} campo=ferramenta"
        assert runbook, f"celula_vazia {identificador} campo=runbook"


def test_itens_de_le_tabela_com_numero_lista_numerada_e_pontos_de_lista() -> None:
    texto = (
        "# T99\n\n| # | Pendência | Quem |\n|---|---|---|\n| 1 | a | x |\n| b2 | b | y |\n\n"
        "1. Primeiro\n   - sub-item ignorado\n2. Segundo\n\n- ponto um\n  - aninhado ignorado\n"
        "- ponto dois\n\n| Pendência | Situação |\n|---|---|\n| c | ok |\n"
    )
    assert itens_de(texto) == ["1", "b2", "1", "2", "i1", "i2", "i3"]


def test_itens_de_ignora_cabecalho_e_separador_de_tabela() -> None:
    texto = "| # | Pendência |\n|---|---|\n| 14 | x |\n"
    assert itens_de(texto) == ["14"]


def test_expandir_aceita_faixas_unitarios_e_prefixos() -> None:
    assert expandir("1-3, 8") == ["1", "2", "3", "8"]
    assert expandir("1-2, i1-i3, b1") == ["1", "2", "i1", "i2", "i3", "b1"]
    assert expandir("") == []


@pytest.mark.parametrize("valor", ["a-b", "1-b2", "i1-3"])
def test_expandir_recusa_faixa_invalida(valor: str) -> None:
    with pytest.raises(AssertionError, match="faixa_"):
        expandir(valor)


def test_leitor_da_base_le_arquivo_itens_total_e_hash() -> None:
    texto = "corpo\n\n## Base da consolidação\n\n| Arquivo | Itens | Total | SHA-256 |\n"
    texto += "|---|---|---|---|\n"
    texto += f"| T04 | 1-41 | 41 | {'a' * 64} |\n| T02 | 1-14, i1-i4 | 18 | {'b' * 64} |\n"
    assert ler_base(texto) == {
        "T04": Base("1-41", 41, "a" * 64),
        "T02": Base("1-14, i1-i4", 18, "b" * 64),
    }


def test_leitor_de_acoes_junta_continuacoes_e_para_na_base() -> None:
    texto = (
        "### PQ-01 — Primeira\n\n- **Itens:** T02-1 (um);\n  T02-2 (dois)\n"
        "- **Estado:** aberta\n\n## Outra seção\n\n- **Estado:** ignorado\n\n"
        "### EN-02 — Segunda\n\n- **Estado:** aberta\n\n"
        "## Base da consolidação\n\n### PQ-99 — fora\n\n- **Estado:** fora\n"
    )
    primeira, segunda = ler_acoes(texto)
    assert (primeira.id, primeira.titulo) == ("PQ-01", "Primeira")
    assert primeira.campos == {"Itens": "T02-1 (um); T02-2 (dois)", "Estado": "aberta"}
    assert segunda.campos == {"Estado": "aberta"}


def test_chaves_das_acoes_reconhece_os_tres_formatos_de_chave() -> None:
    acao = Acao("PQ-01", "x", {"Itens": "T04-19 (a); T13-b1 (b), T07-i11 (c)"})
    assert chaves_das_acoes([acao]) == {"T04-19", "T13-b1", "T07-i11"}


def test_chave_prefixo_de_outra_nao_conta() -> None:
    acao = Acao("PQ-01", "x", {"Itens": "T04-19 (a)"})
    assert "T04-1" not in chaves_das_acoes([acao])


def test_leitor_do_orquestrador_le_so_as_linhas_orq_antes_da_base() -> None:
    texto = (
        "| ORQ-01 | T13b | #25 | p | f | r |\n| outro | x |\n"
        "## Base da consolidação\n| ORQ-02 | T05 | #31 | p | f | r |\n"
    )
    assert linhas_do_orquestrador(texto) == [["ORQ-01", "T13b", "#25", "p", "f", "r"]]
