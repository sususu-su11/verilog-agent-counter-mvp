"""Independent golden models. Host-side only — never shipped into the LLM prompt."""
from __future__ import annotations

import json
from pathlib import Path

TRUSTED = Path(__file__).resolve().parent


def counter_step(count: int, rst: int, en: int) -> int:
    if rst:
        return 0
    if en:
        return (count + 1) & 0xF
    return count


def load_counter_vectors() -> dict:
    return json.loads((TRUSTED / "vectors" / "counter.json").read_text())


def expected_counter_trace(vectors: dict | None = None) -> list[dict]:
    """Return per-step expected POST count (and PRE = previous POST)."""
    vectors = vectors or load_counter_vectors()
    count = 0  # undefined until first sync reset; we start assuming X but step0 resets
    # Spec: before any clock, outputs may be X; we only check POST[0] after rst.
    # Initialize latent state as 0 for oracle bookkeeping; PRE[0] is omitted.
    state = 0
    out = []
    for row in vectors["steps"]:
        step = row["step"]
        rst, en = int(row["rst"]), int(row["en"])
        pre = state if step > 0 else None
        state = counter_step(state, rst, en)
        out.append({"step": step, "rst": rst, "en": en, "pre": pre, "post": state})
    return out


FAMILIES = {
    "counter": {
        "suite_id": "counter4_sync_v1",
        "module": "dut",
        "ports": {
            "clk": ("input", 1),
            "rst": ("input", 1),
            "en": ("input", 1),
            "count": ("output", 4),
        },
        "outputs": ["count"],
        "tb_file": "tb_counter.sv",
        "vector_file": "vectors/counter.json",
        "expected_steps": 22,
        "expected_records": 87,  # see tb_counter.sv
    }
}
