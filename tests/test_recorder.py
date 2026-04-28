from __future__ import annotations

import multiprocessing as mp
import time
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
import pytest
import pyxdf
from mne import create_info
from mne.io import RawArray
from numpy.testing import assert_allclose

from pylabrecorder import LabRecorder

if TYPE_CHECKING:
    from pathlib import Path

    from mne.io import BaseRaw


@pytest.fixture(scope="module")
def chunk_size() -> int:
    """Return the chunk size for testing."""
    return 200


@pytest.fixture(scope="module")
def source_id() -> str:
    """Return a random source ID for testing."""
    return uuid.uuid4().hex


@pytest.fixture(scope="module")
def raw() -> RawArray:
    """Raw object with the first channel indexing the samples."""
    info = create_info(ch_names=["ch1", "ch2", "ch3"], sfreq=1000, ch_types="eeg")
    rng = np.random.default_rng()
    data = rng.random((3, 10000))
    data[0, :] = np.arange(10000)
    return RawArray(data, info)


def _player_mock_lsl_stream(
    raw: BaseRaw,
    chunk_size: int,
    name: str,
    source_id: str,
    status: mp.managers.ValueProxy,
) -> None:
    """Player for the 'mock_lsl_stream' fixture."""
    # nest the PlayerLSL import to first write the temporary LSL configuration file
    from mne_lsl.player import PlayerLSL  # noqa: E402

    player = PlayerLSL(raw, chunk_size=chunk_size, name=name, source_id=source_id)
    player.start()
    status.value = 1
    while status.value:
        time.sleep(0.1)
    player.stop()


@pytest.fixture(scope="module")
def mock_lsl_stream1(raw: BaseRaw, chunk_size: int, source_id: str):
    """Create a mock LSL stream for testing."""
    manager = mp.Manager()
    status = manager.Value("i", 0)
    name = "mock1"
    process = mp.Process(
        target=_player_mock_lsl_stream, args=(raw, chunk_size, name, source_id, status)
    )
    process.start()
    while status.value != 1:
        pass
    yield
    status.value = 0
    process.join(timeout=2)
    process.kill()


@pytest.fixture(scope="module")
def mock_lsl_stream2(raw: BaseRaw, chunk_size: int, source_id: str):
    """Create a mock LSL stream for testing."""
    manager = mp.Manager()
    status = manager.Value("i", 0)
    name = "mock2"
    process = mp.Process(
        target=_player_mock_lsl_stream, args=(raw, chunk_size, name, source_id, status)
    )
    process.start()
    while status.value != 1:
        pass
    yield
    status.value = 0
    process.join(timeout=2)
    process.kill()


def load_xdf(fname: Path) -> dict[str, RawArray]:
    """Load an XDF file into MNE Raw object.

    Parameters
    ----------
    fname : Path
        Path to an XDF file.

    Returns
    -------
    raws : dict of Raw
        Dict with the stream name as key and the corresponding :class:`mne.io.Raw`.
    """
    assert fname.exists()
    assert fname.suffix == ".xdf"
    streams, _ = pyxdf.load_xdf(fname)
    assert len(streams) != 0
    raws = {}
    for k, name in (
        (idx, stream["info"]["name"][0]) for idx, stream in enumerate(streams)
    ):
        stream = streams[k]
        data = stream["time_series"].T
        sfreq = float(Decimal(stream["info"]["nominal_srate"][0]))
        ch_names, ch_types = [], []
        for ch in stream["info"]["desc"][0]["channels"][0]["channel"]:
            ch_names.append(ch["label"][0])
            ch_types.append(ch["type"][0].lower())
        info = create_info(ch_names, sfreq, ch_types)
        raws[name] = RawArray(data, info)
    return raws


def test_LabRecorder_no_stream(tmp_path: Path) -> None:
    """Test LabRecorder with no stream matching."""
    recorder = LabRecorder()
    with pytest.raises(RuntimeError, match="The requested streams could not be found."):
        recorder.start(streams=[{"name": "test", "source_id": "101"}], fname="test.xdf")


def test_LabRecorder_invalid_CLI() -> None:
    """Test LabRecorder with an invalid CLI path."""
    with pytest.raises(FileNotFoundError, match="does not exist"):
        LabRecorder(labrecorder_cli_path="101")


@pytest.mark.usefixtures("mock_lsl_stream1")
@pytest.mark.usefixtures("mock_lsl_stream2")
def test_LabRecorder_stream_selection(tmp_path: Path) -> None:
    """Test LabRecorder stream selection."""
    recorder = LabRecorder()
    recorder.start(streams=[{"name": "mock1"}], fname=tmp_path / "test.xdf")
    time.sleep(0.5)
    recorder.stop()
    raws = load_xdf(tmp_path / "test.xdf")
    assert len(raws) == 1
    assert "mock1" in raws
    assert_allclose(
        np.diff(raws["mock1"].get_data(picks=0).squeeze()),
        np.ones(raws["mock1"].times.size - 1),
    )


@pytest.mark.usefixtures("mock_lsl_stream1")
@pytest.mark.usefixtures("mock_lsl_stream2")
def test_LabRecorder_stream_selection_by_source_id(
    tmp_path: Path, source_id: str
) -> None:
    """Test LabRecorder stream selection by source ID."""
    recorder = LabRecorder()
    with pytest.warns(RuntimeWarning, match="not match the number of streams expected"):
        recorder.start(streams=[{"source_id": source_id}], fname=tmp_path / "test.xdf")
    time.sleep(0.5)
    recorder.stop()
    raws = load_xdf(tmp_path / "test.xdf")
    assert len(raws) == 2
    assert "mock1" in raws
    assert "mock2" in raws


@pytest.mark.usefixtures("mock_lsl_stream1")
@pytest.mark.usefixtures("mock_lsl_stream2")
def test_LabRecorder_expression_selection(tmp_path: Path, source_id: str) -> None:
    """Test LabRecorder stream selection with an expression under-the-hood."""
    recorder = LabRecorder()
    recorder.start(
        streams=[{"name": "mock1", "source_id": source_id}], fname=tmp_path / "test.xdf"
    )
    time.sleep(0.5)
    recorder.stop()
    raws = load_xdf(tmp_path / "test.xdf")
    assert len(raws) == 1
    assert "mock1" in raws


@pytest.mark.usefixtures("mock_lsl_stream1")
@pytest.mark.usefixtures("mock_lsl_stream2")
def test_LabRecorder_restart_and_overwrite(tmp_path: Path) -> None:
    """Test LabRecorder restart and overwrite."""
    recorder = LabRecorder()
    recorder.start(streams=[{"name": "mock1"}], fname=tmp_path / "test.xdf")
    time.sleep(0.5)
    recorder.stop()
    raws = load_xdf(tmp_path / "test.xdf")
    assert len(raws) == 1
    assert "mock1" in raws
    with pytest.raises(FileExistsError, match="already exists"):
        recorder.start(
            streams=[{"name": "mock2"}], fname=tmp_path / "test.xdf", overwrite=False
        )
    recorder.start(
        streams=[{"name": "mock2"}], fname=tmp_path / "test.xdf", overwrite=True
    )
    time.sleep(0.5)
    recorder.stop()
    raws = load_xdf(tmp_path / "test.xdf")
    assert len(raws) == 1
    assert "mock2" in raws


@pytest.mark.usefixtures("mock_lsl_stream1")
@pytest.mark.usefixtures("mock_lsl_stream2")
def test_LabRecorder_record_all(tmp_path) -> None:
    """Test LabRecorder recording all streams."""
    recorder = LabRecorder()
    recorder.start(fname=tmp_path / "test.xdf")
    time.sleep(0.5)
    recorder.stop()
    raws = load_xdf(tmp_path / "test.xdf")
    assert len(raws) == 2
    assert "mock1" in raws
    assert "mock2" in raws


@pytest.mark.usefixtures("mock_lsl_stream1")
def test_LabRecorder_set_experiment_info(tmp_path: Path) -> None:
    """Test LabRecorder set_experiment_info."""
    recorder = LabRecorder()
    assert recorder._fname is None
    with pytest.raises(RuntimeError, match="Either provide a file name"):
        recorder.start(streams=[{"name": "mock1"}])
    recorder.set_experiment_info(
        root=tmp_path,
        task="test",
        participant="101",
        session="2",
        run=1,
        modality="eeg",
    )
    assert recorder._fname is not None
    assert not recorder._fname.exists()
    assert not recorder._fname.parent.exists()
    recorder.start(streams=[{"name": "mock1"}])
    assert recorder._fname.parent.exists()
    time.sleep(0.5)
    fname = recorder._fname
    recorder.stop()
    assert recorder._fname is None
    raws = load_xdf(fname)
    assert len(raws) == 1
    assert "mock1" in raws
