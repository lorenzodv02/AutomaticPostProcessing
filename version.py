# -*- coding: utf-8 -*-
"""
Versione del progetto — unica sorgente di verità.

`tests/test_version.py` verifica che il numero sia in formato SemVer e che il
README (e la CLI) lo riportino: così non si può creare una release senza
aggiornare la documentazione.
"""

__version__ = "1.11.4"

__all__ = ["__version__"]
