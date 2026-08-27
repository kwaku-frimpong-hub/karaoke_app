# DOMAIN_MODEL.md — Friday Karaoke

Domain concepts, entities, states, and relationships. This document is the target
model for v1; persistence schemas (SQLAlchemy) and API schemas (Pydantic) will be
defined in later milestones (M2 onward) and must map to these concepts.

---

## 1. Overview

```text
Host
 |
 +---- Session
          |
          +---- Participant
          |
          +---- Round
                  |
                  +---- QueueEntry
                          |
                          +---- YouTubeVideo
```

- A **Host** owns Sessions.
- A **Session** is one karaoke night and contains multiple Rounds.
- A **Participant** exists only within a Session (v1). No account.
- A **Round** contains QueueEntries for one pass through the queue.
- A **QueueEntry** references exactly one **YouTubeVideo** and one Participant.

## 2. Entities

### Host

An authenticated account that can create and manage sessions.

```text
id
email             # v1: email/password auth
password_hash
createdAt
```

### Session

One karaoke night.

```text
id
hostId
name              # e.g. "Friday Karaoke - 2026-08-14"
joinCode          # short code for the QR join link
status            # SessionStatus
createdAt
startedAt
endedAt
```

### Participant

A session-scoped identity created when a student joins. **No account.**

```text
id
sessionId
nickname
token            # opaque participant token used for authorization
createdAt
```

### Round

One pass through the queue within a session.

```text
id
sessionId
number           # 1-based round number
status           # RoundStatus (implied by session/queue state; not stored — M10.1)
startedAt
endedAt
```

### QueueEntry

A participant's song in a round.

```text
id
sessionId
roundId
participantId
youtubeVideoId
status            # QueueEntryStatus
createdAt         # determines order (authoritative ordering, no mutable position field)
startedAt
endedAt
```

### YouTubeVideo

Metadata snapshot of a submitted video.

```text
id
youtubeVideoId
youtubeUrl
title
channel
durationSeconds
thumbnailUrl
```

## 3. State enums

### SessionStatus

```text
CREATED          # session exists, not yet started
ACTIVE           # running
PAUSED           # automatic progression paused (host-controlled)
ENDED            # session finished
```

`ROUND_COMPLETE` was removed at M10.1: rounds advance automatically while the
session is `ACTIVE` (no enrollment).

### QueueEntryStatus

```text
WAITING
NEXT             # promoted to sing next
SINGING
COMPLETED
SKIPPED
CANCELLED        # participant withdrew their own entry
REMOVED          # host removed the entry
```

### PlaybackState (backend playback state machine, M11)

```text
IDLE
PREPARING
COUNTDOWN
PLAYING
COOLDOWN
FINISHED
SKIPPED
```

Example normal transition chain:

```text
NEXT
  -> PREPARING
  -> COUNTDOWN
  -> PLAYING
  -> COOLDOWN
  -> NEXT
```

The host can interrupt transitions at any point.

## 4. Round system (revised at M10.1)

- A Session contains multiple Rounds; never create a new session per round.
- Round N holds **one song per participant** (their N-th song). At most one
  non-terminal entry per participant per round.
- When a round's queue is exhausted, the round completes and the session advances
  **automatically** to the next round that has entries (participants' next songs).
  There is **no enrollment prompt** and no `ROUND_COMPLETE` state.
- The **active round is derived** from queue state (the lowest-numbered round with
  a non-terminal entry), never stored as a mutable counter.
- Ordering within a round is the **stable participant order**: each participant's
  earliest submission time (`MIN(created_at)`), fixed once and repeated every
  round; `created_at` + `id` are the deterministic tie-break.
- Round assignment: a participant's first song goes into the current round;
  subsequent songs go one round above their highest round. A late joiner's first
  song is appended to the current round.
- Participants whose songs run out do not appear in later rounds; a participant
  opts out by cancelling their remaining songs.
- Disconnected/absent participants should not silently remain forever (cleanup
  strategy defined in M16).

## 5. Business rules that constrain the model

1. A participant can exist only within a session (v1).
2. Queue order is determined by authoritative backend state: the active queue is
   the current round's entries, one song per participant, in stable participant
   order (earliest first engagement). No mutable position field.
3. A participant may cancel their own WAITING entry (current or upcoming round).
4. The host may remove any entry and edit the YouTube URL of an entry
   (participant stays in the queue).
5. A participant cannot modify another participant's entry.
6. One participant has a per-participant **total** song cap (default 5,
   configurable via `KARAOKE_QUEUE_MAX_SONGS_PER_PARTICIPANT`), enforced
   server-side.
7. Invalid YouTube URLs cannot become QueueEntries.
8. Long videos produce a warning, never automatic rejection.
9. A participant has at most one non-terminal entry per round; a new song goes to
   the current round if the participant has no non-terminal entry there,
   otherwise to the next round above their highest round.
