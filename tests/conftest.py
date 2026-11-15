# -*- coding: utf-8 -*-
"""Rende importabili i moduli del progetto quando pytest gira da `tests/`."""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
