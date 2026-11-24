// v0 (punkt odniesienia): drzewo zapisane w pamięci ROM, jeden węzeł na iterację.
// Słowo węzła: [15:0] próg, [23:16] numer cechy, [31:24] lewe dziecko,
//              [39:32] prawe dziecko, [47:40] klasa. Liść wskazuje sam na siebie,
// więc pętla ma stałą liczbę iteracji (TREE_DEPTH) i nie potrzebuje "break".
#include "dt.h"

cls_t dt_v0(packed_t xp) {
#pragma HLS INTERFACE s_axilite port=xp
#pragma HLS INTERFACE s_axilite port=return
#pragma HLS BIND_STORAGE variable=tree_nodes type=rom_1p impl=bram

    node_t node = 0;
WALK:
    for (int d = 0; d < TREE_DEPTH; d++) {
#pragma HLS PIPELINE off
        ap_uint<64> w = tree_nodes[node];
        feat_t thr   = w.range(15, 0);
        int    f     = w.range(23, 16);
        node_t left  = w.range(31, 24);
        node_t right = w.range(39, 32);
        feat_t x = get_feat(xp, f);          // multiplekser wyboru cechy
        node = (x <= thr) ? left : right;
    }
    ap_uint<64> leaf = tree_nodes[node];
    return leaf.range(47, 40);
}
