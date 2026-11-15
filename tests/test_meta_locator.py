# -*- coding: utf-8 -*-
"""Test del locator di META Post (nessuna dipendenza da META installato)."""

import os
import shutil
import tempfile
from unittest import mock

from meta_locator import describe_meta, find_meta_executable, version_of


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")
    return path


def _fake_install(root, version):
    """Crea una finta installazione con la struttura reale di BETA CAE."""
    launcher = _touch(os.path.join(root, f"meta_post_v{version}", "meta_post64.bat"))
    exe = _touch(os.path.join(root, f"shared_v{version}", "win64", "meta_post.exe"))
    return launcher, exe


def test_version_of_parses_install_path():
    assert version_of(r"C:\x\meta_post_v25.1.0\meta_post64.bat") == "25.1.0"
    assert version_of(r"C:\x\shared_v19.1.2\win64\meta_post.exe") == "19.1.2"
    assert version_of(r"C:\x\niente_da_parsare\meta_post.exe") == ""


def test_highest_version_wins_and_launcher_is_preferred():
    root = tempfile.mkdtemp(prefix="meta_install_")
    try:
        _fake_install(root, "19.1.2")
        launcher_25, _exe_25 = _fake_install(root, "25.1.0")

        found = find_meta_executable("auto", roots=[root])
        assert found, "doveva trovare META Post"
        assert version_of(found) == "25.1.0", found
        # a parita' di versione si preferisce il launcher .bat
        assert os.path.basename(found).lower() == "meta_post64.bat", found
        assert os.path.normcase(found) == os.path.normcase(launcher_25)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_explicit_config_path_wins():
    root = tempfile.mkdtemp(prefix="meta_install_")
    try:
        _fake_install(root, "19.1.2")
        custom = _touch(os.path.join(root, "custom", "mio_meta.bat"))
        assert find_meta_executable(custom, roots=[root]) == custom
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_env_var_is_used():
    root = tempfile.mkdtemp(prefix="meta_install_")
    try:
        launcher, _exe = _fake_install(root, "25.1.0")
        # niente fixture pytest: il runner interno (tests/run_tests.py) non le fornisce
        with mock.patch.dict(os.environ, {"META_POST_EXE": launcher}):
            assert find_meta_executable("auto", roots=[]) == launcher
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_missing_install_returns_empty():
    assert find_meta_executable("auto", roots=[]) == ""


def test_describe_meta_labels():
    root = tempfile.mkdtemp(prefix="meta_install_")
    try:
        launcher, _exe = _fake_install(root, "25.1.0")
        info = describe_meta(launcher)
        assert info["found"] is True
        assert info["version"] == "25.1.0"
        assert info["kind"] == "launcher"
        assert info["label"] == "META Post v25.1.0"

        missing = describe_meta("")
        assert missing["found"] is False
        assert missing["kind"] == "missing"
        assert "non trovato" in missing["label"]
    finally:
        shutil.rmtree(root, ignore_errors=True)
