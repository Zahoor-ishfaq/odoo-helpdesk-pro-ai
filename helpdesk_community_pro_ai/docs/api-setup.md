# Getting an Anthropic API Key

Helpdesk AI Copilot brings your own Anthropic API key — there's no
markup, no reseller, and Anthropic bills you directly for what you
use.

## 1. Create an account and a key

1. Go to [console.anthropic.com](https://console.anthropic.com) and
   sign up (or sign in).
2. Under **API Keys**, click **Create Key**. Give it a name you'll
   recognize later, e.g. `odoo-helpdesk-prod`.
3. Copy the key immediately — it starts with `sk-ant-` and is shown
   only once. If you lose it, delete it and create a new one.

## 2. Set a spending limit (strongly recommended)

Before pasting the key into Odoo, set a monthly budget so a runaway
loop or unexpectedly high ticket volume can't produce a surprise bill:

1. In the Anthropic Console, go to **Settings ▸ Billing ▸ Usage
   limits**.
2. Set a **Monthly spend limit**. For the pricing example below (100
   tickets/day, Haiku), $10–15/month leaves comfortable headroom.
3. Optionally set an **email alert threshold** (e.g. 80% of the limit)
   so you hear about it before the limit is hit.

## 3. Paste the key into Odoo

1. Go to **Settings ▸ General Settings ▸ Helpdesk AI**.
2. Paste the key into **Anthropic API Key** and save.
3. The field is write-only — once saved, it's never shown again, only
   an **API Key Configured** ✓ indicator. Paste a new key to replace
   it; leave the field blank to keep the current one.

Only administrators (`base.group_system`) can read or write this
setting. It's stored in `ir.config_parameter`, never in source code,
git, or logs.

## 4. Pick a model

Under the same settings page, choose an **AI Model**:

| Model | Relative cost | Use it when |
|---|---|---|
| Claude Haiku 4.5 | Lowest (default) | Triage, sentiment, and reply drafting for most teams — fast, cheap, and accurate enough for structured, short-context tasks. |
| Claude Sonnet 4.6 | Mid | You want noticeably better reply drafts and can absorb a higher per-call cost. |
| Claude Opus 4.6 | Highest | Occasional use on your most complex/highest-value tickets only. |

The model choice is global — it applies to every AI-enabled team's
triage, sentiment, and reply-draft calls.

## What it costs

Every call is small: triage and sentiment prompts are a few hundred
tokens, reply drafts a bit more. At Haiku's published rate, a typical
helpdesk doing **100 tickets/day** (triage + sentiment on each, plus
occasional reply drafts) lands around **$3–10/month** — see the
**AI Usage Log** pivot/graph (**Helpdesk ▸ Reporting ▸ AI Usage Log**)
for your own real numbers once you're running, including a per-call
cost estimate.

## Rotating or revoking a key

If a key is compromised or you're rotating credentials on a schedule:

1. Create a new key in the Anthropic Console first.
2. Paste it into **Anthropic API Key** in Odoo and save.
3. Only then delete the old key in the Console — this avoids a gap
   where triage/sentiment/reply-draft calls fail with
   `missing_or_invalid_api_key` between the two steps.

## Troubleshooting

**Every AI call fails silently.** Check the key format: it must start
with `sk-ant-` and be exactly 108 characters. A malformed key is
rejected on save with a clear error; a key that *looks* valid but has
been revoked in the Console fails at call time instead — check the
server log for `missing_or_invalid_api_key` or an HTTP error code, and
the **AI Usage Log** for whether calls are landing at all.

**I want to confirm the key is actually being used.** Trigger any AI
action (create a ticket on an AI-enabled team, or click **Draft
Reply**) and check **Helpdesk ▸ Reporting ▸ AI Usage Log** for a new
row with a real `model_used` and non-zero token counts.
