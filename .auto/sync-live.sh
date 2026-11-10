#!/usr/bin/env bash
# Push the current templates to https://edit.lvh.me.
# The local compose file bind-mounts ./templates into the container, so only a
# restart is needed (Jinja caches templates when Flask isn't in debug mode).
set -euo pipefail
cd "$(dirname "$0")/.."

local_sha=$(sha1sum templates/index.html | cut -d' ' -f1)
remote_sha=$(docker exec remislop sha1sum /app/templates/index.html | cut -d' ' -f1)
if [ "$local_sha" != "$remote_sha" ]; then
  echo "templates are not bind-mounted into the container (local $local_sha != live $remote_sha)"
  echo "run: docker compose -f docker-compose.local.yml up -d"
  exit 1
fi

docker restart remislop >/dev/null
for _ in $(seq 1 40); do
  code=$(curl -sk -o /dev/null -w '%{http_code}' https://edit.lvh.me/ || true)
  if [ "$code" = "200" ]; then
    echo "live ok (https://edit.lvh.me -> 200)"
    exit 0
  fi
  sleep 0.5
done
echo "live site did not come back"
exit 1
