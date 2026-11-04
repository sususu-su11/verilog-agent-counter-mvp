# LabLab submission copy — evidence-conscious English

## Title

Blast Radius Zero — Verilog Agent

## Tagline

An RTL-generation agent that never grades its own code.

## Short summary (card)

Vultr Serverless Inference proposes Verilog RTL. A fixed trusted testbench runs inside a resource-limited Docker sandbox, and a host-side Python oracle—not the model—issues PASS/FAIL. When a candidate fails, the agent edits RTL and reruns the same frozen tests. Counter MVP; public demo uses fixed MOCK cases.

## The problem

An AI coding agent can hallucinate success, weaken its own tests, or print a convincing “PASS.” A Verilog simulation is not trustworthy if the generating model controls both the implementation and the verdict.

## The solution

We separate model generation from verification. Vultr Serverless Inference can emit only candidate `dut.v`. A preflight policy rejects disallowed constructs before compilation. A host-owned testbench drives immutable vectors and prints observations, which an independent Python reference checks. The only authoritative green verdict comes from `trusted/verdict.py`. A self-heal loop may modify RTL, but not the testbench, oracle, vectors, or pass criteria.

## Technology

Vultr Serverless Inference (OpenAI-compatible API); Python/FastAPI; Icarus Verilog; Docker (`--network none`, memory/CPU/PID caps, read-only root filesystem); host-side oracle; static source preflight; MIT license.

## Demonstration scope

A working **4-bit synchronous counter** path with reset, enable, and wraparound tests. A deliberately broken enable path produces a host FAIL; a fixed subsequent candidate can PASS the same trusted suite. The public site intentionally offers fixed MOCK examples, not arbitrary user RTL or live inference. A separate operator-only private live run may demonstrate Vultr Serverless Inference when verified evidence is attached.

## Trust and limitations

The self-heal visualization and fixed demo are not proof of model live usage. Passing a finite counter suite is not formal equivalence. The public fixed MOCK VM permits rootful Docker by operator choice; a compromised backend with access to the Docker socket can still compromise the host. Containment claims must be backed by target-VM probe footage, sentinel results, and container-cleanup logs, not merely by UI labels.

## Evidence checklist for submission

- [ ] GitHub Actions `tests` green at submitted commit
- [ ] GitHub Actions `docker-containment-regression` green at submitted commit
- [ ] Verified public fixed MOCK URL
- [ ] VM console: network and resource-limit probes, sentinel read denied, chaos TB forged text rejected, containers removed
- [ ] Vultr Serverless Inference redacted request/response (or live capture), independent of public MOCK
- [ ] 75–90 second video with on-screen `MOCK` / `LIVE` distinctions
- [ ] Presentation link or PDF export (do not misstate evidence)
- [ ] MIT license and source repo link

## Links

Source: https://github.com/sususu-su11/verilog-agent-counter-mvp

Demo website: **pending confirmed URL — do not invent one**.

## Claims to avoid

- “Zero blast radius is proven” (only bounded containment tests are offered)
- “Arbitrary Verilog verified” (restricted counter MVP)
- “Live inference in public demo” (public fixed MOCK mode)
- “Formal verification” (finite simulation-based checking)
- “All CI green” unless checked on the final commit
