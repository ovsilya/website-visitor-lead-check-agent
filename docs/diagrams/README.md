# Diagrams

Open any file in a browser. They are standalone HTML (no external assets).

| File | What it shows |
|---|---|
| [lead-check-rules.html](lead-check-rules.html) | The agreed approach: the four checks (who · which · what · rule out), points, top N per account, and an example answer |
| [app-code-overview.html](app-code-overview.html) | One Python process on Cloud Run: access check, ADK API, upload plugin, agent, tool, memory-only storage, accounts and permissions, code map |
| [agent-internals.html](agent-internals.html) | How the app uses ADK: runner, plugin hooks, tool context, artifacts, the rules engine step by step, tests |
| [data-flow-and-privacy.html](data-flow-and-privacy.html) | Where personal data goes (and doesn't): upload → memory → rules → model (counts and titles only) → download once |
| [target-architecture.html](target-architecture.html) | Hub-and-spoke target: Gemini Enterprise (A2A import) in the hub, the agent in the business unit's own project, central AI gateway, weekly scheduled run |
| [terraform-cicd-deployment.html](terraform-cicd-deployment.html) | Two lanes to production: infrastructure via Terraform (plan/apply on git tags) and app release via Cloud Build, three environments |

**Anonymized.** People are replaced by roles, the company by "the company", cloud project IDs and repo names by placeholders, and client accounts by fictional names (Globex, Initech, …). Internal decision-log IDs are removed. Some diagrams still mention a *legacy weekly report* that the agent could run for comparison. That tool reproduced a colleague's script and is **not** part of this repository.
