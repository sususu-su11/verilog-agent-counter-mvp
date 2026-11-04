# Throwaway simulation sandbox: Icarus Verilog + Verilator (lint) + tiny runner. No secrets, no network at runtime.
FROM debian:bookworm-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3
RUN apt-get update \
 && apt-get install -y --no-install-recommends iverilog verilator python3 \
 && rm -rf /var/lib/apt/lists/*
COPY runner.py /opt/runner.py
COPY probe.py /opt/probe.py
# Unprivileged user; the container is additionally run with --user 65534, read-only rootfs, no caps.
USER 65534:65534
WORKDIR /work
ENTRYPOINT ["python3", "/opt/runner.py"]
