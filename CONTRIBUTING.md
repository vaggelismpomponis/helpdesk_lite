# Contributing to HelpDesk Lite

This is the team agreement for HelpDesk Lite: how we work together, branch, commit, review and decide when something is done. Every team member follows it.

> **Status: draft.** Items marked _TBD_ are still open. Decisions are tracked in the [CONTRIBUTING log](./docs/CONTRIBUTING_LOG.md) and moved here once the team agrees on them.

## Table of Contents

1. [Team and Communication](#team-and-communication)
2. [Branching](#branching)
3. [Commit Messages](#commit-messages)
4. [Pull Requests and Reviews](#pull-requests-and-reviews)
5. [Code Conventions](#code-conventions)
6. [Definition of Done](#definition-of-done)
7. [Changing This Agreement](#changing-this-agreement)

## Team and Communication

| Topic | Agreement |
|-------|-----------|
| Roles | Platform, Interface, Workflow, Knowledge, Quality. Each has a primary owner and a backup: _TBD_ (see [roles](./docs/roles/README.md)). |
| Ownership | No silos. A primary owner leads an area, but nobody holds exclusive knowledge of it. Every member commits code. |
| Communication channel | _TBD_ |
| Daily stand-up | 10–15 minutes; asynchronous is acceptable. Time and channel: _TBD_ |
| Pair/mob session | One mid-week session each week. Day and time: _TBD_ |
| Integration time | Weekly. |

## Branching

We use two permanent branches and short-lived task branches. The [Git Guide](./docs/GIT_GUIDE.md) has step-by-step commands and Codeberg walkthroughs.

- `main` is the release branch. `develop` is the integration branch. Both are protected: never commit or push to them directly.
- Create every branch from an up-to-date `develop`.
- One branch per task. Names are lowercase with hyphens and use a prefix:

| Prefix | Use for | Example |
|--------|---------|---------|
| `feature/` | New capability | `feature/ticket-creation` |
| `bugfix/` | Bug fix | `bugfix/login-error` |
| `hotfix/` | Urgent fix | `hotfix/fix-crash` |
| `docs/` | Documentation | `docs/update-readme` |

- Never run `git push --force`, `git reset --hard` or `git rebase` on a branch someone else uses.

## Commit Messages

We follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/).

```text
<type>(<scope>): <subject>

<body>

<footer>
```

- English, imperative mood: "add", not "added" or "adds".
- Subject: at most 72 characters, lowercase after the colon, no trailing period.
- Body (optional): explain **what** and **why**, wrapped at 100 characters.
- One logical change per commit. Do not mix refactoring, formatting and behavior changes.
- Reference issues in the footer: `Refs: #12` or `Closes: #12`.
- Mark breaking changes with `!` after the type or scope and a `BREAKING CHANGE:` footer.

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `build`, `perf`, `style`, `revert`.

**Scopes:** `graph`, `ui`, `policy`, `neo4j`, `db`, `approval`, `eval`, `docker`, `docs`, `deps`.

```text
feat(approval): pause graph before account-changing actions

Add an interrupt node that waits for human approval and persists the
action_id so the flow resumes after an application restart.

Closes: #14
```

## Pull Requests and Reviews

- Open pull requests into `develop`. The title follows the commit format: `<type>(<scope>): <subject>`.
- The description states what changed, why, and how it was tested, and links the issue with `Closes #<n>`.
- Keep pull requests small: under 300 changed lines.
- At least one reviewer approves. No self-merge: the reviewer merges.
- Reviews happen within 24 hours. Reviewers rotate (see the [proposed rotation](./docs/roles/README.md)).
- Merge into `develop` with **Squash**. Release pull requests from `develop` into `main` use a **Merge commit**.
- After merging, the reviewer deletes the remote task branch. `main` and `develop` are never deleted.

### Before Opening a Pull Request

- [ ] The branch is based on the latest `develop`.
- [ ] The code runs and the tests pass.
- [ ] No secrets, credentials or stray files are included.
- [ ] Commit messages follow the convention above.
- [ ] Any new dependency is justified in the description.

## Code Conventions

- Python with type hints. Use Pydantic models for state, tool inputs and outputs.
- **Contracts first.** The state schema, Pydantic models and tool signatures are agreed before implementation. Contracts file: _TBD_
- Keep LangGraph nodes small and single-purpose. Map `thread_id` consistently to the Chainlit session.
- Every state-changing action (credential reset, ticket creation) requires explicit human approval and must be idempotent: persist the `action_id` and its status (`pending`, `approved`, `executed`) and check it before executing.
- Store `doc_id` and `effective_date` with every policy chunk. Retrieval returns the latest effective version and cites it.
- If an application depends on a service with an active outage, propose *link to outage*, not a credential reset.
- Never hardcode credentials. Read configuration from environment variables, keep `.env` out of version control and keep `.env.example` up to date.
- Do not add dependencies without a clear need.

## Definition of Done

A task is done when its pull request is merged into `develop` with passing tests and an approving review. The project as a whole is done when it meets the [Definition of Done in the README](./README.md#definition-of-done).

## Changing This Agreement

1. Propose the change in a meeting, issue or pull request.
2. Record it in the [CONTRIBUTING log](./docs/CONTRIBUTING_LOG.md).
3. Once the team agrees, update this file through a pull request with a `docs` commit.
