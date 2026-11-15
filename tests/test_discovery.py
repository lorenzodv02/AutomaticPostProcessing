# -*- coding: utf-8 -*-
"""
Test dell'individuazione dei file `.cas`/`.dat` (`file_discovery.py`).

Nascono da un caso reale: lanciando l'eseguibile senza argomenti, la pipeline
partiva sulla cartella corrente e prendeva il primo `*.dat` in ordine alfabetico,
che sul Desktop era la licenza di BETA CAE (`BK120908EDUNIVERSITYED_license.dat`).
"""

import os
import shutil
import tempfile

from file_discovery import NoCaseFilesFound, case_files_in, discover_cas_dat, try_discover


def _temp_dir():
    return tempfile.mkdtemp(prefix="dsh_discovery_")


def _write(folder, name, payload=b"contenuto finto"):
    path = os.path.join(folder, name)
    with open(path, "wb") as handle:
        handle.write(payload)
    return path


def test_license_dat_is_ignored_and_pair_is_found():
    folder = _temp_dir()
    try:
        _write(folder, "BK120908EDUNIVERSITYED_license.dat")
        _write(folder, "caso.cas")
        _write(folder, "caso.dat")

        cas_file, dat_file = discover_cas_dat(folder)
        assert os.path.basename(cas_file) == "caso.cas"
        assert os.path.basename(dat_file) == "caso.dat"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_missing_cas_raises_actionable_message():
    folder = _temp_dir()
    try:
        _write(folder, "BK120908EDUNIVERSITYED_license.dat")

        raised = False
        try:
            discover_cas_dat(folder)
        except NoCaseFilesFound as exc:
            raised = True
            message = str(exc)
            assert ".cas" in message
            assert "--workspace" in message
            assert "GUI" in message
            # deve dire anche cosa ha trovato, per orientare l'utente
            assert "license.dat" in message
        assert raised, "la scoperta doveva fallire con NoCaseFilesFound"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_dat_is_paired_by_stem():
    folder = _temp_dir()
    try:
        _write(folder, "a.cas")
        _write(folder, "b.dat")
        _write(folder, "a.dat")

        cas_file, dat_file = discover_cas_dat(folder)
        assert os.path.basename(cas_file) == "a.cas"
        assert os.path.basename(dat_file) == "a.dat", dat_file
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_h5_and_gz_are_ignored():
    """Solo .cas e .dat: .cas.h5/.gz non sono leggibili dal parser, quindi si ignorano."""
    folder = _temp_dir()
    try:
        _write(folder, "caso.cas.h5")
        _write(folder, "caso.dat.gz")
        cas_files, dat_files = case_files_in(folder)
        assert cas_files == [], cas_files
        assert dat_files == [], dat_files

        raised = False
        try:
            discover_cas_dat(folder)
        except NoCaseFilesFound:
            raised = True
        assert raised, "senza .cas/.dat la scoperta deve fallire"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_only_dat_files_are_reported_as_such():
    folder = _temp_dir()
    try:
        _write(folder, "uno.dat")
        _write(folder, "due.dat")
        cas_files, dat_files = case_files_in(folder)
        assert cas_files == []
        assert len(dat_files) == 2
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_dat_is_optional():
    folder = _temp_dir()
    try:
        _write(folder, "solo_cas.cas")
        cas_file, dat_file = discover_cas_dat(folder)
        assert os.path.basename(cas_file) == "solo_cas.cas"
        assert dat_file is None
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ------------------------------------------------------------------------------
# Variante senza eccezioni, usata dalla GUI nei callback Tkinter
# ------------------------------------------------------------------------------
def test_try_discover_does_not_raise_when_cas_is_missing():
    """
    La GUI chiama la scoperta dentro un callback `after`: se sollevasse, Tkinter
    stamperebbe "Exception in Tkinter callback" su stderr e l'utente non
    vedrebbe nulla. `try_discover` restituisce invece il messaggio.
    """
    folder = _temp_dir()
    try:
        _write(folder, "BK120908EDUNIVERSITYED_license.dat")

        cas_file, dat_file, error = try_discover(folder)
        assert cas_file is None
        assert dat_file is None
        assert error and ".cas" in error
        assert "license.dat" in error
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_try_discover_returns_pair_without_error():
    folder = _temp_dir()
    try:
        _write(folder, "caso.cas")
        _write(folder, "caso.dat")

        cas_file, dat_file, error = try_discover(folder)
        assert error is None
        assert os.path.basename(cas_file) == "caso.cas"
        assert os.path.basename(dat_file) == "caso.dat"
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    # e la variante che solleva continua a comportarsi come prima
    folder = _temp_dir()
    try:
        try:
            discover_cas_dat(folder)
        except NoCaseFilesFound:
            pass
        else:
            raise AssertionError("discover_cas_dat doveva sollevare")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
