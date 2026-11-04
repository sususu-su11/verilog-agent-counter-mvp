// Trusted testbench for family=counter. Host-owned. LLM never sees or edits this.
// Emits VLTB1 observation protocol only — never PASS/FAIL.
`timescale 1ns/1ps
module tb_top;
    reg clk = 0;
    reg rst = 0;
    reg en  = 0;
    wire [3:0] count;

    localparam integer N = 22;
    reg vec_rst [0:N-1];
    reg vec_en  [0:N-1];

    integer step;
    integer rec_count;
    integer tb_errors;
    string run_nonce;

    dut uut (
        .clk(clk),
        .rst(rst),
        .en(en),
        .count(count)
    );

    always #5 clk = ~clk;

    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb_top);
    end

    initial begin
        #200000;
        $display("VLTB1|%s|TBERR|WATCHDOG|main|%0d", run_nonce, step);
        tb_errors = tb_errors + 1;
        $finish;
    end

    initial begin
        rec_count = 0;
        tb_errors = 0;
        step = 0;

        vec_rst[0]=1;  vec_en[0]=0;
        vec_rst[1]=0;  vec_en[1]=1;
        vec_rst[2]=0;  vec_en[2]=1;
        vec_rst[3]=0;  vec_en[3]=0;
        vec_rst[4]=1;  vec_en[4]=1;
        vec_rst[5]=0;  vec_en[5]=1;
        vec_rst[6]=0;  vec_en[6]=1;
        vec_rst[7]=0;  vec_en[7]=1;
        vec_rst[8]=0;  vec_en[8]=1;
        vec_rst[9]=0;  vec_en[9]=1;
        vec_rst[10]=0; vec_en[10]=1;
        vec_rst[11]=0; vec_en[11]=1;
        vec_rst[12]=0; vec_en[12]=1;
        vec_rst[13]=0; vec_en[13]=1;
        vec_rst[14]=0; vec_en[14]=1;
        vec_rst[15]=0; vec_en[15]=1;
        vec_rst[16]=0; vec_en[16]=1;
        vec_rst[17]=0; vec_en[17]=1;
        vec_rst[18]=0; vec_en[18]=1;
        vec_rst[19]=0; vec_en[19]=1;
        vec_rst[20]=0; vec_en[20]=1;
        vec_rst[21]=0; vec_en[21]=0;

        if (!$value$plusargs("nonce=%s", run_nonce)) begin
            $display("VLTB1|MISSING|TBERR|NO_NONCE|main|0");
            $finish;
        end
        if (run_nonce.len() != 32) begin
            $display("VLTB1|%s|TBERR|BAD_NONCE|main|0", run_nonce);
            $finish;
        end

        $display("VLTB1|%s|BEGIN|counter|counter4_sync_v1", run_nonce);

        for (step = 0; step < N; step = step + 1) begin
            @(negedge clk);
            rst = vec_rst[step];
            en  = vec_en[step];
            #1;
            $display("VLTB1|%s|IN|main|%0d|rst|1|%b", run_nonce, step, rst);
            $display("VLTB1|%s|IN|main|%0d|en|1|%b",  run_nonce, step, en);
            rec_count = rec_count + 2;
            if (step > 0) begin
                $display("VLTB1|%s|PRE|main|%0d|count|4|%04b", run_nonce, step, count);
                rec_count = rec_count + 1;
            end
            @(posedge clk);
            #1;
            $display("VLTB1|%s|POST|main|%0d|count|4|%04b", run_nonce, step, count);
            rec_count = rec_count + 1;
        end

        $display("VLTB1|%s|END|%0d|%0d", run_nonce, rec_count, tb_errors);
        $finish;
    end
endmodule
