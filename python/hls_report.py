#!/usr/bin/env python3
"""Zbiera wyniki syntezy HLS (csynth.xml) wszystkich wariantów do jednej tabeli.

Uruchom po run_hls.tcl:   python3 python/hls_report.py
Wynik: results/hls_results.md (gotowa tabela do sprawozdania i prezentacji)
"""
import glob
import json
import os
import xml.etree.ElementTree as ET

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DESC = {
    "v0": "drzewo w ROM, węzeł po węźle (12 bit)",
    "v1": "wszystkie porównania naraz (12 bit)",
    "v2": "las 8 drzew + głosowanie (12 bit)",
    "v3": "las 8 drzew + głosowanie (8 bit)",
}
MODEL = {"v0": "b12", "v1": "b12", "v2": "b12", "v3": "b8"}


def txt(root, *paths):
    for p in paths:
        e = root.find(p)
        if e is not None and e.text is not None:
            return e.text.strip()
    return "?"


def main():
    rows = []
    for v in ["v0", "v1", "v2", "v3"]:
        files = glob.glob(os.path.join(ROOT, "hls", f"proj_{v}", "*", "syn", "report", "csynth.xml"))
        if not files:
            print(f"{v}: brak raportu (nie uruchomiono syntezy?)")
            continue
        r = ET.parse(files[0]).getroot()
        pe, ae = "PerformanceEstimates", "AreaEstimates/Resources"
        lat = txt(r, f"{pe}/SummaryOfOverallLatency/Worst-caseLatency",
                  f"{pe}/SummaryOfOverallLatency/Best-caseLatency")
        ii = txt(r, f"{pe}/SummaryOfOverallLatency/Interval-max",
                 f"{pe}/SummaryOfOverallLatency/Interval-min")
        clk = txt(r, f"{pe}/SummaryOfTimingAnalysis/EstimatedClockPeriod")
        res = {k: txt(r, f"{ae}/{k}") for k in ["BRAM_18K", "FF", "LUT"]}
        res["DSP"] = txt(r, f"{ae}/DSP", f"{ae}/DSP48E")
        acc = "?"
        sj = os.path.join(ROOT, "gen", MODEL[v], "summary.json")
        if os.path.exists(sj):
            s = json.load(open(sj))
            acc = s["tree"]["accuracy"] if v in ("v0", "v1") else s["forest"]["accuracy_hard_vote"]
            acc = f"{acc:.4f}"
        rows.append(f"| {v} | {DESC[v]} | {lat} | {ii} | {clk} | {res['LUT']} | {res['FF']} | "
                    f"{res['BRAM_18K']} | {res['DSP']} | {acc} |")

    out = ["# Wyniki syntezy HLS (xc7z020, zegar 10 ns)\n",
           "| wariant | opis | opóźnienie [takty] | II [takty] | okres zegara [ns] | LUT | FF | BRAM18K | DSP | dokładność |",
           "|---|---|---|---|---|---|---|---|---|---|"] + rows
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    path = os.path.join(ROOT, "results", "hls_results.md")
    open(path, "w").write("\n".join(out) + "\n")
    print("\n".join(out))
    print(f"-> {path}")


if __name__ == "__main__":
    main()
