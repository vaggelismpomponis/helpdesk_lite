# Demo Rehearsal Log

**Issue:** #55 · **Owner:** Quality · **Script:** [DEMO_SCRIPT.md](./DEMO_SCRIPT.md)

We run at least two full dry runs of the 10-minute demo. Presenters rotate so that every member presents
a different part each time and can explain the whole flow.

## Team

| Member | Role |
|---|---|
| @vaggelismpomponis | Platform |
| @AlexZarkalis | Interface |
| @stef-fot | Knowledge |
| @VickyMil-ai | Quality |

## Rotation

Segment numbers and times follow [DEMO_SCRIPT.md](./DEMO_SCRIPT.md#timing). Rules:

- No one presents a segment that belongs to their own role.
- No one presents the same segment in both rehearsals.
- Each person presents 2–3 minutes per rehearsal.

| # | Segment | Time | Rehearsal 1 | Rehearsal 2 |
|---|---|---|---|---|
| 1 | Objective & stack | 1′ | @VickyMil-ai | @stef-fot |
| 2 | Clarification flow | 2′ | @VickyMil-ai | @stef-fot |
| 3 | Policy citation & version conflict | 2′ | @vaggelismpomponis | @AlexZarkalis |
| 4 | Outage detection & link to outage | 2′ | @AlexZarkalis | @vaggelismpomponis |
| 5 | Human approval & restart resume | 2′ | @stef-fot | @VickyMil-ai |
| 6 | LangSmith tracing & evaluation | 1′ | @stef-fot | @AlexZarkalis |

If we hold a third rehearsal, each member presents the segment closest to their own role, as a check
on the final run.

## How to run a rehearsal

1. **T-30 min:** run the [pre-demo check](./DEMO_SCRIPT.md#before-the-demo-t-30-min). It must end with
   `RESULT: PASS`.
2. **Run the demo:** go through all 6 segments, presented by the members listed above. One member
   who isn't presenting keeps time.
3. **Recheck the [known issues](./DEMO_SCRIPT.md#known-issues):** record whether each one still occurs.
4. **Architecture questions:** each member answers one question about a part of the flow they did
   *not* present. Use the follow-up questions from the brief:
   - "Why didn't you reset the password?"
   - "Which other teams are affected by this outage?"
   - "Which policy did you base this on?"
   - "Continue the request I opened before the restart."
5. **Follow up:** each problem found becomes an issue for the owning role. Link it in the table below.

## Rehearsal 1

**Date:** _TBD_ · **Timekeeper:** _TBD_ · **`demo_check`:** _TBD_

| # | Segment | Presenter | Planned | Actual | Notes |
|---|---|---|---|---|---|
| 1 | Objective & stack | @VickyMil-ai | 1′ | | |
| 2 | Clarification flow | @VickyMil-ai | 2′ | | |
| 3 | Policy citation & version conflict | @vaggelismpomponis | 2′ | | |
| 4 | Outage detection & link to outage | @AlexZarkalis | 2′ | | |
| 5 | Human approval & restart resume | @stef-fot | 2′ | | |
| 6 | LangSmith tracing & evaluation | @stef-fot | 1′ | | |
| | **Total** | | **10′** | | |

**Known issues**

| # | Issue | Still occurs? |
|---|---|---|
| 1 | Approval buttons fail on `chainlit==1.3.2` | |
| 2 | Live evaluation 8/10 (EVAL-06, EVAL-09 citations) | |
| 3 | No logged-in user in the UI | |
| 4 | Doubled period at the end of responses | |

**Architecture questions**

| Member | Question | Explained clearly? |
|---|---|---|
| @vaggelismpomponis | | |
| @AlexZarkalis | | |
| @stef-fot | | |
| @VickyMil-ai | | |

**Problems found**

| Problem | Owner | Issue |
|---|---|---|
| | | |

## Rehearsal 2

**Date:** _TBD_ · **Timekeeper:** _TBD_ · **`demo_check`:** _TBD_

| # | Segment | Presenter | Planned | Actual | Notes |
|---|---|---|---|---|---|
| 1 | Objective & stack | @stef-fot | 1′ | | |
| 2 | Clarification flow | @stef-fot | 2′ | | |
| 3 | Policy citation & version conflict | @AlexZarkalis | 2′ | | |
| 4 | Outage detection & link to outage | @vaggelismpomponis | 2′ | | |
| 5 | Human approval & restart resume | @VickyMil-ai | 2′ | | |
| 6 | LangSmith tracing & evaluation | @AlexZarkalis | 1′ | | |
| | **Total** | | **10′** | | |

**Known issues**

| # | Issue | Still occurs? |
|---|---|---|
| 1 | Approval buttons fail on `chainlit==1.3.2` | |
| 2 | Live evaluation 8/10 (EVAL-06, EVAL-09 citations) | |
| 3 | No logged-in user in the UI | |
| 4 | Doubled period at the end of responses | |

**Architecture questions**

| Member | Question | Explained clearly? |
|---|---|---|
| @vaggelismpomponis | | |
| @AlexZarkalis | | |
| @stef-fot | | |
| @VickyMil-ai | | |

**Problems found**

| Problem | Owner | Issue |
|---|---|---|
| | | |

## Sign-off

Tick each box when its rehearsal is logged above, then close #55.

- [ ] Rehearsal 1 held and logged
- [ ] Rehearsal 2 held and logged
- [ ] Every member answered an architecture question on a part they did not present
