# LSS Online Classroom — production deployment runbook

Two hosts are involved:

- **Application VPS** (existing, `167.235.202.139`) — LSS Bot, deployed by
  pushing to `main`. Carries the new backend routes, the classroom UI, the
  LibreOffice converter and `celery_beat`.
- **Media host** (new, Hetzner CCX23, `live.lssbot.net`) — LiveKit SFU, TURN
  and the Egress recorder. Set up by hand, once.

Online Classes stays dormant until the `LIVEKIT_*` variables are set, and the
rest of LSS Bot is unaffected either way. That is deliberate: the application
can be deployed before the media host exists, and nothing breaks in between.

---

## Step 1 — Application VPS (automatic, on push to `main`)

The workflow pulls, rewrites `.env` from the GitHub `backend_variables`
variable, and runs `docker compose up --build -d --remove-orphans`. Migrations
run themselves: the backend's `start.sh` executes `alembic upgrade head` before
uvicorn starts.

What changes on this host:

| Change | Effect |
|---|---|
| `backend` image rebuild | Adds `livekit-api`; applies migrations `a1b2c3d4e5f6` and `b2c3d4e5f6a7` (14 new tables, nothing altered) |
| `frontend` image rebuild | Adds the classroom UI (`livekit-client`, `pdfjs-dist`), code-split so the dashboard bundle is unaffected |
| `converter` (new) | LibreOffice worker on the `conversion` queue — PowerPoint/Word → PDF, cached in MinIO |
| `celery_beat` (new) | Closes abandoned classes, materialises the timetable, sends reminders, expires recordings |

> ⚠️ **The deploy rewrites `.env` in full.** Any variable missing from the
> GitHub `backend_variables` is erased from the server. Add the new variables
> there *before* the deploy, or Online Classes comes up dormant.

### Variables to add to `backend_variables`

```
# Media server (from step 2)
LIVEKIT_URL=wss://live.lssbot.net
LIVEKIT_HTTP_URL=https://live.lssbot.net
LIVEKIT_API_KEY=APIxxxxxxxx
LIVEKIT_API_SECRET=<secret>
LIVEKIT_TOKEN_TTL_HOURS=3

# Recording storage (see step 4)
RECORDING_BUCKET=class-recordings
RECORDING_S3_ENDPOINT=https://minio.lssbot.net
RECORDING_S3_ACCESS_KEY=<minio user>
RECORDING_S3_SECRET_KEY=<minio password>
RECORDING_S3_REGION=us-east-1

# AI model routing (optional — this is the default)
AI_MODEL_FAST=claude-haiku-4-5
```

### Verifying this host

```bash
curl -s https://api.lssbot.net/health
docker compose ps                     # backend, frontend, converter, celery_beat up
docker compose logs backend | grep -i alembic
docker compose exec backend alembic current      # expect b2c3d4e5f6a7 (head)
docker compose logs converter | tail -20         # LibreOffice ready
```

Existing modules to spot-check afterwards: login, AI chat, Knowledge Base
upload, assignments, lesson plans, question papers.

---

## Step 2 — Media host (manual, once)

Full instructions in `deploy/livekit/README.md`. In short:

1. Hetzner **CCX23** (4 dedicated vCPU, 16 GB, 20 TB traffic), Ubuntu 24.04.
2. DNS → the new host's IPv4:
   - `live.lssbot.net` (signalling)
   - `turn.lssbot.net` (TURN relay, shares 443 by SNI)
3. Firewall: **TCP 443, 7881**; **UDP 3478, 7882, 50000–60000**; SSH.
   The UDP range is not optional — without it every student is forced through
   TURN, multiplying bandwidth and latency.
4. Copy `deploy/livekit/{docker-compose.yml,livekit.yaml,caddy.yaml}` to
   `/opt/lss-livekit/`.
5. Generate the key pair **on the host** so the secret never travels through a
   chat log or a ticket:
   ```bash
   docker run --rm livekit/generate --keys
   ```
   Put it in `/opt/lss-livekit/.env`, paste the **key** into `livekit.yaml`
   (replacing `REPLACE_WITH_LIVEKIT_API_KEY`), and put the same pair into the
   GitHub `backend_variables` from step 1.
6. `docker compose up -d` — Caddy obtains both certificates on first start.
7. Check: `curl -s https://live.lssbot.net` answers, and
   `docker compose logs livekit | tail` shows the webhook URL.

---

## Step 3 — Recording (enabled for this deployment)

The `egress` service is enabled in `deploy/livekit/docker-compose.yml`. Three
further things make recordings actually work:

1. **Reachable, encrypted storage.** The recorder uploads directly, so MinIO
   must be reachable from the media host over TLS — see
   `nginx/minio-recordings.conf.example` (a TLS hostname for MinIO, plus
   binding the raw ports to localhost).
2. **The bucket.** `class-recordings` is created automatically on first upload,
   or in advance:
   ```bash
   docker compose exec minio mc mb --ignore-existing local/class-recordings
   ```
3. **The school's policy switch.** Recording is off in the database until an
   administrator turns it on — **Admin → Live Classes → Settings → "Recording
   available school-wide"**, where retention days and the concurrency cap also
   live. Equivalent SQL if you prefer:
   ```sql
   UPDATE online_class_settings
      SET recording_enabled_globally = true,
          recording_retention_days   = 30,
          max_concurrent_recordings  = 2;
   ```
   Leave `recording_default_on` false unless every scheduled class should be
   recorded automatically; teachers can still press Record per class.

Budget roughly **1 CPU core and ~500 MB of storage per 45-minute recording**.
The concurrency cap exists so recordings cannot starve live classes of the CPU
they need.

---

## Step 4 — Post-deployment checks

| Check | How |
|---|---|
| Existing app healthy | `curl https://api.lssbot.net/health`; log in as each role |
| Migrations applied | `alembic current` → `b2c3d4e5f6a7` |
| New routes live | `GET /api/online-classes/student/today` returns 401 (route exists, auth enforced) — not 404 |
| Media server connected | Admin → Live Classes: the "not connected yet" banner is gone |
| Module health | `GET /api/admin/online-classes/health` as an admin |
| No secrets in the bundle | `grep -ri secret frontend/dist/assets/*.js` returns nothing |
| First class | Start a class as a teacher, join as a student on another device |
| Recording | Record 2 minutes, stop, confirm it appears under Recorded Classes for that class only |

---

## Rollback

The application and the media host roll back independently.

**Application:**
```bash
git revert -m 1 <merge-commit>      # then push; the workflow redeploys
# or, on the VPS:
git checkout pre-online-classes && docker compose up --build -d
```
The migrations are additive — 14 new tables, nothing altered — so the previous
code runs unchanged against the new schema. Only drop the tables if you want the
schema back too:
```bash
docker compose exec backend alembic downgrade e1f2a3b4c5d6
```

**Media host:** `docker compose down` on `/opt/lss-livekit`. With the media
server gone, Online Classes shows "not connected yet" and the rest of LSS Bot
carries on.

**Emergency stop without a deploy:** clear `LIVEKIT_URL` in the GitHub
`backend_variables` and redeploy. Classes stop being startable; nothing else
changes.
