# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow Odoo's `<series>.<major>.<minor>.<patch>.<build>` tagging
convention (e.g. `v19.0.1.0.0`).

## [1.0.0] - 2026-07-21

Initial release, for Odoo 19.0, tagged `v19.0.1.0.0`. Requires
[Helpdesk Pro](https://github.com/Zahoor-ishfaq/odoo-helpdesk-pro)
(`helpdesk_community_pro`) and your own Anthropic API key.

### Added

- **AI Settings** — admin-only Anthropic API key storage (masked,
  write-only, format-validated on save), model selector (Claude Haiku
  4.5 / Sonnet 4.6 / Opus 4.6), and a per-team `ai_enabled` opt-in with
  a configurable auto-apply confidence threshold.
- **`anthropic_client.py`** — the single point of contact for every
  Anthropic API call: stdlib-only HTTP, hard 30s timeout, SSL
  certificate validation always on, typed non-raising results, never
  logs a raw prompt or response.
- **Smart Triage** — on ticket create, Claude suggests a team,
  priority, and tags with a confidence score. High-confidence
  suggestions apply automatically; low-confidence ones show as a
  chatter banner with Accept/Dismiss. A ticket is only ever triaged
  once.
- **Sentiment Detection** — `message_new`/`message_update`/`message_post`
  hooks queue a sentiment check for genuine inbound messages (email or
  portal/chatter, never an agent's own note); a cron scores calm /
  neutral / frustrated / angry every 5 minutes in batches of 20. Angry
  sentiment bumps priority to Urgent and notifies the team's managers
  via activity.
- **Reply Assistant** — a "Draft Reply" wizard builds a lightweight RAG
  prompt from the ticket's recent conversation plus up to 5 similar
  resolved tickets on the same team, drafts an editable reply, and
  lets the agent stage it into the chatter as an internal note. The AI
  never sends to the customer — the agent always reviews and sends.
- **Usage Dashboard** — `helpdesk.ai.log` pivot/graph views (rows by
  team, columns by call type; tokens, cost estimate, and count as
  measures), an accurately-priced `cost_estimate` (prompt/completion
  tokens costed separately at Haiku's published rate, 6-decimal
  precision), and a per-team **AI Accuracy** stat button.
- **Demo data** — two AI-enabled teams and eight tickets in a Saudi
  business context, covering auto-applied and banner-pending triage,
  all four sentiment states (including two auto-escalated angry
  tickets), and two tickets with a reply draft already staged —
  showing all three AI features working from the moment demo data
  installs.
- **Arabic (`ar`) translation** — full UI translation using a Gulf
  business register, alongside the English source strings.
- **Security** — every prompt field truncated and stripped of HTML;
  customer email/phone never included in a prompt; API key
  admin-only, encrypted at rest, masked in the UI; `helpdesk.ai.log`
  stores only token counts and short summaries, never raw prompts or
  responses.
- **Tests** — full suite mocking the Anthropic API (never called for
  real in CI), covering triage, sentiment, the reply wizard, API-key
  validation, access control, and the usage dashboard.
