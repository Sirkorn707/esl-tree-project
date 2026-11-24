// v1: wszystkie porównania naraz + logika wyboru liścia.
// 1) Każdy węzeł wewnętrzny ma własny komparator (cecha i próg są stałymi,
//    więc to tylko kilka LUT-ów na węzeł, zero DSP).
// 2) Liść jest wybrany, gdy wszystkie porównania na jego ścieżce mają właściwy wynik
//    (iloczyn logiczny). Dokładnie jeden liść jest aktywny -> OR klas.
// Funkcja jest w potoku z II=1: nowa próbka w każdym takcie.
#include "dt.h"

cls_t dt_v1(packed_t xp) {
#pragma HLS INTERFACE s_axilite port=xp
#pragma HLS INTERFACE s_axilite port=return
#pragma HLS PIPELINE II=1
#pragma HLS ARRAY_PARTITION variable=tree_feature complete dim=0
#pragma HLS ARRAY_PARTITION variable=tree_threshold complete dim=0
#pragma HLS ARRAY_PARTITION variable=tree_path_node complete dim=0
#pragma HLS ARRAY_PARTITION variable=tree_path_dir complete dim=0
#pragma HLS ARRAY_PARTITION variable=tree_path_len complete dim=0
#pragma HLS ARRAY_PARTITION variable=tree_leaf_class complete dim=0

    bool cmp[TREE_N_NODES];
#pragma HLS ARRAY_PARTITION variable=cmp complete

COMPARE:
    for (int n = 0; n < TREE_N_NODES; n++) {
#pragma HLS UNROLL
        cmp[n] = get_feat(xp, tree_feature[n]) <= (feat_t)tree_threshold[n];
    }

    cls_t result = 0;
LEAVES:
    for (int l = 0; l < TREE_N_LEAVES; l++) {
#pragma HLS UNROLL
        bool hit = true;
    PATH:
        for (int k = 0; k < TREE_DEPTH; k++) {
#pragma HLS UNROLL
            if (k < tree_path_len[l])
                hit = hit && (cmp[tree_path_node[l][k]] == (bool)tree_path_dir[l][k]);
        }
        if (hit) result |= (cls_t)tree_leaf_class[l];
    }
    return result;
}
