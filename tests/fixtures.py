# -*- coding: utf-8 -*-
"""
Fixture di test: genera un caso Fluent `.cas`/`.dat` minimo ma REALE nel formato
binario che `fluent_parser` si aspetta.

Perche' non si possono usare file veri: i `.cas`/`.dat` di una monoposto pesano
centinaia di MB e sono ignorati da git. Questo caso sintetico contiene solo cio'
che serve al parser, con numeri calcolabili a mano:

  nodi (4, giacenti sul piano y = 0, normali verso -Y):
      n1 (0, 0, 0)   n2 (1, 0, 0)   n3 (0, 0, 1)   n4 (1, 0, 1)

  PID 2 "flat_floor": 2 triangoli  -> area totale 1.0 m^2
  PID 3 "venturi"   : 1 triangolo  -> area totale 0.5 m^2

  pressione relativa applicata: +100 Pa su entrambi i PID
  forza viscosa di parete sul solo PID 2: F_visc,x = -1 N per faccia

Attese (verificate in test_parser_synthetic.py):
  F_y = p * A * n_y = 100 * 1.0 * (-1) = -100 N  (PID 2)
                     100 * 0.5 * (-1) =  -50 N  (PID 3)
  tau_w,x = -F_visc,x / A_faccia = 1 / 0.5 = +2.0 Pa  -> flusso attaccato
  drag viscoso = |F_visc,x| = 2 N, drag di pressione = 0
"""

import os
import tempfile

import numpy as np

ZONE_TABLE = b"(39 (2 wall flat_floor))\n(39 (3 wall venturi))\n"

NODES = [
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0),
    (1.0, 0.0, 1.0),
]

ZONES = [
    {
        "id": 2,
        "name": "flat_floor",
        "faces": [(1, 2, 3), (2, 4, 3)],
        "pressure": 100.0,
        "f_visc": [(-1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)],
    },
    {
        "id": 3,
        "name": "venturi",
        "faces": [(1, 2, 3)],
        "pressure": 100.0,
        "f_visc": None,
    },
]


def _footer(section_id: int) -> bytes:
    """Footer di sezione binaria nel formato che il parser cerca."""
    return b")\nEnd of Binary Section " + str(section_id).encode("ascii") + b")\n"


def _node_section() -> bytes:
    payload = np.asarray(NODES, dtype=np.float32).tobytes()
    header = b"(2010 (1 1 4 0 0 3)("
    return header + b"\n" + payload + _footer(2010)


def _face_section(zone: dict) -> bytes:
    """Sezione facce: 5 interi per triangolo (n0, n1, n2, c0, c1)."""
    rows = []
    for index, (a, b, c) in enumerate(zone["faces"], start=1):
        rows.append([a, b, c, index, index + 10])
    payload = np.asarray(rows, dtype=np.int32).tobytes()
    first_face = 1
    last_face = len(rows)
    header = ("(2013 (%d %d %d 3 3)(" % (zone["id"], first_face, last_face)).encode("ascii")
    return header + b"\n" + payload + _footer(2013)


def _dat_section(sub_id: int, zone_id: int, vec_size: int, values) -> bytes:
    """Sezione dati .dat: (2300 (sub_id zid vec_size 0 0 first last) e payload."""
    array = np.asarray(values, dtype=np.float32)
    n_items = array.size // vec_size
    header = ("(2300 (%d %d %d 0 0 1 %d)(" % (sub_id, zone_id, vec_size, n_items)).encode("ascii")
    return header + b"\n" + array.tobytes() + _footer(2300)


def build_synthetic_case(folder: str = None):
    """
    Scrive `synthetic.cas` e `synthetic.dat` e restituisce
    (cas_path, dat_path, attese).
    """
    folder = folder or tempfile.mkdtemp(prefix="dsh_fixture_")
    os.makedirs(folder, exist_ok=True)

    cas_path = os.path.join(folder, "synthetic.cas")
    dat_path = os.path.join(folder, "synthetic.dat")

    cas_bytes = bytearray(ZONE_TABLE)
    cas_bytes += _node_section()
    for zone in ZONES:
        cas_bytes += _face_section(zone)
    with open(cas_path, "wb") as handle:
        handle.write(bytes(cas_bytes))

    dat_bytes = bytearray()
    for zone in ZONES:
        pressure = np.full(len(zone["faces"]), zone["pressure"], dtype=np.float32)
        dat_bytes += _dat_section(1, zone["id"], 1, pressure)
        if zone["f_visc"]:
            flat = [component for vector in zone["f_visc"] for component in vector]
            dat_bytes += _dat_section(19, zone["id"], 3, flat)
    with open(dat_path, "wb") as handle:
        handle.write(bytes(dat_bytes))

    expectations = {
        "nodes": len(NODES),
        "faces": sum(len(zone["faces"]) for zone in ZONES),
        "areas": {"flat_floor": 1.0, "venturi": 0.5},
        "total_area": 1.5,
        # F_y totale = somma di p*A*n_y con n_y = -1.0
        "vertical_force_N": -150.0,
        "drag_pressure_N": 0.0,
        # Solo il PID 2 ha la forza viscosa: 2 facce da |−1| N
        "drag_viscous_N": 2.0,
        "tau_flat_floor_Pa": 2.0,
    }
    return cas_path, dat_path, expectations
