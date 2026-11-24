#!/usr/bin/env python3
"""
Temat 14 ESL: drzewo decyzyjne i las losowy w sprzęcie.

Skrypt:
  1. wczytuje zbiór (domyślnie Breast Cancer Wisconsin z scikit-learn),
  2. kwantyzuje cechy do liczb całkowitych bez znaku o szerokości --bits
     (min-max na zbiorze uczącym, dokładnie to samo zrobi host przed wysłaniem do FPGA),
  3. trenuje DecisionTreeClassifier i RandomForestClassifier NA CECHACH CAŁKOWITYCH,
  4. eksportuje model i dane testowe do nagłówków C++ dla Vitis HLS.

Dlaczego trenujemy na liczbach całkowitych?
  Progi w sklearn to środki między sąsiednimi wartościami cechy, czyli k + 0.5.
  Dla całkowitego x:  x <= k + 0.5  <=>  x <= k.  Zapisujemy więc próg floor(t)
  i porównanie w sprzęcie jest DOKŁADNIE takie samo jak w sklearn (zgodność bit w bit).

Użycie:
  python3 train_export.py                       # 12 bitów -> gen/b12
  python3 train_export.py --bits 8              # 8 bitów  -> gen/b8
  python3 train_export.py --sweep               # tabele: dokładność vs bity i vs głębokość
"""
import argparse
import json
import os

import numpy as np
from sklearn import datasets
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------- dane
def load_dataset(name):
    loaders = {
        "breast_cancer": datasets.load_breast_cancer,
        "wine": datasets.load_wine,
        "iris": datasets.load_iris,
        "digits": datasets.load_digits,
    }
    d = loaders[name]()
    return d.data.astype(np.float64), d.target.astype(np.int64)


def quantize(x, lo, hi, bits):
    """min-max -> [0, 2^bits - 1], zaokrąglenie, obcięcie (dla testu wartości spoza zakresu)."""
    qmax = (1 << bits) - 1
    span = np.where(hi > lo, hi - lo, 1.0)
    q = np.round((x - lo) / span * qmax)
    return np.clip(q, 0, qmax).astype(np.int64)


def prepare(dataset, bits, test_size, seed):
    X, y = load_dataset(dataset)
    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y)
    lo, hi = Xtr.min(axis=0), Xtr.max(axis=0)
    return quantize(Xtr, lo, hi, bits), quantize(Xte, lo, hi, bits), ytr, yte, lo, hi


# ---------------------------------------------------------------- model
def tree_tables(est):
    """Zamienia sklearn Tree na tablice: węzły (do wariantu sekwencyjnego)
    i ścieżki do liści (do wariantu równoległego)."""
    t = est.tree_
    n = t.node_count
    feat = np.zeros(n, dtype=np.int64)
    thr = np.zeros(n, dtype=np.int64)
    left = np.zeros(n, dtype=np.int64)
    right = np.zeros(n, dtype=np.int64)
    cls = np.zeros(n, dtype=np.int64)
    for i in range(n):
        cls[i] = int(np.argmax(t.value[i][0]))  # klasa większościowa w węźle
        if t.children_left[i] == -1:          # liść: wskazuje sam na siebie
            left[i] = right[i] = i
        else:
            feat[i] = t.feature[i]
            thr[i] = int(np.floor(t.threshold[i]))  # x <= k+0.5  <=>  x <= k
            left[i] = t.children_left[i]
            right[i] = t.children_right[i]

    # ścieżki do liści: lista (węzeł, kierunek); kierunek 1 = w lewo (x <= próg)
    leaves = []

    def walk(i, path):
        if t.children_left[i] == -1:
            leaves.append((path, cls[i]))
            return
        walk(t.children_left[i], path + [(i, 1)])
        walk(t.children_right[i], path + [(i, 0)])

    walk(0, [])
    depth = max(1, max(len(p) for p, _ in leaves))
    return dict(n_nodes=n, feat=feat, thr=thr, left=left, right=right, cls=cls,
                leaves=leaves, depth=depth)


def hard_vote(forest, X, n_classes):
    """Głosowanie większościowe drzew lasu (remis -> mniejszy numer klasy).
    Tak liczy sprzęt. sklearn RandomForest uśrednia prawdopodobieństwa (soft voting),
    więc zgodność z forest.predict raportujemy osobno."""
    votes = np.zeros((X.shape[0], n_classes), dtype=np.int64)
    for est in forest.estimators_:
        p = est.predict(X.astype(np.float32)).astype(np.int64)
        votes[np.arange(len(p)), p] += 1
    return np.argmax(votes, axis=1)


# ---------------------------------------------------------------- eksport C++
def c_array(name, ctype, arr):
    arr = np.asarray(arr)
    dims = "".join(f"[{s}]" for s in arr.shape)

    def fmt(a):
        if a.ndim == 1:
            return "{" + ", ".join(str(int(v)) for v in a) + "}"
        return "{\n  " + ",\n  ".join(fmt(s) for s in a) + "}"

    return f"const {ctype} {name}{dims} = {fmt(arr)};\n"


def node_words(tt):
    """Węzeł spakowany w jedno 64-bitowe słowo pamięci (wariant v0):
    [15:0] próg, [23:16] cecha, [31:24] lewy, [39:32] prawy, [47:40] klasa."""
    w = []
    for i in range(tt["n_nodes"]):
        v = (int(tt["thr"][i]) & 0xFFFF) | (int(tt["feat"][i]) << 16) | \
            (int(tt["left"][i]) << 24) | (int(tt["right"][i]) << 32) | (int(tt["cls"][i]) << 40)
        w.append(v)
    return w


def path_tables(tt, n_leaves_pad, depth_pad):
    pn = np.zeros((n_leaves_pad, depth_pad), dtype=np.int64)
    pd = np.zeros((n_leaves_pad, depth_pad), dtype=np.int64)
    plen = np.zeros(n_leaves_pad, dtype=np.int64)
    pcls = np.zeros(n_leaves_pad, dtype=np.int64)
    valid = np.zeros(n_leaves_pad, dtype=np.int64)
    for l, (path, c) in enumerate(tt["leaves"]):
        for k, (node, d) in enumerate(path):
            pn[l, k], pd[l, k] = node, d
        plen[l], pcls[l], valid[l] = len(path), c, 1
    return pn, pd, plen, pcls, valid


def pad(a, n):
    out = np.zeros(n, dtype=np.int64)
    out[:len(a)] = a
    return out


def export(outdir, bits, n_features, n_classes, tree, forest, Xte, yte, ref_tree, ref_forest, meta):
    os.makedirs(outdir, exist_ok=True)
    tt = tree_tables(tree)
    ft = [tree_tables(e) for e in forest.estimators_]
    T = len(ft)
    f_nodes = max(t["n_nodes"] for t in ft)
    f_leaves = max(len(t["leaves"]) for t in ft)
    f_depth = max(t["depth"] for t in ft)
    assert max(tt["n_nodes"], f_nodes) <= 255 and n_features <= 255, "indeksy mają 8 bitów"

    h = []
    h.append("// WYGENEROWANE przez python/train_export.py - nie edytować ręcznie\n")
    h.append("#ifndef MODEL_H\n#define MODEL_H\n\n")
    h.append(f"// zbiór: {meta['dataset']}, cechy {bits}-bitowe, "
             f"drzewo max_depth={meta['tree_depth']}, las {T} drzew max_depth={meta['forest_depth']}\n")
    h.append(f"#define FEAT_BITS {bits}\n#define N_FEATURES {n_features}\n#define N_CLASSES {n_classes}\n\n")

    # --- pojedyncze drzewo
    pn, pd, plen, pcls, _ = path_tables(tt, len(tt["leaves"]), tt["depth"])
    h.append(f"// ---- drzewo: {tt['n_nodes']} węzłów, {len(tt['leaves'])} liści, głębokość {tt['depth']}\n")
    h.append(f"#define TREE_N_NODES {tt['n_nodes']}\n#define TREE_N_LEAVES {len(tt['leaves'])}\n"
             f"#define TREE_DEPTH {tt['depth']}\n")
    h.append("// v0: węzeł = jedno słowo 64-bit [15:0]próg [23:16]cecha [31:24]lewy [39:32]prawy [47:40]klasa\n")
    h.append("const unsigned long long tree_nodes[TREE_N_NODES] = {"
             + ", ".join(f"0x{w:012X}ULL" for w in node_words(tt)) + "};\n")
    h.append("// v1: porównania w każdym węźle + ścieżki do liści (kierunek 1 = x <= próg)\n")
    h.append(c_array("tree_feature", "unsigned char", tt["feat"]))
    h.append(c_array("tree_threshold", "unsigned short", tt["thr"]))
    h.append(c_array("tree_path_node", "unsigned char", pn))
    h.append(c_array("tree_path_dir", "unsigned char", pd))
    h.append(c_array("tree_path_len", "unsigned char", plen))
    h.append(c_array("tree_leaf_class", "unsigned char", pcls))

    # --- las
    h.append(f"\n// ---- las: {T} drzew, maks. {f_nodes} węzłów / {f_leaves} liści / głębokość {f_depth}\n")
    h.append(f"#define FOREST_N_TREES {T}\n#define FOREST_N_NODES {f_nodes}\n"
             f"#define FOREST_N_LEAVES {f_leaves}\n#define FOREST_DEPTH {f_depth}\n")
    F_feat = np.stack([pad(t["feat"], f_nodes) for t in ft])
    F_thr = np.stack([pad(t["thr"], f_nodes) for t in ft])
    P = [path_tables(t, f_leaves, f_depth) for t in ft]
    h.append(c_array("forest_feature", "unsigned char", F_feat))
    h.append(c_array("forest_threshold", "unsigned short", F_thr))
    h.append(c_array("forest_path_node", "unsigned char", np.stack([p[0] for p in P])))
    h.append(c_array("forest_path_dir", "unsigned char", np.stack([p[1] for p in P])))
    h.append(c_array("forest_path_len", "unsigned char", np.stack([p[2] for p in P])))
    h.append(c_array("forest_leaf_class", "unsigned char", np.stack([p[3] for p in P])))
    h.append(c_array("forest_leaf_valid", "unsigned char", np.stack([p[4] for p in P])))
    h.append("\n#endif\n")
    with open(os.path.join(outdir, "model.h"), "w") as f:
        f.write("".join(h))

    # --- dane testowe
    d = ["// WYGENEROWANE przez python/train_export.py\n#ifndef TEST_DATA_H\n#define TEST_DATA_H\n"]
    d.append(f"#define N_TEST {len(yte)}\n")
    d.append(c_array("test_x", "unsigned short", Xte))
    d.append(c_array("test_y", "unsigned char", yte))
    d.append("// oczekiwane wyniki: sklearn tree.predict oraz głosowanie większościowe lasu\n")
    d.append(c_array("ref_tree", "unsigned char", ref_tree))
    d.append(c_array("ref_forest", "unsigned char", ref_forest))
    d.append("#endif\n")
    with open(os.path.join(outdir, "test_data.h"), "w") as f:
        f.write("".join(d))

    # dane dla hosta na płytce (PYNQ)
    np.savez(os.path.join(outdir, "test_data.npz"), x=Xte, y=yte,
             ref_tree=ref_tree, ref_forest=ref_forest,
             q_lo=meta["q_lo"], q_hi=meta["q_hi"], bits=bits,
             tree_nodes=np.array(node_words(tt), dtype=np.uint64), tree_depth=tt["depth"])
    return tt, ft


# ---------------------------------------------------------------- główne
def train(args, bits, tree_depth=None, forest_depth=None):
    tree_depth = tree_depth or args.depth
    forest_depth = forest_depth or args.forest_depth
    Xtr, Xte, ytr, yte, lo, hi = prepare(args.dataset, bits, args.test_size, args.seed)
    n_classes = int(max(ytr.max(), yte.max()) + 1)
    tree = DecisionTreeClassifier(max_depth=tree_depth, random_state=args.seed).fit(Xtr, ytr)
    forest = RandomForestClassifier(n_estimators=args.trees, max_depth=forest_depth,
                                    random_state=args.seed).fit(Xtr, ytr)
    return dict(Xtr=Xtr, Xte=Xte, ytr=ytr, yte=yte, lo=lo, hi=hi, n_classes=n_classes,
                tree=tree, forest=forest)


def float_baseline(args):
    """Punkt odniesienia: te same modele na cechach float (bez kwantyzacji)."""
    X, y = load_dataset(args.dataset)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=args.test_size,
                                          random_state=args.seed, stratify=y)
    t = DecisionTreeClassifier(max_depth=args.depth, random_state=args.seed).fit(Xtr, ytr)
    f = RandomForestClassifier(n_estimators=args.trees, max_depth=args.forest_depth,
                               random_state=args.seed).fit(Xtr, ytr)
    return (t.predict(Xte) == yte).mean(), (f.predict(Xte) == yte).mean()


def sweep(args):
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    ft, ff = float_baseline(args)
    lines = [f"# Dokładność a szerokość cech ({args.dataset}, drzewo depth={args.depth}, "
             f"las {args.trees}x depth={args.forest_depth})\n",
             "| cechy | drzewo | las (głosowanie) | węzły drzewa |",
             "|---|---|---|---|",
             f"| float (odniesienie) | {ft:.4f} | {ff:.4f} | - |"]
    for b in [2, 3, 4, 6, 8, 10, 12, 16]:
        m = train(args, b)
        at = (m["tree"].predict(m["Xte"]) == m["yte"]).mean()
        af = (hard_vote(m["forest"], m["Xte"], m["n_classes"]) == m["yte"]).mean()
        lines.append(f"| {b} bit | {at:.4f} | {af:.4f} | {m['tree'].tree_.node_count} |")
    lines += ["", f"# Dokładność a głębokość drzewa ({args.bits} bit)\n",
              "| max_depth | węzły | liście | dokładność |", "|---|---|---|---|"]
    for dpt in [1, 2, 3, 4, 5, 6, 8, 10]:
        m = train(args, args.bits, tree_depth=dpt)
        t = m["tree"]
        lines.append(f"| {dpt} | {t.tree_.node_count} | {t.get_n_leaves()} | "
                     f"{(t.predict(m['Xte']) == m['yte']).mean():.4f} |")
    out = "\n".join(lines) + "\n"
    with open(os.path.join(ROOT, "results", "sweep.md"), "w") as f:
        f.write(out)
    print(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="breast_cancer",
                    choices=["breast_cancer", "wine", "iris", "digits"])
    ap.add_argument("--bits", type=int, default=12)
    ap.add_argument("--depth", type=int, default=5, help="max_depth pojedynczego drzewa")
    ap.add_argument("--trees", type=int, default=8, help="liczba drzew w lesie")
    ap.add_argument("--forest-depth", type=int, default=5)
    ap.add_argument("--test-size", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None, help="katalog wyjściowy (domyślnie gen/b<bits>)")
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()

    if args.sweep:
        sweep(args)
        return

    m = train(args, args.bits)
    Xte, yte, tree, forest = m["Xte"], m["yte"], m["tree"], m["forest"]
    ref_tree = tree.predict(Xte).astype(np.int64)
    ref_forest = hard_vote(forest, Xte, m["n_classes"])
    sk_forest = forest.predict(Xte)

    outdir = args.out or os.path.join(ROOT, "gen", f"b{args.bits}")
    meta = dict(dataset=args.dataset, tree_depth=args.depth, forest_depth=args.forest_depth,
                q_lo=m["lo"], q_hi=m["hi"])
    tt, ft = export(outdir, args.bits, Xte.shape[1], m["n_classes"], tree, forest,
                    Xte, yte, ref_tree, ref_forest, meta)

    ft_acc, ff_acc = float_baseline(args)
    summary = {
        "dataset": args.dataset, "bits": args.bits, "n_test": int(len(yte)),
        "tree": {"max_depth": args.depth, "nodes": tt["n_nodes"], "leaves": len(tt["leaves"]),
                 "depth": tt["depth"], "accuracy": float((ref_tree == yte).mean()),
                 "accuracy_float": float(ft_acc)},
        "forest": {"trees": args.trees, "max_depth": args.forest_depth,
                   "nodes_total": int(sum(t["n_nodes"] for t in ft)),
                   "accuracy_hard_vote": float((ref_forest == yte).mean()),
                   "accuracy_sklearn_soft_vote": float((sk_forest == yte).mean()),
                   "agreement_hard_vs_sklearn": float((ref_forest == sk_forest).mean()),
                   "accuracy_float": float(ff_acc)},
    }
    with open(os.path.join(outdir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"-> {outdir}/model.h, test_data.h, test_data.npz, summary.json")


if __name__ == "__main__":
    main()
