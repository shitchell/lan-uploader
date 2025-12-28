# Project Instructions for Claude

## Multi-Level Supervisor System

This project uses a hierarchical supervisor system for automated ticket implementation.

### Hierarchy

```
Human
  └─► Supervisor0 (top-level agent for ticket/implementation orchestration)
        └─► claude --agent {workflow}-supervisor --dangerously-skip-permissions -p "ticket_dir: ..."
              │
              Supervisor1 (Claude Code agent in .claude/agents/)
              ├─► Ensures chunks/ directory exists for ticket
              └─► claude --dangerously-skip-permissions -p "Read identity file..."
                    │
                    Supervisor2 (reads _work/identities/{workflow}/00_supervisor.md)
                    └─► Task(subagent_type="general-purpose") → Analyst/Developer/Tester/Validator
```

**Note:** If reading this file as a sub-agent, your identity will be provided to you explicitly. If no identity was provided, you are Supervisor0.

### Available Workflows

| Workflow | Agent | Identity Directory |
|----------|-------|--------------------|
| Feature implementation | `feature-supervisor` | `_work/identities/feature/` |
| Bug fixes | `bugfix-supervisor` | `_work/identities/bugfix/` |
| Test coverage | `test-coverage-supervisor` | `_work/identities/test-coverage/` |

### How to Launch a Supervisor

Supervisor0 launches the appropriate supervisor for a ticket via Bash (NOT via Task tool):

```bash
# For features/enhancements
claude --agent feature-supervisor --dangerously-skip-permissions -p "You are the feature-supervisor (Supervisor1). Your job is to oversee feature implementation for ticket_dir: _work/tickets/open/XXX-ticket-name"

# For bug fixes
claude --agent bugfix-supervisor --dangerously-skip-permissions -p "You are the bugfix-supervisor (Supervisor1). Your job is to oversee bugfix implementation for ticket_dir: _work/tickets/open/XXX-ticket-name"

# For test coverage
claude --agent test-coverage-supervisor --dangerously-skip-permissions -p "You are the test-coverage-supervisor (Supervisor1). Your job is to oversee test coverage implementation for ticket_dir: _work/tickets/open/XXX-ticket-name"
```

### What Each Level Does

**Supervisor0 (Top-Level Orchestrator):**
- Receives request from human
- Determines appropriate workflow (feature, bugfix, test-coverage)
- Launches the corresponding `-supervisor` agent via Bash

**Supervisor1 (Claude Code Agent):**
- Ensures `chunks/` directory exists in the ticket directory
- If no chunks exist, creates `chunks/001/` and symlinks ticket docs into it
- Reads identity file to discover required variables
- Launches a chunk-level supervisor for each chunk via `claude --dangerously-skip-permissions -p "..."`

**Supervisor2 (Chunk Supervisor):**
- Reads `_work/identities/{workflow}/00_supervisor.md` for workflow instructions
- Dispatches agents in sequence via Task tool: Analyst → Developer → Tester → Validator
- Handles retries, human review triggers, and attempt archival

### Chunks Paradigm

ALL work uses chunks. Even single-task tickets get a `chunks/001/` directory. This ensures consistent structure and allows for future expansion.

### Key Constraint

**Tasks cannot spawn sub-Tasks.** Only top-level Claude instances have the Task tool. This is why:
- Supervisor1 uses `claude --dangerously-skip-permissions -p` to launch Supervisor2
- Supervisor2 uses Task tool to dispatch individual agents

### Tickets Location

Open tickets are in `_work/tickets/open/`. Each ticket directory contains markdown files describing the work to be done.
