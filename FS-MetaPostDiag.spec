# -*- mode: python ; coding: utf-8 -*-
"""
Configurazione PyInstaller per la build Windows di FS-MetaPostDiag.

Uso:
    python -m PyInstaller --noconfirm --clean FS-MetaPostDiag.spec

Produce un singolo eseguibile `dist/FS-MetaPostDiag.exe` che non richiede
Python installato. `config.yaml` e il worker di META sono inclusi come dati:
senza il primo l'exe girerebbe con i default interni, senza il secondo la
sessione `.ses` generata punterebbe a un file inesistente.
"""

datas = [
    ("config.yaml", "."),
    ("meta_driver/meta_post_worker.py", "meta_driver"),
    # Icona della finestra Tkinter (quella dell'exe la imposta `icon=` qui sotto)
    ("assets/FS-MetaPostDiag.ico", "assets"),
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "_pytest", "tkinter.test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FS-MetaPostDiag",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/FS-MetaPostDiag.ico",
)
