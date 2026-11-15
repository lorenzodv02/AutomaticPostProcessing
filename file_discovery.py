# -*- coding: utf-8 -*-
"""
Individuazione della coppia `.cas` / `.dat` nella cartella di lavoro.

Modulo volutamente leggero (solo standard library): e' testabile in CI, dove
matplotlib/scipy non sono installati, e ospita la logica di validazione che
prima stava in `meta_driver/launcher.py`.

Perche' serve una validazione esplicita: filtrando per sola estensione, una
cartella come il Desktop puo' contenere file che si chiamano `*.dat` senza essere
dataset CFD (tipico: la licenza di BETA CAE `*_license.dat`). Il vecchio codice
prendeva il primo `.dat` in ordine alfabetico e poi falliva con un traceback.
"""

import glob
import os

__all__ = ["NoCaseFilesFound", "discover_cas_dat", "try_discover", "case_files_in", "ignored_files"]

CAS_PATTERNS = ("*.cas", "*.cas.h5", "*.cas.gz")
DAT_PATTERNS = ("*.dat", "*.dat.h5", "*.dat.gz")

# Nomi che condividono l'estensione ma non sono dataset CFD
DENY_SUBSTRINGS = ("license", "licence", ".lic", "licenza")

_CAS_SUFFIXES = (".cas.h5", ".cas.gz", ".cas")
_DAT_SUFFIXES = (".dat.h5", ".dat.gz", ".dat")


class NoCaseFilesFound(RuntimeError):
    """Nessun file `.cas` utilizzabile nella cartella indicata."""


def _stem(path: str) -> str:
    """Nome del file senza l'estensione CFD (gestisce .cas.h5 e .dat.gz)."""
    base = os.path.basename(path)
    lowered = base.lower()
    for suffix in _CAS_SUFFIXES + _DAT_SUFFIXES:
        if lowered.endswith(suffix):
            return base[: -len(suffix)]
    return os.path.splitext(base)[0]


def _reject(name: str) -> bool:
    lowered = name.lower()
    return any(bad in lowered for bad in DENY_SUBSTRINGS)


def _collect(folder: str, patterns) -> list:
    """Raccoglie i file che rispettano i pattern, scartando i falsi positivi."""
    found = []
    for pattern in patterns:
        for path in sorted(glob.glob(os.path.join(folder, pattern))):
            if os.path.isdir(path) or _reject(os.path.basename(path)):
                continue
            if path not in found:
                found.append(path)
    return found


def case_files_in(folder: str):
    """Restituisce `(cas, dat)` candidati nella cartella (un livello di sottocartelle)."""
    cas_files = _collect(folder, CAS_PATTERNS)
    dat_files = _collect(folder, DAT_PATTERNS)

    if not cas_files:
        for pattern in CAS_PATTERNS:
            for path in sorted(glob.glob(os.path.join(folder, "*", pattern))):
                if not os.path.isdir(path) and not _reject(os.path.basename(path)) and path not in cas_files:
                    cas_files.append(path)
    if not dat_files:
        for pattern in DAT_PATTERNS:
            for path in sorted(glob.glob(os.path.join(folder, "*", pattern))):
                if not os.path.isdir(path) and not _reject(os.path.basename(path)) and path not in dat_files:
                    dat_files.append(path)
    return cas_files, dat_files


def ignored_files(folder: str) -> list:
    """
    File con estensione CFD ma scartati perche' non sono dataset (es. licenze).

    Servono solo per il messaggio d'errore: dire "ho ignorato la licenza" e'
    molto piu' utile che dire soltanto "nessun .cas trovato".
    """
    skipped = []
    for pattern in CAS_PATTERNS + DAT_PATTERNS:
        for path in sorted(glob.glob(os.path.join(folder, pattern))):
            if os.path.isdir(path):
                continue
            if _reject(os.path.basename(path)) and path not in skipped:
                skipped.append(path)
    return skipped


def _missing_case_message(folder: str, dat_files: list) -> str:
    """Messaggio d'errore per il caso "nessun .cas", con cosa e' stato trovato/ignorato."""
    hint = ""
    if dat_files:
        elenco = ", ".join(os.path.basename(path) for path in dat_files[:3])
        hint = (
            "\n  Ho trovato %d file .dat (%s) ma nessun .cas: servono entrambi."
            % (len(dat_files), elenco)
        )
    skipped = ignored_files(folder)
    if skipped:
        elenco_skip = ", ".join(os.path.basename(path) for path in skipped[:3])
        hint += (
            "\n  Ho ignorato %d file con estensione CFD ma non-dataset (es. %s)."
            % (len(skipped), elenco_skip)
        )
    return (
        "Nessun file .cas trovato in '%s'.%s\n"
        "  Indica la cartella del caso CFD con --workspace (-w) oppure scegli la cartella dalla GUI (--gui).\n"
        "  Nota: il parser legge il formato binario .cas/.dat di Fluent; i file di licenza non sono dataset."
        % (os.path.abspath(folder), hint)
    )


def try_discover(workspace_dir: str):
    """
    Variante che NON solleva: restituisce `(cas, dat, messaggio_errore)`.

    E' pensata per le interfacce grafiche: un'eccezione dentro un callback
    Tkinter (`after`) diventa un `Exception in Tkinter callback` su stderr, non
    gestito e invisibile all'utente. La GUI usa questa variante e mostra il
    messaggio nella console dell'app; la CLI usa `discover_cas_dat` e stampa
    l'errore con codice di uscita.
    """
    folder = workspace_dir or "."
    cas_files, dat_files = case_files_in(folder)

    if not cas_files:
        return None, None, _missing_case_message(folder, dat_files)

    cas_file = cas_files[0]
    dat_file = None
    cas_stem = _stem(cas_file).lower()
    for candidate in dat_files:
        if _stem(candidate).lower() == cas_stem:
            dat_file = candidate
            break
    if dat_file is None and dat_files:
        dat_file = dat_files[0]
    return cas_file, dat_file, None


def discover_cas_dat(workspace_dir: str):
    """
    Individua la coppia `(cas, dat)`; solleva `NoCaseFilesFound` se il `.cas` manca.

    Regole: `.cas` obbligatorio, `.dat` preferito con lo stesso nome base, file
    che sembrano licenze ignorati, `.dat` opzionale. Per la versione senza
    eccezioni (GUI) vedi `try_discover`.
    """
    cas_file, dat_file, error = try_discover(workspace_dir)
    if error:
        raise NoCaseFilesFound(error)
    return cas_file, dat_file
