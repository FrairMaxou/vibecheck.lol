# PyInstaller spec for VibeCheck.lol.
#
# Build:  .venv\Scripts\pyinstaller vibecheck.spec --noconfirm
# Output: dist/VibeCheck.exe  (single file, no console)
#
# The bundled data keeps its `vibecheck/...` prefix so config.PACKAGE_DIR
# resolves identically whether running from source or frozen.

block_cipher = None

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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # tray app: never show a console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="vibecheck/assets/logo.ico",
)
