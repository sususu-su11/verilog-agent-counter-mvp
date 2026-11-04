"""Tiny VCD parser -> JSON-friendly waveform data, plus a matplotlib PNG renderer."""
import io

MAX_SIGNALS = 32


def parse(text: str) -> dict:
    ids, order, scope, timescale = {}, [], [], "1ns"
    changes = {}
    t = 0
    end_time = 0
    tokens = iter(text.split())
    in_header = True
    for tok in tokens:
        if in_header:
            if tok == "$timescale":
                parts = []
                for x in tokens:
                    if x == "$end":
                        break
                    parts.append(x)
                timescale = "".join(parts)
            elif tok == "$scope":
                next(tokens); scope.append(next(tokens)); next(tokens)
            elif tok == "$upscope":
                scope.pop() if scope else None; next(tokens)
            elif tok == "$var":
                _kind, width, ident, ref = next(tokens), int(next(tokens)), next(tokens), next(tokens)
                rest = next(tokens)
                if rest != "$end":      # bit-range like [3:0]; width already known
                    next(tokens)
                full = ".".join(scope + [ref])
                if _kind in ("integer", "real", "event", "parameter"):
                    continue                # testbench bookkeeping, not hardware
                if ident not in ids:
                    ids[ident] = {"name": full, "width": width, "changes": []}
                    order.append(ident)
            elif tok == "$enddefinitions":
                next(tokens); in_header = False
            continue
        if tok.startswith("#"):
            t = int(tok[1:]); end_time = max(end_time, t)
        elif tok in ("$dumpvars", "$end", "$dumpall", "$dumpon", "$dumpoff"):
            continue
        elif tok[0] in "bBrR":
            val = tok[1:]
            ident = next(tokens)
            if ident in ids:
                ids[ident]["changes"].append([t, val])
        elif tok[0] in "01xXzZ" and len(tok) > 1:
            ident = tok[1:]
            if ident in ids:
                ids[ident]["changes"].append([t, tok[0]])
    # dedupe by name, prefer shallow (tb-level) signals first
    seen, sigs = set(), []
    def rank(i):
        n = ids[i]["name"]; leaf = n.rsplit(".", 1)[-1]
        return (n.count("."), 0 if leaf in ("clk", "clock") else 1 if leaf in ("rst", "reset", "rst_n") else 2)
    for ident in sorted(order, key=rank):
        s = ids[ident]
        if s["name"] in seen:
            continue
        seen.add(s["name"])
        sigs.append(s)
    return {"timescale": timescale, "end": end_time, "signals": sigs[:MAX_SIGNALS],
            "total_signals": len(sigs)}


def _to_int(v):
    try:
        return int(v, 2)
    except ValueError:
        return None


def render_png(wave: dict, title: str = "", max_signals: int = 16) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sigs = [s for s in wave["signals"] if s["changes"]][:max_signals]
    end = max(wave["end"], 1)
    fig, ax = plt.subplots(figsize=(14, 0.55 * len(sigs) + 1.2), dpi=110)
    for row, s in enumerate(sigs):
        y0 = len(sigs) - 1 - row
        ch = s["changes"] + [[end, s["changes"][-1][1]]]
        for (ta, va), (tb, _vb) in zip(ch, ch[1:]):
            if tb <= ta and ta != end:
                continue
            if s["width"] == 1:
                lvl = {"1": 0.7, "0": 0.1}.get(va.lower(), 0.4)
                color = "#1f77b4" if va in "01" else "#d62728"
                ax.plot([ta, tb], [y0 + lvl] * 2, color=color, lw=1.4)
                ax.plot([ta, ta], [y0 + 0.1, y0 + 0.7], color=color, lw=0.6, alpha=0.5)
            else:
                ax.fill_between([ta, tb], y0 + 0.1, y0 + 0.7, color="#e8f0fb", edgecolor="#1f77b4", lw=0.8)
                n = _to_int(va)
                label = f"{n:X}" if n is not None else va
                if (tb - ta) > end / 60:
                    ax.text((ta + tb) / 2, y0 + 0.4, label, ha="center", va="center", fontsize=7)
        ax.text(-end * 0.005, y0 + 0.4, s["name"].split(".", 1)[-1], ha="right", va="center", fontsize=8)
    ax.set_xlim(0, end); ax.set_ylim(-0.2, len(sigs))
    ax.set_yticks([]); ax.set_xlabel(f"time ({wave['timescale']} units)")
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.set_title(title, fontsize=10, loc="left")
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    return buf.getvalue()
