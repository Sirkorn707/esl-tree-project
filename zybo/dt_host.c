/*
 * Program hosta dla Zybo (Zynq-7000, bare-metal, Vitis).
 *
 * Wysyła każdą próbkę testową do akceleratora przez AXI4-Lite, sprawdza zgodność
 * z wynikiem z Pythona, liczy dokładność i mierzy czas: układ vs to samo drzewo
 * liczone programowo na procesorze ARM. Wyniki idą na UART (115200 8N1).
 *
 * Do katalogu src aplikacji w Vitis skopiuj:
 *   - ten plik,
 *   - gen/b12/model.h i gen/b12/test_data.h (dla v3: z gen/b8).
 *
 * Wariant ustaw poniżej (DT_VARIANT) albo w opcjach kompilatora (-DDT_VARIANT=1):
 *   0 = dt_v0, 1 = dt_v1, 2 = rf_v2 (v2 i v3 - las).
 */
#include <stdint.h>
#include "xil_io.h"
#include "xil_printf.h"
#include "xparameters.h"
#include "xtime_l.h"

#include "model.h"
#include "test_data.h"

#ifndef DT_VARIANT
#define DT_VARIANT 1
#endif

/* ---- adres bazowy IP (nazwa komórki w block design: "dt") ---------------- */
#if defined(DT_BASEADDR)
/* podany ręcznie */
#elif defined(XPAR_DT_S_AXI_CONTROL_BASEADDR)
#define DT_BASEADDR XPAR_DT_S_AXI_CONTROL_BASEADDR
#elif defined(XPAR_DT_BASEADDR)
#define DT_BASEADDR XPAR_DT_BASEADDR
#else
#warning "Nie znaleziono adresu IP w xparameters.h - używam 0x43C00000 (sprawdź w Address Editor w Vivado)"
#define DT_BASEADDR 0x43C00000
#endif

/* ---- przesunięcia rejestrów: z nagłówka sterownika HLS, jeśli jest w BSP -- */
#if DT_VARIANT == 0 && __has_include("xdt_v0_hw.h")
#include "xdt_v0_hw.h"
#define REG_RET XDT_V0_CONTROL_ADDR_AP_RETURN
#define REG_XP  XDT_V0_CONTROL_ADDR_XP_DATA
#elif DT_VARIANT == 1 && __has_include("xdt_v1_hw.h")
#include "xdt_v1_hw.h"
#define REG_RET XDT_V1_CONTROL_ADDR_AP_RETURN
#define REG_XP  XDT_V1_CONTROL_ADDR_XP_DATA
#elif DT_VARIANT == 2 && __has_include("xrf_v2_hw.h")
#include "xrf_v2_hw.h"
#define REG_RET XRF_V2_CONTROL_ADDR_AP_RETURN
#define REG_XP  XRF_V2_CONTROL_ADDR_XP_DATA
#endif
#ifndef REG_RET
#define REG_RET 0x10   /* typowy układ rejestrów Vitis HLS */
#endif
#ifndef REG_XP
#define REG_XP 0x18
#endif
#define REG_CTRL 0x00  /* bit0 ap_start, bit1 ap_done */

#define XP_WORDS ((N_FEATURES * FEAT_BITS + 31) / 32)

/* Pakowanie cech: cecha f zajmuje bity [f*FEAT_BITS + FEAT_BITS-1 : f*FEAT_BITS],
 * dokładnie tak jak packed_t w hls/dt.h. */
static void pack(const unsigned short *x, uint32_t w[XP_WORDS]) {
    for (int i = 0; i < XP_WORDS; i++) w[i] = 0;
    for (int f = 0; f < N_FEATURES; f++) {
        int bit = f * FEAT_BITS, idx = bit / 32, off = bit % 32;
        uint32_t v = x[f];
        w[idx] |= v << off;
        if (off + FEAT_BITS > 32) w[idx + 1] |= v >> (32 - off);
    }
}

static int classify_hw(const unsigned short *x) {
    uint32_t w[XP_WORDS];
    pack(x, w);
    for (int i = 0; i < XP_WORDS; i++)
        Xil_Out32(DT_BASEADDR + REG_XP + 4 * i, w[i]);
    Xil_Out32(DT_BASEADDR + REG_CTRL, 1);                      /* ap_start */
    while ((Xil_In32(DT_BASEADDR + REG_CTRL) & 0x2) == 0) {}   /* ap_done  */
    return (int)Xil_In32(DT_BASEADDR + REG_RET);
}

/* To samo drzewo na ARM (odpowiednik v0 w programie), do porównania czasu. */
static int classify_sw(const unsigned short *x) {
    unsigned node = 0;
    for (int d = 0; d < TREE_DEPTH; d++) {
        unsigned long long w = tree_nodes[node];
        unsigned thr = w & 0xFFFF, f = (w >> 16) & 0xFF;
        node = (x[f] <= thr) ? (unsigned)((w >> 24) & 0xFF) : (unsigned)((w >> 32) & 0xFF);
    }
    return (int)((tree_nodes[node] >> 40) & 0xFF);
}

static uint32_t to_ns(XTime ticks, int n) {
    return (uint32_t)((ticks * 1000000000ULL) / COUNTS_PER_SECOND / (XTime)n);
}

int main(void) {
    static int hw[N_TEST];
    XTime t0, t1;
    int mismatch = 0, correct = 0, sw_mismatch = 0;

    xil_printf("\r\n=== ESL temat 14: wariant %d, cechy %d-bitowe, %d probek ===\r\n",
               DT_VARIANT, FEAT_BITS, N_TEST);
    xil_printf("IP @ 0x%08x, ap_return 0x%02x, xp 0x%02x (%d slow)\r\n",
               (unsigned)DT_BASEADDR, REG_RET, REG_XP, XP_WORDS);

    XTime_GetTime(&t0);
    for (int i = 0; i < N_TEST; i++) hw[i] = classify_hw(test_x[i]);
    XTime_GetTime(&t1);
    uint32_t ns_hw = to_ns(t1 - t0, N_TEST);

    for (int i = 0; i < N_TEST; i++) {
#if DT_VARIANT >= 2
        int ref = ref_forest[i];
#else
        int ref = ref_tree[i];
#endif
        if (hw[i] != ref) {
            if (mismatch < 10) xil_printf("NIEZGODNOSC %d: hw=%d ref=%d\r\n", i, hw[i], ref);
            mismatch++;
        }
        correct += (hw[i] == test_y[i]);
    }

    static volatile int sink;
    XTime_GetTime(&t0);
    for (int i = 0; i < N_TEST; i++) {
        int r = classify_sw(test_x[i]);
        sink = r;
        sw_mismatch += (r != ref_tree[i]);
    }
    XTime_GetTime(&t1);
    (void)sink;
    uint32_t ns_sw = to_ns(t1 - t0, N_TEST);

    xil_printf("Niezgodnosci HW vs Python: %d\r\n", mismatch);
    xil_printf("Dokladnosc HW: %d/%d (%d.%d%%)\r\n", correct, N_TEST,
               correct * 100 / N_TEST, (correct * 1000 / N_TEST) % 10);
    xil_printf("Czas na probke: HW (z transferem AXI-Lite) %u ns, SW drzewo na ARM %u ns\r\n",
               (unsigned)ns_hw, (unsigned)ns_sw);
    xil_printf("Kontrola SW vs Python: %d niezgodnosci\r\n", sw_mismatch);
    xil_printf(mismatch == 0 ? "TEST OK\r\n" : "TEST NIEUDANY\r\n");
    return 0;
}
