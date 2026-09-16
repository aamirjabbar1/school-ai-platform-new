#!/usr/bin/env bash
# Simulate N simultaneous LSS classrooms against the media server.
#
# Sizing the production server from measurements rather than assumptions is the
# whole point (spec §27): run this at 5, 10 and 20 rooms while watching CPU and
# bandwidth on the media host, and write the numbers down.
#
#   export LIVEKIT_URL=wss://live.lssbot.net
#   export LIVEKIT_API_KEY=APIxxxx
#   export LIVEKIT_API_SECRET=…
#   scripts/load_test_classrooms.sh 10 [students] [duration]
#
# Requires the LiveKit CLI: https://github.com/livekit/livekit-cli

set -euo pipefail

ROOMS=${1:-5}
STUDENTS=${2:-30}
DURATION=${3:-5m}

: "${LIVEKIT_URL:?set LIVEKIT_URL}"
: "${LIVEKIT_API_KEY:?set LIVEKIT_API_KEY}"
: "${LIVEKIT_API_SECRET:?set LIVEKIT_API_SECRET}"

command -v lk >/dev/null || { echo "The LiveKit CLI (lk) is not installed."; exit 1; }

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="loadtest-${STAMP}"
mkdir -p "$OUT"

echo "Simulating ${ROOMS} classrooms × ${STUDENTS} students for ${DURATION}"
echo "Results: ${OUT}/"

pids=()
for i in $(seq 1 "$ROOMS"); do
  # One publisher per room is the teacher; subscribers are the class. Students
  # do not publish video in LSS unless a teacher grants it, so this matches the
  # real traffic shape rather than inflating it.
  lk load-test \
    --room "lss-loadtest-${STAMP}-${i}" \
    --publishers 1 \
    --subscribers "$STUDENTS" \
    --duration "$DURATION" \
    > "${OUT}/room-${i}.log" 2>&1 &
  pids+=($!)
  sleep 1   # stagger joins slightly, as a real period does
done

echo "Running. On the media host, capture in parallel:"
echo "  docker stats --no-stream lss_livekit"
echo "  ifstat -t 5 12"

for pid in "${pids[@]}"; do wait "$pid" || true; done

echo
echo "── Summary ─────────────────────────────────────────────"
grep -h -E "Summary|packets|latency|error" "${OUT}"/room-*.log | tail -40 || true
echo
echo "Full logs in ${OUT}/. Record CPU, bandwidth and join latency against the"
echo "run before sizing the production server."
