// Testbench: każda próbka testowa przez wybrany wariant, porównanie bit w bit
// z wynikiem z Pythona (sklearn tree.predict / głosowanie lasu).
// VARIANT: 0 = dt_v0, 1 = dt_v1, 2 = rf_v2 (v3 = rf_v2 z modelem 8-bitowym)
// Zwraca 0, gdy wszystko się zgadza (wymagane przez csim/cosim w Vitis HLS).
#include <cstdio>
#include "dt.h"
#include "test_data.h"

#ifndef VARIANT
#define VARIANT 1
#endif

static packed_t pack(const unsigned short x[N_FEATURES]) {
    packed_t p = 0;
    for (int f = 0; f < N_FEATURES; f++)
        p.range(f * FEAT_BITS + FEAT_BITS - 1, f * FEAT_BITS) = x[f];
    return p;
}

int main() {
    int mismatch = 0, correct = 0;
    for (int i = 0; i < N_TEST; i++) {
        packed_t xp = pack(test_x[i]);
#if VARIANT == 0
        int hw = dt_v0(xp); int ref = ref_tree[i];
#elif VARIANT == 1
        int hw = dt_v1(xp); int ref = ref_tree[i];
#else
        int hw = rf_v2(xp); int ref = ref_forest[i];
#endif
        if (hw != ref) {
            if (mismatch < 10) printf("NIEZGODNOSC próbka %d: hw=%d ref=%d\n", i, hw, ref);
            mismatch++;
        }
        correct += (hw == test_y[i]);
    }
    printf("VARIANT %d, FEAT_BITS %d: %d próbek, niezgodności z Pythonem: %d, dokładność: %.4f\n",
           VARIANT, FEAT_BITS, N_TEST, mismatch, (double)correct / N_TEST);
    if (mismatch == 0) printf("TEST OK (zgodność bit w bit)\n");
    return mismatch == 0 ? 0 : 1;
}
