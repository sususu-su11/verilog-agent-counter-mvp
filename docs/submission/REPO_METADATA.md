# GitHub About and Topics — operator copy/paste

GitHub's repository metadata update API is not available under the current read-only GitHub connection. The text below is **prepared, not published**. Only add a demo website after the operator confirms a working public URL. **Do not use the GitHub repository link as a fake demo URL.**

## Description (About)

AI generates Verilog; a host-owned oracle verifies it. Fixed testbench, Docker sandbox, self-heal loop. Vultr Inference + Icarus Verilog.

## Website

Leave blank until the operator confirms the actual working HTTPS demo URL. In GitHub, Settings → General → About / edit repository details → Website.

## Topics

`verilog`, `rtl-verification`, `vultr`, `llm-agent`, `docker`, `iverilog`, `trusted-oracle`, `self-healing`, `hackathon`

## Steps

1. Open repository landing page → About gear icon. Paste Description.
2. Paste the **verified** demo URL only; enable website display.
3. Add each Topic. Save.
4. Confirm About/About website/topics display on the public page.

## Optional GitHub CLI (for an authenticated repository owner only)

```bash
# Fill DEMO_HTTPS_URL with the verified public URL or omit --homepage.
gh repo edit sususu-su11/verilog-agent-counter-mvp \
  --description 'AI generates Verilog; a host-owned oracle verifies it. Fixed testbench, Docker sandbox, self-heal loop. Vultr Inference + Icarus Verilog.'
# gh repo edit sususu-su11/verilog-agent-counter-mvp --homepage "$DEMO_HTTPS_URL"
```

GitHub CLI topic update can be done through the About gear without sharing additional tokens with the project.
