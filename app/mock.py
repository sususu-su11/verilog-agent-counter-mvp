"""Canned RTL for mock mode (no Vultr Inference key). Counter-first; attempt1 can be buggy for self-heal demo."""
from __future__ import annotations

import json

DEMOS = [
    {
        "id": "counter",
        "title": "4-bit sync counter",
        "prompt": "4-bit synchronous up counter with active-high sync reset and count enable",
        "family": "counter",
    },
    {
        "id": "counter_heal",
        "title": "Counter self-heal demo (bad → good)",
        "prompt": "demo self-heal: broken 4-bit counter that forgets enable (then fix)",
        "family": "counter",
    },
]

# Correct DUT matching GPT_TESTBENCH interface (count, not q)
COUNTER_OK = """module dut(
    input  wire       clk,
    input  wire       rst,
    input  wire       en,
    output reg  [3:0] count
);
    always @(posedge clk) begin
        if (rst)
            count <= 4'd0;
        else if (en)
            count <= count + 4'd1;
    end
endmodule
"""

# Bug: ignores en (always increments) — oracle will catch hold cycles
COUNTER_BAD_EN = """module dut(
    input  wire       clk,
    input  wire       rst,
    input  wire       en,
    output reg  [3:0] count
);
    always @(posedge clk) begin
        if (rst)
            count <= 4'd0;
        else
            count <= count + 4'd1; // BUG: ignores en
    end
endmodule
"""

# Bug: wrong port name q instead of count — interface lint fails / compile fails
COUNTER_BAD_PORT = """module dut(
    input  wire       clk,
    input  wire       rst,
    input  wire       en,
    output reg  [3:0] q
);
    always @(posedge clk) begin
        if (rst) q <= 4'd0;
        else if (en) q <= q + 4'd1;
    end
endmodule
"""


def _heal_demo(request: str) -> bool:
    r = request.lower()
    return "self-heal" in r or "broken" in r or "forget" in r or "demo self" in r


def answer(request: str, attempt: int) -> str:
    if _heal_demo(request):
        if attempt == 1:
            d = {
                "rtl": COUNTER_BAD_EN,
                "notes": "4-bit sync counter. (Intentionally ignores en on attempt 1 for self-heal demo.)",
            }
        else:
            d = {
                "rtl": COUNTER_OK,
                "notes": "Fix: honor en — hold when en=0; reset still has priority. Mod-16 wrap on overflow.",
            }
    else:
        d = {
            "rtl": COUNTER_OK,
            "notes": "4-bit synchronous up-counter; rst priority; en increments mod 16; else hold.",
        }
    return json.dumps(d)
