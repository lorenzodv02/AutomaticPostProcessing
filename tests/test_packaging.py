# -*- coding: utf-8 -*-
"""
Test del contratto di packaging.

Non eseguono PyInstaller (troppo lento per la CI): verificano che lo spec
continui a includere i file senza i quali l'eseguibile funziona male.
"""

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_PATH = os.path.join(REPO_ROOT, "FS-MetaPostDiag.spec")


def _spec() -> str:
    with open(SPEC_PATH, "r", encoding="utf-8") as handle:
        return handle.read()


def test_spec_exists():
    assert os.path.isfile(SPEC_PATH)


def test_spec_bundles_config_and_meta_worker():
    """Senza config.yaml l'exe userebbe i default; senza il worker la .ses sarebbe rotta."""
    spec = _spec()
    assert "config.yaml" in spec
    assert "meta_post_worker.py" in spec


def test_spec_builds_console_onefile():
    spec = _spec()
    assert "console=True" in spec
    # In PyInstaller 6 la variante onefile non ha lo stage COLLECT
    assert "COLLECT" not in spec


def test_spec_excludes_test_tooling():
    spec = _spec()
    assert "pytest" in spec


def test_spec_uses_the_icon():
    """L'exe deve avere l'icona del team, non quella generica di PyInstaller."""
    spec = _spec()
    assert "assets/FS-MetaPostDiag.ico" in spec
    assert "icon=None" not in spec


def test_icon_file_is_a_valid_multi_size_ico():
    """Controllo del formato ICO senza dipendenze (Pillow non e' in CI)."""
    import struct

    icon_path = os.path.join(REPO_ROOT, "assets", "FS-MetaPostDiag.ico")
    assert os.path.isfile(icon_path)
    with open(icon_path, "rb") as handle:
        header = handle.read(6)
    reserved, kind, count = struct.unpack("<HHH", header)
    assert reserved == 0, reserved
    assert kind == 1, ("non e' un ICO", kind)
    assert count >= 5, ("misure dichiarate", count)
    assert os.path.isfile(os.path.join(REPO_ROOT, "assets", "FS-MetaPostDiag.png"))
