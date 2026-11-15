# -*- coding: utf-8 -*-
"""
Individuazione di BETA CAE META Post.

Modulo **leggero** (solo standard library) cosi' da poter essere testato in CI
senza numpy, matplotlib o META installato. La logica di scelta:

1. percorso esplicito dal config, se esiste;
2. variabili d'ambiente `META_POST_EXE` / `BETA_META_PATH`;
3. scansione dei percorsi standard di installazione, scegliendo la **versione
   piu' alta** e, a parita' di versione, il **launcher .bat** (che imposta
   l'ambiente BETA) prima dell'eseguibile nudo.
"""

import glob
import os
import re

ENV_VARS = ("META_POST_EXE", "BETA_META_PATH")

# In ordine di preferenza: il .bat imposta PATH e variabili BETA corrette.
LAUNCHERS = ("meta_post64.bat", "meta_post.bat")
EXECUTABLES = ("meta_post64.exe", "meta_post.exe")

_VERSION_RE = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?")


def _env_roots():
    """Percorsi standard in cui BETA CAE installa le sue applicazioni."""
    roots = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Apps", "BETA_CAE_Systems"))
        roots.append(os.path.join(local, "BETA_CAE_Systems"))
    for env in ("ProgramFiles", "ProgramFiles(x86)", "PROGRAMDATA"):
        base = os.environ.get(env)
        if base:
            roots.append(os.path.join(base, "BETA_CAE_Systems"))
    roots.extend((r"C:\BETA_CAE_Systems", r"D:\BETA_CAE_Systems", r"E:\BETA_CAE_Systems"))
    # dedup preservando l'ordine
    return [root for root in dict.fromkeys(roots) if root and os.path.isdir(root)]


def version_of(path) -> str:
    """
    Estrae la versione dalla path di installazione (es. ...\\meta_post_v25.1.0\\... -> "25.1.0").

    Restituisce "" se non c'e' un pattern riconoscibile.
    """
    match = _VERSION_RE.search(str(path or ""))
    if not match:
        return ""
    parts = [part for part in match.groups() if part is not None]
    return ".".join(parts)


def _version_key(version: str):
    parts = []
    for chunk in str(version or "").split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _is_launcher(path: str) -> bool:
    return os.path.basename(str(path)).lower() in {name.lower() for name in LAUNCHERS}


def find_meta_executable(configured_path: str = "auto", roots=None) -> str:
    """
    Percorso di META Post da usare ("" se non trovato).

    `roots` permette di sostituire i percorsi di ricerca nei test.
    """
    configured = str(configured_path or "").strip()
    if configured and configured.lower() != "auto" and os.path.isfile(configured):
        return configured

    for var in ENV_VARS:
        candidate = os.environ.get(var)
        if candidate and os.path.isfile(candidate):
            return candidate

    search_roots = _env_roots() if roots is None else [root for root in roots if os.path.isdir(root)]

    candidates = []
    for root in search_roots:
        for name in LAUNCHERS + EXECUTABLES:
            candidates.extend(glob.glob(os.path.join(root, "**", name), recursive=True))
    if not candidates:
        return ""

    def ranking(path: str):
        # prima la versione piu' recente, poi il launcher rispetto all'exe
        return (_version_key(version_of(path)), 1 if _is_launcher(path) else 0)

    return max(candidates, key=ranking)


def describe_meta(path) -> dict:
    """Informazioni leggibili sull'installazione trovata."""
    path = str(path or "")
    if not path:
        return {
            "path": "",
            "version": "",
            "kind": "missing",
            "found": False,
            "label": "META Post non trovato",
        }
    version = version_of(path)
    kind = "launcher" if _is_launcher(path) else "executable"
    label = "META Post" + (f" v{version}" if version else "")
    return {
        "path": path,
        "version": version,
        "kind": kind,
        "found": os.path.isfile(path),
        "label": label,
    }
