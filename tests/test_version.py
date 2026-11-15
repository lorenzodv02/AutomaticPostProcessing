# -*- coding: utf-8 -*-
"""Coerenza della versione: formato SemVer, README e CLI allineati."""

import os
import re

from version import __version__

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_is_semver():
    assert SEMVER.match(__version__), __version__


def test_readme_mentions_the_version():
    """Se cambi versione devi aggiornare il README: evita release con documentazione sfasata."""
    with open(os.path.join(REPO_ROOT, "README.md"), "r", encoding="utf-8") as handle:
        readme = handle.read()
    assert "v%s" % __version__ in readme, "README non cita v%s" % __version__


def test_cli_exposes_version():
    """main.py deve dichiarare la versione: la stessa che finisce nella release."""
    with open(os.path.join(REPO_ROOT, "main.py"), "r", encoding="utf-8") as handle:
        source = handle.read()
    assert '--version' in source
    assert "from version import __version__" in source
