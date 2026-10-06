"""Arquivos que a cadeia do `reproduce` abre e o que acontece quando um deles não abre (T14).

Cada arquivo (ou grupo de arquivos do mesmo leitor, na mesma etapa) tem a sua `Leitura`: de que
raiz vem, quem o lê, de onde vem o que ele diz, o que o confere e o resultado documentado de cada
`Dano` (diretório no lugar do arquivo, sem permissão, bytes que não decodificam ou truncados).
Nenhum dano dá traceback, `DIVERGENTE` ou `IGUAL` sem justificativa: a falta de arquivo necessário é
verificação inconclusiva (item `INCONCLUSIVO`, saída 5), o arquivo que é entrada da config ou do
repositório sai 2 com `chave=valor`, e o registro de rodadas adulterado é falha operacional. Os
testes derivam daqui o que estragar, e uma auditoria das aberturas de uma reprodução real falha se a
cadeia abre arquivo sem linha aqui. O que fica fora (`sem_estrago`) diz por quê.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["LEITURAS", "Dano", "Estrago", "Leitura", "Origem", "Raiz", "Resultado"]


class Dano(StrEnum):
    """O que se faz a um arquivo que a cadeia abre para ele não abrir."""

    DIRETORIO = "DIRETORIO"
    PERMISSAO = "PERMISSAO"
    BYTES = "BYTES"


class Origem(StrEnum):
    """De que lado do `reproduce` o arquivo está."""

    CONFIG = "CONFIG"
    CATALOGO = "CATALOGO"
    ORIGINAL = "ORIGINAL"
    PRODUZIDO = "PRODUZIDO"
    CODIGO = "CODIGO"
    TEMPORARIO = "TEMPORARIO"


class Raiz(StrEnum):
    """De onde o caminho do arquivo parte; o valor é como o runbook o escreve."""

    CONFIG = "<config>"
    CONGELAMENTOS = "<dir_congelamentos>"
    MANIFESTOS = "<raiz_manifestos>"
    SAIDAS = "<raiz_saidas>"
    DADOS = "<raiz_dados>"
    FONTES = "<catalogos.fontes>"
    TERRITORIO = "<piloto.territorio>"
    CATALOGO = "catalog"
    TRABALHO = "<diretorio_de_trabalho>"
    DESTINO = "<saida>"
    CODIGO = "<clone>"
    TEMPORARIO = "<tmp>"


class Resultado(StrEnum):
    """O que o `reproduce` faz com o arquivo estragado."""

    CONFIG_INVALIDA = "CONFIG_INVALIDA"
    FALHA = "FALHA"
    INCONCLUSIVO = "INCONCLUSIVO"
    IGUAL_PELO_DECLARADO = "IGUAL_PELO_DECLARADO"


@dataclass(frozen=True)
class Estrago:
    """O resultado documentado de um dano e os itens de `reproducao.json` que ele atinge."""

    resultado: Resultado
    itens: tuple[str, ...] = ()
    observacao: str = ""

    @property
    def texto(self) -> str:
        """Como o runbook escreve o resultado."""
        nomes = ", ".join(f"`{item}`" for item in self.itens)
        return {
            Resultado.CONFIG_INVALIDA: "saída 2",
            Resultado.FALHA: "falha operacional (saída 5)",
            Resultado.INCONCLUSIVO: f"`INCONCLUSIVO` ({nomes})",
            Resultado.IGUAL_PELO_DECLARADO: f"`IGUAL` pelo hash declarado ({nomes})",
        }[self.resultado]


@dataclass(frozen=True)
class Leitura:
    """Arquivo, ou grupo de arquivos do mesmo leitor, que a cadeia abre.

    `padroes` são globs relativos a `raiz` (`.` é a própria raiz, quando ela é um arquivo), na ordem
    em que a cadeia os lê: o primeiro é o que a varredura estraga. `estragos` diz o resultado de
    cada dano; o dano que falta não se aplica e `sem_estrago` diz por quê (o conteúdo não conta, ou
    o arquivo é gravado pela própria reprodução, ou é código).
    """

    raiz: Raiz
    padroes: tuple[str, ...]
    origem: Origem
    quem_le: str
    fonte: str
    confere: str
    estragos: Mapping[Dano, Estrago] = field(default_factory=dict)
    sem_estrago: str = ""

    @property
    def arquivo(self) -> str:
        """Como o runbook escreve o arquivo."""
        if self.padroes == (".",):
            return f"`{self.raiz.value}`"
        return " e ".join(f"`{self.raiz.value}/{padrao}`" for padrao in self.padroes)

    def casa(self, raiz: Raiz, relativo: str) -> bool:
        """Se o arquivo de caminho `relativo` a `raiz` é desta leitura."""
        return raiz is self.raiz and any(fnmatchcase(relativo, p) for p in self.padroes)


R = Resultado


def _e(resultado: Resultado, *itens: str, observacao: str = "") -> Estrago:
    return Estrago(resultado, itens, observacao)


def _tres(estrago: Estrago, **trocas: Estrago) -> dict[Dano, Estrago]:
    """O resultado nos três danos, menos os de `trocas` (`diretorio`, `permissao` e `bytes`)."""
    estragos = dict.fromkeys(Dano, estrago)
    estragos.update({Dano[nome.upper()]: trocado for nome, trocado in trocas.items()})
    return estragos


_CONFIG = _tres(_e(R.CONFIG_INVALIDA))
_MANIFESTO = _tres(_e(R.INCONCLUSIVO, "manifesto:aquisicao"))
_SAIDAS = _tres(_e(R.INCONCLUSIVO, "saida:*"))
_DO_RELATORIO = _tres(_e(R.INCONCLUSIVO, "metricas", "notas", "relatorio:campos"))
_DO_REGISTRO = _e(R.INCONCLUSIVO, "metricas", "notas", "relatorio:campos", "saida:*")
_DO_DECLARADO = _tres(
    _e(R.IGUAL_PELO_DECLARADO, "conjunto:*", "split:particao:*", "split:rotulos:*")
)
_DOS_ORIGINAIS = _e(R.INCONCLUSIVO, "conjunto:*", "insumos:*")
_DO_INGEST = _e(R.INCONCLUSIVO, "ingest:originais")

_DESTINO_NOVO = (
    "o destino é novo e vazio (`reproduce_destino_nao_vazio`): nada de fora o estraga antes de a "
    "reprodução gravá-lo, e o que se perde durante a execução sai falha operacional "
    "(`reproduce_saida_ilegivel`)"
)
_CODIGO = "é o código que roda: a instalação do pacote não é entrada da reprodução"
_TEMPORARIO = "temporário que o próprio processo grava e lê na mesma chamada"
_LOCK = "o conteúdo não conta, só a abertura do arquivo de trava"

LEITURAS: dict[str, Leitura] = {
    "config": Leitura(
        Raiz.CONFIG,
        (".",),
        Origem.CONFIG,
        "`load_config`",
        "`--config`",
        "ilegível ou inválida sai 2 antes de abrir outro arquivo",
        _CONFIG,
    ),
    "congelamento": Leitura(
        Raiz.CONGELAMENTOS,
        ("frz_*.json",),
        Origem.CONFIG,
        "`carregar_freeze`",
        "`--freeze`",
        "id recomputado do conteúdo; ausente, ilegível, adulterado ou de outro id sai 2",
        _CONFIG,
    ),
    "fontes": Leitura(
        Raiz.FONTES,
        (".",),
        Origem.CONFIG,
        "`configuracao_do_ingest`, `ingest`",
        "`catalogos.fontes` da config",
        "SHA-256 na configuração gravada do `ingest`: ilegível sai 2; outro conteúdo, "
        "`manifesto:aquisicao` inconclusivo",
        _tres(_e(R.CONFIG_INVALIDA), bytes=_e(R.INCONCLUSIVO, "manifesto:aquisicao")),
    ),
    "territorio": Leitura(
        Raiz.TERRITORIO,
        (".",),
        Origem.CONFIG,
        "`ingest`, `validate`",
        "`piloto.territorio` da config",
        "recorte territorial na identidade dos insumos; ilegível sai 2",
        _CONFIG,
    ),
    "registro": Leitura(
        Raiz.CONGELAMENTOS,
        ("registro_execucoes.jsonl",),
        Origem.ORIGINAL,
        "`ler_registro`, `rodada_registrada`",
        "o congelamento e o modo",
        "cadeia de hashes; adulterado é falha operacional; que não abre, não há original",
        _tres(
            _e(R.INCONCLUSIVO, *_DO_REGISTRO.itens, observacao="registro_ilegivel"),
            bytes=_e(R.FALHA),
        ),
    ),
    "relatorio": Leitura(
        Raiz.SAIDAS,
        ("avaliacao/*/rep_*.json",),
        Origem.ORIGINAL,
        "`ler_original`",
        "o `report_id` do registro",
        "tem de bater com a entrada do registro; senão, original indisponível",
        _DO_RELATORIO,
    ),
    "execucao_original": Leitura(
        Raiz.SAIDAS,
        ("runs/*/run_result.json",),
        Origem.ORIGINAL,
        "`ler_original`",
        "os `runs` do registro",
        "`run_id` coerente com a pasta; que não abre, a execução fica sem original",
        _SAIDAS,
    ),
    "saidas_originais": Leitura(
        Raiz.SAIDAS,
        ("runs/*/*.parquet",),
        Origem.ORIGINAL,
        "`comparar_execucoes`",
        "as saídas do `run_result.json`",
        "leiaute e hash lógico das cinco saídas; que não abre, `INCONCLUSIVO`",
        _SAIDAS,
    ),
    "conjuntos_originais": Leitura(
        Raiz.SAIDAS,
        ("split/ds_*.parquet", "split/rotulos/ds_*.parquet", "split/entradas/ds_*.parquet"),
        Origem.ORIGINAL,
        "`comparar_referencia`, `comparar_split`",
        "o `DatasetRef` do manifesto (caminho absoluto)",
        "vale o hash declarado no congelamento; o arquivo original é a segunda conferência",
        _DO_DECLARADO,
    ),
    "insumos": Leitura(
        Raiz.SAIDAS,
        ("split/insumos/*.json",),
        Origem.ORIGINAL,
        "`conferir_entradas`, `politicas_congeladas`",
        "`entradas_validacao` e `politicas_sha256`",
        "identidade campo a campo; a política, também contra a execução registrada",
        _tres(_e(R.INCONCLUSIVO, "insumos:*")),
    ),
    "ingest_datasets": Leitura(
        Raiz.SAIDAS,
        ("ingest/execucao_*/datasets.jsonl",),
        Origem.ORIGINAL,
        "`resolver_manifesto`",
        "o SIA-PA congelado",
        "acha a execução do `ingest` pelo SIA-PA; que não abre, a execução não é candidata",
        _MANIFESTO,
    ),
    "ingest_posicao": Leitura(
        Raiz.SAIDAS,
        ("ingest/execucao_*/manifesto_lido.json",),
        Origem.ORIGINAL,
        "`resolver_manifesto`",
        "a execução do `ingest`",
        "linhas e hash da última linha do manifesto que o `ingest` leu",
        _MANIFESTO,
    ),
    "ingest_config": Leitura(
        Raiz.SAIDAS,
        ("ingest/execucao_*/configuracao_ingest.json",),
        Origem.ORIGINAL,
        "`resolver_manifesto`",
        "a execução do `ingest`",
        "a configuração com que o `ingest` rodou tem de ser a do refeito",
        _MANIFESTO,
    ),
    "manifesto": Leitura(
        Raiz.MANIFESTOS,
        ("aquisicao.jsonl",),
        Origem.ORIGINAL,
        "`resolver_manifesto`, `gravar_manifesto`",
        "a posição que o `ingest` leu",
        "prefixo até essa posição, com a cadeia e o hash da última linha; corrompido ou ilegível, "
        "a posição não se sabe",
        _MANIFESTO,
    ),
    "ancora": Leitura(
        Raiz.MANIFESTOS,
        ("aquisicao.jsonl.ancora",),
        Origem.ORIGINAL,
        "`Manifesto.ler`",
        "o manifesto de aquisição",
        "sequência e hash da última linha gravada; ilegível ou divergente é manifesto corrompido",
        _MANIFESTO,
    ),
    "trava": Leitura(
        Raiz.MANIFESTOS,
        ("aquisicao.jsonl.trava",),
        Origem.ORIGINAL,
        "`Manifesto.ler`",
        "o manifesto de aquisição",
        "trava de leitura compartilhada; que não abre, o manifesto não se lê",
        {d: _e(R.INCONCLUSIVO, "manifesto:aquisicao") for d in (Dano.DIRETORIO, Dano.PERMISSAO)},
        _LOCK,
    ),
    "brutos_dbc": Leitura(
        Raiz.DADOS,
        ("raw/sha256/*/*.dbc",),
        Origem.ORIGINAL,
        "o `ingest` refeito (SIA-PA, CNES)",
        "o manifesto de aquisição",
        "SHA-256 do bruto; ausente ou truncado, `originais_indisponiveis`; sem permissão, "
        "`ingest:originais`",
        _tres(_DOS_ORIGINAIS, permissao=_DO_INGEST),
    ),
    "brutos_zip": Leitura(
        Raiz.DADOS,
        ("raw/sha256/*/*.zip",),
        Origem.ORIGINAL,
        "o `ingest` refeito (SIGTAP)",
        "o manifesto de aquisição",
        "SHA-256 do bruto; ausente ou truncado, `originais_indisponiveis`; sem permissão, "
        "`ingest:originais`",
        _tres(_DOS_ORIGINAIS, permissao=_DO_INGEST),
    ),
    "selecao_versoes_cwd": Leitura(
        Raiz.TRABALHO,
        ("catalog/schemas/selecao_versoes.yaml",),
        Origem.CATALOGO,
        "`validate` (`temporal.lote`)",
        "o diretório de trabalho (T14-15)",
        "esquema da seleção de versões; ilegível sai 2",
        _CONFIG,
    ),
    "familias": Leitura(
        Raiz.CATALOGO,
        ("familias.yaml",),
        Origem.CATALOGO,
        "`carregar_regras`, `build_coverage`",
        "o repositório",
        "famílias de fonte que as regras e a cobertura usam; ilegível sai 2",
        _CONFIG,
    ),
    "regras": Leitura(
        Raiz.CATALOGO,
        ("rules/*/*.yaml",),
        Origem.CATALOGO,
        "`carregar_regras`",
        "o repositório",
        "SHA-256 do catálogo no manifesto (observação); ilegível sai 2",
        _CONFIG,
    ),
    "esquemas_das_regras": Leitura(
        Raiz.CATALOGO,
        (
            "schemas/sia_pa.yaml",
            "schemas/cnes_estab_cbo.yaml",
            "schemas/sigtap_proc_registro.yaml",
            "schemas/sigtap_proc_ocupacao.yaml",
            "schemas/sigtap_procedimento.yaml",
        ),
        Origem.CATALOGO,
        "`carregar_regras`",
        "o repositório",
        "esquemas das tabelas que as regras leem; ilegível sai 2",
        _CONFIG,
    ),
    "politicas": Leitura(
        Raiz.CATALOGO,
        ("policies/M_TEMP_PADRAO.yaml", "policies/*.yaml"),
        Origem.CATALOGO,
        "`politicas_congeladas`",
        "o repositório",
        "a política congelada tem de ser a padrão do método ou a do catálogo de mesmo conteúdo",
        _tres(_e(R.INCONCLUSIVO, "insumos:*")),
    ),
    "leiaute_sia_pa": Leitura(
        Raiz.CATALOGO,
        ("layouts/sia_pa.yaml",),
        Origem.CATALOGO,
        "`configuracao_do_ingest`, `ingest`",
        "`catalogos.leiaute_sia_pa` ou o repositório",
        "SHA-256 na configuração gravada do `ingest`; ilegível sai 2",
        _tres(_e(R.CONFIG_INVALIDA), bytes=_e(R.INCONCLUSIVO, "manifesto:aquisicao")),
    ),
    "leiaute_cnes": Leitura(
        Raiz.CATALOGO,
        ("layouts/cnes.yaml",),
        Origem.CATALOGO,
        "o `ingest` refeito (CNES)",
        "o repositório",
        "leiaute dos arquivos do CNES; ilegível sai 2",
        _CONFIG,
    ),
    "leiaute_sigtap": Leitura(
        Raiz.CATALOGO,
        ("layouts/sigtap.yaml",),
        Origem.CATALOGO,
        "o `ingest` refeito (SIGTAP)",
        "o repositório",
        "leiaute das tabelas do SIGTAP; ilegível sai 2",
        _CONFIG,
    ),
    "esquemas_do_ingest": Leitura(
        Raiz.CATALOGO,
        ("schemas/cnes_estabelecimento.yaml", "schemas/sigtap_registro.yaml"),
        Origem.CATALOGO,
        "o `ingest` refeito (normalização do CNES ST e do SIGTAP)",
        "o repositório",
        "esquemas das tabelas normalizadas; sem abrir, sai 2; com bytes que não decodificam, o "
        "`ingest` põe o artefato em `FALHA_NORMALIZACAO` (`originais_indisponiveis`)",
        _tres(_e(R.CONFIG_INVALIDA), bytes=_e(R.INCONCLUSIVO, "insumos:*")),
    ),
    "esquema_da_cobertura": Leitura(
        Raiz.CATALOGO,
        ("schemas/cobertura.yaml",),
        Origem.CATALOGO,
        "`build_coverage` (o `ingest` refeito)",
        "o repositório",
        "esquema da tabela de cobertura; ilegível sai 2",
        _CONFIG,
    ),
    "rotulos": Leitura(
        Raiz.CATALOGO,
        ("labels/sia_pa.yaml", "schemas/sia_pa_rotulos.yaml"),
        Origem.CATALOGO,
        "`derivar_protocolo` (rótulos)",
        "o repositório",
        "livro de códigos dos rótulos do SIA-PA e o esquema deles; ilegível sai 2",
        _CONFIG,
    ),
    "esquemas_da_validacao": Leitura(
        Raiz.CATALOGO,
        ("schemas/selecao_versoes.yaml", "schemas/agregados_registro.yaml"),
        Origem.CATALOGO,
        "`validate`",
        "o repositório",
        "esquemas das saídas da validação; ilegível sai 2",
        _CONFIG,
    ),
    "esquemas_da_comparacao": Leitura(
        Raiz.CATALOGO,
        ("schemas/avaliacoes.yaml", "schemas/evidencias.yaml", "schemas/falhas.yaml"),
        Origem.CATALOGO,
        "`identidade_do_arquivo`",
        "o repositório",
        "leiaute esperado de cada saída comparada; ilegível sai 2",
        _CONFIG,
    ),
    "destino": Leitura(
        Raiz.DESTINO,
        ("*",),
        Origem.PRODUZIDO,
        "o `ingest`, `derivar_protocolo`, `validate` e a avaliação refeitos",
        "a própria reprodução",
        "o que a reprodução grava e relê no destino novo",
        sem_estrago=_DESTINO_NOVO,
    ),
    "codigo": Leitura(
        Raiz.CODIGO,
        ("*.py", "*.pyc", "*.sql"),
        Origem.CODIGO,
        "o interpretador, as regras em SQL",
        "o clone",
        "versão do código e pacotes em `observacoes_do_ambiente` (observação)",
        sem_estrago=_CODIGO,
    ),
    "temporarios": Leitura(
        Raiz.TEMPORARIO,
        ("tmp*",),
        Origem.TEMPORARIO,
        "o `ingest` refeito (descompressão do DBC)",
        "o próprio processo",
        "o conteúdo vem do bruto já conferido pelo SHA-256",
        sem_estrago=_TEMPORARIO,
    ),
}
