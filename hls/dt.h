// Temat 14 ESL: drzewo decyzyjne i las losowy w sprzęcie (Vitis HLS)
#ifndef DT_H
#define DT_H

#include <ap_int.h>
#include "model.h"   // wygenerowany: gen/b12/model.h albo gen/b8/model.h

// Cechy są liczbami bez znaku o szerokości FEAT_BITS (kwantyzacja min-max robi host).
typedef ap_uint<FEAT_BITS> feat_t;
// Wszystkie cechy jednej próbki spakowane w jedno szerokie słowo:
// cecha f zajmuje bity [f*FEAT_BITS + FEAT_BITS-1 : f*FEAT_BITS].
// Dzięki temu w wariantach równoległych wszystkie cechy są dostępne w tym samym takcie.
typedef ap_uint<N_FEATURES * FEAT_BITS> packed_t;
typedef ap_uint<8> cls_t;
typedef ap_uint<8> node_t;

static inline feat_t get_feat(const packed_t &xp, int f) {
#pragma HLS INLINE
    return xp.range(f * FEAT_BITS + FEAT_BITS - 1, f * FEAT_BITS);
}

// Warianty (każdy kolejny = jedna zmiana względem poprzedniego):
//  v0  drzewo w pamięci ROM (BRAM), przechodzenie węzeł po węźle
//  v1  wszystkie porównania naraz + logika wyboru liścia (pełna równoległość, potok II=1)
//  v2  las FOREST_N_TREES drzew liczonych równolegle + głosowanie większościowe
//  v3  = v2 z cechami/progami 8-bitowymi (kompilowany z gen/b8/model.h)
cls_t dt_v0(packed_t xp);
cls_t dt_v1(packed_t xp);
cls_t rf_v2(packed_t xp);

#endif
