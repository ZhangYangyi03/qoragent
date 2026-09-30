// The same multiply-accumulate, renamed -- the POSITIVE control for the
// equivalence gate. Identical function, different module name, so
// `equivalence_script` can have one of each side. A gate that cannot say
// YES to this is broken in the other direction and would reject every
// correct optimisation the search finds. -- enough logic that synthesis choices
// visibly move area and depth, small enough to prove equivalent in seconds.
module mac_alt #(parameter W = 16) (
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
    wire signed [2*W-1:0] sum  = acc + prod + {{W{1'b0}}, c};

    always @(posedge clk) begin
        if (rst)      acc <= {2*W{1'b0}};
        else if (en)  acc <= sum;
    end

    assign acc_zero = (acc == {2*W{1'b0}});
endmodule
