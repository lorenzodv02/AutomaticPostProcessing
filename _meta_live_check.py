# -*- coding: utf-8 -*-
"""Verifica reale: META Post viene riconosciuto e invocato dalla pipeline."""
import os
import shutil
import sys

WORK = r"C:\Users\lollo\Documents\deepseek-harness\default-workspace\tmp\meta_live"

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK, exist_ok=True)

from tests.fixtures import build_synthetic_case  # noqa: E402

build_synthetic_case(WORK)

from config_bridge import load_config  # noqa: E402
from meta_locator import describe_meta, find_meta_executable  # noqa: E402

exe = find_meta_executable("auto")
print("DETECT:", describe_meta(exe), flush=True)

loaded = load_config()
cfg = loaded[0] if isinstance(loaded, tuple) else loaded
cfg.setdefault("meta", {})
cfg["meta"]["executable_path"] = "auto"
cfg["meta"]["batch_timeout_s"] = 90

from meta_driver.launcher import run_postprocessing_session  # noqa: E402

result = run_postprocessing_session(cfg, WORK, force_meta_batch=True, log_fn=print)
print("META_EXECUTABLE:", result.get("meta_executable"), flush=True)
print("META_BATCH_EXECUTED:", result.get("meta_batch_executed"), flush=True)

images_dir = os.path.join(WORK, "output_diagnostics", "images_raw")
names = sorted(os.listdir(images_dir)) if os.path.isdir(images_dir) else []
print("IMMAGINI:", len(names), flush=True)
for name in names:
    if name.startswith(("05", "06", "07")):
        print("  ", name, flush=True)
