# PyInstaller spec for VibeCheck.lol.
#
# Build:  .venv\Scripts\pyinstaller vibecheck.spec --noconfirm
# Output: dist/VibeCheck.exe  (single file, no console)
#
# The bundled data keeps its `vibecheck/...` prefix so config.PACKAGE_DIR
# resolves identically whether running from source or frozen.

import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

block_cipher = None

# Read APP_VERSION as text rather than importing config: importing it runs the
# data-folder migration at module level, which has no business happening on a
# build machine.
_version = re.search(
    r'^APP_VERSION = "([^"]+)"',
    (Path(SPECPATH) / "vibecheck" / "config.py").read_text(encoding="utf-8"),
    re.M,
).group(1)
# Digits only: a version resource takes four integers, so a prerelease suffix
# like "1.0.0-rc1" must not take the whole build down with a ValueError.
_fields = [int(n) for n in re.findall(r"\d+", _version)][:4]
_vtuple = tuple(_fields + [0] * (4 - len(_fields)))

# A Windows version resource. Without it the exe carries no publisher, product
# name or version at all — and an unsigned, metadata-less single-file binary is
# exactly the shape Defender's ML model scores as Trojan:Win32/Wacatac.B!ml.
# It doesn't replace code signing, it just stops us looking gratuitously
# anonymous. Sourced from APP_VERSION so release-please keeps it in step.
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_vtuple,
        prodvers=_vtuple,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,  # VOS_NT_WINDOWS32
        fileType=0x1,  # VFT_APP
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",  # US English, Unicode
                    [
                        StringStruct("CompanyName", "VibeCheck.lol"),
                        StringStruct(
                            "FileDescription",
                            "VibeCheck — rate how much fun your League games were",
                        ),
                        StringStruct("FileVersion", _version),
                        StringStruct("InternalName", "VibeCheck"),
                        StringStruct(
                            "LegalCopyright",
                            "Open source — github.com/FrairMaxou/vibecheck.lol",
                        ),
                        StringStruct("OriginalFilename", "VibeCheck.exe"),
                        StringStruct("ProductName", "VibeCheck"),
                        StringStruct("ProductVersion", _version),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x409, 1200])]),
    ],
)

a = Analysis(
    ["run_vibecheck.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("vibecheck/web", "vibecheck/web"),
        ("vibecheck/assets", "vibecheck/assets"),
    ],
    hiddenimports=[
        # uvicorn resolves these by string at runtime, so PyInstaller's static
        # analysis can't see them.
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="VibeCheck",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # Never turn UPX back on. A UPX-packed binary is one of the strongest
    # signals antivirus heuristics have, and we already ship unsigned — the
    # ~10 MB it would save is not worth the extra false positives. (It was
    # never actually applied in CI, since the runner has no upx binary.)
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # tray app: never show a console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="vibecheck/assets/logo.ico",
    version=version_info,
)
