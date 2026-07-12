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
    _patch_lsl_cmake(install_dir)
    _link_lsl_static_deps(build_dir_liblsl, install_dir)
    return install_dir


def _link_lsl_static_deps(build_dir_liblsl: Path, install_dir: Path) -> None:
    """Propagate liblsl's private link dependencies to the static 'LSL::lsl' target.

    liblsl (>= 1.17.5) attaches its dependencies to an internal object library and links
    it into 'lsl' through ``$<BUILD_INTERFACE:...>``, so none of them propagate to
    consumers of the exported static 'LSL::lsl' target. A shared liblsl bakes them into
    the library, but as we link liblsl statically 'LabRecorderCLI' must resolve them
    itself. We append the missing dependencies to the target's interface link libraries
    in the installed 'LSLConfig.cmake' (CMake then orders them correctly after liblsl):

    - pugixml, built as a separate static library (copied next to 'LSLConfig.cmake');
    - on Windows, the system libraries iphlpapi, winmm, mswsock and ws2_32.
    """
    candidates = list(install_dir.rglob("LSLConfig.cmake"))
    assert len(candidates) == 1, f"Expected 1 LSLConfig.cmake, found {len(candidates)}"
    lsl_config = candidates[0]
    pugixml = next(
        (
            elt
            for pattern in ("libpugixml.a", "pugixml.lib")
            for elt in build_dir_liblsl.rglob(pattern)
        ),
        None,
    )
    assert pugixml is not None, "Could not locate the pugixml static library."
    move(str(pugixml), str(lsl_config.parent / pugixml.name))
    content = (
        lsl_config.read_text()
        + "\n# pylabrecorder: propagate liblsl's private static deps (see setup.py).\n"
        + "set_property(TARGET LSL::lsl APPEND PROPERTY INTERFACE_LINK_LIBRARIES "
        + '"${CMAKE_CURRENT_LIST_DIR}/'
        + pugixml.name
        + '")\n'
    )
    if platform.system() == "Windows":
        content += (
            "set_property(TARGET LSL::lsl APPEND PROPERTY INTERFACE_LINK_LIBRARIES "
            "iphlpapi winmm mswsock ws2_32)\n"
        )
    lsl_config.write_text(content)


def _patch_lsl_cmake(install_dir: Path) -> None:
    """Neutralize liblsl bundling helpers for our statically-linked build.

    LabRecorder (>= 1.17.0) includes liblsl's LSLCMake.cmake and unconditionally calls
    ``LSL_install_liblsl()`` and ``LSL_codesign()`` to bundle and sign a *shared* liblsl
    (a framework on macOS, a shared library elsewhere). We link liblsl statically into
    'LabRecorderCLI', so there is nothing to bundle or sign; on macOS the bundling step
    would even recursively copy the build tree. Append no-op overrides to the installed
    LSLCMake.cmake so those calls become harmless.
    """
    candidates = list(install_dir.rglob("LSLCMake.cmake"))
    assert len(candidates) == 1, f"Expected 1 LSLCMake.cmake, found {len(candidates)}"
    lsl_cmake = candidates[0]
    lsl_cmake.write_text(
        lsl_cmake.read_text()
        + "\n# pylabrecorder: liblsl is statically linked, nothing to bundle or sign.\n"
        "function(LSL_install_liblsl)\nendfunction()\n"
        "function(LSL_codesign)\nendfunction()\n"
    )


def _build_labrecorder(build_dir_labrecorder: Path) -> Path:
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
        "-DLABRECORDER_BUILD_GUI=OFF",  # CLI-only, no Qt required
        "-DLSL_FETCH_IF_MISSING=OFF",  # use our vendored static liblsl, never fetch
    ]
    if platform.system() == "Darwin":
        args.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=11")
    subprocess.run(args, check=True)
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
