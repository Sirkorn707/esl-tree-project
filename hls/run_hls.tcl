# Vitis HLS: symulacja C, synteza, (opcjonalnie) kosymulacja i eksport IP dla wariantów.
#
# Uruchomienie z katalogu hls/:
#   vitis_hls -f run_hls.tcl                     (Vitis HLS 2020.2 - 2023.2)
#   vitis-run --mode hls --tcl run_hls.tcl       (Vitis 2024.1 i nowsze)
# Jeden wariant:  VARIANTS="v1" vitis_hls -f run_hls.tcl
# Bez kosymulacji (szybciej): COSIM=0 vitis_hls -f run_hls.tcl
#
# Płytka: Zybo Z7-20 (xc7z020clg400-1), zegar 100 MHz.
# Zybo Z7-10 i stare Zybo mają układ xc7z010clg400-1:  PART=xc7z010clg400-1 vitis_hls -f run_hls.tcl

set here [file normalize [file dirname [info script]]]
set part  "xc7z020clg400-1"
if {[info exists ::env(PART)]} { set part $::env(PART) }
set clock 10

set variants {v0 v1 v2 v3}
if {[info exists ::env(VARIANTS)]} { set variants $::env(VARIANTS) }
set do_cosim 1
if {[info exists ::env(COSIM)]} { set do_cosim $::env(COSIM) }

# wariant -> {funkcja top, plik jądra, VARIANT dla testbencha, katalog modelu}
array set cfg {
    v0 {dt_v0 dt_v0_seq.cpp    0 b12}
    v1 {dt_v1 dt_v1_par.cpp    1 b12}
    v2 {rf_v2 rf_v2_forest.cpp 2 b12}
    v3 {rf_v2 rf_v2_forest.cpp 2 b8}
}

foreach v $variants {
    lassign $cfg($v) top src tbvar model
    set inc "-I$here -I[file normalize $here/../gen/$model]"

    open_project -reset proj_$v
    set_top $top
    add_files $here/$src -cflags $inc
    add_files -tb $here/tb.cpp -cflags "$inc -DVARIANT=$tbvar"
    open_solution -reset sol -flow_target vivado
    set_part $part
    create_clock -period $clock -name default

    csim_design
    csynth_design
    if {$do_cosim} { cosim_design }
    export_design -format ip_catalog -rtl verilog -display_name "dt_$v"
    close_project
}
exit
