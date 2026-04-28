from __future__ import annotations

import subprocess
import threading
import time
from importlib.resources import files
from typing import TYPE_CHECKING

from pylabrecorder.utils._checks import check_type, ensure_path
from pylabrecorder.utils.logs import logger, warn

if TYPE_CHECKING:
    from pathlib import Path


class LabRecorder:
    """Interface for LabRecorderCLI using :class:`subprocess.Popen`.

    Parameters
    ----------
    labrecorder_cli_path : str | Path | None
        Path to the ``LabRecorderCLI`` executable. If None, the ``LabRecorderCLI``
        bundled with this package will be used.
    """

    def __init__(self, *, labrecorder_cli_path: str | Path | None = None) -> None:
        self._reset_variables()
        # validate arguments
        if labrecorder_cli_path is None:
            dir_bin = files("pylabrecorder") / "lib"
            for elt in dir_bin.iterdir():
                if elt.is_file() and "LabRecorderCLI" in elt.name:
                    labrecorder_cli_path = elt
                    break
        self._labrecorder_cli_path = ensure_path(labrecorder_cli_path, must_exist=True)

    def start(
        self,
        fname: str | Path,
        streams: list[dict[str, str]] | None = None,
        *,
        overwrite: bool = False,
        timeout: float = 10,
    ) -> None:
        """Start recording to an XDF file.

        Parameters
        ----------
        fname : str | Path
            Name of the XDF file to record to.
        streams : list of dict | None
            List of :class:`dict`, each defining a stream to record. Each :class:`dict`
            must contain recognized keys by ``LabRecorder`` and ``LSL``, for instance a
            stream could be defined by
            ``{"name": "test", "type": "EEG", "source_id": "D-10234"}``. Ideally, each
            entry should uniquely identify a stream. A warning will be issued if this is
            not the case. If None, all available streams will be recorded.
        overwrite : bool
            If True, overwrite existing files.
        timeout : float
            Timeout duration in seconds during which LabRecorderCLI attempts to start
            the recording if the streams are found.

        Notes
        -----
        In practice, the CLI interface can filter streams based on a predicate which is
        essentially an XPath 1.0 expression applied to the ``<info>`` XML node of the
        strean description. It supports both simple equality checks
        (``name='BioSemi'``), logical combinations using ``and`` and ``or``
        (``type='EEG' and name='BioSemi'``, ``type='EEG' or type='ECG'``) or functions
        (``starts-with(name,'BioSemi')``, ``contains(name,'EEG')``,
        ``count(info/desc/channel)=32``). For example:

        * ``name='Tobii' and type='Eyetracker' and count(info/desc/channel)=2``
        * ``(type='EEG' or type='ECG') and starts-with(name, 'Bio')``

        The predicates are case-sensitive. Thus ``type='eeg'`` will not match the stream
        with type ``EEG``.
        """
        if self._process is not None:
            raise RuntimeError("The recording is already started.")
        fname = ensure_path(fname, must_exist=False)
        check_type(streams, (list, None), "streams")
        if streams is not None:
            for stream in streams:
                check_stream(stream)
        check_type(overwrite, (bool,), "overwrite")
        if not overwrite and fname.exists():
            raise FileExistsError(f"File {fname} already exists.")
        elif overwrite and fname.exists():
            fname.unlink()
        if not fname.parent.exists():
            logger.info("Directory '%s' does not exist, creating it.", fname.parent)
            fname.parent.mkdir(parents=True)
        # convert streams into valid CLI arguments
        if streams is None:
            stream_args = ["true()"]
        else:
            stream_args = [
                " and ".join([f"{key}='{value}'" for key, value in stream.items()])
                for stream in streams
            ]
        # start process
        self._process = subprocess.Popen(
            [str(self._labrecorder_cli_path), str(fname)] + stream_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
        )
        # start acquisition thread to parse stdout
        self._stdout_thread = threading.Thread(
            target=self._stdout_reader_thread, daemon=True
        )
        self._stdout_thread.start()
        # wait until data collection starts and log important messages from LabRecorder
        start = time.time()
        n_streams = None
        while time.time() - start < timeout:
            if any("matched no stream!" in line for line in self._stdout_lines):
                self._close_process()
                raise RuntimeError("The requested streams could not be found.")
            if n_streams is None:
                for line in self._stdout_lines:
                    if line == "Starting the recording, press Enter to quit":
                        n_streams = self._stdout_lines.index(line)
            start_lines = [
                line
                for line in self._stdout_lines
                if line.startswith("Started data collection")
            ]
            if len(start_lines) == n_streams:
                break
        else:  # pragma: no cover
            raise TimeoutError("The recording did not start in time.")
        for line in self._stdout_lines:
            if line.startswith(("Found", "Started data collection")):
                logger.info(line)
        if streams is not None and len(streams) != n_streams:
            warn(
                f"The number of streams found {len(start_lines)} does not match the "
                f"number of streams expected {len(streams)}."
            )

    def stop(self) -> None:
        """Stop the recording and wait for it to exit."""
        if self._process is None:
            raise RuntimeError("The recording was not started.")
        self._process.stdin.write("\n")
        self._process.stdin.flush()
        self._close_process()
        if self._process.returncode != 0:
            raise RuntimeError(
                f"LabRecorderCLI exited with code {self._process.returncode}."
            )
        logger.info("Recording stopped.")
        self._reset_variables()

    def _close_process(self) -> None:
        """Close the open process and attached resources."""
        if self._process is None:  # pragma: no cover
            raise RuntimeError("The process does not exist.")
        self._process.wait()  # wait for the process to exit
        if self._stdout_thread is not None and self._stdout_thread.is_alive():
            self._stdout_thread.join(timeout=1.0)
        for std in (self._process.stdout, self._process.stderr, self._process.stdin):
            if std:
                std.close()

    def _reset_variables(self) -> None:
        """Reset variables between acquisitions."""
        self._process: subprocess.Popen | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stdout_lines: list[str] = []

    def _stdout_reader_thread(self) -> None:
        """Thread to read from stdout and store the lines in a shared list."""
        while True:
            if self._process is None or self._process.stdout is None:
                break
            line = self._process.stdout.readline()
            if not line:
                break
            line = line.removesuffix("\n")
            self._stdout_lines.append(line)
            logger.debug(line)


def check_stream(stream: dict[str, str]) -> None:
    """Validate a stream dictionary.

    Parameters
    ----------
    stream : dict
        A :class:`dict` defining an LSL stream with recognized keys. For instance,
        ``{"name": "test", "type": "EEG", "source_id": "D-10234"}``.
    """
    check_type(stream, (dict,), "stream")
    for key, value in stream.items():
        check_type(key, (str,), "stream key")
        check_type(value, (str,), "value")
