#!/usr/bin/env bash
# Bring up an Alertmanager and a receiver, replay one incident through them, and tear down.
#
# Usage:  scripts/incident_stack.sh
#
# A DOCKER NETWORK RATHER THAN HOST PORTS BETWEEN THE TWO, because Alertmanager has to reach the
# receiver by a name that resolves the same way on a laptop and on a runner. `host.docker.internal`
# does not exist on Linux, and discovering that in CI after the measurement is written is a waste
# of a run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK=quietz-incident

cleanup() {
  docker rm -f quietz-am quietz-receiver >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
rm -f "$ROOT/target/received.jsonl"
mkdir -p "$ROOT/target"

docker network create "$NETWORK" >/dev/null

echo "==> the receiver, which records what a human would be sent"
docker run -d --name quietz-receiver --network "$NETWORK" --network-alias receiver \
  -v "$ROOT":/repo -w /repo -p 19099:9099 \
  python:3.13-slim python scripts/receiver.py >/dev/null

echo "==> alertmanager, with the configuration this repository ships"
docker run -d --name quietz-am --network "$NETWORK" \
  -v "$ROOT/alertmanager":/etc/alertmanager -p 19093:9093 \
  prom/alertmanager:v0.29.0 --config.file=/etc/alertmanager/alertmanager.yml >/dev/null

# A readiness loop rather than a sleep: a fixed wait is too short on a slow runner and wasted on
# a fast one, and the failure it produces looks like a bug in the thing being measured.
for attempt in $(seq 1 60); do
  if curl -sf http://127.0.0.1:19093/-/ready >/dev/null; then
    echo "    ready after ${attempt} attempts"
    break
  fi
  sleep 1
done

uv run python "$ROOT/scripts/measure_incident.py"
