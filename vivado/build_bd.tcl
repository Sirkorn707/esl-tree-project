# Vivado: projekt z Zynq PS + IP z HLS, synteza, implementacja, bitstream.
# Wymaga wcześniejszego uruchomienia hls/run_hls.tcl (eksport IP).
#
#   cd vivado
#   vivado -mode batch -source build_bd.tcl -tclargs v1      (albo v0, v2, v3)
#
# Wynik: vivado/out/dt_<v>.bit i dt_<v>.hwh -> skopiować na płytkę PYNQ.
# Uwaga: konfiguracja PS bez presetu płytki (DDR, MIO) - pod PYNQ to nie przeszkadza,
# bo PS jest już skonfigurowany przez system PYNQ; ładujemy tylko logikę programowalną.

set v "v1"
if {$argc > 0} { set v [lindex $argv 0] }
set here [file normalize [file dirname [info script]]]
set top  [dict get {v0 dt_v0 v1 dt_v1 v2 rf_v2 v3 rf_v2} $v]
set proj_dir $here/vivado_$v

create_project -force dt_$v $proj_dir -part xc7z020clg400-1
set_property ip_repo_paths [list $here/../hls/proj_$v/sol/impl/ip] [current_project]
update_ip_catalog

create_bd_design "design_1"
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7 ps7]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" apply_board_preset "0" Master "Disable" Slave "Disable"} $ps
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100}] $ps

set ipdef [lindex [get_ipdefs -filter "NAME == $top"] 0]
if {$ipdef eq ""} { error "Nie znaleziono IP $top - czy uruchomiono run_hls.tcl?" }
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
file copy -force [glob $proj_dir/dt_$v.runs/impl_1/*.bit] $here/out/dt_$v.bit
set hwh [glob -nocomplain $proj_dir/dt_$v.gen/sources_1/bd/design_1/hw_handoff/*.hwh \
                           $proj_dir/dt_$v.srcs/sources_1/bd/design_1/hw_handoff/*.hwh]
file copy -force [lindex $hwh 0] $here/out/dt_$v.hwh

# raport zasobów po implementacji (dokładniejszy niż szacunek HLS)
open_run impl_1
report_utilization -file $here/out/utilization_$v.txt
report_timing_summary -file $here/out/timing_$v.txt
puts "GOTOWE: $here/out/dt_$v.bit + .hwh"
