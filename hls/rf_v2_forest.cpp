// v2: las losowy - FOREST_N_TREES drzew w wersji z v1 liczonych równolegle,
// potem głosowanie większościowe (remis -> mniejszy numer klasy).
// v3 to ten sam plik skompilowany z 8-bitowym modelem (gen/b8).
#include "dt.h"

cls_t rf_v2(packed_t xp) {
#pragma HLS INTERFACE s_axilite port=xp
#pragma HLS INTERFACE s_axilite port=return
#pragma HLS PIPELINE II=1
#pragma HLS ARRAY_PARTITION variable=forest_feature complete dim=0
#pragma HLS ARRAY_PARTITION variable=forest_threshold complete dim=0
#pragma HLS ARRAY_PARTITION variable=forest_path_node complete dim=0
#pragma HLS ARRAY_PARTITION variable=forest_path_dir complete dim=0
#pragma HLS ARRAY_PARTITION variable=forest_path_len complete dim=0
#pragma HLS ARRAY_PARTITION variable=forest_leaf_class complete dim=0
#pragma HLS ARRAY_PARTITION variable=forest_leaf_valid complete dim=0

    cls_t tree_out[FOREST_N_TREES];
#pragma HLS ARRAY_PARTITION variable=tree_out complete

TREES:
    for (int t = 0; t < FOREST_N_TREES; t++) {
#pragma HLS UNROLL
        bool cmp[FOREST_N_NODES];
#pragma HLS ARRAY_PARTITION variable=cmp complete
    COMPARE:
        for (int n = 0; n < FOREST_N_NODES; n++) {
#pragma HLS UNROLL
            cmp[n] = get_feat(xp, forest_feature[t][n]) <= (feat_t)forest_threshold[t][n];
        }
        cls_t r = 0;
    LEAVES:
        for (int l = 0; l < FOREST_N_LEAVES; l++) {
#pragma HLS UNROLL
            bool hit = forest_leaf_valid[t][l];
        PATH:
            for (int k = 0; k < FOREST_DEPTH; k++) {
#pragma HLS UNROLL
                if (k < forest_path_len[t][l])
                    hit = hit && (cmp[forest_path_node[t][l][k]] == (bool)forest_path_dir[t][l][k]);
            }
            if (hit) r |= (cls_t)forest_leaf_class[t][l];
        }
        tree_out[t] = r;
    }

    // głosowanie
    cls_t best = 0;
    ap_uint<8> best_cnt = 0;
VOTE:
    for (int c = 0; c < N_CLASSES; c++) {
#pragma HLS UNROLL
        ap_uint<8> cnt = 0;
        for (int t = 0; t < FOREST_N_TREES; t++) {
#pragma HLS UNROLL
            cnt += (tree_out[t] == c);
        }
        if (cnt > best_cnt) { best_cnt = cnt; best = c; }
    }
    return best;
}
