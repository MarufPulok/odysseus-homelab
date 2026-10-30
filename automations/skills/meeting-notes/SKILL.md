---
name: meeting-notes
description: "Format rough notes from a client or team meeting into a fixed meeting-notes template (summary, decisions, client asks, deadlines, open questions), and put dated deadlines in the calendar. Use for: meeting notes, format my notes, notes from my call, 'done' after typing notes."
version: 1.1.0
category: communication
tags: [meeting, notes, deadlines, calendar]
status: published
confidence: 1.0
source: taught
owner: admin
created: "2026-10-26T00:00:00Z"
---

## When to Use

The user gives rough notes from a meeting or call (fragments, typos, half sentences) and wants them formatted.

## Procedure

1. Your whole reply is the template below, filled from the notes. No intro line, no commentary, no other headings, no tables.

```
**Meeting:** <who> · <topic> · <today's date>

**Summary**
- <2 to 4 bullets: what it was about and where things landed>

**Decisions**
- <what was agreed>

**Client asks**
- [feat|bug|chore|question] <short task title>: "<the ask in the client's own words>"

**Deadlines**
- <what> · <date, your time> · <owner>

**Open questions**
- <what is still unanswered> → <who should answer>
```

2. Leave out a section only when nothing in the notes belongs in it. Keep the order.
3. Copy the client's words for asks; fix typos only. Never expand an abbreviation the notes didn't expand (AP stays AP).
4. Never invent a date, owner, cause, or detail. Anything unclear goes under Open questions.
5. Times: show deadline times in the user's time zone. If the client named another time zone, add theirs in brackets.
6. For each deadline with a clear date, create a calendar event: title `Due: <what>`, all-day on that date unless a time was given, meeting name in the description, reminder the day before. Add one last line: `Added to calendar: <titles>`. No clear date means no event.
