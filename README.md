# Temat 14: drzewo decyzyjne i las losowy w sprzęcie (ESL, Vitis HLS, Zynq-7020)

Wytrenowane w scikit-learn drzewo decyzyjne (a potem las losowy) zamienione na układ
porównań w logice programowalnej. Nie ma mnożeń (DSP = 0), a jest dużo równoległości.
Zbiór: Breast Cancer Wisconsin (30 cech, 2 klasy, 569 próbek, test 30% = 171 próbek).

## Struktura

```
python/train_export.py   trening + kwantyzacja cech + eksport modelu do C++ (gen/b12, gen/b8)
python/hls_report.py     zbiera wyniki syntezy wszystkich wariantów do results/hls_results.md
gen/b12, gen/b8          wygenerowane model.h, test_data.h, test_data.npz, summary.json
hls/dt.h                 typy wspólne (ap_uint), deklaracje
hls/dt_v0_seq.cpp        v0: drzewo w ROM, węzeł po węźle
hls/dt_v1_par.cpp        v1: wszystkie porównania naraz + wybór liścia, potok II=1
hls/rf_v2_forest.cpp     v2: las 8 drzew równolegle + głosowanie (v3 = to samo, 8 bit)
hls/tb.cpp               testbench: zgodność bit w bit z Pythonem
hls/run_csim.sh          szybka symulacja C wszystkich wariantów zwykłym g++
hls/run_hls.tcl          Vitis HLS: csim, synteza, kosymulacja, eksport IP
vivado/build_bd.tcl      Vivado: Zynq PS + IP, bitstream (.bit + .hwh)
pynq/dt_host.py          program na płytce: test, czas HW vs ARM
results/sweep.md         dokładność a liczba bitów i a głębokość drzewa
```

## Warianty (cykl ulepszania, jedna zmiana na wariant)

| wariant | co się zmienia | czego się spodziewać |
|---|---|---|
| v0 | punkt odniesienia: węzły w BRAM (1 słowo 64 bit = węzeł), pętla po głębokości | kilka taktów na poziom, mało LUT, 1 BRAM |
| v1 | wszystkie porównania naraz, liść = AND porównań na ścieżce | opóźnienie 1–3 takty, II = 1, więcej LUT, 0 BRAM |
| v2 | las 8 drzew równolegle + głosowanie | ok. 8× więcej LUT, opóźnienie prawie bez zmian |
| v3 | v2 z cechami i progami 8 zamiast 12 bitów | mniej LUT (krótsze komparatory i węższy rejestr wejścia), dokładność bez zmian |

Liczby w tabeli wyników uzupełnia się po syntezie (`python3 python/hls_report.py`).

## Dlaczego zgodność bit w bit ze sklearn jest gwarantowana

Cechy są kwantyzowane do liczb całkowitych **przed** treningiem (min-max na zbiorze uczącym,
12 albo 8 bitów). sklearn ustawia progi w połowie między sąsiednimi wartościami cechy,
czyli `k + 0.5`. Dla całkowitego `x`: `x <= k + 0.5  ⇔  x <= k`. Do sprzętu trafia więc
próg `floor(t)` i porównanie daje dokładnie ten sam wynik co sklearn.

Las: sklearn uśrednia prawdopodobieństwa z liści (soft voting), sprzęt liczy głosy
(hard voting, remis → mniejszy numer klasy). Referencją dla lasu jest głosowanie
liczone w Pythonie na drzewach sklearn. Zgodność z `forest.predict` jest raportowana
w `summary.json` (tutaj 100%).

## Wyniki z Pythona (już policzone)

| model | cechy | dokładność |
|---|---|---|
| drzewo, max_depth=5 (27 węzłów, 14 liści) | float | 0.9298 |
| drzewo | 12 bit | 0.9298 |
| drzewo | 8 bit | 0.9240 |
| las 8 × depth 5 | 12 bit | 0.9298 |
| las 8 × depth 5 | 8 bit | 0.9298 |

Pełne tabele: `results/sweep.md`. Symulacja C (`run_csim.sh`): wszystkie 4 warianty,
171/171 próbek zgodnych z Pythonem.

## Jak uruchomić

### 1. Python (dowolny komputer)
```bash
pip install scikit-learn numpy
python3 python/train_export.py            # gen/b12
python3 python/train_export.py --bits 8   # gen/b8
python3 python/train_export.py --sweep    # results/sweep.md
```
(Pliki w `gen/` są już wygenerowane, ten krok jest potrzebny tylko po zmianie parametrów.)

### 2. Vitis HLS
```bash
cd hls
vitis_hls -f run_hls.tcl                  # Vitis 2020.2–2023.2
vitis-run --mode hls --tcl run_hls.tcl    # Vitis 2024.1+
# jeden wariant / bez kosymulacji:
VARIANTS="v1" COSIM=0 vitis_hls -f run_hls.tcl
cd .. && python3 python/hls_report.py
```
W GUI: nowy projekt, top = `dt_v1` (itd.), źródło = plik jądra, testbench = `tb.cpp`,
w CFLAGS obu plików `-I<ścieżka>/gen/b12` (testbench dodatkowo `-DVARIANT=1`),
część `xc7z020clg400-1`, zegar 10 ns.

Szybki test bez Vitis: `AP_INCLUDE=<katalog z ap_int.h> hls/run_csim.sh`.

### 3. Vivado + płytka
```bash
cd vivado && vivado -mode batch -source build_bd.tcl -tclargs v1
```
Na płytkę PYNQ: `out/dt_v1.bit`, `out/dt_v1.hwh`, `gen/b12/test_data.npz`, `pynq/dt_host.py`,
potem `sudo python3 dt_host.py v1`. Dla v3 użyj `gen/b8/test_data.npz`.

Skrypt Vivado nie był uruchamiany na prawdziwej instalacji. Jeśli coś nie przejdzie, block design
da się wyklikać w 3 krokach: dodać ZYNQ7 Processing System → Run Block Automation, dodać IP `dt_v1`
→ Run Connection Automation, potem Create HDL Wrapper → Generate Bitstream.

## Co mierzyć (kryteria z karty tematu)

- takty na próbkę (opóźnienie) i II, z raportu HLS i z kosymulacji,
- LUT / FF / BRAM / DSP (HLS + po implementacji w Vivado),
- dokładność wobec scikit-learn (ma być identyczna) i wobec etykiet,
- głębokość drzewa a koszt (`results/sweep.md` + synteza z innym `--depth`),
- na płytce: czas HW vs ten sam algorytm na ARM. Przy pojedynczej próbce przez AXI-Lite dominuje
  transfer, nie obliczenia. To dobry przykład prawa Amdahla na obronę.

## Pytania, które mogą paść na obronie

- **Dlaczego DSP = 0?** Drzewo to tylko porównania z progami, nie ma mnożeń.
- **Skąd zgodność bit w bit?** Trening na cechach całkowitych, próg `k+0.5` → `x <= k`.
- **Dlaczego v1 nie używa BRAM?** Progi i numery cech są stałymi, więc synteza wbudowuje je w komparatory.
- **Ile kosztuje las?** Koszt rośnie mniej więcej liniowo z liczbą drzew, a opóźnienie prawie się nie zmienia (drzewa liczą się równolegle, dochodzi drzewo sumatorów do głosowania).
- **Czemu las nie jest dokładniejszy?** Zbiór jest mały i łatwy, a pojedyncze drzewo już osiąga ~93%. To uczciwy wynik do pokazania w kompromisie koszt / dokładność.
