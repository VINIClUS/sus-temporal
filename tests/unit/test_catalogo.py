"""Catálogo versionado: esquemas canônicos, famílias candidatas, território e configurações."""

import re
import shutil
from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest

from sustemporal.acquisition.sources import carregar_catalogo
from sustemporal.config import load_config
from sustemporal.contracts import (
    CatalogoFamilias,
    Confirmacao,
    EsquemaCanonico,
    EstadoDocumento,
    EstadoRegra,
    FamiliaFonte,
    FamiliaRegra,
    MetodoId,
    ModoExecucao,
    OrigemDados,
    PapelColuna,
    Particao,
    PertencaGeografica,
    Proveniencia,
    Territorio,
    TipoCanonico,
    UnidadeAvaliacao,
)
from sustemporal.errors import ConfigInvalida
from sustemporal.yamlio import carregar_yaml

RAIZ = Path(__file__).resolve().parents[2]
ESQUEMAS = RAIZ / "catalog" / "schemas"
FONTES = RAIZ / "catalog" / "sources.yaml"
REGISTRO_DE_FONTES = RAIZ / "docs" / "references" / "fontes.md"
CONFIGS = RAIZ / "config"
NOMES_ESQUEMAS = (
    "sia_pa",
    "sia_pa_rotulos",
    "cnes_estab_cbo",
    "cnes_estabelecimento",
    "sigtap_procedimento",
    "sigtap_proc_ocupacao",
    "sigtap_proc_registro",
    "cobertura",
    "selecao_versoes",
    "avaliacoes",
    "evidencias",
    "agregados_registro",
    "falhas",
    "sigtap_registro",
    "piloto_contagens",
    "piloto_exclusoes",
    "piloto_campos",
    "piloto_defasagem",
    "piloto_rotulos",
    "piloto_inconclusivos",
    "piloto_disponibilidade",
    "valores_p3",
    "predicoes_baseline",
)
ATRIBUTOS_SIA_PA = frozenset(
    {
        "cnes",
        "municipio_estabelecimento",
        "competencia_processamento",
        "competencia_atendimento",
        "procedimento",
        "instrumento",
        "cbo",
        "cid_principal",
        "cid_secundario",
        "cid_causas_associadas",
        "carater_atendimento",
        "idade",
        "idade_unidade",
        "sexo",
        "quantidade_apresentada",
    }
)
DIAGNOSTICOS_SIA_PA = frozenset(
    {
        "pa_codoco",
        "pa_flqt",
        "pa_fler",
        "pa_flidade",
        "quantidade_aprovada",
        "valor_aprovado",
        "valor_apresentado",
        "nu_vpa_tot",
        "nu_pa_tot",
        "pa_dif_val",
        "pa_ufdif",
        "pa_mndif",
        "tipo_unidade",
    }
)
TRECHOS_POS_PROCESSAMENTO = (
    "indica",
    "rotulo",
    "aprovad",
    "codoco",
    "flqt",
    "fler",
    "flidade",
    "valor",
    "vl_",
    "dif",
    "tot",
)
MONETARIA = re.compile(r"valor_\w+|vl_s[hap]|pa_vl_\w+|pa_dif_val|nu_v?pa_tot")
CODIGO = re.compile(
    r"cnes|cbo|procedimento|instrumento|sexo|co_\w+|tp_\w+|cid_\w+|pa_\w+|idademin|idademax"
    r"|competencia\w*|municipio\w*|\w+_ids?|\w+_bruto|\w+_motivo"
)
INSTRUMENTOS_PA_DOCORIG = frozenset({"C", "I", "P", "S", "A", "B"})
COMPETENCIAS_PILOTO = ("201801", "201807", "202001", "202007", "202201", "202207")
FONTES_PILOTO = (
    "SIA_PA",
    "CNES_ST",
    "CNES_PF",
    "CNES_SR",
    "CNES_HB",
    "SIGTAP",
    "TERRITORIO_DRS",
    "DOCUMENTO",
)
REGIOES_DRS_XI = {
    "Alta Paulista": 12,
    "Alta Sorocabana": 19,
    "Alto Capivari": 5,
    "Extremo Oeste Paulista": 5,
    "Pontal do Paranapanema": 4,
}


def _esquema(nome: str) -> EsquemaCanonico:
    return EsquemaCanonico.de_yaml(ESQUEMAS / f"{nome}.yaml")


def _papeis(esquema: EsquemaCanonico) -> dict[str, PapelColuna]:
    return {coluna.nome: coluna.papel for coluna in esquema.colunas}


def _tipos(esquema: EsquemaCanonico) -> dict[str, TipoCanonico]:
    return {coluna.nome: coluna.tipo for coluna in esquema.colunas}


def _descricoes(esquema: EsquemaCanonico) -> dict[str, str]:
    return {coluna.nome: coluna.descricao for coluna in esquema.colunas}


def _monetaria(nome: str) -> bool:
    return bool(MONETARIA.fullmatch(nome)) and not nome.endswith(("_bruto", "_motivo"))


def _familias() -> CatalogoFamilias:
    return CatalogoFamilias.model_validate(carregar_yaml(RAIZ / "catalog" / "familias.yaml"))


def _territorio() -> Territorio:
    caminho = RAIZ / "catalog" / "territorio" / "drs_xi.yaml"
    return Territorio.model_validate(carregar_yaml(caminho))


def _digito_verificador_ibge(ibge6: str) -> str:
    soma = 0
    for posicao, digito in enumerate(ibge6):
        produto = int(digito) * (1 + posicao % 2)
        soma += produto // 10 + produto % 10
    return str((10 - soma % 10) % 10)


def test_catalogo_tem_um_arquivo_por_esquema_canonico() -> None:
    presentes = {caminho.stem for caminho in ESQUEMAS.glob("*.yaml")}
    assert presentes >= set(NOMES_ESQUEMAS)


@pytest.mark.parametrize("caminho", sorted(ESQUEMAS.glob("*.yaml")), ids=lambda c: c.name)
def test_esquema_carrega_e_schema_id_corresponde_ao_arquivo(caminho: Path) -> None:
    esquema = EsquemaCanonico.de_yaml(caminho)
    assert re.fullmatch(rf"{re.escape(caminho.stem)}\.v\d+", esquema.schema_id)


def test_sia_pa_preserva_registro_fisico_e_separa_competencias() -> None:
    esquema = _esquema("sia_pa")
    descricoes = _descricoes(esquema)
    assert esquema.chave == ("row_id",)
    linhagem = {"artifact_id", "membro", "indice_registro", "deletado"}
    assert linhagem <= set(esquema.colunas_com_papel(PapelColuna.LINHAGEM))
    assert descricoes["competencia_processamento"].startswith("PA_MVM ")
    assert descricoes["competencia_atendimento"].startswith("PA_CMP ")


def test_sia_pa_indica_e_rotulo_e_atributos_excluem_rotulo_e_diagnostico() -> None:
    esquema = _esquema("sia_pa")
    atributos = set(esquema.colunas_com_papel(PapelColuna.ATRIBUTO))
    assert esquema.colunas_com_papel(PapelColuna.ROTULO) == ("pa_indica",)
    assert _descricoes(esquema)["pa_indica"].startswith("PA_INDICA ")
    assert atributos == ATRIBUTOS_SIA_PA
    assert not {nome for nome in atributos if any(t in nome for t in TRECHOS_POS_PROCESSAMENTO)}


def test_sia_pa_diagnostico_inclui_campos_de_erro_e_valores_aprovados() -> None:
    diagnosticos = set(_esquema("sia_pa").colunas_com_papel(PapelColuna.DIAGNOSTICO))
    assert diagnosticos >= DIAGNOSTICOS_SIA_PA


def test_sia_pa_campo_normalizado_guarda_bruto_e_motivo() -> None:
    esquema = _esquema("sia_pa")
    papeis = _papeis(esquema)
    numericos = {
        nome
        for nome, tipo in _tipos(esquema).items()
        if tipo in {TipoCanonico.INTEIRO, TipoCanonico.DECIMAL}
    }
    normalizados = (ATRIBUTOS_SIA_PA - {"idade_unidade"}) | (numericos - {"indice_registro"})
    normalizados |= {"tipo_unidade"}
    for nome in normalizados:
        assert papeis.get(f"{nome}_bruto") is PapelColuna.BRUTO, nome
        assert papeis.get(f"{nome}_motivo") is PapelColuna.MOTIVO, nome
    companheiras = esquema.colunas_com_papel(PapelColuna.BRUTO) + esquema.colunas_com_papel(
        PapelColuna.MOTIVO
    )
    assert {nome.rsplit("_", 1)[0] for nome in companheiras} == normalizados


def test_sia_pa_nao_traz_identificador_de_pessoa_nem_de_autorizacao() -> None:
    nomes = {coluna.nome for coluna in _esquema("sia_pa").colunas}
    assert not {nome for nome in nomes if re.search(r"cpf|cns|cnpj|autoriz|nome", nome)}


@pytest.mark.parametrize("nome", NOMES_ESQUEMAS)
def test_codigos_sao_texto_e_valores_monetarios_sao_decimal(nome: str) -> None:
    for coluna in _esquema(nome).colunas:
        if _monetaria(coluna.nome):
            assert coluna.tipo is TipoCanonico.DECIMAL, coluna.nome
        elif CODIGO.fullmatch(coluna.nome):
            assert coluna.tipo is TipoCanonico.TEXTO, coluna.nome


def test_colunas_monetarias_esperadas_existem_como_decimal() -> None:
    esperadas = {
        "sia_pa": {
            "valor_apresentado",
            "valor_aprovado",
            "pa_dif_val",
            "nu_vpa_tot",
            "nu_pa_tot",
            "pa_vl_cf",
            "pa_vl_cl",
            "pa_vl_inc",
        },
        "sia_pa_rotulos": {"valor_apresentado", "valor_aprovado"},
        "sigtap_procedimento": {"vl_sh", "vl_sa", "vl_sp"},
    }
    for nome, monetarias in esperadas.items():
        tipos = _tipos(_esquema(nome))
        assert {coluna for coluna in tipos if _monetaria(coluna)} == monetarias
        assert {tipos[coluna] for coluna in monetarias} == {TipoCanonico.DECIMAL}


def test_cnes_estab_cbo_guarda_so_contagens_sem_identificar_profissional() -> None:
    esquema = _esquema("cnes_estab_cbo")
    nomes = [coluna.nome for coluna in esquema.colunas]
    assert not [nome for nome in nomes if re.search(r"cpf|cns|nome|registro", nome)]
    assert esquema.chave == ("competencia_arquivo", "cnes", "cbo", "artifact_id")
    assert _tipos(esquema)["n_vinculos"] is TipoCanonico.INTEIRO


def test_sigtap_idade_em_meses_trata_sentinela_9999_por_motivo() -> None:
    esquema = _esquema("sigtap_procedimento")
    papeis = _papeis(esquema)
    descricoes = _descricoes(esquema)
    for limite in ("vl_idade_minima", "vl_idade_maxima"):
        assert _tipos(esquema)[limite] is TipoCanonico.INTEIRO
        assert "meses" in descricoes[limite]
        assert papeis[f"{limite}_bruto"] is PapelColuna.BRUTO
        assert papeis[f"{limite}_motivo"] is PapelColuna.MOTIVO
        assert "9999" in descricoes[f"{limite}_motivo"]


def test_familias_sao_as_quatro_candidatas_pre_g0_do_primeiro_incremento() -> None:
    catalogo = _familias()
    candidatas = [familia.familia for familia in catalogo.familias]
    assert sorted(candidatas) == sorted(
        [
            FamiliaRegra.PROCEDIMENTO_CBO,
            FamiliaRegra.ESTABELECIMENTO_CBO,
            FamiliaRegra.INSTRUMENTO_REGISTRO,
            FamiliaRegra.VIGENCIA_PROCEDIMENTO,
        ]
    )
    assert {familia.estado for familia in catalogo.familias} == {EstadoRegra.CANDIDATA_PRE_G0}
    assert set(catalogo.reservadas) == {
        FamiliaRegra.SERVICO_CLASSIFICACAO,
        FamiliaRegra.HABILITACAO,
        FamiliaRegra.CID,
        FamiliaRegra.IDADE,
        FamiliaRegra.SEXO,
        FamiliaRegra.QUANTIDADE_MAXIMA,
    }


def test_familias_citam_documento_pendente_a_confirmar_e_instrumentos_pa_docorig() -> None:
    proveniencias = {Proveniencia.SECUNDARIA, Proveniencia.OFICIAL_VISTO_EM_BUSCA}
    for familia in _familias().familias:
        assert familia.referencia.estado is EstadoDocumento.PENDENTE
        assert familia.referencia.confirmacao is Confirmacao.A_CONFIRMAR
        assert familia.referencia.proveniencia in proveniencias
        assert set(familia.instrumentos) <= INSTRUMENTOS_PA_DOCORIG


def test_estabelecimento_cbo_usa_contagens_do_cnes_pf_por_estabelecimento_cbo() -> None:
    por_familia = {familia.familia: familia for familia in _familias().familias}
    familia = por_familia[FamiliaRegra.ESTABELECIMENTO_CBO]
    fontes = {requisito.fonte: requisito.schema_id for requisito in familia.requisitos_fonte}
    assert familia.unidade_avaliacao is UnidadeAvaliacao.ESTABELECIMENTO_CBO
    assert fontes[FamiliaFonte.CNES_PF] == "cnes_estab_cbo.v1"


def test_requisitos_das_familias_existem_nos_esquemas() -> None:
    for familia in _familias().familias:
        for requisito in familia.requisitos_fonte:
            esquema = _esquema(requisito.schema_id.rsplit(".v", 1)[0])
            assert esquema.schema_id == requisito.schema_id
            assert set(requisito.campos) <= {coluna.nome for coluna in esquema.colunas}


def _vistos_em_busca() -> set[str]:
    """IDs que `docs/references/fontes.md` dá como OFICIAL_VISTO_EM_BUSCA (`O2–O6` é faixa)."""
    texto = REGISTRO_DE_FONTES.read_text(encoding="utf-8")
    linha = next(x for x in texto.splitlines() if x.startswith("| OFICIAL_VISTO_EM_BUSCA |"))
    situacao = linha.strip().strip("|").split("|")[2]
    ids: set[str] = set()
    for parte in situacao.split(","):
        casamento = re.fullmatch(r"([A-Z])(\d+)(?:–[A-Z](\d+))?", parte.strip())
        assert casamento, f"id_ilegivel valor={parte}"
        prefixo, inicio, fim = casamento.groups()
        ids |= {f"{prefixo}{n}" for n in range(int(inicio), int(fim or inicio) + 1)}
    return ids


def test_documentos_vistos_em_busca_sao_os_que_o_registro_de_fontes_diz() -> None:
    documentos = carregar_catalogo(FONTES).documentos
    vistos = {d.doc_id for d in documentos if d.proveniencia is Proveniencia.OFICIAL_VISTO_EM_BUSCA}
    assert vistos == _vistos_em_busca() & {d.doc_id for d in documentos}
    assert {d.confirmacao for d in documentos} == {Confirmacao.A_CONFIRMAR}


def test_territorio_drs_xi_tem_45_municipios_em_5_regioes() -> None:
    territorio = _territorio()
    assert territorio.uf == "SP"
    assert len(territorio.municipios) == 45
    assert Counter(municipio.regiao for municipio in territorio.municipios) == REGIOES_DRS_XI
    assert territorio.proveniencia is Proveniencia.SECUNDARIA
    assert territorio.confirmacao is Confirmacao.A_CONFIRMAR


def test_territorio_inclui_presidente_epitacio_e_presidente_prudente() -> None:
    por_ibge7 = {municipio.ibge7: municipio for municipio in _territorio().municipios}
    epitacio = por_ibge7["3541307"]
    assert (epitacio.nome, epitacio.ibge6) == ("Presidente Epitácio", "354130")
    assert por_ibge7["3541406"].nome == "Presidente Prudente"
    assert "3541308" not in por_ibge7


def test_territorio_codigos_ibge7_tem_digito_verificador_valido() -> None:
    invalidos = [
        municipio.ibge7
        for municipio in _territorio().municipios
        if _digito_verificador_ibge(municipio.ibge6) != municipio.ibge7[6]
    ]
    assert invalidos == []


def test_territorio_cita_fontes_pendentes_com_proveniencia_explicita() -> None:
    fontes = {fonte.doc_id: fonte for fonte in _territorio().fontes}
    assert {fonte.estado for fonte in fontes.values()} == {EstadoDocumento.PENDENTE}
    assert {fontes[i].proveniencia for i in ("O4", "O5")} == {Proveniencia.OFICIAL_VISTO_EM_BUSCA}
    assert {fontes[i].proveniencia for i in ("S23", "S24", "S25")} == {Proveniencia.SECUNDARIA}


def test_configuracoes_do_plano_existem() -> None:
    presentes = {caminho.name for caminho in CONFIGS.glob("*.yaml")}
    assert presentes >= {"runtime.yaml", "pilot.yaml", "cohort.yaml", "splits.yaml"}


@pytest.mark.parametrize("caminho", sorted(CONFIGS.glob("*.yaml")), ids=lambda c: c.name)
def test_configuracao_carrega_e_valida_antes_de_processar(caminho: Path) -> None:
    assert load_config(caminho).versao == "1"


def test_runtime_padrao_fica_sem_rede_com_limites_do_plano() -> None:
    runtime = load_config(CONFIGS / "runtime.yaml").runtime
    assert runtime.rede_permitida is False
    assert (runtime.duckdb_memoria, runtime.duckdb_threads) == ("8GB", 4)


def test_piloto_tem_seis_competencias_de_processamento_do_drs_xi() -> None:
    config = load_config(CONFIGS / "pilot.yaml")
    piloto = config.piloto
    assert piloto is not None
    assert tuple(str(c) for c in piloto.competencias_processamento) == COMPETENCIAS_PILOTO
    assert tuple(fonte.value for fonte in piloto.familias_fontes) == FONTES_PILOTO
    assert (config.modo, config.origem_dados) == (ModoExecucao.EXPLORATORIO, OrigemDados.REAL)
    assert config.runtime.rede_permitida is True
    assert config.runtime.duckdb_memoria == "8GB"
    assert (RAIZ / piloto.territorio).is_file()


def test_coorte_cobre_drs_xi_de_2018_a_2025_com_pertenca_a_definir() -> None:
    config = load_config(CONFIGS / "cohort.yaml")
    coorte = config.coorte
    assert coorte is not None
    assert (str(coorte.inicio), str(coorte.fim)) == ("201801", "202512")
    assert coorte.pertenca is PertencaGeografica.A_DEFINIR
    assert (RAIZ / coorte.territorio).is_file()
    assert config.metodos == (MetodoId.M_TEMP, MetodoId.B_ATEND, MetodoId.B_PROC)
    assert config.politica_id == "M_TEMP_PADRAO"


def test_particoes_ordenadas_disjuntas_e_contiguas_sobre_a_coorte() -> None:
    particoes = load_config(CONFIGS / "splits.yaml").particoes
    coorte = load_config(CONFIGS / "cohort.yaml").coorte
    assert particoes is not None
    assert coorte is not None
    intervalos = particoes.intervalos
    assert [(i.particao, str(i.inicio), str(i.fim)) for i in intervalos] == [
        (Particao.DESENVOLVIMENTO, "201801", "202212"),
        (Particao.CALIBRACAO, "202301", "202312"),
        (Particao.TESTE, "202401", "202512"),
    ]
    assert (intervalos[0].inicio, intervalos[-1].fim) == (coorte.inicio, coorte.fim)
    for anterior, seguinte in pairwise(intervalos):
        assert seguinte.inicio == anterior.fim.deslocar(1)


def test_particoes_sobrepostas_sao_recusadas_ao_carregar(tmp_path: Path) -> None:
    for nome in ("runtime.yaml", "splits.yaml"):
        shutil.copy(CONFIGS / nome, tmp_path / nome)
    sobreposta = tmp_path / "sobreposta.yaml"
    sobreposta.write_text(
        "base: splits.yaml\n"
        "particoes:\n"
        "  intervalos:\n"
        "    - {particao: DESENVOLVIMENTO, inicio: 201801, fim: 202301}\n"
        "    - {particao: CALIBRACAO, inicio: 202301, fim: 202312}\n"
        "    - {particao: TESTE, inicio: 202401, fim: 202512}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigInvalida, match="particoes_sobrepostas"):
        load_config(sobreposta)


def test_bootstrap_inicial_tem_2000_reamostragens_e_semente_2027() -> None:
    bootstrap = load_config(CONFIGS / "splits.yaml").bootstrap
    assert (bootstrap.reamostragens, bootstrap.semente) == (2000, 2027)


def test_piloto_so_usa_competencias_de_desenvolvimento() -> None:
    piloto = load_config(CONFIGS / "pilot.yaml").piloto
    particoes = load_config(CONFIGS / "splits.yaml").particoes
    assert piloto is not None
    assert particoes is not None
    desenvolvimento = next(
        i for i in particoes.intervalos if i.particao is Particao.DESENVOLVIMENTO
    )
    fora = [
        competencia
        for competencia in piloto.competencias_processamento
        if not desenvolvimento.inicio <= competencia <= desenvolvimento.fim
    ]
    assert fora == []
