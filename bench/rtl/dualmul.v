// Two multiplies, both live on every cycle: `y <= a*b + c*d`.
//
// This exists to be the negative control the equivalence gate is supposed to
// reject. Resource sharing is a real area win, and it is only valid when the two
// uses are provably exclusive -- one operand arriving while the other is idle.
// Here neither is ever idle, so a forced share must produce a smaller netlist
// that computes something else. If the gate accepts that, the gate is decoration.
module dualmul #(parameter W = 8) (
    input  wire             clk,
    input  wire [W-1:0]     a,
    input  wire [W-1:0]     b,
    input  wire [W-1:0]     c,
    input  wire [W-1:0]     d,
    output reg  [2*W-1:0]   y
);
    always @(posedge clk)
        y <= (a * b) + (c * d);
endmodule
