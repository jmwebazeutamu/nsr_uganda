#!/usr/bin/env bash
# NSR MIS — dev server launcher.
#
# Starts the Django dev server which serves both the API
# (/api/v1/...) and the design harness (/console/) on the same
# origin so fetch() inherits the Django session cookie.
#
# Usage:
#   ./start-nsr-ug.sh                # bind 127.0.0.1:8000, open browser
#   ./start-nsr-ug.sh 9000           # custom port
#   ./start-nsr-ug.sh 0.0.0.0:8000   # bind all interfaces (LAN access)
#   NSR_NO_OPEN=1 ./start-nsr-ug.sh  # don't open browser
#   NSR_NO_MIGRATE=1 ./start-nsr-ug.sh  # skip migrate
#
# Stop with Ctrl-C.

set -euo pipefail

# Resolve to the repo root so the script works from anywhere.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

BIND="${1:-127.0.0.1:8000}"

if [[ ! -d .venv ]]; then
  echo "ERROR: .venv/ not found. Bootstrap with:" >&2
  echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'" >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [[ "${NSR_NO_MIGRATE:-}" != "1" ]]; then
  python manage.py migrate --noinput
fi

# Pretty banner with the URLs that matter.
HOST_PORT="${BIND/0.0.0.0/localhost}"
HOST_PORT="${HOST_PORT/127.0.0.1/localhost}"
cat <<BANNER

NSR MIS dev server starting on http://${HOST_PORT}

  Console (design harness)  http://${HOST_PORT}/console/
  Admin                     http://${HOST_PORT}/admin/
  OpenAPI schema            http://${HOST_PORT}/api/schema/
  Swagger UI                http://${HOST_PORT}/api/docs/

Tip: a Django superuser is required to use the console. Create one
with  python manage.py createsuperuser  in another shell.

BANNER

# Open the console in the default browser unless suppressed.
if [[ "${NSR_NO_OPEN:-}" != "1" ]] && command -v open >/dev/null 2>&1; then
  ( sleep 1 && open "http://${HOST_PORT}/console/" ) &
fi

exec python manage.py runserver "$BIND"
