#!/usr/bin/env bash
#
# Deploy the demo box from git: pull, build here, restart.
#
# The mechanism, and why it is this one
# -------------------------------------
# dev pushes to GitHub, this box pulls from GitHub and builds its own
# image. No container registry in the path.
#
# It replaces a GitHub Actions workflow that built `linux/amd64`,
# pushed to GHCR and sshed in to `docker compose pull`. That had two
# problems. It was gated on CI passing, and when CI went red on
# 25 September the deploy silently *skipped* for three weeks while the
# box quietly served a September image — a deploy that does nothing
# and says nothing is worse than one that fails. And building
# elsewhere hid an architecture difference: an image built on an
# aarch64 dev box will not exec here, which is how this box lost four
# minutes on 11 October. Building where the thing runs cannot get the
# architecture wrong.
#
# Safe to re-run. It backs up before it changes anything, refuses to
# deploy a dirty tree, and leaves the previous image tagged so a
# rollback is one command.
#
# Usage:
#   ./deploy-demo.sh              # pull main, build, restart
#   ./deploy-demo.sh --no-pull    # build and restart what is checked out
#   ./deploy-demo.sh --rollback   # back to the previous image
#
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE="docker compose -f compose.prod.yml"
IMAGE="nsr-mis:demo"
PREVIOUS="nsr-mis:previous"
LOG="deploy.log"
HEALTH_URL="http://127.0.0.1:8005/healthz"

say() { printf '\n== %s: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"; }
run() { printf '   $ %s\n' "$*" | tee -a "$LOG"; "$@" >>"$LOG" 2>&1; }

rollback() {
  say "rolling back to $PREVIOUS"
  if ! docker image inspect "$PREVIOUS" >/dev/null 2>&1; then
    say "there is no $PREVIOUS image to roll back to"; exit 1
  fi
  run docker tag "$PREVIOUS" "$IMAGE"
  run $COMPOSE up -d
  say "rolled back"
  exit 0
}

[ "${1:-}" = "--rollback" ] && rollback

say "deploy starting on $(hostname)"

# 1. Never deploy a tree somebody has been editing by hand. A local
#    change here is invisible to everyone on dev and makes the running
#    code unreproducible from the repository.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  say "REFUSING: the checkout has uncommitted changes"
  git status --short | tee -a "$LOG"
  exit 1
fi

# 2. Pull. Fast-forward only, so a diverged local history stops the
#    deploy instead of being silently merged.
if [ "${1:-}" != "--no-pull" ]; then
  run git fetch origin main
  run git merge --ff-only origin/main
fi
say "deploying $(git log --oneline -1)"

# 3. Back up the database before anything restarts. Small, quick, and
#    the one thing that cannot be rebuilt from git.
mkdir -p backups
DUMP="backups/pre-deploy-$(date -u +%Y%m%d-%H%M%S).dump"
say "backing up to $DUMP"
$COMPOSE exec -T db pg_dump -U "${POSTGRES_USER:-nsr}" -d "${POSTGRES_DB:-nsr}" \
  -Fc --no-owner --no-acl > "$DUMP"
[ -s "$DUMP" ] || { say "REFUSING: the dump is empty"; exit 1; }
say "dump is $(du -h "$DUMP" | cut -f1)"

# 4. Keep the image that is working, so --rollback has somewhere to go.
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  run docker tag "$IMAGE" "$PREVIOUS"
fi

# 5. Build here. Native architecture, by construction.
say "building $IMAGE"
run docker build -t "$IMAGE" .

# 6. Restart. Migrations and collectstatic run in the web entrypoint.
say "restarting"
run env NSR_IMAGE="$IMAGE" $COMPOSE up -d --remove-orphans

# 7. Say whether it actually works, rather than whether the command
#    returned 0.
say "waiting for health"
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)
  [ "$code" = "200" ] && break
  sleep 4
done
if [ "${code:-}" != "200" ]; then
  say "UNHEALTHY: $HEALTH_URL returned ${code:-no response}"
  $COMPOSE logs web --tail 40 | tee -a "$LOG"
  say "roll back with: ./deploy-demo.sh --rollback"
  exit 1
fi

$COMPOSE ps --format '{{.Service}} {{.State}}' | tee -a "$LOG"
say "deployed $(git log --oneline -1) — healthz 200"
