# LSS Online Classroom — media server setup

The media server runs on its **own host**, separate from the application VPS.
Nothing in this directory is deployed by the main GitHub Actions workflow; it is
set up once, by hand, on the media host.

Why a separate host: real-time media must not compete with Milvus and PostgreSQL
for CPU, and TURN needs port 443 — which nginx already holds on the application
VPS. Students on mobile networks behind carrier-grade NAT often cannot connect
at all without TURN on 443, so this is about whether classes work, not tidiness.

---

## 1. Provision

- Hetzner **CPX32** (4 shared vCPU, 8 GB RAM, 160 GB disk), Ubuntu 24.04, Nuremberg
  — see the sizing note in docs/ONLINE_CLASSES_ARCHITECTURE.md §8 before changing this
- DNS, both pointing at the new host's IPv4 (and AAAA if you use IPv6):
  - `live.lssbot.net` — signalling
  - `turn.lssbot.net` — TURN relay (shares port 443, routed by SNI)
- Firewall: allow **TCP 443, 7881**, **UDP 3478, 7882, 50000–60000**, plus SSH

The UDP range is not optional — WebRTC media flows over it. Blocking it forces
every participant through TURN, which multiplies bandwidth and latency.

## 2. Install Docker and fetch this directory

```bash
curl -fsSL https://get.docker.com | sh
mkdir -p /opt/lss-livekit && cd /opt/lss-livekit
# copy deploy/livekit/{docker-compose.yml,livekit.yaml,caddy.yaml} here
```

## 3. Generate the key pair

```bash
docker run --rm livekit/generate --keys
```

Put the result in `/opt/lss-livekit/.env` on this host:

```
LIVEKIT_API_KEY=APIxxxxxxxx
LIVEKIT_API_SECRET=<long secret>
```

Then paste the **key** (not the secret) into `livekit.yaml` in place of
`REPLACE_WITH_LIVEKIT_API_KEY` — that file is read literally, so an unreplaced
placeholder means webhooks are signed with a key the backend will reject, and
attendance silently stops working.

The **same pair** goes into the application VPS's `.env` (and the GitHub
`backend_variables` environment), together with the URLs:

```
LIVEKIT_URL=wss://live.lssbot.net
LIVEKIT_HTTP_URL=https://live.lssbot.net
LIVEKIT_API_KEY=APIxxxxxxxx
LIVEKIT_API_SECRET=<long secret>
```

The secret authorises token minting and room control. It stays on servers — it
is never sent to a browser, and never appears in a `VITE_*` variable.

## 4. Start

```bash
docker compose up -d
docker compose logs -f livekit
```

Caddy obtains the TLS certificate on first start; give it a minute, then check:

```bash
curl -s https://live.lssbot.net | head     # LiveKit responds "OK"
```

## 5. Verify end to end

1. On the application VPS, redeploy so the backend picks up the new variables.
2. Log in as a teacher → **Online Classes** → pick class/section/subject →
   **START CLASS**.
3. Log in as a student of that class on another device → **JOIN CLASS**.
4. Check attendance is recording:

```sql
SELECT user_name, first_join_at, total_seconds, status
FROM online_class_participants
ORDER BY created_at DESC LIMIT 10;
```

If rows never appear, the webhook is not arriving: confirm
`https://api.lssbot.net/api/livekit/webhook` is reachable from this host and
that both sides share the same API key and secret.

## 6. Recording (Phase 3, optional)

The `egress` service in `docker-compose.yml` is the recorder. Leave it commented
out until the school turns recording on — an idle recorder holds memory the SFU
could be using, and each concurrent recording costs roughly a CPU core.

To enable it:

1. Uncomment `egress` and `docker compose up -d`.
2. On the **application** VPS, set the storage variables so the recorder can
   upload finished files:

   ```
   RECORDING_BUCKET=class-recordings
   RECORDING_S3_ENDPOINT=https://minio.lssbot.net      # must be reachable from THIS host
   RECORDING_S3_ACCESS_KEY=…
   RECORDING_S3_SECRET_KEY=…
   ```

   The endpoint has to be reachable from the media host, not just from the
   application — the recorder uploads directly. Put MinIO behind TLS rather than
   exposing port 9000 in the clear; these are recordings of children.
3. In LSS Bot: **Admin → Live Classes → Settings** → turn on "Recording
   available school-wide", set the retention period, and cap how many classes
   may record at once (one core each).

Storage to plan for: roughly 500 MB per 45-minute class, so about 220 GB per
30-day retention window at 20 classes a day.

## 7. Load test before a real timetable depends on it

```bash
lk load-test --url wss://live.lssbot.net --api-key … --api-secret … \
  --room loadtest --publishers 1 --subscribers 30 --duration 5m
```

Repeat for 5, 10 and 20 concurrent rooms while watching `htop` and
`docker stats`. Size the host from what you measure, not from these notes.

---

## What is deliberately not here

- **No recording.** `livekit-egress` arrives in Phase 3, once the classroom
  itself is proven. It needs its own CPU budget (roughly one core per recording).
- **No transcription of any kind.** No Speech-to-Text service, container or API
  is part of this deployment. Classroom audio travels from the teacher to the
  students and nowhere else.
