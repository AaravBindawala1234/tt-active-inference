/*
 * Copyright (c) 2026 Aarav
 * SPDX-License-Identifier: Apache-2.0
 *
 * TinyTapeout wrapper for the Active Inference core (3-state, log-domain).
 * Maps the core's ports onto TinyTapeout's standard pin interface.
 */
`default_nettype none

module tt_um_active_inference (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

    // ---- Pin mapping ----
    // ui_in[1:0] : observation (0/1/2)
    // ui_in[2]   : tick (pulse high to run one inference step)
    // uo_out[1:0]: action (0=move LEFT, 1=stay, 2=move RIGHT)
    // uo_out[2]  : ready (decision valid)
    // uio_out    : belief[LEFT] debug byte (always driven out)

    wire [1:0] action;
    wire       ready;
    wire [7:0] belief0;

    active_inference_core core (
        .clk        (clk),
        .rst        (~rst_n),       // core uses active-high reset
        .obs        (ui_in[1:0]),
        .tick       (ui_in[2]),
        .action     (action),
        .ready      (ready),
        .belief0    (belief0)
    );

    assign uo_out[1:0] = action;
    assign uo_out[2]   = ready;
    assign uo_out[7:3] = 5'b00000;

    assign uio_out = belief0;        // expose belief on bidirectional pins
    assign uio_oe  = 8'hFF;          // drive all 8 bidirectional pins as outputs

    // List all unused inputs to prevent warnings
    wire _unused = &{ena, uio_in, ui_in[7:3], 1'b0};

endmodule
