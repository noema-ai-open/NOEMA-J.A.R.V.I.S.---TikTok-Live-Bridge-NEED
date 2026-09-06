from pathlib import Path


repo = Path(SPECPATH)

a = Analysis(
    [str(repo / "app" / "desktop.py")],
    pathex=[str(repo)],
    binaries=[],
    datas=[(str(repo / "frontend"), "frontend")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NOEMA-JARVIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
