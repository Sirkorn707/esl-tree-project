# Vivado: projekt dla Zybo z Zynq PS + IP z HLS, bitstream i plik platformy .xsa dla Vitis.
# Wymaga wcześniejszego uruchomienia hls/run_hls.tcl (eksport IP).
#
#   cd vivado
#   vivado -mode batch -source build_bd.tcl -tclargs v1                 (Zybo Z7-20)
#   vivado -mode batch -source build_bd.tcl -tclargs v1 zybo-z7-10      (Zybo Z7-10)
#   vivado -mode batch -source build_bd.tcl -tclargs v1 zybo            (stare Zybo)
#
# Wynik: vivado/out/dt_<v>.xsa (z bitstreamem) -> platforma w Vitis, program zybo/dt_host.c
#
# Ustawienia PS (DDR, UART, zegary) pochodzą z pliku płytki Digilent. Pliki płytek muszą być
# zainstalowane w Vivado: https://github.com/Digilent/vivado-boards (instrukcja w README repozytorium).
# Bez nich skrypt przerwie pracę, bo program bare-metal nie uruchomi się przy złych ustawieniach DDR.

set v     "v1"
set board "zybo-z7-20"
if {$argc > 0} { set v     [lindex $argv 0] }
if {$argc > 1} { set board [lindex $argv 1] }

set here [file normalize [file dirname [info script]]]
set top  [dict get {v0 dt_v0 v1 dt_v1 v2 rf_v2 v3 rf_v2} $v]
set part [expr {$board eq "zybo-z7-20" ? "xc7z020clg400-1" : "xc7z010clg400-1"}]
set proj_dir $here/vivado_$v

set bp [lindex [lsort [get_board_parts -quiet "*:${board}:*"]] end]
if {$bp eq ""} {
    error "Brak pliku płytki '$board' w Vivado. Zainstaluj Digilent vivado-boards (patrz README)."
}

create_project -force dt_$v $proj_dir -part $part
set_property board_part $bp [current_project]
set_property ip_repo_paths [list $here/../hls/proj_$v/sol/impl/ip] [current_project]
update_ip_catalog

create_bd_design "design_1"
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7 ps7]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable"} $ps
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100}] $ps

set ipdef [lindex [get_ipdefs -filter "NAME == $top"] 0]
if {$ipdef eq ""} { error "Nie znaleziono IP $top - czy uruchomiono hls/run_hls.tcl?" }
create_bd_cell -type ip -vlnv $ipdef dt
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/ps7/M_AXI_GP0" Clk "Auto"} [get_bd_intf_pins dt/s_axi_control]

validate_bd_design
save_bd_design
set wrapper [make_wrapper -files [get_files design_1.bd] -top]
add_files -norecurse $wrapper
set_property top design_1_wrapper [current_fileset]

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

file mkdir $here/out
open_run impl_1
report_utilization    -file $here/out/utilization_$v.txt
report_timing_summary -file $here/out/timing_$v.txt
write_hw_platform -fixed -include_bit -force -file $here/out/dt_$v.xsa
puts "GOTOWE: $here/out/dt_$v.xsa (platforma dla Vitis, zawiera bitstream)"
