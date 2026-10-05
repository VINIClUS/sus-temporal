"""Split do disco conferido por inteiro com o congelado, não só pelo `split_id` (T11).

O id não deriva do conteúdo do `SplitManifest`: partições ou rótulos editados o mantêm. Cenário
SINTETICO rotulado REAL só nos contratos; decisões G0/G2 só em diretórios temporários. Nenhum
resultado empírico.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.protocolo_cli import (
    REGISTRO,
    config_confirmatoria_yaml,
    congelar_pela_cli,
    gravar_runs,
    manifesto_da_cli,
    runs_da_cli,
)
from tests.fixtures.protocolo_confirmatorio import (
    Confirmatorio,
    editar_rotulos_do_teste_no_disco,
    montar_confirmatorio,
    rotulos_do_teste_invertidos,
    split_com_rotulos_do_teste,
)
from tests.fixtures.protocolo_dados import cenario_baseline

from sustemporal.cli import main
from sustemporal.contracts.experiment import Particao, SplitManifest
from sustemporal.errors import ExitCode, PortaoRecusado
from sustemporal.evaluation.freeze_conferencia import verificar_congelamento_completo
from sustemporal.evaluation.metrics import evaluate_runs

if TYPE_CHECKING:
    from tests.fixtures.protocolo_dados import Cenario

OUTRO_HASH = f"lh1:{'e' * 64}"
CASOS = ["rotulos_do_teste_trocados", "hash_da_particao_de_teste_trocado", "limites_alterados"]


@pytest.fixture(scope="module")
def cenario(tmp_path_factory: pytest.TempPathFactory) -> Cenario:
    return cenario_baseline(tmp_path_factory.mktemp("cenario"))


@pytest.fixture
def confirmatorio(tmp_path: Path, cenario: Cenario) -> Confirmatorio:
    return montar_confirmatorio(tmp_path, cenario)


def _editado(caso: str, conf: Confirmatorio, raiz: Path) -> SplitManifest:
    """Split com o `split_id` do congelado e conteúdo diferente."""
    split = conf.manifesto.split
    trocados = {**split.hash_por_particao, Particao.TESTE: OUTRO_HASH}
    editado = {
        "rotulos_do_teste_trocados": lambda: split_com_rotulos_do_teste(
            split, rotulos_do_teste_invertidos(conf.cenario, raiz / "trocados.parquet")
        ),
        "hash_da_particao_de_teste_trocado": lambda: split.model_copy(
            update={"hash_por_particao": trocados}
        ),
        "limites_alterados": lambda: split.model_copy(update={"limites": ("limite novo",)}),
    }[caso]()
    assert editado.split_id == split.split_id
    assert editado != split
    return editado


def _conferir(conf: Confirmatorio, split: SplitManifest) -> None:
    verificar_congelamento_completo(conf.manifesto, conf.estado_com(split=split))


@pytest.mark.parametrize("caso", CASOS)
def test_conferencia_recusa_split_com_o_mesmo_id_e_conteudo_diferente(
    tmp_path: Path, confirmatorio: Confirmatorio, caso: str
) -> None:
    editado = _editado(caso, confirmatorio, tmp_path)
    mensagem = f"freeze_incompativel campos=split freeze={confirmatorio.manifesto.freeze_id}"
    with pytest.raises(PortaoRecusado, match=f"^{re.escape(mensagem)}$"):
        _conferir(confirmatorio, editado)


def test_conferencia_aceita_o_mesmo_split_lido_de_novo(confirmatorio: Confirmatorio) -> None:
    congelado = confirmatorio.manifesto.split
    lido_de_novo = SplitManifest.model_validate_json(congelado.model_dump_json())
    assert lido_de_novo is not congelado
    _conferir(confirmatorio, lido_de_novo)


def test_avaliacao_confirmatoria_recusa_split_com_o_mesmo_id_e_rotulos_trocados(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    adulterado = _editado("rotulos_do_teste_trocados", confirmatorio, tmp_path)
    rotulos = (adulterado.rotulos_por_particao or {})[Particao.TESTE]
    freeze = confirmatorio.manifesto.freeze_id
    mensagem = f"freeze_incompativel campos=split freeze={freeze}"
    with pytest.raises(PortaoRecusado, match=f"^{re.escape(mensagem)}$"):
        evaluate_runs(
            confirmatorio.runs,
            rotulos,
            adulterado,
            tmp_path / "av",
            bootstrap=confirmatorio.manifesto.bootstrap,
            congelamento=confirmatorio.referencia(),
        )
    assert not (tmp_path / "av").exists()


def test_split_adulterado_e_recusado_antes_de_ler_qualquer_dado(tmp_path: Path) -> None:
    conf = montar_confirmatorio(tmp_path, cenario_baseline(tmp_path / "cenario"))
    adulterado = _editado("rotulos_do_teste_trocados", conf, tmp_path)
    assert adulterado.particoes is not None
    assert adulterado.rotulos_por_particao is not None
    rotulos = adulterado.rotulos_por_particao[Particao.TESTE]
    for dataset in (adulterado.particoes[Particao.TESTE], rotulos):
        Path(dataset.caminho).unlink()
    with pytest.raises(PortaoRecusado, match="freeze_incompativel campos=split"):
        evaluate_runs(
            conf.runs,
            rotulos,
            adulterado,
            tmp_path / "av",
            bootstrap=conf.manifesto.bootstrap,
            congelamento=conf.referencia(),
        )


def test_cli_recusa_o_confirmatorio_com_split_editado_que_mantem_o_split_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    gravar_runs(tmp_path, runs_da_cli(tmp_path, cenario, freeze))
    congelado = manifesto_da_cli(tmp_path, freeze).split
    adulterado = editar_rotulos_do_teste_no_disco(
        tmp_path / "saidas" / "split", cenario, tmp_path / "adulterado" / "rotulos.parquet"
    )
    assert adulterado.split_id == congelado.split_id
    assert adulterado != congelado
    config = config_confirmatoria_yaml(tmp_path, freeze)
    codigo = main(["evaluate", "--config", str(config), "--freeze", freeze])
    assert codigo == ExitCode.PORTAO_RECUSADO
    assert f"freeze_incompativel campos=split freeze={freeze}" in capsys.readouterr().err
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()
