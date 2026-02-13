# Roadmap

## Phase 1: Quick Launch ✦ NOW
OpenClaw sessions, SQLite, wizard. Get it running on a $5 VPS in under 10 minutes.

- [ ] `install.sh` — checks for OpenClaw, installs if missing, launches wizard
- [ ] Wizard TUI (gum) — use case, models, API keys, integrations, agent mode
- [ ] Config generation from Jinja2 templates
- [ ] SQLite schema — message bus, memory tables, knowledge cache, embeddings
- [ ] Brain agent as main OpenClaw session (single-agent mode)
- [ ] Memory engine — store/retrieve with importance + recency scoring
- [ ] Agent interface (portable abstraction over OpenClaw sessions)
- [ ] Multi-agent: Brain spawns Builder, Verifier, Researcher, Guardian
- [ ] Context scoping — Brain filters what each agent sees
- [ ] Sub-agent pools for Builder (parallel builds) and Researcher (parallel search)
- [ ] Knowledge cache with verified facts (no decay)
- [ ] Basic cost tracking via Guardian

## Phase 1.5: Project Mode & GitOps ✦ DONE
Structured project management and basic version control.

- [x] ProjectManager — SQLite-backed project/task tracking
- [x] Spec Writer — LLM-powered SPEC.md generation from user ideas
- [x] Task Decomposer — Breaks specs into ordered, agent-assigned tasks
- [x] Brain integration — Project intent detection, creation, task advancement
- [x] GitOps (free tier) — auto-commit, pre-commit secret scanning, status, log, rollback
- [x] Pre-commit hook — Guardian credential scanner blocks secrets from commits
- [x] Wizard integration — git init + hook install during deploy step

## Pro Tier (Future)
Advanced features for power users and teams.

- [ ] Parallel task execution (Builder + Researcher simultaneously)
- [ ] Multiple concurrent projects with priority management
- [ ] Sprint planning with velocity tracking
- [ ] Dependency graph visualization (Mission Control frontend)
- [ ] Branch-per-feature with automated PR creation + Guardian review
- [ ] CI/CD pipeline (auto-test, auto-deploy on merge)
- [ ] War Room mode (watch agents discuss in real-time group chat)
- [ ] Smart model routing (cheap models for simple tasks, expensive for complex)
- [ ] Team analytics (agent performance, bottleneck detection)
- [ ] One-command rollback
- [ ] Multi-repo project management
- [ ] GitHub Actions integration
- [ ] Remote GitOps (push to VPS from GitHub)

## Future: Hardened Build
Docker containers with proper isolation. For users who want security boundaries between agents.

- [ ] Dockerfiles per agent
- [ ] Docker Compose orchestration
- [ ] Network isolation (sandbox for Builder, external for Researcher/Verifier)
- [ ] Resource limits per container (CPU, memory, disk)
- [ ] Optional Redis message bus (replaces SQLite bus for multi-container)
- [ ] Volume-based memory sharing with permissions
- [ ] Health checks and auto-restart

## Future: Plugin System
Let users add custom agents without forking.

- [ ] Agent plugin spec (interface, manifest, permissions declaration)
- [ ] Plugin discovery and installation via wizard
- [ ] Sandboxed plugin execution
- [ ] Community plugin registry

## Future: Mission Control Frontend
Web UI for monitoring and managing the agent system.

- [ ] Real-time agent activity dashboard
- [ ] Message bus inspector
- [ ] Memory browser and search
- [ ] Cost tracking charts
- [ ] Config editor with validation
- [ ] Session management (start/stop/restart agents)

## Future: Model Fallback Chains
Resilient model selection with automatic failover.

- [ ] Primary → fallback → emergency model chain per agent
- [ ] Automatic failover on rate limit, timeout, or error
- [ ] Cost-aware routing (cheaper model for simple tasks)
- [ ] Quality monitoring — detect degraded responses and escalate
- [ ] Provider health tracking
