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
    # Brand identity: icona PNG, monogramma UC, logotipo e font Roboto (OFL).
    # I font vengono registrati a runtime come privati del processo.
    ("assets/FS-MetaPostDiag.png", "assets"),
    ("assets/uc-monogram-white.png", "assets"),
    ("assets/uc-monogram-navy.png", "assets"),
    ("assets/wordmark-white.png", "assets"),
    ("assets/fonts", "assets/fonts"),
    # Aero Suite dentro l'exe: orchestratore, template brandizzato e motori.
    # `--suite` li importa da _MEIPASS, senza Python installato a parte.
    ("suite/aero_suite.py", "suite"),
    ("suite/brand_theme.py", "suite"),
    ("suite/suite_template.html", "suite"),
    ("tools/design_explorer.py", "tools"),
    ("tools/recombination.py", "tools"),
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
