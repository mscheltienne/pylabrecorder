import os
import platform
import subprocess
from pathlib import Path
from shutil import move
from tempfile import TemporaryDirectory

from setuptools import setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_ext import build_ext as _build_ext
from setuptools.command.develop import develop as _develop
from setuptools.dist import Distribution


class BinaryDistribution(Distribution):  # noqa: D101
    def has_ext_modules(self):  # noqa: D102
        return True


class build_ext(_build_ext):  # noqa: D101
    def run(self) -> None:
        """Build 'labrecorder' with cmake as part of the extension build process.

        This build process is similar to the GitHub build workflow of LabRecorder, and
        starts by building a static version of liblsl used in the build of LabRecorder.
        """
        with TemporaryDirectory() as build_dir_labrecorder:
            build_dir_labrecorder = Path(build_dir_labrecorder)
            with TemporaryDirectory() as build_dir_liblsl:
                install_dir_liblsl = _build_liblsl(Path(build_dir_liblsl))
                move(install_dir_liblsl, build_dir_labrecorder / "install")
            install_dir_labrecorder = _build_labrecorder(build_dir_labrecorder)
            # create the destination directory in the python package where the build
            # artifacts are moved
            dst = (
                Path(__file__).parent / "src" / "pylabrecorder" / "lib"
                if self.inplace
                else Path(self.build_lib) / "pylabrecorder" / "lib"
            )
            dst.mkdir(parents=True, exist_ok=True)
            # locate and move the build artifacts
            file_bin = [
                file
                for file in install_dir_labrecorder.rglob("LabRecorderCLI*")
                if file.is_file()  # discard .app bundle on macOS
            ]
            assert len(file_bin) == 1  # sanity-check
            print(f"Moving {file_bin[0]} to {dst / file_bin[0].name}")  # noqa: T201
            move(file_bin[0], dst / file_bin[0].name)
        super().run()


def _build_liblsl(build_dir_liblsl: Path) -> Path:
    """Build a static version of liblsl.

    Parameters
    ----------
    build_dir_liblsl : Path
        The directory in which to build liblsl.

    Returns
    -------
    install_dir_liblsl : Path
        The 'install' directory in which a static liblsl is available.
    """
    src = Path(__file__).parent / "src" / "liblsl"
    assert src.exists()  # sanity-check
    args = [
        "cmake",
        "-S",
        str(src),
        "-B",
        str(build_dir_liblsl),
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_INSTALL_PREFIX={str(build_dir_liblsl / 'install')}",
        "-DLSL_BUILD_STATIC=ON",
    ]
    if platform.system() == "Darwin":
        args.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=11")
        args.append("-DLSL_FRAMEWORK=OFF")
    if platform.system() == "Linux":
        args.append("-DLSL_UNIXFOLDERS=ON")
    subprocess.run(args, check=True)
    subprocess.run(
        [
            "cmake",
            "--build",
            str(build_dir_liblsl),
            "--config",
            "Release",
            "-j",
            "--target install",
        ],
        check=True,
    )
    install_dir = build_dir_liblsl / "install"
    _patch_lsl_config(install_dir)
    return install_dir


def _patch_lsl_config(install_dir: Path) -> None:
    """Patch LSLConfig.cmake to include LSLCMake.cmake.

    liblsl v1.17.4 generates LSLConfig.cmake from export targets which doesn't
    include LSLCMake.cmake. LabRecorder uses functions from LSLCMake.cmake
    (installLSLApp), so we need to patch the installed LSLConfig.cmake to include it.
    """
    # Find LSLConfig.cmake - location depends on platform
    candidates = list(install_dir.rglob("LSLConfig.cmake"))
    assert len(candidates) == 1, f"Expected 1 LSLConfig.cmake, found {len(candidates)}"
    lsl_config = candidates[0]
    content = lsl_config.read_text()
    # Add include for LSLCMake.cmake if not already present
    include_line = 'include("${CMAKE_CURRENT_LIST_DIR}/LSLCMake.cmake")'
    if include_line not in content:
        content += f"\n{include_line}\n"
        lsl_config.write_text(content)


def _build_labrecorder(build_dir_labrecorder: Path):
    """Build LabRecorder.

    Parameters
    ----------
    build_dir_labrecorder : Path
        The directory in which to build LabRecorder.

    Returns
    -------
    install_dir_labrecorder : Path
        The 'install_labrecorder' directory in which LabRecorder is available.
    """
    src = Path(__file__).parent / "src" / "labrecorder"
    assert src.exists()  # sanity-check
    args = [
        "cmake",
        "-S",
        str(src),
        "-B",
        str(build_dir_labrecorder),
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_INSTALL_PREFIX={str(build_dir_labrecorder / 'install_labrecorder')}",
        f"-DLSL_INSTALL_ROOT={str(build_dir_labrecorder / 'install')}",
        "-DBUILD_GUI=OFF",
    ]
    if platform.system() == "Darwin":
        args.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=11")
    if platform.system() == "Linux":
        args.append("-DLSL_UNIXFOLDERS=ON")
    # On macOS, LabRecorder's CMakeLists.txt has a bundle fixup step that only applies
    # to GUI builds but isn't guarded by BUILD_GUI. Setting GITHUB_ACTIONS skips it.
    # See: https://github.com/labstreaminglayer/App-LabRecorder/pull/137
    env = os.environ.copy()
    if platform.system() == "Darwin":
        env["GITHUB_ACTIONS"] = "1"
    subprocess.run(args, check=True, env=env)
    subprocess.run(
        [
            "cmake",
            "--build",
            str(build_dir_labrecorder),
            "--config",
            "Release",
            "-j",
            "--target install",
        ],
        check=True,
        env=env,
    )
    return build_dir_labrecorder / "install_labrecorder"


class develop(_develop):  # noqa: D101
    def run(self) -> None:  # noqa: D102
        self.run_command("build_ext")
        super().run()


class bdist_wheel_abi3(bdist_wheel):  # noqa: D101
    def get_tag(self):  # noqa: D102
        python, abi, plat = super().get_tag()
        if python.startswith("cp") and not abi.endswith("t"):
            return "cp311", "abi3", plat
        return python, abi, plat


setup(
    cmdclass={
        "build_ext": build_ext,
        "bdist_wheel": bdist_wheel_abi3,
        "develop": develop,
    },
    distclass=BinaryDistribution,
)
