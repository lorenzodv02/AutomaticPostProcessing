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

__all__ = ["NoCaseFilesFound", "discover_cas_dat", "case_files_in"]

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


def discover_cas_dat(workspace_dir: str):
    """
    Individua la coppia di file da analizzare.

    Regole:
      * il `.cas` e' obbligatorio: senza di esso solleva `NoCaseFilesFound` con
        un messaggio che dice cosa fare (prima si arrivava a un FileNotFoundError);
      * il `.dat` viene preferito con lo stesso nome base del `.cas`
        (`caso.cas` + `caso.dat`), altrimenti si usa il primo `.dat` valido;
      * i file che sembrano licenze o autre non-dataset sono ignorati.

    Restituisce `(cas_path, dat_path)`; `dat_path` puo' essere `None` (il parser
    tollera l'assenza del `.dat` e usa pressione nulla).
    """
    folder = workspace_dir or "."
    cas_files, dat_files = case_files_in(folder)

    if not cas_files:
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
        raise NoCaseFilesFound(
            "Nessun file .cas trovato in '%s'.%s\n"
            "  Indica la cartella del caso CFD con --workspace (-w) oppure scegli la cartella dalla GUI (--gui).\n"
            "  Nota: il parser legge il formato binario .cas/.dat di Fluent; i file di licenza non sono dataset."
            % (os.path.abspath(folder), hint)
        )

    cas_file = cas_files[0]
    dat_file = None

    cas_stem = _stem(cas_file).lower()
    for candidate in dat_files:
        if _stem(candidate).lower() == cas_stem:
            dat_file = candidate
            break
    if dat_file is None and dat_files:
        dat_file = dat_files[0]

    return cas_file, dat_file
