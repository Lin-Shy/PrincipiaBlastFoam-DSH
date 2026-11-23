# Linux DSH Web human acceptance

The normal entry is deployment/web/serve_web.py under the Linux workspace virtual environment. Node/pnpm live in workspace/runtime; source remains in the authoritative Linux application and deepseek-harness worktrees. Windows opens the loopback service through an SSH tunnel; no DSH backend or model credential runs in the browser.

Verified 2026-11-23: workspace selection, real deepseek-v4.1-flash reply, one principia_domain.get_status call with expanded input/output, trajectory display, history after refresh and service restart, and SSH tunnel reconnection. One initial transport failure remains unknown in the ledger; the user explicitly approved one manual recovery. Three requests total, two settled, one unknown, 21002 reported tokens. The independent cap remains 100 and persists across restarts. No solver or batch experiment was launched.

This validates basic interaction and a read-only status tool, not every domain tool, unattended long runs, host-reboot auto-start or full batch readiness. There is no automatic retry of unknown requests and no budget rollover into research experiments. The one-off ledger recovery was an explicit maintenance decision, not a default mechanism.

Private model configuration, generated Web URL/token, logs, session state and request bodies stay outside Git in workspace/services/chapter3-web-20261123. browser_url.py returns the current process login URL to the local opener; do not paste that URL into reports. The original single-case acceptance source snapshot remains separately identified; this Web overlay does not retroactively replace its tool composition or source identity.

Local mesh implementation (2026-11-23): use mesh_case for bounded local blockMesh/checkMesh; real 1,000-cell creation and Mesh OK check passed. Current bounds and pinned tool version: deployment/local_mesh/README.md. Full solver execution remains HPC-only. No batch experiment was started.
