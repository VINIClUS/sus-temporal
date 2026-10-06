"""Auditoria de `docs/method/claims.md`: cada alegação com evidência exigida e estado (T14).

Cada alegação é um bloco `### AL-NN — título` com campos `- **Campo:** valor`. O estado só sai
de PENDENTE com decisão humana que cite a alegação (`test_alegacoes_decisoes.py`) e, em
CONFIRMADA ou NAO_CONFIRMADA, com a decisão de cada portão de que depende; o texto não traz a
linguagem proibida pelo AGENTS.md.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from sustemporal.contracts.experiment import Portao
from sustemporal.errors import PortaoRecusado
from sustemporal.gates import carregar_decisoes, exigir_portao
from tests.fixtures.reproducao_alegacoes import DIR_ALEGACOES, ESTADOS, problemas_de_decisoes

if TYPE_CHECKING:
    from collections.abc import Sequence

RAIZ = Path(__file__).resolve().parents[2]
CLAIMS = RAIZ / "docs" / "method" / "claims.md"
DECISOES = RAIZ / "experiments" / "decisions"
MANIFESTO = RAIZ / "docs" / "spec" / "manifest.yaml"
PENDENCIAS = RAIZ / "docs" / "PENDENCIAS.md"

CAMPOS_OBRIGATORIOS = (
    "Conclusão possível",
    "Natureza",
    "Evidência exigida",
    "Depende de",
    "Estado",
    "Limites",
)
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
PREFIXOS_DE_DECISAO = (
    "alegacao_sem_decisao_humana",
    "alegacao_sobre_esboco",
    "estado_sem_decisao_da_alegacao",
    "estado_diverge_da_decisao",
    "decisoes_de_alegacao_empatadas",
    "decisao_de_alegacao_invalida",
    "decisao_de_alegacao_em_link_simbolico",
    "decisoes_de_alegacao_em_link_simbolico",
    "decisao_cita_alegacao_inexistente",
)
RAIZES_CITAVEIS = ("tests/", "docs/", "src/", "catalog/", "config/", "scripts/", "experiments/")
AUSENTES_DE_PROPOSITO = {
    "docs/spec/esboco_original.pdf": "esboço PENDENTE em docs/spec/manifest.yaml",
    "tests/integration/test_reproduce_offline.py": "entregue na parte B da T14",
}
_SEM_NEGACAO = r"(?:(?!\bnao\b|\bnunca\b|\bjamais\b|\bsem\b)[^.;]){0,80}?"
_AGENTE = (
    r"\b(?:alteracao|alteracoes|mudanca|mudancas|ajuste|ajustes|correcao|correcoes|"
    r"atualizacao|atualizacoes|operacao|operacoes)\b"
)
_EFEITO_ATIVO = (
    r"\b(?:modifica|modificam|modificou|modificaram|altera|alteram|alterou|alteraram|"
    r"muda|mudam|mudou|mudaram|reescreve|reescrevem|reescreveu|reescreveram|reabre|reabrem|"
    r"reabriu|reabriram|corrige|corrigem|corrigiu|corrigiram|retifica|retificam|retificou|"
    r"retroage|retroagem|retroagiu)\b"
)
_COMPETENCIA_ENCERRADA = r"\bcompetencias?\s+(?:ja\s+)?(?:encerrad|fechad)\w*"
_EFEITO_PASSIVO = (
    r"\b(?:e|sao|foi|foram|sera|serao)\s+"
    r"(?:modificad|alterad|reescrit|reabert|corrigid|retificad)\w*"
)
PROIBIDAS = {
    "altera competência encerrada": (
        _AGENTE
        + _SEM_NEGACAO
        + _EFEITO_ATIVO
        + r"[^.;]{0,60}?"
        + _COMPETENCIA_ENCERRADA
        + "|"
        + _COMPETENCIA_ENCERRADA
        + _SEM_NEGACAO
        + _EFEITO_PASSIVO
        + r"\s+(?:pela|pelas|por)\b"
        + _SEM_NEGACAO
        + _AGENTE
    ),
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


_CABECALHO = re.compile(r"^### (AL-\d{2}) — (.+)$")
_CAMPO = re.compile(r"^- \*\*([^*:]+):\*\*\s*(.*)$")
_SECAO = re.compile(r"^#{1,3} ")


class _Bloco:
    def __init__(self, id_: str, titulo: str) -> None:
        self.id = id_
        self.titulo = titulo
        self.campos: dict[str, str] = {}
        self.repetidos: list[str] = []
        self.ultimo: str | None = None

    def campo(self, nome: str, valor: str) -> None:
        if nome in self.campos:
            self.repetidos.append(nome)
        else:
            self.campos[nome] = valor
        self.ultimo = nome

    def continuar(self, texto: str) -> None:
        if self.ultimo is not None:
            self.campos[self.ultimo] = f"{self.campos[self.ultimo]} {texto}".strip()

    def congelar(self) -> Alegacao:
        return Alegacao(self.id, self.titulo, dict(self.campos), tuple(self.repetidos))


def ler_alegacoes(texto: str) -> list[Alegacao]:
    """Blocos `### AL-NN — título`; título `###` fora do formato vira alegação de id vazio."""
    blocos: list[_Bloco] = []
    atual: _Bloco | None = None
    for linha in texto.splitlines():
        casamento = _CABECALHO.match(linha)
        if linha.startswith("### "):
            atual = _Bloco(*casamento.groups()) if casamento else _Bloco("", linha)
            blocos.append(atual)
        elif _SECAO.match(linha):
            atual = None
        elif atual is not None:
            _acumular(atual, linha)
    return [bloco.congelar() for bloco in blocos]


def _acumular(bloco: _Bloco, linha: str) -> None:
    campo = _CAMPO.match(linha)
    if campo:
        bloco.campo(campo[1].strip(), campo[2].strip())
    elif linha.startswith("  ") and linha.strip():
        bloco.continuar(linha.strip())


def _normalizado(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acentos = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acentos.casefold().split())


def termos_proibidos(texto: str) -> list[str]:
    """Rótulos da linguagem proibida encontrada, ignorando caixa, acentos e quebras de linha."""
    normalizado = _normalizado(texto)
    return [rotulo for rotulo, padrao in PROIBIDAS.items() if re.search(padrao, normalizado)]


def caminhos_citados(texto: str) -> list[str]:
    """Caminhos do repositório entre crases; modelos com `<>`, `*` ou `{}` ficam de fora."""
    citados = re.findall(r"`([^`\s]+)`", texto)
    return [c for c in citados if c.startswith(RAIZES_CITAVEIS) and not re.search(r"[<>*{}]", c)]


def _dependencias_de(alegacao: Alegacao) -> list[str]:
    bruto = alegacao.campos.get("Depende de", "")
    return [item.strip() for item in bruto.split(",") if item.strip()]


def _problemas_de_campos(alegacao: Alegacao) -> list[str]:
    id_, campos = alegacao.id, alegacao.campos
    problemas = [
        f"alegacao_sem_campo id={id_} campo={campo}"
        for campo in CAMPOS_OBRIGATORIOS
        if not campos.get(campo)
    ]
    problemas += [f"campo_repetido id={id_} campo={campo}" for campo in alegacao.repetidos]
    natureza, estado = campos.get("Natureza"), campos.get("Estado")
    if natureza and natureza not in NATUREZAS:
        problemas.append(f"natureza_invalida id={id_} valor={natureza}")
    if estado and estado not in ESTADOS:
        problemas.append(f"estado_invalido id={id_} valor={estado}")
    return problemas


def _problemas_de_dependencias(alegacao: Alegacao) -> list[str]:
    id_, dependencias = alegacao.id, _dependencias_de(alegacao)
    problemas = [
        f"dependencia_invalida id={id_} valor={dependencia}"
        for dependencia in dependencias
        if dependencia not in DEPENDENCIAS
    ]
    if dependencias and not {*PORTOES, "DADOS_REAIS"} & set(dependencias):
        problemas.append(f"alegacao_sem_portao_nem_dado_real id={id_}")
    confirmatoria = alegacao.campos.get("Natureza") == "CONFIRMATORIA"
    if confirmatoria and not {"G2", "DADOS_REAIS"} <= set(dependencias):
        problemas.append(f"confirmatoria_sem_g2_e_dados_reais id={id_}")
    return problemas


def _portao_liberado(diretorio: Path, portao: str) -> bool:
    enumerado = Portao(portao)
    congelamentos = {decisao.freeze_id for decisao in carregar_decisoes(diretorio, enumerado)}
    for freeze_id in congelamentos or {None}:
        try:
            exigir_portao(diretorio, enumerado, freeze_id=freeze_id)
        except PortaoRecusado:
            continue
        return True
    return False


def _problemas_de_resultado(
    alegacao: Alegacao, decisoes: Path, *, esboco_preservado: bool
) -> list[str]:
    estado = alegacao.campos.get("Estado")
    if estado not in ESTADOS_COM_RESULTADO:
        return []
    dependencias = _dependencias_de(alegacao)
    problemas = [
        f"alegacao_sem_decisao_humana id={alegacao.id} estado={estado} portao={portao}"
        for portao in PORTOES
        if portao in dependencias and not _portao_liberado(decisoes, portao)
    ]
    if "ESBOCO" in dependencias and not esboco_preservado:
        problemas.append(f"alegacao_sobre_esboco_pendente id={alegacao.id} estado={estado}")
    return problemas


def validar_alegacoes(
    alegacoes: Sequence[Alegacao], *, decisoes: Path, esboco_preservado: bool
) -> list[str]:
    """Mensagens `chave=valor` das violações; lista vazia quando o registro está consistente."""
    problemas: list[str] = []
    for alegacao in alegacoes:
        if not alegacao.id:
            problemas.append(f"cabecalho_invalido linha={alegacao.titulo}")
            continue
        problemas += _problemas_de_campos(alegacao)
        problemas += _problemas_de_dependencias(alegacao)
        problemas += _problemas_de_resultado(
            alegacao, decisoes, esboco_preservado=esboco_preservado
        )
    estados = {
        alegacao.id: alegacao.campos["Estado"]
        for alegacao in alegacoes
        if alegacao.id and alegacao.campos.get("Estado") in ESTADOS
    }
    return problemas + problemas_de_decisoes(estados, decisoes / DIR_ALEGACOES)


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
    assert _problemas_do_registro(*PREFIXOS_DE_DECISAO) == []


def test_registro_nao_traz_linguagem_proibida() -> None:
    assert termos_proibidos(_texto_do_registro()) == []


def test_registro_declara_que_teste_de_software_nao_e_confirmacao_empirica() -> None:
    texto = " ".join(_texto_do_registro().split())
    assert "Nenhum teste de software" in texto
    assert "SINTETICO" in texto


def test_arquivos_citados_no_registro_existem() -> None:
    ausentes = [
        caminho
        for caminho in caminhos_citados(_texto_do_registro())
        if caminho not in AUSENTES_DE_PROPOSITO and not (RAIZ / caminho.rstrip("/")).exists()
    ]
    assert ausentes == [], f"caminho_citado_inexistente caminhos={ausentes}"


def test_pendencias_citadas_no_registro_existem_na_consolidacao() -> None:
    consolidacao = PENDENCIAS.read_text(encoding="utf-8").partition("## Base da consolidação")[0]
    existentes = {f"T{n}-{c}" for n, c in re.findall(r"\bT(\d{2})-([bi]?\d+)\b", consolidacao)}
    citadas = [
        chave.strip()
        for alegacao in ler_alegacoes(_texto_do_registro())
        for chave in alegacao.campos.get("Pendências", "").split(",")
        if chave.strip()
    ]
    invalidas = [chave for chave in citadas if not re.fullmatch(r"T\d{2}-[bi]?\d+", chave)]
    assert invalidas == [], f"chave_de_pendencia_invalida chaves={invalidas}"
    ausentes = sorted({chave for chave in citadas if chave not in existentes})
    assert ausentes == [], f"pendencia_citada_inexistente chaves={ausentes}"


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
        "A alteração atual modifica a competência encerrada.",
        "A alteração feita hoje altera o resultado de competências já encerradas.",
        "O ajuste no cadastro atual corrige a competência fechada.",
        "As alterações atuais reescrevem competências encerradas.",
        "A mudança no CNES reabriu a competência encerrada de 2019.",
        "A operação modificou, retroativamente, a competência já encerrada.",
        "A competência encerrada é modificada pela alteração atual.",
        "Competências fechadas foram alteradas pela correção do cadastro.",
        "A alteração\natual  MODIFICA a competência\nENCERRADA.",
    ],
)
def test_afirmar_que_alteracao_atual_modifica_competencia_encerrada_e_detectado(
    frase: str,
) -> None:
    assert termos_proibidos(frase) == ["altera competência encerrada"]


@pytest.mark.parametrize(
    "frase",
    [
        "A explicação não atribui o motivo registrado pelo sistema oficial.",
        "Valor de tabela não aprovado não equivale a dinheiro perdido.",
        "Nenhum teste de software é confirmação empírica.",
        "A aprovação do registro continua dependendo do processamento.",
        "Uma alteração atual não modifica a competência encerrada.",
        "A alteração atual nunca altera competência já encerrada.",
        "Não assegura que uma alteração atual modificaria uma competência encerrada.",
        "Contrafactual lido como se modificasse uma competência encerrada não é evidência.",
        "A alteração atual não pode modificar competência fechada.",
        "A republicação da fonte modifica a competência encerrada no portal oficial.",
        "A alteração atual modifica o cadastro; a competência encerrada fica como estava.",
        "Competência encerrada: a alteração hipotética é hipótese passada.",
    ],
)
def test_redacao_alternativa_nao_e_confundida_com_linguagem_proibida(frase: str) -> None:
    assert termos_proibidos(frase) == []


def test_caminhos_citados_ignoram_modelos_padroes_e_comandos() -> None:
    texto = (
        "Veja `docs/method/claims.md`, `catalog/policies/` e `uv run`; modelos como "
        "`experiments/decisions/G0_<AAAA-MM-DD>.yaml`, `tests/unit/test_*.py` e "
        "`src/{a,b}.py` não contam; `sustemporal.gates` também não."
    )
    assert caminhos_citados(texto) == ["docs/method/claims.md", "catalog/policies/"]
