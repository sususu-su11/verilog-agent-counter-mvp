"""Map natural-language requests onto the supported MVP family (counter first)."""
from __future__ import annotations

COUNTER_HINTS = (
    "counter", "计数", "计数器", "up-counter", "up counter", "count enable",
    "4-bit", "4 bit", "modulo", "wrap",
)


def detect_family(request: str) -> str:
    r = request.lower()
    # MVP: only counter is fully wired. Other keywords still map to counter with a note,
    # unless clearly another family — then we still refuse non-counter for now.
    if any(k in r for k in ("uart", "serial", "串口", "fifo", "queue", "队列", "fsm", "状态机", "pwm")):
        if any(k in r for k in ("uart", "serial", "串口")):
            return "unsupported:uart"
        if any(k in r for k in ("fifo", "queue", "队列")):
            return "unsupported:fifo"
        if any(k in r for k in ("fsm", "状态机")):
            return "unsupported:fsm"
        if "pwm" in r:
            return "unsupported:pwm"
    return "counter"


def family_spec_text(family: str) -> str:
    if family != "counter":
        return ""
    return (
        "Family: synchronous 4-bit up-counter.\n"
        "Exact module interface (names and widths are mandatory):\n"
        "  module dut(\n"
        "      input  wire       clk,\n"
        "      input  wire       rst,   // active-high, synchronous, priority over en\n"
        "      input  wire       en,\n"
        "      output reg  [3:0] count\n"
        "  );\n"
        "Semantics: on rising clk, if rst then count<=0; else if en then count<=count+1 (mod 16); else hold.\n"
        "No async reset. Synthesizable Verilog-2005 only.\n"
    )
