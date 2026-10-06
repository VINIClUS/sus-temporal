"""Mundo SINTETICO do fluxo ponta a ponta da T14: originais num FTP local e três janelas.

Os arquivos de SIA-PA, CNES (PF e ST) e SIGTAP são gerados por código e servidos por um FTP local
(`servidor_ftp`); nada aqui provém de fonte oficial nem é resultado empírico. As competências de
processamento ficam em três janelas, que o protocolo separa em partições: DEV (201801 e 201803),
CAL (202301) e TESTE (arquivo de 202401). Em DEV há uma linha de cada situação do cartão da T14:
ausência (CBO fora do CNES), mês faltante (atendimento 201802 sem arquivos) e borda de 2018
(atendimento 201712, antes do recorte). Os arquivos de 201712 e 201802 não existem de propósito.
O arquivo de 202401 traz linhas processadas em 202402 (o ingest aceita: PA_MVM pode diferir do nome
do arquivo), e por isso o piloto da janela TESTE lista as duas competências.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal import cli
from sustemporal.contracts import FamiliaFonte
from tests.fixtures.aquisicao_dados import servidor_ftp
from tests.fixtures.cnes_dbc import dbc_cnes, registro_pf, registro_st
from tests.fixtures.piloto_conjuntos import registro
from tests.fixtures.sia_pa_fixtures import dbc_pa
from tests.fixtures.sigtap_zip import pacote_padrao, zip_sigtap

if TYPE_CHECKING:
    from collections.abc import Mapping

RAIZ = Path(__file__).resolve().parents[2]
FONTES = RAIZ / "catalog" / "sources.yaml"
DRS_XI = RAIZ / "catalog" / "territorio" / "drs_xi.yaml"
JANELAS = {"dev": ("201801", "201803"), "cal": ("202301",), "teste": ("202401", "202402")}
COMPETENCIAS = ("201801", "201803", "202301", "202401")
ATENDIMENTO = ("201712", "201801", "201802", "201803", "202301", "202401")
PROCEDIMENTO = "0101010010"
CBO_NO_CNES, CBO_FORA_DO_CNES = "225125", "223505"
POLITICAS = ("documented", "atendimento", "processamento")
_REJEITADO = {"PA_INDICA": "0", "PA_QTDAPR": "0", "PA_VALAPR": "0.00"}
_APROVADO = {"PA_INDICA": "5"}
_NIVEL = ["--nivel-log", "WARNING"]


def _linha(instrumento: str, processamento: str, atendimento: str, **campos: str) -> dict[str, str]:
    return registro(instrumento, processamento, atendimento, PA_PROC_ID=PROCEDIMENTO, **campos)


def _quatro_casos(competencia: str, processamento: str | None = None) -> list[dict[str, str]]:
    """Alerta com rejeição, alerta com aprovação, rejeição sem alerta e aprovação sem alerta.

    Atendidos em `competencia` e processados em `processamento` (padrão: o mesmo mês).
    """
    mes = processamento or competencia
    return [
        _linha("I", mes, competencia, PA_CBOCOD=CBO_FORA_DO_CNES, **_REJEITADO),
        _linha("I", mes, competencia, PA_CBOCOD=CBO_FORA_DO_CNES, **_APROVADO),
        _linha("C", mes, competencia, PA_CBOCOD=CBO_NO_CNES, **_REJEITADO),
        _linha("C", mes, competencia, PA_CBOCOD=CBO_NO_CNES, **_APROVADO),
    ]


def producao_do_mes(competencia: str) -> list[dict[str, str]]:
    """Os quatro casos do SIA-PA de uma competência, atendida e processada no mesmo mês."""
    return _quatro_casos(competencia)


def producao_por_competencia() -> dict[str, list[dict[str, str]]]:
    """Registros do SIA-PA de cada arquivo (pela competência do arquivo), na ordem do arquivo."""
    ausencia = _linha("I", "201801", "201801", PA_CBOCOD=CBO_NO_CNES, **_REJEITADO)
    borda_de_2018 = _linha("C", "201801", "201712", **_APROVADO)
    mes_faltante = _linha("C", "201803", "201802", **_APROVADO)
    conforme = _linha("I", "201803", "201803", PA_CBOCOD=CBO_NO_CNES, **_REJEITADO)
    return {
        "201801": [ausencia, borda_de_2018],
        "201803": [mes_faltante, conforme],
        "202301": _quatro_casos("202301"),
        "202401": _quatro_casos("202401", "202402"),
    }


def _cbo_do_pf(competencia: str) -> str:
    return CBO_FORA_DO_CNES if competencia == "201801" else CBO_NO_CNES


def publicar_originais(ftp: Path) -> None:
    """Árvore do FTP local no formato do catálogo de fontes (SIA-PA, CNES PF e ST, SIGTAP)."""
    dados = ftp / "SIASUS" / "200801_" / "Dados"
    cnes = ftp / "CNES" / "200508_" / "Dados"
    sigtap = ftp / "pub" / "sistemas" / "tup" / "downloads"
    for pasta in (dados, cnes / "PF", cnes / "ST", sigtap):
        pasta.mkdir(parents=True, exist_ok=True)
    for competencia, registros in producao_por_competencia().items():
        aamm = competencia[2:]
        (dados / f"PASP{aamm}a.dbc").write_bytes(dbc_pa(registros))
        pf = [registro_pf("0012345", _cbo_do_pf(competencia), competencia)]
        (cnes / "PF" / f"PFSP{aamm}.dbc").write_bytes(dbc_cnes(FamiliaFonte.CNES_PF, pf))
        st = [registro_st("0012345", competencia), registro_st("0099999", competencia)]
        (cnes / "ST" / f"STSP{aamm}.dbc").write_bytes(dbc_cnes(FamiliaFonte.CNES_ST, st))
        zip_do_mes = zip_sigtap(pacote_padrao(competencia))
        (sigtap / f"TabelaUnificada_{competencia}_v{aamm}101010.zip").write_bytes(zip_do_mes)


def catalogo_local(pasta: Path, porta: int) -> Path:
    """Catálogo de fontes apontando para o FTP local, com a parte `a` esperada em cada mês."""
    texto = FONTES.read_text(encoding="utf-8")
    for remoto in ("ftp://ftp.datasus.gov.br/dissemin/publicos", "ftp://ftp2.datasus.gov.br"):
        texto = texto.replace(remoto, f"ftp://127.0.0.1:{porta}")
    marcador = '    multipartes: "true"\n'
    esperadas = "".join(f'      "{c}": [a]\n' for c in COMPETENCIAS)
    if marcador not in texto:
        raise ValueError("catalogo_sem_marcador_multipartes")
    texto = texto.replace(marcador, f"{marcador}    partes_esperadas:\n{esperadas}", 1)
    destino = pasta / "sources.yaml"
    destino.write_text(texto, encoding="utf-8")
    return destino


@dataclass(frozen=True)
class Mundo:
    """Raiz de trabalho limpa; as configurações do fluxo ficam nela como `config_<nome>.yaml`."""

    raiz: Path

    @property
    def fontes(self) -> Path:
        return self.raiz / "sources.yaml"

    @property
    def saidas(self) -> Path:
        return self.raiz / "saidas"

    @property
    def congelamentos(self) -> Path:
        return self.raiz / "congelamentos"

    def config(self, nome: str) -> Path:
        return self.raiz / f"config_{nome}.yaml"


def escrever_config(
    mundo: Mundo, nome: str, competencias: tuple[str, ...], *, threads: int = 1, rede: bool = False
) -> Path:
    """Configuração do fluxo: mesmos caminhos e catálogos, só o recorte do piloto muda."""
    lista = ", ".join(f'"{c}"' for c in competencias)
    linhas = [
        'versao: "1"',
        "origem_dados: SINTETICO",
        "catalogos:",
        f"  fontes: {mundo.fontes}",
        "runtime:",
        f"  raiz_dados: {mundo.raiz / 'dados'}",
        f"  raiz_manifestos: {mundo.raiz / 'manifestos'}",
        f"  raiz_saidas: {mundo.saidas}",
        f"  dir_congelamentos: {mundo.congelamentos}",
        "  duckdb_memoria: 256MB",
        f'  duckdb_threads: "{threads}"',
        f"  rede_permitida: {'true' if rede else 'false'}",
        "piloto:",
        "  uf: SP",
        f"  competencias_processamento: [{lista}]",
        f"  territorio: {DRS_XI}",
        "  familias_fontes: [SIA_PA, CNES_PF, CNES_ST, SIGTAP]",
        "coorte:",
        "  cohort_id: coorte_sintetica",
        "  uf: SP",
        f"  territorio: {DRS_XI}",
        "  pertenca: FIXA",
        '  inicio: "201801"',
        '  fim: "202512"',
        "bootstrap:",
        "  correcao: HOLM",
        "  reamostragens: 50",
    ]
    caminho = mundo.config(nome)
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def escrever_configs(mundo: Mundo, *, threads: int = 1) -> Mapping[str, Path]:
    """Configurações de cada janela: DEV, CAL e TESTE (a do protocolo, que também ingere)."""
    return {
        nome: escrever_config(mundo, nome, competencias, threads=threads)
        for nome, competencias in JANELAS.items()
    }


def preparar_mundo(raiz: Path) -> Mundo:
    """Diretório limpo com cópia de `catalog/` e `config/`, como na raiz de um clone novo.

    Alguns padrões do código são relativos ao diretório de trabalho (`config/splits.yaml`,
    `catalog/schemas/selecao_versoes.yaml` e `experiments/decisions`); por isso os comandos
    rodam de dentro dele.
    """
    shutil.copytree(RAIZ / "catalog", raiz / "catalog")
    shutil.copytree(RAIZ / "config", raiz / "config")
    return Mundo(raiz)


def comando(*argumentos: str) -> int:
    """Código de saída da CLI, inclusive o `SystemExit` do argparse."""
    try:
        return int(cli.main([*_NIVEL, *argumentos]))
    except SystemExit as saida:
        return int(saida.code) if isinstance(saida.code, int) else 1


def adquirir(mundo: Mundo) -> dict[str, int]:
    """`acquire` primário e auxiliar contra o FTP local; devolve os códigos de saída.

    A passada auxiliar pede também 201712 e 201802, que não existem: a ausência é registrada e o
    comando sai com FALHA_OPERACIONAL (5).
    """
    ftp = mundo.raiz / "ftp"
    publicar_originais(ftp)
    atendimento = mundo.raiz / "atendimento.txt"
    atendimento.write_text("\n".join(ATENDIMENTO) + "\n", encoding="utf-8")
    with servidor_ftp(ftp) as porta:
        catalogo_local(mundo.raiz, porta)
        config = str(escrever_config(mundo, "acq", COMPETENCIAS, rede=True))
        primaria = comando("acquire", "--config", config)
        passada = ["--passada", "auxiliar", "--competencias-atendimento", str(atendimento)]
        auxiliar = comando("acquire", "--config", config, *passada)
    return {"primaria": primaria, "auxiliar": auxiliar}
