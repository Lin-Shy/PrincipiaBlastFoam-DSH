# principia-blastfoam-dsh-bundle

Installable DeepSeek Harness configuration bundle for PrincipiaBlastFoam. It contributes one policy plugin, the Python retrieval MCP connection, and five role-specific tools over the official in-process `spawn` subagent provider.

The bundle assumes it is layered after `@deepseek-ai/dsh-base`; it deliberately does not register another `spawn` provider because provider names are process-global and the official base already owns that registration. The DSH application runtime supplies `@deepseek-ai/dsh-tool-subagent` and `@deepseek-ai/dsh-mcp-client`; this bundle does not install private copies that could split Cordis service identity. Compatibility pins their host-supplied versions in the repository's `compatibility/dsh-version.json`.

DSH's current subagent `toolFilter` controls tool names, not filesystem paths. Role filters therefore use allowlists: the reviewer receives only `read`, `glob`, `grep`, and `skill`, and returns structured review content. The parent or a deterministic writer materializes the three review artifacts; prompt text is not treated as a path-level security control. Physics and setup deliberately fail closed if their allowlisted MCP tools were not discovered.

Build and test:

```bash
npm install
npm run check
npm pack
```

The checked-in `lib/` output makes local-path and tarball installation loadable without authorizing an install-time build script. Before booting DSH, set `PRINCIPIA_PROJECT_ROOT` and optionally `PRINCIPIA_PYTHON`, `BLASTFOAM_TUTORIALS`, and `PRINCIPIA_KNOWLEDGE_GRAPH` in the DSH environment. Solver execution and strict execution artifacts default on through `ENABLE_EXECUTION=true` and `REQUIRE_EXECUTION=true`; set both false explicitly for a non-executing session.
