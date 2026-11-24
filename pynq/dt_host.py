#!/usr/bin/env python3
"""Host na płytce PYNQ (Zynq-7020): wysyła próbki testowe do akceleratora,
sprawdza zgodność z Pythonem i mierzy czas. Porównuje też z tym samym drzewem
liczonym programowo na procesorze ARM.

Na płytce, w jednym katalogu:  dt_v1.bit, dt_v1.hwh, test_data.npz (z gen/b12 albo gen/b8 dla v3)
    sudo python3 dt_host.py v1
"""
import sys
import time

import numpy as np
from pynq import Overlay

v = sys.argv[1] if len(sys.argv) > 1 else "v1"
npz = sys.argv[2] if len(sys.argv) > 2 else "test_data.npz"

ol = Overlay(f"dt_{v}.bit")
ip = ol.dt
d = np.load(npz)
X, y = d["x"], d["y"]
bits = int(d["bits"])
ref = d["ref_tree"] if v in ("v0", "v1") else d["ref_forest"]
n_feat = X.shape[1]
n_words = (n_feat * bits + 31) // 32

# Adresy rejestrów z pliku .hwh (PYNQ czyta je do ip_dict); domyślnie układ Vitis HLS.
regs = ol.ip_dict["dt"].get("registers", {})
ret_off = regs["ap_return"]["address_offset"] if "ap_return" in regs else 0x10
xp_offs = [r["address_offset"] for k, r in regs.items() if k.lower().startswith("xp")]
xp_off = min(xp_offs) if xp_offs else 0x18
print(f"ap_return @0x{ret_off:02X}, xp @0x{xp_off:02X} ({n_words} słów 32-bit)")


def classify_hw(x):
    packed = 0
    for f in range(n_feat):
        packed |= int(x[f]) << (f * bits)
    for i in range(n_words):
        ip.write(xp_off + 4 * i, (packed >> (32 * i)) & 0xFFFFFFFF)
    ip.write(0x00, 1)                    # ap_start
    while (ip.read(0x00) & 0x2) == 0:    # ap_done
        pass
    return ip.read(ret_off)


def classify_sw(x, nodes=d["tree_nodes"], depth=int(d["tree_depth"])):
    """To samo drzewo na ARM (odpowiednik v0 w programie)."""
    node = 0
    for _ in range(depth):
        w = int(nodes[node])
        thr, f = w & 0xFFFF, (w >> 16) & 0xFF
        node = (w >> 24) & 0xFF if x[f] <= thr else (w >> 32) & 0xFF
    return (int(nodes[node]) >> 40) & 0xFF


t0 = time.perf_counter()
hw = np.array([classify_hw(x) for x in X])
t_hw = (time.perf_counter() - t0) / len(X)

t0 = time.perf_counter()
sw = np.array([classify_sw(x) for x in X])
t_sw = (time.perf_counter() - t0) / len(X)

print(f"wariant {v}: {len(X)} próbek")
print(f"  niezgodności HW vs Python: {(hw != ref).sum()}")
print(f"  dokładność HW: {(hw == y).mean():.4f}")
print(f"  czas na próbkę: HW (z transferem AXI-Lite) {t_hw*1e6:.1f} us, SW na ARM {t_sw*1e6:.1f} us")
if v in ("v0", "v1"):
    print(f"  niezgodności SW vs Python: {(sw != ref).sum()}")
