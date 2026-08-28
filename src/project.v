/*
 * Copyright (c) 2026 Aarav
 * SPDX-License-Identifier: Apache-2.0
 *
 * TinyTapeout wrapper — Active Inference core v3 (3-state, runtime-switchable
 * goal, precision input, full belief readout).
 */
`default_nettype none

module tt_um_active_inference (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (1=output)
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
    // ---- Pin mapping ----
    // ui_in[1:0] : observation (0/1/2)
    // ui_in[2]   : tick
    // ui_in[4:3] : unused (was gamma; removed in v3.1 as provably inert)
    // ui_in[6:5] : bsel (belief readout select 0/1/2)
    // ui_in[7]   : csel (goal: 0=seek RIGHT, 1=seek LEFT)
    // uo_out[1:0]: action (0=L,1=stay,2=R)
    // uo_out[2]  : ready
    // uio_out    : selected belief value (per bsel)

    wire [1:0] action;
    wire       ready;
    wire [7:0] belief_dbg;

    active_inference_core core (
        .clk        (clk),
        .rst        (~rst_n),
        .obs        (ui_in[1:0]),
        .tick       (ui_in[2]),
        .bsel       (ui_in[6:5]),
        .csel       (ui_in[7]),
        .action     (action),
        .ready      (ready),
        .belief_dbg (belief_dbg)
    );

    assign uo_out[1:0] = action;
    assign uo_out[2]   = ready;
    assign uo_out[7:3] = 5'b00000;
    assign uio_out     = belief_dbg;
    assign uio_oe      = 8'hFF;

    wire _unused = &{ena, uio_in, ui_in[4:3], 1'b0};
endmodule
