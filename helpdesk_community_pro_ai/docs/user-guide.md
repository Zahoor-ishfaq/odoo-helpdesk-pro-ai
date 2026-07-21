# Helpdesk AI Copilot — User Guide

Helpdesk AI Copilot adds Claude-powered Smart Triage, Sentiment
Detection, and a Reply Assistant to Helpdesk Pro, plus a Usage
Dashboard to track what it costs and how well it's working. This guide
covers setup and day-to-day use for agents and managers.

## Contents

- [Concepts](#concepts)
- [Setup](#setup)
- [Smart Triage](#smart-triage)
- [Sentiment Detection](#sentiment-detection)
- [Reply Assistant](#reply-assistant)
- [Usage Dashboard](#usage-dashboard)
- [Permissions](#permissions)
- [Data privacy](#data-privacy)
- [FAQ](#faq)

## Concepts

| Term | Meaning |
|---|---|
| **AI-enabled team** | A helpdesk team with AI features switched on (off by default — opt in per team). |
| **Auto-apply threshold** | The confidence (0.0–1.0) above which a triage suggestion is applied automatically instead of shown as a banner for review. Default 0.85. |
| **AI Usage Log** | One record per Anthropic API call — model, token counts, cost estimate, and a short non-sensitive summary. Never the raw prompt or response. |

## Setup

1. Install **Helpdesk Pro** first, then install **Helpdesk AI Copilot**
   on top of it.
2. Get an Anthropic API key — see [api-setup.md](api-setup.md) for the
   full walkthrough, including how to set a spending limit.
3. Go to **Settings ▸ General Settings ▸ Helpdesk AI** and paste the
   key under **Anthropic API Key**. Only administrators can see or set
   this field, and the key is never echoed back after saving.
4. Pick an **AI Model** — Claude Haiku 4.5 is the default and cheapest;
   Sonnet and Opus are also available for teams that want more
   capability at a higher cost.
5. Go to **Helpdesk ▸ Configuration ▸ Teams**, open a team, and check
   **AI Enabled** under the **AI Copilot** section. Set the
   **Ai Auto Apply Threshold** — lower it if you want more suggestions
   auto-applied without review; raise it toward 1.0 if you'd rather
   review everything yourself at first.

AI features are strictly opt-in per team. A team with **AI Enabled**
unchecked never calls the API — Smart Triage, Sentiment Detection, and
the Draft Reply button are all inactive for its tickets.

## Smart Triage

The moment a ticket is created (by email or manually) on an AI-enabled
team, Claude reads the subject and description and suggests a
**team**, **priority**, and **tags**, along with a confidence score.

- **High confidence** (at or above the team's threshold): applied
  automatically. The ticket's team, priority, and tags update right
  away, and `AI Accuracy` on the team counts this as accepted.
- **Low confidence**: nothing changes automatically. Instead, a banner
  appears on the ticket form — *"AI suggested: Team X | Priority Y |
  Tags Z"* — with **Accept** and **Dismiss** buttons. Accepting applies
  the suggestion (and counts toward accuracy); dismissing leaves the
  ticket as-is.

A ticket is only ever triaged once — `ai_triage_done` is set
regardless of outcome, so re-saving a ticket never re-triggers a call.
Very short tickets (under 20 characters combined subject + body) skip
triage entirely — there isn't enough content for a meaningful
suggestion.

## Sentiment Detection

Every genuine inbound email — a new ticket or a threaded reply routed
through the mail gateway — queues a sentiment check. A cron runs every
5 minutes and scores the message as **calm**, **neutral**,
**frustrated**, or **angry**, shown as a colored badge on the ticket
form and kanban card.

If the customer sounds **angry**, two things happen automatically:

1. Priority is bumped to **Urgent** (never lowered — if it's already
   Urgent, nothing changes).
2. Every manager on the ticket's team gets an activity: *"Customer
   sentiment: Angry — review recommended."*

A message typed directly into the chatter (not routed through email)
also queues a check, as long as it isn't the agent's own note or
reply — so a customer commenting from the portal is covered too, not
just email.

## Reply Assistant

On any ticket, click **Draft Reply** in the header. Claude reads:

- The ticket's own recent conversation (last 3 messages).
- Up to 5 already-resolved tickets on the same team with a similar
  subject, as style/content reference (a lightweight form of RAG — no
  vector database involved).

...and drafts a professional, empathetic reply under 150 words, shown
in an editable text box. Edit it however you like, then click **Use
This Reply** to stage it as an internal chatter note. **The AI never
sends anything to the customer** — you still copy the text into your
own reply and click Send yourself.

Only agents on the ticket's own team can open the wizard for it, even
if you belong to `group_helpdesk_user` generally.

## Usage Dashboard

**Helpdesk ▸ Reporting ▸ AI Usage Log** lists every API call — list,
pivot, or graph view. The pivot groups by team and call type, with
total tokens, cost estimate, and count as measures; the graph shows
total tokens by call type as a bar chart.

Each **Team** form also shows an **AI Accuracy** stat button —
accepted triage calls (auto-applied or manually accepted) divided by
all triage calls for that team. Clicking it opens the log filtered to
that team.

Cost estimates are priced from Claude Haiku 4.5's published rate
(prompt and completion tokens separately) and shown to 6 decimal
places, since a single call typically costs a fraction of a cent — a
2-decimal display would just show `0.00` for almost everything.

## Permissions

- **User: Agent** (`group_helpdesk_user`) — sees triage banners, can
  Accept/Dismiss, and can use the Draft Reply wizard for tickets on
  their own team.
- **Manager** (`group_helpdesk_manager`) — everything an agent can do,
  plus the AI Usage Log and the AI Accuracy stat button.
- **Administrator** (`base.group_system`) — the only role that can
  read or write the Anthropic API key.

## Data privacy

- No customer email address or phone number is ever included in a
  prompt.
- Every field sent to Claude is truncated (subject, body, and chatter
  messages all have hard character limits) — never a full ticket
  history.
- `helpdesk.ai.log` stores only token counts and a short, non-sensitive
  summary — never the raw prompt or the raw response.
- All traffic uses TLS with certificate validation on; there is no
  option to disable it.

## FAQ

**A ticket isn't getting triaged — why?**
Check that its team has **AI Enabled** checked, and that the combined
subject + description is at least 20 characters. Also confirm a valid
API key is configured — a missing or malformed key fails silently
(the helpdesk still works, just without AI), logged as a warning in
the server log.

**The sentiment badge never appears on a ticket I tested manually.**
Sentiment only triggers on a genuine inbound message — a real email
routed through the mail gateway, or a chatter comment/portal message
from someone other than the acting agent. Typing a note into the
chatter as yourself doesn't count; that's by design; see [Sentiment
Detection](#sentiment-detection).

**Why did Draft Reply show an error instead of a draft?**
The API call failed (missing/invalid key, timeout, or rate limit) —
the wizard shows a friendly message and stays open so you can still
write the reply by hand.

**Can I use a different Claude model for different teams?**
No — the model is a single global setting under **AI Model**, applied
to every AI-enabled team's triage, sentiment, and reply-draft calls.
