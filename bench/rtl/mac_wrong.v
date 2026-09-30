// A SMALLER mac that computes something else -- the negative control.
//
// This is the shape of every "42% fewer cells" result that is quietly wrong: the
// accumulator lost the `+ c` addend, so the netlist is genuinely smaller and the
// function genuinely differs. It is here to be rejected by the gate, on purpose,
// so that "the gate is load-bearing" is a measurement and not a claim.
//
// The gate must say no. If the gate says yes, the search is an area optimiser
// that happens to also break designs, and every number it reports is worthless.
module mac_small #(parameter W = 16) (
    input  wire                clk,
    input  wire                rst,
    input  wire                en,
    input  wire signed [W-1:0] a,
    input  wire signed [W-1:0] b,
    input  wire signed [W-1:0] c,
    output reg  signed [2*W-1:0] acc,
    output wire                acc_zero
);
    wire signed [2*W-1:0] prod = a * b;
    wire signed [2*W-1:0] sum  = acc + prod;      // <- `+ c` is gone

    always @(posedge clk) begin
        if (rst)      acc <= {2*W{1'b0}};
        else if (en)  acc <= sum;
    end

    assign acc_zero = (acc == {2*W{1'b0}});
endmodule
