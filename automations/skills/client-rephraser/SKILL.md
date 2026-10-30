---
name: client-rephraser
description: "Rephrase rough notes into a short, clear client message for Slack or email. Use when the user says rephrase, reword, clean up, draft a reply, or pastes a rough message for a client."
version: 1.0.0
category: communication
tags: [client, slack, email, rephrase, writing]
status: published
confidence: 1.0
source: taught
owner: admin
created: "2026-10-26T00:00:00Z"
---

## When to Use

The user pastes rough notes or a draft meant for a client and wants a message they can send. Messages only (Slack, email). Long client documents go to Claude on the Mac.

If no message was given, reply exactly: `Ready for rephrasing — send the message.`

## Procedure

1. Pick the surface. Default is Slack. Email only if the user says email (then add a one-line greeting and a name).
2. Find the real point. You are cutting noise, not adding polish.
3. Write the message in this shape:

```
<one line saying what the bullets are about>

- point
- point
```

   - One context line, then at most six bullets. One idea per bullet.
   - A true one-liner (a single ask, "yes, done") is one plain sentence. No bullets.
   - A question: start with `### Question 1: <short title>` (that header replaces the context line), then the reason in one line, then what each answer leads to. Sub-number asks as 1.1, 1.2.
   - Bad news or a delay goes in the first line, then the cause, then what happens next.
   - Two topics: separate them with `---`, each with its own context line.
4. Check before sending: could it be half as long and still complete? If yes, cut.
5. Output only the finished message. No "Here's your message". Give 2 versions (V1 tight, V2 with one line of context) only when the approach truly forks.
6. If a fact the message needs is missing (who acts, the deadline, the actual ask), add `---` then `Some additional context...` with up to 3 short questions for the user. This part is for the user, never the client.

## Hard rules

- No em dashes or en dashes. Use a period, comma, or "so"/"but". Split into two sentences.
- Active voice only. Name who acts: "We'll fix it today", "You can upload it now". Never "it has been fixed".
- Every sentence simple enough for a ten year old. Most under 15 words. Small words: fix, use, show, start.
- No invented facts. No new names, dates, numbers, causes, or scope. Never upgrade "most" to "all" or "we think" to "we confirmed".
- No jargon: API, endpoint, sync, schema, workflow, cache, deploy pipeline. Say what the client sees on screen. Their own terms and labels stay, in quotes.
- No AI words: delve, leverage, seamless, robust, ensure, streamline, in order to, kindly, please be advised, as mentioned, excited to.
- No padding: no "I wanted to reach out", no "Hope you're well", no sign-off fluff, no "Good news first", no "Here's the breakdown".
- No talking down: drop simply, just, obviously.
- Don't restate the client's message back to them.
- Keep the author's voice. Blunt stays blunt. Keep contractions.
- Copy numbers, names, dates, item numbers, and links exactly.
- Hedge only when truly unsure. "Friday won't work" beats "we may face challenges".
- When the user flags one wrong line, change only that line and keep the rest word for word.
