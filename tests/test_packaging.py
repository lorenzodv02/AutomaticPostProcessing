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
