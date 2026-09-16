# LSS Online Classes — Technical Implementation Plan

**Status:** Proposal, awaiting validation. No code has been written yet.
**Scope:** Add a native Online Classroom module to the existing LSS Bot (FastAPI + React), per the Online Classes master specification.
**Explicitly excluded (this phase):** Speech-to-Text, class transcription, any audio/video analysis by an AI model.

---

## 1. What already exists (audit findings)

Verified by reading the codebase, not assumed.

| Area | Current state | Reuse for Online Classes |
|---|---|---|
| Backend | FastAPI (async), `backend-python/`, routers mounted under `/api` in [main.py](backend-python/main.py) | Add one router module, same pattern |
| Auth | JWT HS256 bearer, `create_token(user_id)`, `get_current_user`, `require_roles(...)` in [middleware/auth.py](backend-python/middleware/auth.py); token in `localStorage` | Reused as-is. No new login anywhere |
| Roles | `admin` / `teacher` / `student` on `users.role` | Reused |
| Student → class | `users.class_name` (`"Class 1".."Class 12"`, `Pre-Nursery/Nursery/KG`) + `users.section` | Drives JOIN authorization |
| Teacher → class | `users.assigned_classes` (`"Grade N"` wording), `users.assigned_sections` (`"Grade 5 - A"`), `users.subjects` | Drives START CLASS dropdowns |
| Class-name mismatch | `Grade N` vs `Class N`; normalizers exist: `classKey()` in [frontend/src/constants/academics.js](frontend/src/constants/academics.js), `normalize_class`/`normalize_section` in [services/student_excel_import_service.py](backend-python/services/student_excel_import_service.py) | Must be reused — a new backend `class_matching` helper will wrap them |
| Pre-Board mapping | `curriculum_mappings` + [services/curriculum_service.py](backend-python/services/curriculum_service.py) (`Class 8 → Class 9`) | Applied when filtering books/KB for a classroom |
| Knowledge Base | `documents` rows + files in **MinIO** (`documents/{id}/{file}`), chunks in Postgres + **Milvus** with `page_number`, `chapter_title`, `subject`, `class_level` metadata | Book picker + page presentation + Ask-AI retrieval |
| Book file access | [routes/documents.py](backend-python/routes/documents.py) `GET /documents/{id}/download` streams from MinIO | New classroom-scoped, range-capable variant |
| Lesson Plans | `lesson_plans.plan_data` (`{"lessons":[…]}`), review/approval via `ReviewableMixin`, mirrored into the KB by [services/lesson_plan_store.py](backend-python/services/lesson_plan_store.py) | "Today's Lesson Plan" + coverage tracking |
| AI | Anthropic SDK in [services/ai_service.py](backend-python/services/ai_service.py); LangChain agent in [services/agent_service.py](backend-python/services/agent_service.py); single model from `AI_MODEL` env; retrieval via `search_knowledge_base` | Ask-AI, summaries, teacher assistant — with a new routing/budget layer |
| Background jobs | Celery + Redis ([celery_app.py](backend-python/celery_app.py)); **no beat scheduler yet** | Post-class jobs, reminders, retention sweeps — beat must be added |
| Audit | `content_revisions` append-only table + [services/audit_service.py](backend-python/services/audit_service.py) | Pattern copied for classroom event log |
| Notifications | `notifications` table + [routes/notifications.py](backend-python/routes/notifications.py) | Class reminders / "class is live" |
| Storage | MinIO bucket `school-documents`, presigned URLs available | New bucket for recordings/whiteboards |
| Frontend | React 18 + Vite + Tailwind, dark-first glass design system, nav in [components/Layout.jsx](frontend/src/components/Layout.jsx), API client [services/api.js](frontend/src/services/api.js) | New pages + nav entries only; nothing existing is modified beyond additive nav/route lines |
| Deployment | **Single Hetzner VPS** (`167.235.202.139`), docker compose (postgres, redis, minio, etcd, milvus, backend, celery_worker, frontend, attu), nginx TLS for `lssbot.net` / `api.lssbot.net`, GitHub Actions deploy on push to `main` | Determines the media-server decision below |

Two facts that shape everything: **(a)** there is no WebSocket infrastructure anywhere in the app today (chat uses SSE), and **(b)** all services share one VPS whose port 443 is already held by nginx.

---

## 2. Technology decision — media engine

### Recommendation: **LiveKit (self-hosted, Apache-2.0)** with a 100% LSS-built UI

| Requirement from the spec | LiveKit | BigBlueButton |
|---|---|---|
| Feels native, never "another platform" (§1, §2) | We build every pixel in React on top of `livekit-client` | Its HTML5 client *is* the UI; embedding = iframe = visibly another app. Forking it is a heavy, permanent maintenance burden |
| No meeting IDs/passwords (§1) | Server mints a scoped JWT per user; room name is a UUID | Join URL carries meetingID + password (proxy-able, but the UI stays theirs) |
| Simplified Nursery/KG interface (§5) | Trivial — it's our own component tree | Requires patching their client |
| Whiteboard (§6) | We build it (canvas + stroke sync over LiveKit data channels) | Built in, but not ours to shape |
| KB book sharing with page/annotation sync + **structured events** (§7, §16, §18) | Native: our own state machine writes `page_presented` rows as it goes | Would require scraping their presentation state; no clean link to our `documents` table |
| Automatic attendance (§13) | Server-side webhooks (`participant_joined/left`) → DB rows | Available via callbacks, coarser |
| Recording (§15) | LiveKit Egress container → MP4 into our existing MinIO | Built in, heavy post-processing pipeline |
| Runs on our infrastructure (§28) | Single Go binary, Docker, host networking | **Requires a clean, dedicated Ubuntu 22.04 server** — cannot share the existing VPS |
| Low bandwidth (§23) | Simulcast + adaptive stream + dynacast + audio DTX/RED, all built in | Good, less controllable |
| Cost | Free software; cost is server capacity only | Same, but needs a bigger dedicated box |

Also considered and rejected: **Jitsi** (same iframe/native-feel problem; `lib-jitsi-meet` custom UIs are poorly documented), **mediasoup/Janus** (we'd be building the engine — the spec forbids that), **Daily/Agora/Zoom SDK** (per-minute paid APIs → recurring cost, §19J).

BigBlueButton's genuine advantage is that whiteboard + presentation + polls arrive for free. The reason it still loses: the spec's two hardest requirements — *feel native* and *record structured classroom events that feed lesson records and AI* — are exactly the two things an embedded BBB cannot give us. And it needs its own dedicated server anyway, so it is not the cheaper option either.

### How LiveKit maps to the requirements

- **Tokens:** `livekit-api` (Python) mints a short-lived JWT server-side from the already-authenticated LSS user. Students get `canPublish: false` (audio unlocked only by teacher action), `canPublishData: true` (raise hand only), `roomAdmin: false`. The browser never sees the LiveKit API key/secret.
- **Teacher controls (§12):** performed by *our backend* via LiveKit's server API (`mute_published_track`, `update_participant`, `remove_participant`, room metadata). The teacher's browser has no admin rights — it asks our API, which authorizes and then acts.
- **Classroom state (§8, §11):** `stage_mode` ∈ `camera | book | whiteboard | screen` plus per-mode state is broadcast on a **reliable data channel** and simultaneously persisted (Redis + DB). Students' main area follows the teacher automatically; late joiners and reconnects read the persisted state. Book↔whiteboard switching is instant because both panes stay mounted client-side.
- **Book sharing (§7):** only `{document_id, page, zoom, annotations}` crosses the wire — a few hundred bytes — not a video stream. Each student renders the same PDF page locally via `pdf.js` from a class-scoped streaming endpoint. This is dramatically cheaper and sharper than screen-sharing a PDF, which matters on Pakistani home internet.
- **Document camera (§10):** a second video track (`facingMode: "environment"`, `degradationPreference: maintain-resolution`, low framerate) published under track name `doc-cam`. No new infrastructure.
- **No STT anywhere:** audio exists only inside the media plane (LiveKit → students, and optionally → Egress → MP4 in MinIO). No code path will connect recordings or audio tracks to any AI provider. This is an architectural property, not a policy note.

---

## 3. Architecture

```
┌──────────────────────── Browser (React, LSS UI) ─────────────────────────┐
│  Teacher Classroom / Student Classroom / Kids Classroom / Admin room     │
│  livekit-client (media)  ·  pdf.js (books)  ·  canvas whiteboard         │
└───────┬──────────────────────────────────────────────┬──────────────────┘
        │ HTTPS  api.lssbot.net (JWT — existing auth)  │ WSS+WebRTC  live.lssbot.net
        ▼                                              ▼
┌─────────────── FastAPI backend (existing container) ──────┐   ┌──────────────────┐
│ routes/online_classes.py  · livekit_webhooks.py           │   │  livekit-server  │
│ services/livekit_service.py (provider-agnostic interface) │◄──┤  (SFU + TURN)    │
│ services/classroom_state.py (Redis) · attendance_service  │   │  livekit-egress  │
│ services/class_ai_service.py · ai_usage_service           │   │  (recording)     │
└───────┬───────────────────────┬────────────────┬──────────┘   └────────┬─────────┘
        ▼                       ▼                ▼                       ▼
   PostgreSQL              Redis (state,     Milvus + MinIO        MinIO bucket
   (sessions, attendance,   presence,        (KB retrieval,        class-recordings
    events, lesson records) celery)          book files)
                                    │
                                    ▼
                        Celery worker + **beat** (new)
             post-class finalize · AI summary · reminders · retention sweep
```

Three layers, exactly as §19K requires:

1. **Core classroom — zero AI tokens.** Start/join, authorization, media, whiteboard, books, controls, attendance, recording, reconnection, admin monitoring. Every one of these is plain application logic.
2. **Academic data layer.** Structured events recorded as they happen: pages presented, resources opened, whiteboards saved, homework typed, teacher-confirmed coverage.
3. **AI enhancement layer — text-to-text only.** Reads layer 2 + the Knowledge Base. If it is unavailable, layers 1 and 2 are unaffected.

---

## 4. Components to add

**Backend (new files only — no existing file is restructured):**

```
routes/online_classes.py       teacher + student + shared classroom endpoints
routes/live_classes_admin.py   admin control room, settings, AI usage
routes/livekit_webhooks.py     signature-verified webhook receiver (no bearer auth)
services/livekit_service.py    token minting, room ops, egress — behind an interface
services/classroom_state.py    Redis-backed live state (stage, hands, mic grants)
services/attendance_service.py join/leave ledger → durations, %, present/late/partial/absent
services/class_events.py       append-only structured classroom event writer
services/class_ai_service.py   summary / revision notes / coverage / ask-AI / teacher assistant
services/ai_usage_service.py   feature toggles, budgets, usage + cost ledger
services/class_matching.py     wraps existing class/section normalizers for authorization
models/online_classes.py       new tables (imported by models/models.py + alembic env)
tasks/online_class_tasks.py    finalize, AI summary, reminders, retention sweep
```

**Frontend:**

```
pages/teacher/OnlineClasses.jsx     Class → Section → Subject → START CLASS
pages/teacher/Classroom.jsx         teaching interface (large controls only)
pages/student/OnlineClasses.jsx     TODAY'S CLASSES + 🔴 LIVE + JOIN CLASS
pages/student/Classroom.jsx         standard student view
pages/student/KidsClassroom.jsx     Pre-Nursery…Class 2 (3 buttons, nothing else)
pages/student/RecordedClasses.jsx   recordings permitted for their class/section
pages/admin/LiveClasses.jsx         control room + logs + settings + AI usage
components/classroom/*              Stage, Whiteboard, BookViewer, Controls,
                                    ParticipantsPanel, RaiseHand, AskAIPanel,
                                    ConnectionBanner, LowBandwidthToggle
```

New frontend deps: `livekit-client`, `pdfjs-dist`. (Deliberately **not** adding a heavy whiteboard library — a ~600-line pointer-events canvas gives us stroke-level control, touch/stylus support, and a JSON format we can persist and hand to the lesson record.)

**Infrastructure:** `livekit` service (+ `livekit-egress` in Phase 3), `celery_beat` service, `coturn` or LiveKit's embedded TURN, nginx server block for `live.lssbot.net` with WSS upgrade, new MinIO bucket `class-recordings`. LibreOffice added to the worker image only if PPTX/DOCX→PDF conversion is approved (free, no API).

---

## 5. Database changes (all via Alembic migrations)

| Table | Purpose | Key columns |
|---|---|---|
| `online_class_schedules` | §20 scheduled/recurring timetable | teacher_id, subject, class_name, section, recurrence, weekday, start_time, duration_min, start_date, end_date, is_active |
| `online_class_sessions` | one live/ended class | id, schedule_id?, teacher_id, subject, class_name, section, status (`scheduled\|live\|ended\|cancelled`), room_name (UUID), scheduled_start, actual_start, actual_end, planned_duration_min, lesson_plan_id?, stage_mode, stage_state JSON, recording_enabled, teacher_disconnected_at, academic_session |
| `online_class_participants` | §13 attendance summary, one row per user per session | session_id, user_id, role, name/class/section (denormalized), first_join_at, last_leave_at, total_seconds, rejoin_count, attendance_percent, status (`present\|late\|partial\|absent`), finalized |
| `online_class_attendance_events` | append-only join/leave/rejoin ledger | session_id, user_id, event, at, participant_sid, reason |
| `online_class_events` | §19E structured classroom events (the AI's only factual source) | session_id, actor_id, type (`book_opened`, `page_presented`, `whiteboard_saved`, `resource_opened`, `screen_share`, `mute_all`, `hand_raised`, `recording_started`, …), payload JSON, at |
| `online_class_resources` | which KB documents/pages were actually presented | session_id, document_id → `documents.id`, pages_presented JSON, first_shown_at, last_shown_at |
| `online_class_whiteboards` | §6 saved boards | session_id, page_index, strokes JSON, image_object (MinIO), saved_by |
| `online_class_recordings` | §15 | session_id, egress_id, bucket/object, duration_sec, size_bytes, status, retention_days, expires_at, deleted_at |
| `online_class_lesson_records` | §16/§18 official record — **teacher-confirmed** | session_id, topics_covered JSON, pages_covered JSON, homework, teacher_notes, lesson_plan_id, ai_suggestion JSON (unconfirmed), confirmed_by, confirmed_at |
| `online_class_ai_outputs` | §19E cache — one summary per class, not per student | session_id, kind (`summary\|revision_notes\|coverage`), model, content JSON, sources JSON, is_stale, generated_at |
| `online_class_ai_questions` | §19 Ask-AI traceability + dedupe cache | session_id, student_id, question, answer, sources JSON, model, created_at |
| `ai_usage_events` | §19G monitoring | feature, provider, model, user_id, role, session_id, input_tokens, output_tokens, est_cost_usd, status, created_at |
| `online_class_settings` | §19F admin config (single row, JSON) | attendance rules, grace periods, recording defaults + retention, young-grade list, AI toggles, daily/monthly budgets, per-student question cap, model routing |

No existing table is altered. `users`, `documents`, `lesson_plans` are referenced by foreign key only.

---

## 6. API surface

**Teacher** — `POST /api/online-classes/start`, `/{id}/token`, `/{id}/end`, `/{id}/stage`, `/{id}/resources`, `/{id}/resources/{doc}/page`, `/{id}/whiteboard`, `/{id}/recording/start|stop`, `/{id}/controls/{action}` (mute-all, mute, allow-mic, cameras-off, remove, lock, hand-resolve), `GET /teacher/options`, `GET /teacher/today`, `GET|PUT /{id}/lesson-record`, `POST /{id}/ai/summary`, `POST /{id}/ai/assistant`, `GET /{id}/attendance[.csv]`.

**Student** — `GET /online-classes/student/today`, `POST /{id}/join`, `POST /{id}/leave`, `POST /{id}/hand`, `GET /{id}/summary`, `POST /{id}/ask-ai`, `GET /online-classes/recordings`, `GET /recordings/{id}/stream`, `GET /{id}/resource/{document_id}/file` (range-capable, class-scoped).

**Admin** — `GET /admin/live-classes` (12 live / 287 students / 18 teachers + per-class rows), `GET /admin/live-classes/{id}`, `POST /{id}/observe` (audited), `POST /{id}/end`, `GET|PUT /admin/online-classes/settings`, `GET /admin/ai-usage`, `GET /admin/live-classes/logs`.

**Webhook** — `POST /api/livekit/webhook` (HMAC-verified against the LiveKit API secret; never bearer-authenticated).

---

## 7. Security & privacy

- LiveKit API key/secret live only in backend env — never in a browser, never in `VITE_*`.
- Room name is a UUID; tokens are short-lived (2 h, re-mintable on reconnect), bound to `user.id`, and carry the minimum grants. No public or guessable join URL exists.
- Every join re-verifies **class + section** server-side using the shared normalizer (`Grade 5` ≡ `Class 5`), plus teacher assignment for start/control actions. Students cannot join another section's class even with a valid LSS token.
- Students: `canPublish=false` by default (teacher grants mic per student), no screen share, no presenter control, no participant management, stricter defaults for Pre-Nursery…Class 2.
- Admin observation writes an audit row and shows a visible "Administrator is observing" indicator to the class — a minors-privacy requirement, not an optional nicety.
- Recording is off unless enabled by policy; recordings are access-controlled by class/section and streamed through an authorizing endpoint (or 60-second presigned URLs), never a public bucket.
- `slowapi` rate limits on join, ask-AI, and control endpoints (the limiter is registered in `main.py` but currently unused — this module will be its first consumer).
- Recordings and live audio are never passed to any AI provider. There is no code path from the media plane to the AI layer.

---

## 8. Infrastructure, bandwidth, storage

**Server.** LiveKit must not share CPU with Postgres/Milvus/Celery under real load, and it wants port 443 free for TURN/TLS (Pakistani mobile carriers behind CGNAT frequently need TURN; nginx already owns 443 on the current VPS). Recommended: a second Hetzner box, `live.lssbot.net`.

| Option | Spec | Cost | Verdict |
|---|---|---|---|
| **A. Dedicated CCX23** (4 dedicated vCPU, 16 GB, 20 TB traffic) | livekit-server + TURN, egress later | **≈ €24.49/mo** | Recommended for production (10–20 concurrent classes) |
| B. Existing VPS | livekit-server with host networking, TURN on 3478/5349 | €0 | Acceptable for a Phase 1 pilot of 1–2 classes only; shares CPU with Milvus |
| C. CCX33 (8 vCPU, 32 GB, 30 TB) | SFU + egress recording together | ≈ €48.49/mo | If recording is enabled school-wide from day one |

**Bandwidth** (teacher video 360p ≈ 400 kbps received per student + 32 kbps audio; book/whiteboard sync is data-channel, < 10 kbps):

- One class of 30 ≈ **13 Mbps** server egress; 10 concurrent classes ≈ **130 Mbps** — comfortable on a 1 Gbps NIC.
- Monthly traffic ≈ 4.4 GB per 45-minute class → 20 classes/day × 22 days ≈ **1.9 TB/month**; 40/day ≈ 3.8 TB — inside the 20 TB included.
- Low-bandwidth mode (audio + content only) ≈ 40 kbps per student ≈ 1.2 Mbps for a class of 30.

**Storage.** 720p composite recording ≈ 500 MB per 45-minute class → 20/day ≈ 10 GB/day ≈ **220 GB/month**. 30-day retention ≈ 220 GB, 90-day ≈ 660 GB. Retention is admin-configurable (30/60/90/permanent) with a nightly Celery sweep. Recording is the single biggest storage driver — recommend defaulting to 30 days and enabling recording per class rather than globally.

---

## 9. AI usage and cost control (text-to-text only)

| Feature | When it runs | Model tier | Caching |
|---|---|---|---|
| Class summary | Once per class, after the teacher confirms the lesson record | Low-cost | Stored; 30 students read the same row — no second call |
| Lesson-plan vs actual coverage | Once, in the same post-class job | Low-cost | Stored as a *suggestion* until the teacher confirms |
| Revision notes | Once per class, on demand | Low-cost | Stored |
| Ask LSS AI about this class | Only when a student types a question | Capable | Identical questions in a session reuse the stored answer |
| Teacher AI assistant | On demand | Capable | — |

Controls: one post-class job instead of many small calls; retrieval-scoped context (only the pages presented, the lesson plan, the relevant KB chunks — never the whole Knowledge Base); per-feature admin toggles; daily/monthly budgets; per-student question caps; per-feature model routing stored in settings, so models and providers can change without touching the classroom code. Every call writes an `ai_usage_events` row with tokens and estimated cost, which powers the admin monitoring screen and threshold alerts.

Rough cost per class: summary + coverage ≈ 4k in / 1.5k out on a low-cost model ≈ **$0.01–0.03**; a typed student question ≈ 3k in / 700 out on a capable model ≈ **$0.03–0.06**. A school day of 20 classes with 50 student questions lands around **$2–4/day**, fully capped by the configured budget.

If the AI provider is down, disabled or over budget, the classroom is unaffected: the features degrade to "Summary not available yet" and everything else keeps working.

---

## 10. New costs requiring approval (§19J)

| # | Item | Required for | Existing alternative? | Pricing | Est. cost | If disabled |
|---|---|---|---|---|---|---|
| 1 | **LiveKit server software** | All live audio/video | None — we will not build WebRTC | Apache-2.0, free, self-hosted | **€0** | No classroom |
| 2 | **Hetzner CCX23** `live.lssbot.net` | SFU + TURN capacity, free 443 for TURN/TLS | Share the existing VPS (pilot only) | ≈ €24.49/mo (20 TB traffic) | **≈ €24.49/mo** | Runs on the current VPS at 1–2 class capacity |
| 3 | **TURN (coturn / embedded)** | NAT traversal for mobile networks | None | Free | €0 (uses #2) | 20–40% of students fail to connect |
| 4 | **Recording storage** | §15 | Existing MinIO + attached volume | Volume storage only | ≈ 220 GB per 30-day window | No recordings |
| 5 | **LibreOffice in worker image** | PPTX/DOCX → PDF for book sharing | Teacher uses Share Screen instead | Free (LGPL) | €0 (+~400 MB image) | Those formats fall back to screen share |
| 6 | **Existing Anthropic API** (already approved) | §19 text-to-text features | — | Existing account | ≈ $2–4 per school day, budget-capped | AI panels hidden; class unaffected |

**No Speech-to-Text or transcription service appears anywhere in this plan.** Nothing in this table is activated without explicit approval.

---

## 11. Phases

| Phase | Deliverable | Exit test |
|---|---|---|
| **1 — Core classroom** | LiveKit deployed; tokens; START CLASS / JOIN CLASS; class+section authorization; audio/video; teacher mute/remove/end; basic attendance from webhooks; teacher + student + kids UI shells | Two real classes run end-to-end on a phone and a laptop; attendance rows correct after disconnects |
| **2 — Teaching tools** | Whiteboard (+save), book picker from KB, PDF page presentation with annotations, book↔whiteboard switching, screen share, resource sharing, `page_presented` events | Teacher presents page 42, switches to whiteboard, returns to page 42; students follow automatically |
| **3 — Administration** | Admin Live Classes control room, observation with audit, detailed attendance + reports, recording via Egress, retention policy, logs | 3 simultaneous classes visible and controllable; a recording is produced, stored, retrievable and expires on schedule |
| **4 — AI & academic (text-to-text)** | Lesson Plan link, teacher-confirmed lesson record, cached class summary, coverage analysis, revision notes, Ask LSS AI, teacher assistant, admin AI toggles/budgets/monitoring | 30 students open the summary → exactly one AI call in the usage ledger; all features degrade cleanly when disabled |
| **5 — Optimization** | Mobile UX pass, low-bandwidth mode, reconnection/grace periods, load testing, security hardening | 5/10/20 simultaneous rooms load-tested; measured CPU/bandwidth documented before production sign-off |

Nothing moves to production until the previous phase has been tested with real users.

---

## 12. Testing strategy

- **Unit:** attendance arithmetic (join/disconnect/rejoin → total minutes and %), present/late/partial/absent rules, the class+section authorization matrix (`Grade 5` vs `Class 5`, wrong section, inactive user, Pre-Board mapping), stage state machine.
- **Integration:** webhook → attendance ledger → finalized summary; start→present pages→end→lesson record→AI summary caching (assert exactly one AI call for N readers).
- **Security:** student token cannot publish; student of section B cannot join section A; expired/forged token rejected; webhook without valid signature rejected; recording URL unusable by another class.
- **Load:** `lk load-test` simulating 5, 10 and 20 rooms × 30 subscribers; record CPU, memory, bandwidth, join latency, failure rate; size the server from measurements, not assumptions.
- **Device matrix:** Android Chrome (phone + tablet), iOS Safari, Windows Chrome/Edge — including a deliberately throttled 3G profile and a mid-class network drop.
- **Failure drills:** kill the AI provider key, kill Redis, kill the teacher's network for 3 minutes — the class must survive all three.

---

## 12A. Build status — all five phases complete (2026-09-16)

| Phase | Delivered |
|---|---|
| **1 — Core classroom** | START CLASS / JOIN CLASS, class+section authorization, live audio/video, teacher controls (mute all, per-student mic, lock, remove, end), automatic attendance from media-server webhooks, reconnection with a teacher grace period, young-learner interface |
| **2 — Teaching tools** | Canvas whiteboard (pen/highlighter/shapes/text/eraser, thickness, undo, pages, save), Knowledge Base book presentation via pdf.js with live annotation, instant book↔whiteboard switching with state kept, screen share with an honest mobile fallback, document-camera mode, LibreOffice conversion worker with caching, structured `page_presented` events |
| **3 — Administration** | Live Classes control room (counts, live list, history, event log, reports), audited admin observation, force-end, recording via LiveKit Egress to MinIO with retention sweeps, student Recorded Classes with class/section scoping, weekly timetable + notifications, `celery_beat` |
| **4 — AI (text-to-text)** | Teacher-confirmed lesson records, cached class summaries (one call per class), lesson-plan coverage analysis, revision notes, Ask LSS AI About This Class with source traceability, teacher assistant, homework drafting that publishes through the existing Assignments module, admin AI settings, budgets and usage monitoring |
| **5 — Optimization** | Low-bandwidth mode, classroom code-splitting (media client + PDF renderer load on demand), mobile-first controls, 75-test pytest suite, load-test tooling, monitoring endpoint, security review |

**Totals:** 14 new tables across two additive migrations, 59 API endpoints, 12
new backend modules, 13 new frontend pages/components, 2 new containers
(`converter`, `celery_beat`).

**Verified in this build:** every module imports and all routes register in the
backend image; both migrations render valid SQL end to end; `docker compose
config` validates; the frontend builds with the classroom split into its own
chunk; 75 unit tests pass covering the authorization matrix, attendance
arithmetic, webhook signature verification, AI routing and cost control, context
rendering, range requests and presentation formats; no API secret appears in the
built bundle; and a repository-wide grep confirms no speech-to-text,
transcription or audio-analysis code path exists.

Two deliberate scope decisions worth knowing:

- **Students publish nothing until the teacher allows it** — microphone and
  camera are both teacher-granted per student, and a grant survives a reconnect.
  Thirty always-on student cameras would swamp a typical home connection, and
  the spec's own layout puts the teacher and the content on screen, not a grid
  of children.
- **A page being displayed is never recorded as "taught."** The lesson record is
  pre-filled from what the classroom actually showed and then waits for the
  teacher to confirm or edit it. AI proposes; the teacher signs.

Remaining before a real class can run: provision the media host per
`deploy/livekit/README.md`, set the `LIVEKIT_*` and `RECORDING_S3_*` variables,
rebuild the backend image (for `livekit-api`), and run `alembic upgrade head`.
Then work through `docs/ONLINE_CLASSES_TESTING.md`.

## 13. Decisions (approved 2026-09-16)

1. **Media engine: LiveKit, self-hosted.** BigBlueButton not used.
2. **Hosting: dedicated Hetzner CCX23** at `live.lssbot.net` (~€24.49/mo), separate from the application VPS.
3. **Recording: Phase 3**, as planned. Tables and settings are created up front so it can be switched on without a migration.
4. **PPTX/DOCX presentation:** still open — default is Share Screen fallback until LibreOffice conversion is approved.

Implementation proceeds phase by phase; each phase is tested before the next begins.
