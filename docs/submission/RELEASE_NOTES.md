# Counter MVP — repository and submission asset update

Base: `44ccbcff5d8a51686b9824ce737f77ec562f8282` (GitHub `main` at time of preparation).

## CI fix

`.github/workflows/verify.yml` now explicitly exports `SANDBOX_IMAGE=verilog-sandbox:local` for `docker-containment-regression` and checks that this image exists after `docker build -t verilog-sandbox:local ./sandbox`. This removes the observed `:latest` versus `:local` mismatch. **A green remote CI run is not claimed.**

## Repository cleanup and interface copy

- Removed historical `PATCH_REPORT_CN.md`, `PATCH_V3.diff`, `PUSH_INSTRUCTIONS.md`.
- Removed old UART/FIFO/PWM and irrelevant UI screenshots from this counter-only release. Kept local counter verdict/waveform samples.
- Clarified in README and fixed-public-MOCK UI that there is no live inference in public demo.
- Updated `trusted/manifest.json` for the changed protected JavaScript file.

## Submission materials

- `cover_1920x1080.png`: project cover.
- `Blast_Radius_Zero_Verilog_Agent.pptx`: eight slides.
- `SUBMISSION_COPY.md`: project/card text with explicit evidence boundary.
- `REPO_METADATA.md`: prepared About/topics. The website URL must be provided after a working HTTPS site is verified.

Video editing and recordings are reserved for the operator and intentionally excluded from this update.

## Evidence boundary

- `python -m trusted.verify_manifest`: passed locally.
- `python -m unittest discover -s tests -v`: 22 passed locally.
- Static script and JavaScript checks: passed locally.
- Real Docker CI, Vultr live Inference, public VM and LabLab submission: **not verified by this release author**.
- GitHub connector is read-only (`push=false`): commit/bundle supplied for user-authorized push.
