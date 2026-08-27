# PRODUCT_SPEC.md — Friday Karaoke

Behavioral contract for the MVP, frozen at milestone **M1**.
This document is the single source of truth for *what the product does*.
Implementers must follow it without guessing. If a behavior is not described here,
it is out of MVP scope (see §12) unless a later milestone explicitly extends this spec.

Companion documents:

- `docs/DOMAIN_MODEL.md` — entities and state enums referenced below
- `docs/API_CONTRACT.md` — planned API surface (updated when endpoints land)
- `docs/DECISIONS.md` — rationale for the behavioral decisions recorded here
- `plan.md` — milestone plan (M1 defines this document)

---

## 1. Scope

The MVP is a private karaoke queue application for one school's Friday karaoke
night:

- **One host** runs the night from a desktop/projector screen.
- **Participants** join anonymously from their phones by scanning a QR code,
  submit songs by pasting YouTube URLs, and watch their queue position.
- Songs play through the **host's browser** (the playback device). Participants'
  phones never play audio.
- Song flow is **automated** (cooldown → countdown → song), with the host able to
  override anything at any time.
- A session supports **multiple rounds**; each round is one pass through the
  participants' current songs (round N = everyone's N-th song), and rounds
  advance **automatically** to everyone's next song (no enrollment).

## 2. Roles and authority matrix

| Role | Identity | Can do |
| ---- | -------- | ------ |
| Host | Account (email/password, M3). One host owns a session. | Create/start/pause/resume/end session; display QR; monitor queue; remove any entry; edit any song URL; skip; manually advance |
| Participant | Session-scoped identity: nickname + opaque token (M5). No account. | Join; submit songs; review metadata; cancel own WAITING entries (current or upcoming rounds); view queue and position |

| Action | Host | Participant |
| ------ | :--: | :---------: |
| Create / start / pause / resume / end session | ✅ | ❌ |
| Display QR / join code | ✅ | ❌ |
| Join session | — | ✅ |
| Submit song (queue entry) | ❌ | ✅ |
| Review song metadata before submitting | — | ✅ |
| Cancel own WAITING entry (any round) | ❌ (but can remove any) | ✅ |
| Remove any queue entry | ✅ | ❌ |
| Edit a song URL (re-fetch metadata) | ✅ | ❌ |
| Skip current singer / manually advance | ✅ | ❌ |
| Cancel upcoming (future-round) songs | ❌ (but can remove any) | ✅ |

Rule: **Host actions are authorized server-side** against the owning host account.
**Participant actions are authorized server-side** against the participant token.

## 3. Session lifecycle

States (`SessionStatus` in `docs/DOMAIN_MODEL.md`):

```text
CREATED -> ACTIVE <-> PAUSED -> ENDED
```

The diagram shows the **normal path**. `ENDED` is reachable from any state
(§5.7, E11, E18) — the host may end the session at any time; the diagram only
shows the typical progression.

| State | Meaning | Join allowed? | Queue processes? |
| ----- | ------- | :-----------: | :--------------: |
| `CREATED` | Session created; QR/join code shown immediately | ✅ (early birds may join and queue) | ❌ (no automation until start) |
| `ACTIVE` | Host started; automation runs | ✅ | ✅ |
| `PAUSED` | Host paused automatic progression | ✅ | ❌ automation (manual host actions still work) |
| `ENDED` | Session closed for good | ❌ (QR/link returns "session ended") | ❌ |

Rules:

- Creating a session immediately produces a **join code** and **join URL/QR**
  (M4/M5). The QR never changes for the lifetime of the session.
- Only the owning host can change session state. Every state change is a server-side
  transition; the frontend merely renders it.
- `ENDED` is terminal. A new night requires a new session.
- There is no `ROUND_COMPLETE` state (removed at M10.1): rounds advance
  automatically while the session is `ACTIVE`, so the host never has to "start
  the next round".

## 4. Round lifecycle

A session contains one or more rounds. Rounds are numbered 1, 2, 3, … and advance
**automatically** (M10.1): round N holds one song from each participant who has a
song for that round (their N-th song), and when the round's queue is exhausted the
session moves to round N+1 — the participants' next songs — with no prompt and no
host action.

```text
Round N active
  -> participants submit entries (one per participant per round)
  -> automation advances the queue (cooldown/countdown/song)
  -> queue becomes empty
  -> Round N completes -> Round N+1 begins automatically
```

### Queue ordering

- **Within a round**: the default order is the **join order** — the order in
  which participants joined the session (earliest join first), repeated every
  round. The host can **re-arrange the current round** (up/down on the
  dashboard); the reorder is **per-round only** — the next round falls back to
  join order.
- **Skipping an absent singer moves them to the end of the round** (one
  re-chance after everyone else). If the skipped singer is the **only**
  non-terminal entry left in the round, they are excluded (`SKIPPED`) so the
  round can complete. In the next round they are back at the front (join
  order).
- **Between rounds**: round N+1 is simply each participant's next song. There is
  **no enrollment** and no "join the next round" step; a participant whose songs
  run out simply does not appear in later rounds.

### Song submission and round assignment

- A participant may queue up to **5 songs total** (configurable via
  `KARAOKE_QUEUE_MAX_SONGS_PER_PARTICIPANT`, rule B15).
- A participant's new song goes to the **current round** when they have no
  non-terminal entry there (their first song, or rejoining the round after a
  skip/cancel). A participant who already has a non-terminal song in the current
  round places their new song in the next round above their highest round.
  At most **one non-terminal entry per participant per round**.
- A participant who joins mid-round has their first song appended to the current
  round; subsequent songs go to later rounds.
- Cancelling a WAITING entry works for any of the participant's own songs, in the
  current round or a future round (B3).

## 5. Host flow (detailed)

### 5.1 Login
1. Host opens the app and logs in (email/password, M3).
2. On success the host lands on the **dashboard** screen.

### 5.2 Create session
1. Host taps **New Session**.
2. Host optionally sets a **session name** (default: `Friday Karaoke - <date>`).
3. Backend creates the session (`CREATED`) and returns a join code + join URL.
4. Dashboard immediately shows the **QR code** and join code; host displays it on
   the projector.

### 5.3 Monitor queue
1. Dashboard shows: current singer, current song + playback status, next singer,
   full queue (participant names, song titles, durations), and session state.
2. The screen refreshes from realtime events (M10); it is never authoritative.

### 5.4 Start the session
1. Host taps **Start** once participants have joined.
2. Session → `ACTIVE`. Automation takes over the queue (see §10).

### 5.5 Moderate (during the night)
- **Skip**: mark the current entry `SKIPPED` and advance to the next entry.
- **Manually advance**: mark the current entry `COMPLETED` and move to the next
  entry (used when the singer finished early).
- **Remove**: remove any queue entry (status `REMOVED`); the entry disappears from
  the queue. Removing the current singer also advances playback.
- **Edit song**: replace the URL of an entry; backend re-validates and re-fetches
  metadata; the entry keeps its position and participant. Invalid replacement is
  rejected with an error and the old URL is kept.
- **Pause / Resume**: pause stops automatic progression after the current song;
  resume restarts automation.
- **End session**: closes the session for good (`ENDED`).

### 5.6 Round boundaries (automatic)
1. When the queue empties, the round completes and the **next round begins
   automatically** (participants' next songs appear in the queue; the round
   number increments). No enrollment and no host action required.
2. The dashboard shows the active round number. The host may end the session at
   any time (§5.7); a participant who wants out cancels their remaining songs.

### 5.7 End session
1. Host ends the session → `ENDED`. QR/link no longer accepts joins.
2. The host dashboard shows a summary and returns to the home screen.

## 6. Participant flow (detailed)

### 6.1 Scan QR
1. Student scans the QR (or opens the join URL) with their phone.
2. If the session is `ENDED` → "This karaoke night has ended."
3. Otherwise the participant lands on the **join screen**.

### 6.2 Enter nickname
1. Participant enters a nickname.
2. Rules: required; trimmed; 1–20 characters; unique per session
   (case-insensitive). Violations show a message and block submission.

### 6.3 Paste YouTube URL
1. Participant pastes a YouTube URL (watch URL or youtu.be short URL).
2. Backend validates the URL format and extracts the video ID. Invalid/non-YouTube
   URLs are rejected with an error. (Details: `plan.md` §M6, rules in §8.)
3. Backend fetches metadata (title, channel, duration, thumbnail).
   - Unavailable videos → error, no entry created.
   - **Long videos produce a warning, never a rejection.**

### 6.4 Review song metadata
1. Participant sees a preview: thumbnail, title, channel, duration, and any warning
   (e.g., "This video is longer than usual").
2. Participant confirms **Add to Queue** (or **Try Another URL**).

### 6.5 Join the queue
1. On confirm, the backend assigns the entry to a round (rule B19): the current
   round if the participant has no non-terminal entry there, otherwise the next
   round above their highest round.
2. If the participant has reached the **per-participant song cap** (default 5,
   see §9, B15), the submission is rejected with a clear message.
3. The participant lands on the **queue screen**.

### 6.6 Monitor position
1. Queue screen shows: session status, current singer, next singer, the full queue,
   and "your position".
2. Position is computed by the backend from authoritative queue order.

### 6.7 Receive "you're next"
1. When the participant's entry is promoted to `NEXT`, they receive a notification:
   "You're next! Get ready: <song> — <channel>".
2. Notification timing is configurable (default: when promoted to NEXT, and again
   at the start of the countdown).

### 6.8 Perform
1. When their song starts, the participant sings along (audio plays on the host
   device; the participant's phone shows their song/position only).

### 6.9 Manage your songs
1. The participant's queue screen shows all their queued songs: the one in the
   current round (with its position) plus their upcoming songs for later rounds.
2. Any own WAITING song — current round or upcoming — can be cancelled (B3).
   Cancelling a current-round song removes it from the round; cancelling an
   upcoming song takes it out of a later round.
3. A participant who cancels their remaining songs is out for the rest of the
   night (no enrollment to rejoin; they could re-join via a new nickname if the
   host permits, but the session itself does not re-ask).

### 6.10 Leave the session (going home early)
1. A participant who has to leave taps **Leave session** and confirms.
2. They are removed entirely: their identity and **all their songs** (current
   round, future rounds, and sung history) are deleted, and their **nickname is
   freed** so they could rejoin later (a rejoin is a fresh identity).
3. If their song is currently playing, it stops and the **next singer advances**
   (the same behavior as the host removing a singer, E6).
4. Their token stops working immediately; everyone else's queue updates in
   realtime.

## 7. Screen inventory (UX requirements)

### 7.1 Participant: join screen
- Session name, "Scan to join" branding, nickname input, join button, error states.
- Mobile-first, large touch targets (≥ 44px).

### 7.2 Participant: song submit screen
- URL input, submit button, loading state while metadata is fetched, preview card
  (thumbnail/title/channel/duration + warnings), confirm/cancel buttons.

### 7.3 Participant: queue screen
- Session status banner; "Now singing" card; "Up next" card; the active round's
  queue list (one song per participant, with each entry's song title and
  participant name); the participant's own songs highlighted — the current-round
  song with its position plus an "Your songs" section for upcoming rounds, each
  cancellable.
- Reconnect/loading/error states (see §8, P-edge cases).

### 7.4 Host: dashboard
- Current singer + song + playback status; the active round number; queue list
  (one song per participant — names, titles, durations); per-entry actions
  (remove, edit); global actions (start, pause/resume, skip, advance, end
  session); QR + join code display (post-creation).
- Must be usable on a projector/TV (large text, high contrast, minimal scrolling
  for current/next).
- Must handle browser-autoplay restrictions: playback begins only after host
  interaction; the UI must surface "click to start audio" where needed.

## 8. Edge-case catalog

Every edge case lists the **behavior** an implementer must produce.

### E1. Duplicate song
- Two participants submit the same video (same video ID).
- Behavior: both entries are allowed. The submitter sees an informational notice
  ("This song is already in the queue") but the entry is **not** blocked.

### E2. Participant leaves / abandons
- A participant who leaves (closes browser, navigates away, walks off) keeps their
  queue entries.
- Behavior: entries persist; the queue is unchanged. An entry is only removed by:
  participant cancel, host remove, or being processed (completed/skipped) as the
  queue advances. A participant who is `NEXT`/`SINGING` and does not show up can be
  skipped by the host.

### E3. Participant submits an invalid URL
- Behavior: rejected with a clear error message ("That doesn't look like a valid
  YouTube link"). No entry is created.

### E4. YouTube video unavailable at submission
- Behavior: rejected with "We couldn't load this video." No entry is created.
- (Distinct from E3: format is valid but metadata cannot be fetched.)

### E5. Video becomes unavailable after submission
- The entry already exists in the queue.
- Behavior: the entry stays until reached. When playback of that video fails, the
  host dashboard shows a player error; the host can skip or edit the entry. The
  queue order is never auto-modified.

### E6. Host removes a participant (or their entry)
- Behavior: host removes the entry (status `REMOVED`). Removing the current entry
  advances playback to the next. The participant remains connected and can submit
  again (if below the per-participant song cap, B15).

### E7. Host edits a song
- Behavior: host replaces the URL; backend re-validates + re-fetches metadata.
  Invalid replacement → error, previous URL kept. Participant and queue position
  are preserved.

### E8. Participant refreshes the page
- Behavior: nothing is lost. The participant token persists (cookie/storage, M5);
  the page re-fetches authoritative state on load.

### E9. Participant loses internet
- Behavior: their entries remain in the backend. On reconnect, the app re-fetches
  authoritative state and re-establishes the realtime connection. Nothing the
  client did locally is trusted.

### E10. Host loses internet
- Behavior: the backend session state is untouched. Realtime clients keep their
  last-known state but are not authoritative. When the host reconnects, the
  dashboard re-syncs from the backend. Playback on the host device may have
  stopped; the host resumes manually.

### E11. Host closes the browser
- Behavior: the session **remains** in its last state (`ACTIVE`/`PAUSED`/…) in the
  backend. The host reopens the dashboard, logs in, and re-syncs. Sessions are not
  tied to a live browser connection.

### E12. Song ends
- Behavior: normal automation — the entry becomes `COMPLETED`, the backend advances
  through cooldown → countdown → next song (see §10). The host can intervene.

### E13. Host manually skips
- Behavior: current entry → `SKIPPED`; automation advances to the next entry
  immediately (skip bypasses the current song's remaining time).

### E14. Host manually advances
- Behavior: current entry → `COMPLETED`; automation advances to the next entry.
  Used when the singer finished early.

### E15. Queue becomes empty (round ends)
- Behavior: the round completes automatically and the **next round begins
  immediately** (participants' next songs are added to the queue, M10.1). If no
  participant has a next song, the queue simply stays empty and the session
  remains `ACTIVE` waiting for new submissions (see E23) — nothing deadlocks and
  there is no enrollment prompt.

### E16. Round ends
- Behavior: as E15 plus: there is no "join the next round" prompt. The host sees
  the new round number; participants whose songs run out are no longer in the
  queue; the host may moderate or end the session at any time.

### E17. Participant wants to stop after their current song
- Behavior: the participant cancels their remaining (upcoming) songs, or simply
  lets their list run out — either way they do not appear in later rounds. No
  prompt is involved.

### E18. Session ends while participants are connected
- Behavior: their queue screens show "This karaoke night has ended." Entries are
  preserved in the backend for audit/debug but no longer actionable.

### E19. Two participants submit at the same instant
- Behavior: the backend serializes submissions; order is the backend's processing
  order (creation order). Deterministic, no ties by client clock.

### E20. Host skips while an automatic transition is running
- Behavior: only one transition happens. The backend applies the host's action and
  cancels any in-flight automation (see §10). No double-advance.

### E21. Participant cancels while host removes the same entry
- Behavior: both resolve to the entry being terminal; whichever is applied first
  wins and the second is a no-op. The system always ends in a valid queue state.

### E22. Session is PAUSED and the queue has entries
- Behavior: automation is suspended after the current song. Participants can still
  join and submit; host manual actions still work; resume restarts automation.
- Pausing during a transition (PREPARING / COUNTDOWN / COOLDOWN) holds automation
  at that step until resume; the current entry is unaffected.

### E23. No participants joined and the host starts anyway
- Behavior: session → `ACTIVE` with an empty queue; dashboard shows an empty state
  ("Waiting for singers"). Nothing breaks; the round only completes when entries
  are processed (host can end the session at any time).

### E24. Playback fails to start (autoplay / player error)
- Behavior: the host dashboard shows an error and a manual start control; the
  backend playback state does not deadlock — the host can skip/advance/retry.

### E25. Participant queues multiple songs (round assignment)
- Behavior: each song is round-scoped (one non-terminal entry per participant per
  round). The first song goes into the current round; later songs go one round
  above the participant's highest round, so they are invisible in the queue until
  every participant's earlier songs are done. Submissions beyond the per-participant
  cap (B15) are rejected with a clear message. See §4.

### E26. Participant leaves the session mid-night
- Behavior: the participant taps Leave; their identity and all their songs are
  deleted, their nickname is freed, and if they were the current singer playback
  advances to the next singer (E6). Their token stops working immediately. The
  queue updates for everyone in realtime.

## 9. Behavioral rules (implementer-facing)

> These are the normative rules extracted from the flows and edge cases. Every rule
> must be enforced by the **backend**; the frontend only renders.

- **B1.** Only authenticated, session-owning hosts can create/start/pause/resume/end
  a session or moderate its queue. (`plan.md` §5 rules 1, 19)
- **B2.** Anyone with the session QR/join link can join; participants need no
  account. (`plan.md` §5 rule 2)
- **B3.** A participant may cancel their own WAITING entry but may not modify or
  cancel others' entries. (`plan.md` §5 rule 5)
- **B4.** The host may remove any entry and edit any entry's YouTube URL.
  (`plan.md` §5 rules 6, 7)
- **B5.** Invalid YouTube URLs cannot be queued. (`plan.md` §5 rule 8)
- **B6.** Long videos produce a warning, never automatic rejection.
  (`plan.md` §5 rule 9; `plan.md` §1.5)
- **B7.** Queue order is authoritative backend state: the active queue is the
  current round's entries, one song per participant, in **join order** (earliest
  join first) unless the host reorders the current round, with no mutable
  position field. (`plan.md` §5 rule 10; decisions D8/D43)
- **B8.** Host playback is authoritative for actual song playback. Participant
  devices never play audio. (`plan.md` §5 rule 11; §1.6)
- **B9.** Automatic advancement is a fallback/normal path that the host can always
  override (skip, finish, pause, manually start another entry).
  (`plan.md` §5 rules 4, 12; §M13)
- **B10.** A session contains multiple rounds; do not create a new session per
  round. Rounds advance automatically (M10.1).
  (`plan.md` §5 rule 13; §M16)
- **B11.** There is no next-round enrollment: when a round's queue is exhausted
  the next round begins automatically. A participant opts out by cancelling
  their remaining songs.
  (`plan.md` §5 rules 14–16; decisions D44)
- **B12.** Realtime events are delivery, not truth; reconnecting clients must
  resync from the backend. (`plan.md` §5 rules 17, 18; §M10)
- **B13.** The application must remain usable if realtime connections fail.
  (`plan.md` §5 rule 20)
- **B14.** Nicknames are required, trimmed, 1–20 characters, unique per session
  (case-insensitive). (Decision D16)
- **B15.** A participant may queue at most **`KARAOKE_QUEUE_MAX_SONGS_PER_PARTICIPANT`**
  non-terminal songs **total** (across all rounds; default 5). Submissions beyond
  the cap are rejected with a clear message. (Decision D45; enforcement hardened
  in M17)
- **B16.** Duplicate songs are allowed; an informational notice is shown, never a
  block. (Decision D15)
- **B17.** Sessions are not tied to a live browser connection; closing the host
  browser does not end the session. (Decision D18)
- **B18.** "Skip" moves the current singer to the **end of the round** (one
  re-chance); if they are the only singer left, it marks them `SKIPPED` so the
  round can complete. "Manually advance" (`Finish`) marks the current entry
  `COMPLETED` and advances immediately. Both begin the next singer's countdown.
  (Decision D20)
- **B19.** At most one non-terminal entry per participant per round. A new song
  goes to the **current round** when the participant has no non-terminal entry
  there, otherwise to the **next round above their highest round**.
  (Decision D43)
- **B20.** A participant may delete themselves from the session (`POST
  /sessions/{id}/leave`): their identity and all their songs are removed, their
  nickname is freed, and if they were the current singer playback advances to
  the next singer (E6). Their token stops working immediately.

## 10. Playback and automation behavior

> Implementation status: M11 delivered the host-driven playback controls and
> M13 the automatic transitions (cooldown → countdown → auto-start, per-session
> configurable timings, decision D47). The "you're next" notifications
> (M15) and the round/session summaries (M16) are still pending.

The backend runs the playback state machine (`docs/DOMAIN_MODEL.md`,
`PlaybackState`). Automation is the normal path; the host can interrupt any step.

```text
NEXT
  -> PREPARING   (load the next entry's video)
  -> COUNTDOWN   (next-singer countdown; notify "you're next")
  -> PLAYING     (host YouTube player plays the song)
  -> COOLDOWN    (post-song cooldown)
  -> NEXT
```

When the current round's queue is exhausted, the backend advances into the next
round's first entry (M10.1): a round boundary is just another transition in this
chain, with no enrollment step.

Configuration (per session, defaults per `plan.md` §M13):

| Setting | Default | Meaning |
| ------- | ------- | ------- |
| Post-song cooldown | 10 s | Rest between songs before the next countdown |
| Next-singer countdown | 20 s | Countdown shown before the next song starts |
| Notification timing | On NEXT + at countdown start | When the next singer is notified |

Interruptions (all valid at any point):

- **Skip**: current entry `SKIPPED`; go to NEXT immediately (skip cooldown/countdown).
- **Finish / advance**: current entry `COMPLETED`; go to NEXT.
- **Pause**: hold after the current song; no auto-advance until resume.
- **Manually start an entry**: host selects a specific entry and starts it; the
  previous current entry is marked per host choice (completed/skipped).
- **Player error / autoplay blocked**: playback state does not deadlock; the host
  can retry, skip, or advance (E24).

## 11. Notifications

MVP scope: **in-app notifications** (delivered via the realtime channel and visible
in the participant queue screen; optionally a browser notification where permitted).

> Implementation status: M15 delivers the in-app notifications (a typed
> `NextSingerNotified` realtime event rendered as a banner on the participant
> queue screen). Web Push is deferred (needs the M19 service worker + VAPID
> credentials).

- **"You're next"**: shown when the participant's entry is promoted to `NEXT` and
  again at countdown start (timing configurable, §10).
- Message: `You're next! Get ready: <song> — <channel>`.
- Web Push is a **later** milestone and is not part of the MVP contract.

## 12. Non-goals (MVP)

Do not build (also in `plan.md` §6 / PROJECT_BRAIN §13):

- Participant accounts, public session discovery, multi-venue management
- Song streaming, Spotify integration, custom karaoke music hosting
- Voting, leaderboards, payments/tipping, social profiles, complex analytics
- AI recommendations / AI singing analysis
- Full offline karaoke operation (reconnect/resync only, M19)

## 13. Open questions

Tracked in `docs/DECISIONS.md` (§ Open questions). None block implementation of M2+.
