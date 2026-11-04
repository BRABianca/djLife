# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller: gera o djLife onedir com o nucleo enxuto.

Uso:
    pip install -e ".[packaging]"
    pyinstaller packaging/djlife.spec

Os extras pesados (analysis / ml / fingerprint / rekordbox / essentia) ficam de
fora do bundle e sao instalados on-demand no ambiente de quem usa (ver ADR-0016).
Os dados embutidos (schema.sql, genres.yaml, ui/assets) sao carregados em runtime
via `Path(__file__).with_name(...)`, por isso precisam seguir junto do pacote.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
PKG = ROOT / "src" / "djlife"

datas = [
    (str(PKG / "schema.sql"), "djlife"),
    (str(PKG / "genres.yaml"), "djlife"),
    (str(PKG / "ui" / "assets"), "djlife/ui/assets"),
]

excludes = [
    "torch",
    "transformers",
    "librosa",
    "soundfile",
    "essentia",
    "numpy",
    "scipy",
    "numba",
    "llvmlite",
    "pyacoustid",
    "pyrekordbox",
    "matplotlib",
    "PIL",
    "tkinter",
    "pytest",
]

a = Analysis(
    [str(PKG / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("djlife"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="djlife",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="djlife",
)
