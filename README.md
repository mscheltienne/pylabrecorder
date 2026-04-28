[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Imports: isort](https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336)](https://pycqa.github.io/isort/)
[![codecov](https://codecov.io/gh/mscheltienne/pylabrecorder/graph/badge.svg?token=RNqer2pSqQ)](https://codecov.io/gh/mscheltienne/pylabrecorder)
[![ci](https://github.com/mscheltienne/pylabrecorder/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/mscheltienne/pylabrecorder/actions/workflows/ci.yaml)

# PyLabRecorder

A Python package to control [LabRecorder](https://github.com/labstreaminglayer/App-LabRecorder)
from Python. The wheel statically bundles [`liblsl`](https://github.com/sccn/liblsl)
and the `LabRecorderCLI` binary, so no separate installation of either is required.

## Installation

`pylabrecorder` is published on [PyPI](https://pypi.org/project/pylabrecorder/):

```bash
pip install pylabrecorder
```

Wheels are provided for Linux, macOS, and Windows on Python 3.11+.

## Usage

```python
from pylabrecorder import LabRecorder

recorder = LabRecorder()
recorder.start(
    "recording.xdf",
    streams=[
        {"name": "stream1", "source_id": "source1"},
        {"name": "stream2", "source_id": "source2"},
    ],
)
# ... acquisition runs in the background ...
recorder.stop()
```

Each entry in `streams` is a dictionary mapping LSL stream metadata keys
(`name`, `type`, `source_id`, ...) to the value to match. Pass `streams=None`
to record every stream available on the network.
