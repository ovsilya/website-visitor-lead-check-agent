# Diagrams

Click a preview for the full-size image. The interactive HTML version opens on GitHub Pages.

### Architecture overview
How the pieces fit together on Google Cloud: sign-in, the agent and the rules tool on Cloud Run, Gemini, and what comes later

<a href="png/architecture-overview.png"><img src="png/architecture-overview.png" width="720" alt="Architecture overview"></a>

[Open interactive version](https://ovsilya.github.io/website-visitor-lead-check-agent/diagrams/architecture-overview.html)

### Lead check rules
The four checks, points and top N per account, with an example answer

<a href="png/lead-check-rules.png"><img src="png/lead-check-rules.png" width="720" alt="Lead check rules"></a>

[Open interactive version](https://ovsilya.github.io/website-visitor-lead-check-agent/diagrams/lead-check-rules.html)

### App code overview
One Python process on Cloud Run: access check, ADK API, plugin, agent, tool, memory-only storage

<a href="png/app-code-overview.png"><img src="png/app-code-overview.png" width="720" alt="App code overview"></a>

[Open interactive version](https://ovsilya.github.io/website-visitor-lead-check-agent/diagrams/app-code-overview.html)

### Agent internals
How the app uses ADK: runner, plugin hooks, tool context, artifacts, the rules engine

<a href="png/agent-internals.png"><img src="png/agent-internals.png" width="720" alt="Agent internals"></a>

[Open interactive version](https://ovsilya.github.io/website-visitor-lead-check-agent/diagrams/agent-internals.html)

### Data flow and privacy
Where personal data goes and where it doesn't

<a href="png/data-flow-and-privacy.png"><img src="png/data-flow-and-privacy.png" width="720" alt="Data flow and privacy"></a>

[Open interactive version](https://ovsilya.github.io/website-visitor-lead-check-agent/diagrams/data-flow-and-privacy.html)

### Target architecture
Hub-and-spoke target with Gemini Enterprise (A2A), AI gateway and a weekly run

<a href="png/target-architecture.png"><img src="png/target-architecture.png" width="720" alt="Target architecture"></a>

[Open interactive version](https://ovsilya.github.io/website-visitor-lead-check-agent/diagrams/target-architecture.html)

### Terraform cicd deployment
Terraform and app-release lanes across three environments

<a href="png/terraform-cicd-deployment.png"><img src="png/terraform-cicd-deployment.png" width="720" alt="Terraform cicd deployment"></a>

[Open interactive version](https://ovsilya.github.io/website-visitor-lead-check-agent/diagrams/terraform-cicd-deployment.html)

---

**Anonymized.** People are replaced by roles, the company by "the company", cloud project IDs and repo names by placeholders, and client accounts by fictional names. Some diagrams mention a *legacy weekly report* the agent could run for comparison; that tool is not part of this repository.
