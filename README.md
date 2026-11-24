# Drzewo decyzyjne i las losowy w FPGA

Sprzętowy akcelerator klasyfikatora drzewiastego dla układu Zynq-7020, zaprojektowany
w Vitis HLS. Projekt realizowany w ramach przedmiotu **Programowanie wysokopoziomowe
układów (ESL)**, temat 14: *Drzewo decyzyjne i las losowy w sprzęcie*, rok akademicki 2026/2027.

---

## Spis treści

1. [Cel projektu](#cel-projektu)
2. [Model i dane](#model-i-dane)
3. [Zgodność bit w bit z modelem referencyjnym](#zgodność-bit-w-bit-z-modelem-referencyjnym)
4. [Architektura i warianty](#architektura-i-warianty)
5. [Wyniki](#wyniki)
6. [Struktura repozytorium](#struktura-repozytorium)
7. [Wymagania](#wymagania)
8. [Uruchomienie](#uruchomienie)
9. [Harmonogram i podział pracy](#harmonogram-i-podział-pracy)

---

## Cel projektu

Drzewo decyzyjne w każdym węźle porównuje jedną cechę z progiem. W sprzęcie oznacza to
wyłącznie komparatory: nie występują mnożenia (zerowe zużycie bloków DSP), a wszystkie
węzły mogą być obliczane jednocześnie. Celem projektu jest:

- implementacja wytrenowanego w scikit-learn drzewa decyzyjnego, a następnie lasu losowego,
  jako bloku IP w logice programowalnej,
- uzyskanie wyników **identycznych** z modelem referencyjnym w Pythonie,
- porównanie kolejnych wariantów architektury pod względem opóźnienia, przepustowości
  i zużycia zasobów (LUT, FF, BRAM, DSP),
- weryfikacja na płytce z układem Zynq-7020 (PYNQ-Z2) i porównanie z implementacją
  programową na procesorze ARM.

## Model i dane

| parametr | wartość |
|---|---|
| zbiór danych | Breast Cancer Wisconsin (`sklearn.datasets`) |
| liczba cech / klas / próbek | 30 / 2 / 569 |
| podział | 70% uczący, 30% testowy (171 próbek), stratyfikowany, `random_state=42` |
| drzewo | `DecisionTreeClassifier(max_depth=5)`: 27 węzłów, 14 liści |
| las | `RandomForestClassifier(n_estimators=8, max_depth=5)` |
| reprezentacja cech | liczby całkowite bez znaku, 12 bitów (wariant v3: 8 bitów) |

Cechy są skalowane metodą min-max (zakres wyznaczony na zbiorze uczącym) i kwantyzowane
do liczb całkowitych. Tę samą operację wykonuje host przed przesłaniem próbki do układu.

## Zgodność bit w bit z modelem referencyjnym

Model jest trenowany **na cechach już skwantowanych**. scikit-learn wyznacza progi
w połowie odległości między sąsiednimi wartościami cechy, więc dla cech całkowitych
każdy próg ma postać `k + 0.5`. Dla całkowitego `x` zachodzi

```
x ≤ k + 0.5   ⇔   x ≤ k
```

Do sprzętu trafia zatem próg całkowity `k = ⌊t⌋`, a każde porównanie daje dokładnie ten sam
wynik co w scikit-learn. Zgodność wynika z konstrukcji, a nie z doboru danych testowych.

W lesie układ stosuje głosowanie większościowe (remis rozstrzygany na korzyść klasy o niższym
numerze), podczas gdy `RandomForestClassifier.predict` uśrednia prawdopodobieństwa.
Referencją dla lasu jest więc głosowanie większościowe liczone w Pythonie na drzewach
z scikit-learn. Zgodność z `predict` jest raportowana osobno (dla użytego modelu: 100%).

## Architektura i warianty

```mermaid
flowchart LR
    A["Python<br/>trening, kwantyzacja,<br/>eksport model.h"] --> B["Vitis HLS<br/>C++ → RTL,<br/>csim / cosim"]
    B --> C["Vivado<br/>Zynq PS + IP<br/>(AXI4-Lite)"]
    C --> D["PYNQ-Z2<br/>test i pomiar czasu"]
```

Wszystkie cechy próbki są przekazywane jako jedno spakowane słowo przez interfejs AXI4-Lite,
a wynikiem funkcji jest numer klasy. Kolejne warianty zgodnie z cyklem ulepszania wprowadzają
po jednej zmianie:

| wariant | plik | opis | oczekiwany efekt |
|---|---|---|---|
| **v0** | `dt_v0_seq.cpp` | drzewo zapisane w ROM (BRAM), jeden węzeł = jedno słowo 64-bitowe; przechodzenie węzeł po węźle | punkt odniesienia: kilka taktów na poziom drzewa, minimalne zużycie logiki |
| **v1** | `dt_v1_par.cpp` | komparator dla każdego węzła, wszystkie porównania jednocześnie; liść wybierany iloczynem porównań na ścieżce; potok `II=1` | opóźnienie kilku taktów, nowa próbka w każdym takcie, brak BRAM |
| **v2** | `rf_v2_forest.cpp` | las 8 drzew w architekturze v1 liczonych równolegle + głosowanie | zasoby rosnące liniowo z liczbą drzew przy niemal niezmienionym opóźnieniu |
| **v3** | `rf_v2_forest.cpp` + `gen/b8` | wariant v2 z cechami i progami 8-bitowymi zamiast 12-bitowych | mniejsze zużycie LUT przy zachowanej dokładności |

Zegar docelowy: 100 MHz, układ `xc7z020clg400-1`.

## Wyniki

### Dokładność (Python, zbiór testowy 171 próbek)

| model | float | 12 bit | 8 bit |
|---|---|---|---|
| drzewo, `max_depth=5` | 0.9298 | 0.9298 | 0.9240 |
| las, 8 × `max_depth=5` | 0.9298 | 0.9298 | 0.9298 |

Pełne zestawienie dokładności w zależności od szerokości cech (2–16 bitów) i głębokości
drzewa: [`results/sweep.md`](results/sweep.md).

### Weryfikacja funkcjonalna (symulacja C)

| wariant | próbki zgodne z Pythonem | dokładność |
|---|---|---|
| v0 | 171 / 171 | 0.9298 |
| v1 | 171 / 171 | 0.9298 |
| v2 | 171 / 171 | 0.9298 |
| v3 | 171 / 171 | 0.9298 |

### Synteza HLS

Wyniki syntezy (opóźnienie, II, LUT, FF, BRAM, DSP) są zbierane skryptem
`python/hls_report.py` do pliku `results/hls_results.md` i zostaną uzupełnione w kolejnym
etapie projektu.

## Struktura repozytorium

```
├── python/
│   ├── train_export.py     trening, kwantyzacja, eksport modelu i danych testowych do C++
│   └── hls_report.py       zestawienie wyników syntezy wszystkich wariantów
├── gen/
│   ├── b12/                model 12-bitowy: model.h, test_data.h, test_data.npz, summary.json
│   └── b8/                 model 8-bitowy (wariant v3)
├── hls/
│   ├── dt.h                typy wspólne (ap_uint) i deklaracje funkcji
│   ├── dt_v0_seq.cpp       wariant v0
│   ├── dt_v1_par.cpp       wariant v1
│   ├── rf_v2_forest.cpp    warianty v2 i v3
│   ├── tb.cpp              testbench (zgodność bit w bit z Pythonem)
│   ├── run_hls.tcl         csim, synteza, kosymulacja i eksport IP
│   └── run_csim.sh         symulacja C kompilatorem g++
├── vivado/
│   └── build_bd.tcl        projekt blokowy Zynq + IP, bitstream
├── pynq/
│   └── dt_host.py          program hosta na płytce PYNQ
└── results/
    └── sweep.md            dokładność a szerokość cech i głębokość drzewa
```

Pliki w `gen/` są generowane przez `train_export.py` i dołączone do repozytorium, aby kod HLS
można było syntetyzować bez uruchamiania Pythona.

## Wymagania

- AMD Vivado i Vitis HLS (wersje 2020.2–2024.x; licencja bezpłatna obejmuje Zynq-7020)
- Python 3.8+ z pakietami `numpy` i `scikit-learn`
- (opcjonalnie) płytka PYNQ-Z2 lub inna z układem `xc7z020clg400-1` z obrazem PYNQ

## Uruchomienie

```bash
git clone https://github.com/Sirkorn707/esl-tree-project.git
cd esl-tree-project
```

### 1. Model (opcjonalnie, pliki w `gen/` są już wygenerowane)

```bash
pip install numpy scikit-learn
python3 python/train_export.py              # gen/b12
python3 python/train_export.py --bits 8     # gen/b8
python3 python/train_export.py --sweep      # results/sweep.md
```

Parametry: `--dataset`, `--depth`, `--trees`, `--forest-depth`, `--bits`, `--seed`.

### 2. Vitis HLS

```bash
cd hls
vitis_hls -f run_hls.tcl                    # Vitis HLS 2020.2–2023.2
vitis-run --mode hls --tcl run_hls.tcl      # Vitis 2024.1 i nowsze
```

Zmienne środowiskowe: `VARIANTS="v0 v1"` ogranicza listę wariantów, `COSIM=0` pomija
kosymulację. Po syntezie:

```bash
cd .. && python3 python/hls_report.py       # results/hls_results.md
```

Konfiguracja w GUI: funkcja główna `dt_v0`, `dt_v1` lub `rf_v2`; w polu CFLAGS pliku źródłowego
i testbencha `-I<repo>/gen/b12` (dla v3: `gen/b8`); testbench dodatkowo
`-DVARIANT=0|1|2`; część `xc7z020clg400-1`, okres zegara 10 ns.

Szybka symulacja C bez Vitis (wymaga nagłówków `ap_int.h`):

```bash
AP_INCLUDE=<ścieżka>/Vitis_HLS/<wersja>/include hls/run_csim.sh
```

### 3. Vivado

```bash
cd vivado
vivado -mode batch -source build_bd.tcl -tclargs v1
```

Wynik: `vivado/out/dt_v1.bit`, `dt_v1.hwh` oraz raporty zasobów i taktowania po implementacji.
Równoważnie w GUI: ZYNQ7 Processing System → Run Block Automation → dodanie IP z HLS →
Run Connection Automation → Create HDL Wrapper → Generate Bitstream.

### 4. Płytka PYNQ

Do jednego katalogu na płytce należy skopiować `dt_<v>.bit`, `dt_<v>.hwh`,
`gen/b12/test_data.npz` (dla v3: `gen/b8/test_data.npz`) oraz `pynq/dt_host.py`:

```bash
sudo python3 dt_host.py v1
```

Program raportuje liczbę niezgodności z Pythonem, dokładność oraz średni czas klasyfikacji
jednej próbki w układzie (z transferem AXI4-Lite) i na procesorze ARM.

## Harmonogram i podział pracy

| etap | zakres | status |
|---|---|---|
| 1 | model, eksport do C++, testbench, symulacja C | zakończony |
| 2 | v0 i v1: synteza i kosymulacja | w toku |
| 3 | v2 i v3, zestawienie taktów i zasobów | planowany |
| 4 | implementacja w Vivado, pomiary na płytce | planowany |
| 5 | sprawozdanie | planowany |

| osoba | zakres |
|---|---|
| KO | model i weryfikacja: trening i eksport, testbench, analiza dokładności, program hosta i pomiary na płytce |
| RM | sprzęt: jądra HLS, dyrektywy, synteza i kosymulacja, projekt w Vivado, analiza zasobów |
