#!/usr/bin/env bash
#
# NSR MIS — production deploy.
#
#   /opt/nsrmis/deploy.sh [ref]        ref defaults to origin/main
#
# The whole deployment: fetch the code, build the image HERE, switch the
# stack onto it. No registry, no CI artefact, no image transfer.
#
# Why this shape
# --------------
# The registry round-trip was the only part that ever failed. Three
# deploys half-succeeded: a queued run rolled the checkout backwards; a
# `docker compose pull` raced its own push; and one died on an
# unreachable Docker Hub AAAA record. Each time the job had already moved
# the checkout and rewritten .env before the step that failed, leaving
# `.env` naming an image the box did not have. Building here removes
# every one of those moving parts.
#
# The safety properties that matter:
#
#   * The running containers are NEVER stopped until a new image has been
#     built successfully. A failed build leaves the site serving.
#   * A commit that is not an ancestor of origin/main is refused, so a
#     stale invocation cannot roll production back.
#   * If the health check fails, the previous image is restored
#     automatically and the script exits non-zero.
#   * Never `down -v`. Named volumes hold the registry.

set -euo pipefail

APP_DIR=/opt/nsrmis
COMPOSE_FILE=compose.production.yml
ENV_FILE=.env
PUBLIC_HOST=nsr-sris.mglsd.go.ug
KEEP_IMAGES=3           # previous builds retained for rollback
LOG=/opt/nsrmis/deploy.log

cd "$APP_DIR"

ts()   { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
log()  { printf '%s  %s\n' "$(ts)" "$*" | tee -a "$LOG"; }
die()  { log "FAILED: $*"; exit 1; }
dc()   { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

# --- arguments -----------------------------------------------------------
#   deploy.sh                       deploy the tip of origin/main
#   deploy.sh <sha> --rollback      deliberately go back to an older commit
#   deploy.sh --yes                 never prompt (for cron / non-interactive)
REF=""
ROLLBACK=0
ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        --rollback) ROLLBACK=1 ;;
        --yes|-y)   ASSUME_YES=1 ;;
        -h|--help)
            sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        -*) echo "unknown option: $arg" >&2; exit 1 ;;
        *)  REF="$arg" ;;
    esac
done
REF="${REF:-origin/main}"

# Prompting is only possible on a terminal; anywhere else assume no.
confirm() {
    [ "$ASSUME_YES" = "1" ] && return 0
    if [ ! -t 0 ]; then
        log "refusing: $1 (no terminal to confirm on; pass --yes if you mean it)"
        return 1
    fi
    read -rp "  $1 [y/N] " a
    [ "${a:-n}" = "y" ]
}

log "=== deploy started (ref=$REF) ==="

# --- what is running now, so we can put it back --------------------------
PREV_SHA=$(git rev-parse --short HEAD)
PREV_IMAGE=$(grep '^NSR_IMAGE=' "$ENV_FILE" | cut -d= -f2-)
log "current: commit=$PREV_SHA image=$PREV_IMAGE"

# --- resolve and validate the target -------------------------------------
git fetch --prune --quiet origin main || die "git fetch failed"
TARGET_SHA=$(git rev-parse --short "$REF") || die "cannot resolve ref '$REF'"

# Anything not on main is refused outright — a feature branch or a
# rewritten commit must never reach production.
if ! git merge-base --is-ancestor "$TARGET_SHA" origin/main; then
    die "$TARGET_SHA is not an ancestor of origin/main — refusing to deploy it"
fi

# Being ON main is not enough: every older commit on main is also an
# ancestor, so the check above would happily let a stale invocation roll
# production backwards. Going back has to be asked for explicitly.
MAIN_TIP=$(git rev-parse --short origin/main)
if [ "$TARGET_SHA" != "$MAIN_TIP" ]; then
    BEHIND=$(git rev-list --count "$TARGET_SHA..origin/main")
    log "NOTE: $TARGET_SHA is $BEHIND commit(s) behind origin/main ($MAIN_TIP)"
    if [ "$ROLLBACK" != "1" ]; then
        die "deploying an older commit is a rollback — re-run with --rollback if that is what you want"
    fi
    log "proceeding as a deliberate rollback"
fi

if [ "$TARGET_SHA" = "$PREV_SHA" ]; then
    log "already at $TARGET_SHA"
    confirm "rebuild anyway?" || { log "nothing to do"; exit 0; }
fi

IMAGE="nsr-mis:$TARGET_SHA"
log "target : commit=$TARGET_SHA image=$IMAGE"

# --- check out the target ------------------------------------------------
# The build context IS the checkout, so this has to happen before the
# build. Containers are untouched and keep serving throughout; if the
# build fails we put the checkout back.
git checkout --force --quiet "$TARGET_SHA" || die "checkout failed"

# --- build ---------------------------------------------------------------
log "building $IMAGE (this takes a few minutes)..."
if ! docker build -t "$IMAGE" -t nsr-mis:prod-current . >>"$LOG" 2>&1; then
    log "build failed — restoring checkout to $PREV_SHA; the site was never touched"
    git checkout --force --quiet "$PREV_SHA" || true
    die "docker build failed (see $LOG)"
fi
log "build ok"

# --- switch the stack ----------------------------------------------------
sed -i "s|^NSR_IMAGE=.*|NSR_IMAGE=$IMAGE|" "$ENV_FILE"
chmod 600 "$ENV_FILE"

log "starting containers..."
dc up -d --remove-orphans >>"$LOG" 2>&1 || die "compose up failed"

# An nginx config change needs the container restarted: compose sees no
# change to the service spec when only a file inside a mounted directory
# differs, so the boot-time config copy would not re-run.
dc restart nginx >>"$LOG" 2>&1 || true

log "applying migrations..."
dc exec -T web python manage.py migrate --noinput >>"$LOG" 2>&1 \
    || die "migrations failed"

# --- health check, with automatic rollback -------------------------------
log "health check..."
healthy=0
for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' \
             -H "Host: $PUBLIC_HOST" http://127.0.0.1/healthz || true)
    if [ "$code" = "200" ]; then healthy=1; log "healthz ok after ${i} attempt(s)"; break; fi
    sleep 5
done

if [ "$healthy" -ne 1 ]; then
    log "HEALTH CHECK FAILED — rolling back to $PREV_IMAGE"
    sed -i "s|^NSR_IMAGE=.*|NSR_IMAGE=$PREV_IMAGE|" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    git checkout --force --quiet "$PREV_SHA" || true
    dc up -d --remove-orphans >>"$LOG" 2>&1 || true
    dc restart nginx >>"$LOG" 2>&1 || true
    dc logs --tail=60 web | tail -60 | tee -a "$LOG"
    die "rolled back to $PREV_SHA"
fi

# --- housekeeping --------------------------------------------------------
# Each build is ~2.7 GB. Keep the most recent few for rollback and drop
# the rest, plus dangling layers and stale build cache.
log "pruning old images (keeping $KEEP_IMAGES)..."
docker images nsr-mis --format '{{.Tag}} {{.CreatedAt}}' \
  | grep -v '^prod-current' \
  | sort -k2 -r | tail -n +$((KEEP_IMAGES + 1)) | awk '{print $1}' \
  | while read -r tag; do
        [ -n "$tag" ] && docker rmi "nsr-mis:$tag" >/dev/null 2>&1 || true
    done
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -f --filter 'until=168h' >/dev/null 2>&1 || true

log "=== deploy complete: $PREV_SHA -> $TARGET_SHA ==="
echo
dc ps --format "table {{.Service}}\t{{.Status}}"
echo
df -h / | awk 'NR==2 {print "disk free: "$4}'
