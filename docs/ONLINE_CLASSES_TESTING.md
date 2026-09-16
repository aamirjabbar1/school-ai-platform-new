# LSS Online Classroom — testing guide

What has been tested automatically, and what has to be tested with real people
on real devices before a timetable depends on it.

---

## 1. Automated tests (run these on every change)

### Backend unit tests

```bash
cd backend-python
pip install -r requirements-dev.txt
pytest
```

75 tests, no database, media server or AI provider required. They cover the
places where a silent mistake would be worst:

| Area | What is asserted |
|---|---|
| Join authorization | `Grade 5` ≡ `Class 5` ≡ `5` ≡ `V`; wrong section, wrong class, and section-less students are refused; an unrecognised class fails closed |
| Teacher authorization | Own class/section/subject only; a teacher with no assignments yet is not locked out |
| Attendance arithmetic | The spec's worked example (42 of 45 minutes across a disconnect → 93.3% → present); late-but-stayed is *late*, on-time-but-left-early is *partial*, arriving for the last three minutes is *absent* |
| Webhook verification | A tampered body with a valid token is rejected; a foreign signature is rejected; a token with no body digest is rejected |
| AI cost control | Summaries route to the cheap model, student questions to the capable one, admin overrides win, an unknown model is never priced at zero |
| Class context | Page lists render as `24-27, 31`; an unconfirmed lesson record is marked provisional; the "you did not hear the lesson" rule is present in every prompt |
| Range requests | Open-ended, bounded, suffix and out-of-range byte ranges for book pages and recording playback |
| Presentation formats | PDFs/decks render as PDF, images as images, anything else is refused with a Share Screen fallback rather than a broken viewer |

### Frontend build

```bash
cd frontend
yarn install
yarn build
```

The classroom is code-split: the media client and PDF renderer load only when
someone opens a classroom, so the dashboard bundle is unaffected.

### Migration check (no database touched)

```bash
docker compose run --rm backend alembic upgrade b2c3d4e5f6a7 --sql | tail -20
```

---

## 2. Load testing (before production)

Run from any machine with the LiveKit CLI (`lk`), against the media host.

```bash
export LIVEKIT_URL=wss://live.lssbot.net
export LIVEKIT_API_KEY=APIxxxx
export LIVEKIT_API_SECRET=…

# One class of 30
lk load-test --room loadtest-1 --publishers 1 --subscribers 30 --duration 5m

# Five, ten, twenty simultaneous classrooms
scripts/load_test_classrooms.sh 5
scripts/load_test_classrooms.sh 10
scripts/load_test_classrooms.sh 20
```

While each run is going, record from the media host:

```bash
docker stats --no-stream lss_livekit
vmstat 5 12          # CPU and memory
ifstat -t 5 12       # bandwidth
```

**What to write down for each run** — these numbers, not impressions, decide
the production server size:

| Measure | Where from | Expected at 10 classes × 30 |
|---|---|---|
| CPU | `docker stats` | Well under 100% of 4 vCPU |
| Egress bandwidth | `ifstat` | ~130 Mbps |
| Join latency | `lk load-test` summary | Under 2 s |
| Packet loss / freeze rate | `lk load-test` summary | Near zero |

Also exercise the parts `lk` cannot: open a real classroom during the loudest
run and check that a page turn still appears instantly on a student device.

---

## 3. Real-world testing (with teachers and students)

Automated tests cannot tell you whether a Nursery teacher can start a class.
This is the list to work through with real users, on real connections.

### Devices and browsers
- [ ] Android phone (Chrome), Android tablet, iPhone/iPad (Safari), Windows laptop (Chrome and Edge)
- [ ] A low-end Android phone, not just a new one
- [ ] Teacher on a laptop while students are on phones — the common real case

### The two buttons
- [ ] A teacher who has never seen the system starts a class without being told how
- [ ] A Class 1 student (with a parent) joins from the 🔴 LIVE card and sees the simplified screen
- [ ] Nobody is ever asked for a meeting ID, link, code or password

### Network behaviour
- [ ] Turn a student's Wi-Fi off for 60 seconds mid-class → "Reconnecting…", then back into the same lesson
- [ ] Turn the *teacher's* connection off for 2 minutes → students see the class survive; after the grace period it ends cleanly
- [ ] A student on 3G with Data Saver on → the lesson stays audible and the book stays readable
- [ ] Check the register afterwards: the disconnect and rejoin are both recorded, minutes are right

### Teaching tools
- [ ] Open a Knowledge Base book, move pages, zoom, annotate — students follow automatically
- [ ] Switch book → whiteboard → book: the page comes back where it was
- [ ] Save a whiteboard; confirm it appears in the lesson record
- [ ] Present a PowerPoint (first open converts; second open is instant)
- [ ] Share a screen from a laptop; on a phone confirm the honest fallback message, then use Show Book (rear camera)
- [ ] A student joining 10 minutes late sees the board that is already there

### Classroom control
- [ ] Raise hand → teacher grants mic → student speaks → teacher mutes
- [ ] Mute all; lock the class; remove a student
- [ ] End Class for Everyone — all students land back on their dashboard

### Attendance and administration
- [ ] Register matches what actually happened, including rejoins
- [ ] CSV export opens correctly in Excel
- [ ] Admin control room shows the live class, the student count and the teacher
- [ ] Admin observes a class → the class is told; the audit log records it
- [ ] Admin force-ends a class

### Recording (if enabled)
- [ ] Start and stop recording; students see the recording indicator
- [ ] The recording appears under Recorded Classes for that class only
- [ ] A student from another section cannot open it
- [ ] Retention: an expired recording is deleted by the nightly sweep

### Lesson record and AI
- [ ] Pages presented are pre-filled; the teacher edits and confirms
- [ ] Class summary appears for students after confirmation
- [ ] Thirty students opening the summary produce **one** AI request in the admin AI usage tab
- [ ] A student types a question in Ask LSS AI and gets a written answer with sources
- [ ] Turn the AI features off in admin settings → the classroom still works perfectly, AI panels show a plain message
- [ ] Set the daily AI budget to $0 → students get a polite message, classes are unaffected

### Concurrency
- [ ] 5 real classes at once during a school period
- [ ] Then 10, with the admin control room open throughout

---

## 4. Security checks

- [ ] A student token cannot publish audio or video until the teacher grants it
- [ ] A section-B student cannot join a section-A class (expect 403)
- [ ] A recording URL copied from one student does not work for another class's student
- [ ] The LiveKit API secret appears in no browser bundle: `grep -ri "livekit" frontend/dist/assets/*.js | grep -i secret` returns nothing
- [ ] Webhook endpoint rejects an unsigned POST (expect 401)
- [ ] Rate limits hold: 30 students joining simultaneously all succeed; one student spamming Ask AI is capped

---

## 5. What is deliberately not tested, because it does not exist

Speech-to-text, class transcription, spoken-question capture, automatic
translation of speech. No such code path exists in this module, and the AI
usage view has no transcription line because there is no transcription cost to
report. If that changes in a future phase, this section is where its test plan
belongs.
