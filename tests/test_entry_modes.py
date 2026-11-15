# -*- coding: utf-8 -*-
"""Scelta della modalita' di avvio: doppio clic -> launcher, flag -> CLI."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from meta_driver.entry_modes import should_hide_console, started_without_arguments


def test_no_arguments_means_launcher():
    assert started_without_arguments(["FS-MetaPostDiag.exe"]) is True
    assert started_without_arguments(["main.py"]) is True
    assert started_without_arguments(["FS-MetaPostDiag.exe", "--gui"]) is False
    assert started_without_arguments(["FS-MetaPostDiag.exe", "-w", "C:/caso"]) is False
    assert started_without_arguments(["FS-MetaPostDiag.exe", "--suite"]) is False


def test_console_hidden_only_on_double_click_of_the_exe():
    assert should_hide_console(["FS-MetaPostDiag.exe"], frozen=True) is True
    assert should_hide_console(["FS-MetaPostDiag.exe"], frozen=False) is False
    assert should_hide_console(["FS-MetaPostDiag.exe", "--gui"], frozen=True) is False
