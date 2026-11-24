#!/usr/bin/env bash
# Szybka symulacja C wszystkich wariantów zwykłym g++ (bez uruchamiania Vitis HLS).
# Potrzebne nagłówki ap_int.h: z instalacji Vitis (…/Vitis_HLS/<wersja>/include
# albo …/Vitis/<wersja>/include) lub z github.com/Xilinx/HLS_arbitrary_Precision_Types.
#   AP_INCLUDE=/tools/Xilinx/Vitis_HLS/2023.2/include ./run_csim.sh
set -e
cd "$(dirname "$0")"
AP_INCLUDE=${AP_INCLUDE:-/tools/Xilinx/Vitis_HLS/2023.2/include}
CXX=${CXX:-g++}
FLAGS="-std=c++14 -O2 -Wno-unknown-pragmas -I. -I$AP_INCLUDE"
mkdir -p build

run() {  # nazwa, VARIANT, katalog modelu, plik jądra
  $CXX $FLAGS -I../gen/$3 -DVARIANT=$2 tb.cpp $4 -o build/$1
  ./build/$1
}
run v0 0 b12 dt_v0_seq.cpp
run v1 1 b12 dt_v1_par.cpp
run v2 2 b12 rf_v2_forest.cpp
run v3 2 b8  rf_v2_forest.cpp
echo "Wszystkie warianty: OK"
