# -*- coding: utf-8 -*-
"""
Scelta della modalita' di avvio (pura, senza import pesanti).

Regole:
    * nessun argomento  -> parte il launcher grafico (doppio clic / collegamento)
    * argomenti         -> riga di comando come sempre (--suite, --geometry-only, -w, ...)
    * --gui             -> interfaccia classica a caso singolo

La console viene nascosta solo nel caso del doppio clic (nessun argomento) e
solo nell'eseguibile: se si lancia l'exe da un terminale con dei flag, la
console e' dell'utente e non va toccata.
"""
from __future__ import annotations

import os


def started_without_arguments(argv) -> bool:
    """Vero quando non ci sono argomenti oltre al nome del programma."""
    return len(list(argv)) <= 1


def should_hide_console(argv, frozen: bool, stdin_isatty: bool = True) -> bool:
    """Nasconde la console solo se e' quella creata dal doppio clic sull'exe."""
    return bool(frozen) and started_without_arguments(argv)


def full_program_command(frozen: bool, executable: str, project_root: str) -> list:
    """Comando per aprire la GUI completa (tutte le funzioni) da un altro processo."""
    if frozen:
        return [executable, "--gui"]
    return [executable, os.path.join(project_root, "main.py"), "--gui"]
