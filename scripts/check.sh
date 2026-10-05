#!/usr/bin/env bash
# Local checks: the pull-request checks that ran in .github/workflows/ci.yml, run on this machine
# instead (owner decision, 2026-09-27: GitHub Actions runs only the deploy and destroy
# workflows). Run before every push; paste the summary into the pull request.
#
# Usage: scripts/check.sh [--all] [--plan] [--base <ref>] [section ...]
#   (no section)  every section the change touches, compared with the merge base of --base
#                 (default origin/dev) plus uncommitted files, like CI's path filters
#   --all         every section, whatever changed
#   --plan        also run `terraform plan` for foundation and agent against the live state
#                 (needs `az login`; read-only, -lock=false, never applies)
#   section       any of: secrets infra plan api api-image agent agent-image web e2e
#
# Needs: uv, node 22 + npm, docker, terraform 1.16.4, gitleaks, actionlint, shellcheck, jq, and
# tflint 0.64.0 (on PATH or in .work/bin). Scratch files go to .work/check/ (gitignored).

set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

readonly TERRAFORM_VERSION="1.16.4"
readonly TFLINT_VERSION="0.64.0"
# postgres:18.6, pinned by digest (multi-arch index), as the CI jobs used.
readonly PG_IMAGE="postgres:18.6@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722"
# Each worktree gets its own slot (0-99, from its path; FORMAPP_CHECK_SLOT overrides), so parallel
# worktrees use their own container names, image tags and ports.
readonly SLOT="${FORMAPP_CHECK_SLOT:-$(( $(printf '%s' "$ROOT" | cksum | cut -d' ' -f1) % 100 ))}"
readonly PG_CONTAINER="formapp-check-postgres-$SLOT"
readonly API_CONTAINER="formapp-check-api-$SLOT"
readonly AGENT_CONTAINER="formapp-check-agent-$SLOT"
readonly PG_PORT=$((15400 + SLOT))
readonly API_IMAGE_PORT=$((18000 + SLOT))
readonly AGENT_IMAGE_PORT=$((18100 + SLOT))
readonly WEB_PORT_FOR_E2E=$((14200 + SLOT))
readonly API_PORT_FOR_E2E=$((14300 + SLOT))
readonly WORK="$ROOT/.work/check"
readonly ALL_SECTIONS=(secrets infra api api-image agent agent-image web e2e)
# The foundation root and six modules are not validated or tested (owner decisions, 2026-09-27,
# POC only); a plan still parses them.
readonly TF_SKIP=" infra/demo/foundation infra/modules/storage-account infra/modules/resource-group infra/modules/postgresql-flexible-server infra/modules/log-analytics-workspace infra/modules/container-registry infra/modules/container-apps-environment "

export PATH="$ROOT/.work/bin:$PATH"
mkdir -p "$WORK"

base="origin/dev"
run_all=false
want_plan=false
requested=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all) run_all=true ;;
    --plan) want_plan=true ;;
    --base) base="$2"; shift ;;
    -h | --help) sed -n '2,16p' "$0"; exit 0 ;;
    secrets | infra | plan | api | api-image | agent | agent-image | web | e2e) requested+=("$1") ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

# ---------- what changed ----------
changed_files() {
  local mb
  mb="$(git merge-base "$base" HEAD)"
  { git diff --name-only "$mb"; git ls-files --others --exclude-standard; } | sort -u
}

changed="$(changed_files)"
touched() { grep -qE "$1" <<<"$changed"; }

sections=()
if [[ ${#requested[@]} -gt 0 ]]; then
  sections=("${requested[@]}")
elif [[ "$run_all" == "true" ]]; then
  sections=("${ALL_SECTIONS[@]}")
else
  sections=(secrets)
  touched '^(infra/|\.tflint\.hcl$|\.github/workflows/|scripts/check\.sh$)|\.sh$' && sections+=(infra)
  if touched '^(api/|form-schema/|web/)|^scripts/check\.sh$'; then sections+=(api api-image); fi
  if touched '^agent/|^scripts/check\.sh$'; then sections+=(agent agent-image); fi
  if touched '^web/|^scripts/check\.sh$'; then sections+=(web e2e); fi
fi
[[ "$want_plan" == "true" && " ${sections[*]} " != *" plan "* ]] && sections+=(plan)

# ---------- helpers ----------
results=()
failed=0
section() { printf '\n==== %s ====\n' "$1"; }
record() { # name rc
  if [[ "$2" == 0 ]]; then results+=("pass  $1"); else results+=("FAIL  $1"); failed=1; fi
}
need() {
  local missing=0
  for tool in "$@"; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; missing=1; }
  done
  return "$missing"
}

start_postgres() {
  export PGHOST=127.0.0.1 PGPORT="$PG_PORT" PGUSER=postgres PGPASSWORD=postgres PGSSLMODE=disable
  if [[ "$(docker inspect --format '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null)" != "true" ]]; then
    docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
    # Throwaway local container only; synthetic password, not a secret.
    docker run --detach --name "$PG_CONTAINER" --publish "127.0.0.1:${PG_PORT}:5432" \
      --env POSTGRES_PASSWORD=postgres "$PG_IMAGE" >/dev/null
  fi
  local deadline=$((SECONDS + 60))
  until docker exec "$PG_CONTAINER" pg_isready -U postgres >/dev/null 2>&1; do
    ((SECONDS < deadline)) || { echo "PostgreSQL did not become ready." >&2; return 1; }
    sleep 1
  done
}

# shellcheck disable=SC2329 # invoked by the EXIT trap
stop_containers() {
  docker rm -f "$PG_CONTAINER" "$API_CONTAINER" "$AGENT_CONTAINER" >/dev/null 2>&1 || true
}
# Keep the script's own exit status: a crash (e.g. set -u) must not end as exit 0.
trap 'rc=$?; stop_containers; exit "$rc"' EXIT

wait_http() { # url container seconds
  local deadline=$((SECONDS + $3))
  until curl -fsS --max-time 2 "$1" >/dev/null; do
    if ((SECONDS >= deadline)) || [[ "$(docker inspect --format '{{.State.Running}}' "$2")" != "true" ]]; then
      echo "$2 did not answer $1 within $3 seconds." >&2
      docker logs "$2" >&2
      return 1
    fi
    sleep 2
  done
}

non_root() { # container
  local user
  user="$(docker inspect --format '{{.Config.User}}' "$1")"
  if [[ -z "$user" || "$user" == "root" || "$user" == "0" ]]; then
    echo "$1 must run as a non-root user (got '${user}')." >&2
    return 1
  fi
}

# ---------- sections ----------
check_secrets() {
  need gitleaks && gitleaks git --redact --no-banner --config .gitleaks.toml .
}

tf_dirs() {
  local dirs=() d
  if [[ "$run_all" == "true" ]] || touched '^\.tflint\.hcl$|^scripts/check\.sh$'; then
    for d in infra/modules/*/ infra/demo/*/; do dirs+=("${d%/}"); done
  else
    local module_changed=false f
    while IFS= read -r f; do
      if [[ "$f" =~ ^infra/modules/([^/]+)/ ]]; then
        dirs+=("infra/modules/${BASH_REMATCH[1]}"); module_changed=true
      elif [[ "$f" =~ ^infra/demo/([^/]+)/ ]]; then
        dirs+=("infra/demo/${BASH_REMATCH[1]}")
      fi
    done <<<"$changed"
    if [[ "$module_changed" == "true" ]]; then
      for d in infra/demo/*/; do dirs+=("${d%/}"); done
    fi
  fi
  for d in "${dirs[@]}"; do
    [[ "$TF_SKIP" == *" $d "* ]] || echo "$d"
  done | sort -u
}

check_infra() {
  need terraform tflint shellcheck actionlint jq || return 1
  local tf_version tflint_version
  tf_version="$(terraform version)"
  tflint_version="$(tflint --version)"
  [[ "$tf_version" == "Terraform v${TERRAFORM_VERSION}"* ]] || { echo "Terraform must be ${TERRAFORM_VERSION}." >&2; return 1; }
  [[ "$tflint_version" == "TFLint version ${TFLINT_VERSION}"* ]] || { echo "tflint must be ${TFLINT_VERSION}." >&2; return 1; }
  local rc=0 dir fixture name expected got

  echo "-- terraform fmt"
  terraform fmt -check -recursive -diff infra || rc=1

  echo "-- terraform validate and test (affected roots and modules)"
  while IFS= read -r dir; do
    [[ -z "$dir" ]] && continue
    echo "   $dir"
    if terraform -chdir="$dir" init -backend=false -input=false -no-color >/dev/null \
      && terraform -chdir="$dir" validate -no-color \
      && { [[ ! -d "$dir/tests" ]] || terraform -chdir="$dir" test -no-color; }; then
      echo "   ok: $dir"
    else
      echo "   FAILED: $dir" >&2; rc=1
    fi
  done < <(tf_dirs)

  echo "-- tflint"
  { tflint --init --config "$ROOT/.tflint.hcl" && tflint --chdir=infra --recursive --config "$ROOT/.tflint.hcl"; } || rc=1

  echo "-- shellcheck"
  # Vendored BMad files are excluded: they change only through a BMad update.
  git ls-files -z -- '*.sh' ':!:_bmad/*' ':!:.claude/*' ':!:.agents/*' | xargs -0 shellcheck || rc=1

  echo "-- deploy plan guard fixtures"
  for fixture in infra/scripts/tests/fixtures/*.json; do
    name="$(basename "$fixture")"
    case "$name" in
      fail-*) expected=1 ;;
      pass-*) expected=0 ;;
      *) echo "Fixture ${name} must start with fail- or pass-" >&2; rc=1; continue ;;
    esac
    got=0
    infra/scripts/plan-guard.sh "$fixture" >/dev/null || got=$?
    [[ "$got" == "$expected" ]] || { echo "plan-guard.sh ${name}: exit ${got}, expected ${expected}" >&2; rc=1; }
  done

  echo "-- actionlint"
  actionlint || rc=1
  return "$rc"
}

# Read-only plan against the live state with the signed-in az identity; -lock=false so it never
# blocks, or is blocked by, a deploy. Never applies.
check_plan() {
  need terraform az || return 1
  local rc=0 stack
  for stack in foundation agent; do
    local dir="infra/demo/$stack" extra=()
    [[ "$stack" == agent ]] && extra=(-var "image_tag=$(git rev-parse HEAD)")
    echo "-- plan $stack"
    if terraform -chdir="$dir" init -input=false -no-color >/dev/null \
      && terraform -chdir="$dir" plan -input=false -lock=false -no-color -out="$WORK/$stack.tfplan" ${extra[@]+"${extra[@]}"} >"$WORK/plan-$stack.log" 2>&1; then
      terraform -chdir="$dir" show -no-color "$WORK/$stack.tfplan" | grep -E '^\s+# |^Plan:|^No changes' || true
      rm -f "$WORK/$stack.tfplan"
    else
      cat "$WORK/plan-$stack.log" >&2; rc=1
    fi
  done
  return "$rc"
}

check_api() {
  need uv docker || return 1
  local rc=0 schema fixture name rule out got
  (cd api && uv sync --locked) || return 1

  echo "-- form schema lint"
  for schema in form-schema/v*.json; do
    (cd api && uv run --no-sync python ../form-schema/lint.py "../$schema") || rc=1
  done
  for fixture in form-schema/tests/fixtures/*.json; do
    name="$(basename "$fixture")"
    [[ "$name" == fail-* ]] || { echo "Fixture ${name} must start with fail-" >&2; rc=1; continue; }
    rule="${name#fail-}"; rule="${rule%.json}"
    got=0
    out="$(cd api && uv run --no-sync python ../form-schema/lint.py "../$fixture")" || got=$?
    if [[ "$got" != 1 ]] || ! grep -q "^rule ${rule}:" <<<"$out"; then
      echo "lint.py ${name}: exit ${got}, expected 1 with a 'rule ${rule}:' line" >&2; rc=1
    fi
  done

  echo "-- pytest with coverage (80% minimum)"
  start_postgres || return 1
  (cd api && uv run --no-sync pytest --cov) || rc=1
  return "$rc"
}

check_api_image() {
  need docker curl || return 1
  local rc=0 path headers header script expected bundle
  docker build --file api/Dockerfile --tag "formapp-api:check-$SLOT" . || return 1
  docker rm -f "$API_CONTAINER" >/dev/null 2>&1 || true
  docker run --detach --name "$API_CONTAINER" --publish "127.0.0.1:${API_IMAGE_PORT}:8080" \
    --env FORMAPP_DEPLOYMENT=local \
    --env DATABASE_HOST=127.0.0.1 \
    --env DATABASE_PORT=1 \
    --env DATABASE_NAME=formapp \
    --env DATABASE_USER=formapp_api \
    --env DATABASE_PASSWORD=synthetic-ci-password \
    --env DB_MIGRATION_ROLE=formapp_migrator \
    --env TURN_TOKEN_SIGNING_KEY=synthetic-ci-signing-key-synthetic-ci \
    "formapp-api:check-$SLOT" >/dev/null
  wait_http http://127.0.0.1:${API_IMAGE_PORT}/healthz "$API_CONTAINER" 60 || return 1
  non_root "$API_CONTAINER" || rc=1

  echo "-- the image serves the React shell"
  for path in / /proposals/42; do
    headers="$(curl -fsS --max-time 5 --dump-header - --output "$WORK/index.html" "http://127.0.0.1:${API_IMAGE_PORT}${path}")" || { rc=1; continue; }
    grep -q '<div id="root"></div>' "$WORK/index.html" || { echo "${path} did not return the React shell." >&2; rc=1; }
    for header in 'cache-control: no-cache' "content-security-policy: default-src 'self'" 'permissions-policy:'; do
      grep -qiF "$header" <<<"$headers" || { echo "${path} is missing '${header}'." >&2; rc=1; }
    done
  done
  script="$(grep -oE '/assets/[^"]+\.js' "$WORK/index.html" | head -n 1)"
  if [[ -z "$script" ]] || ! curl -fsS --max-time 5 --dump-header - --output /dev/null "http://127.0.0.1:${API_IMAGE_PORT}${script}" \
    | grep -qi '^cache-control: public, max-age=31536000, immutable'; then
    echo "The bundle is missing or not served with the immutable cache header." >&2; rc=1
  fi

  echo "-- the image loads the latest form schema"
  expected="$(docker exec "$API_CONTAINER" sh -c 'ls /form-schema' | sed -nE 's/^v([1-9][0-9]*)\.json$/\1/p' | sort -n | tail -n 1)"
  if [[ -z "$expected" ]]; then
    echo "The image has no /form-schema/v<N>.json." >&2; rc=1
  else
    docker exec "$API_CONTAINER" python -c "from domain.schema import latest_version, load_schema; v = latest_version(); assert v == ${expected}, v; load_schema(v); print('form schema latest =', v)" || rc=1
  fi

  echo "-- the image CA bundle has the Azure PostgreSQL roots"
  bundle="$(docker exec "$API_CONTAINER" printenv DATABASE_SSLROOTCERT)"
  docker exec -i "$API_CONTAINER" python - "$bundle" <<'EOF' || rc=1
import ssl, sys
bundle = sys.argv[1]
ctx = ssl.create_default_context(cafile=bundle)
names = {dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()}
wanted = {"DigiCert Global Root G2", "Microsoft RSA Root Certificate Authority 2017"}
missing = wanted - names
print(f"{bundle}: {len(names)} roots; missing: {sorted(missing) or 'none'}")
sys.exit(1 if missing else 0)
EOF
  docker rm -f "$API_CONTAINER" >/dev/null 2>&1 || true
  return "$rc"
}

check_agent() {
  need uv || return 1
  local rc=0
  (cd agent && uv sync --locked) || return 1
  echo "-- pytest with coverage (80% minimum)"
  (cd agent && uv run --no-sync pytest --cov) || rc=1
  echo "-- evaluation set (offline)"
  (cd agent && uv run --no-sync python -m evals.run --offline) || rc=1
  return "$rc"
}

check_agent_image() {
  need docker curl || return 1
  local rc=0 status
  docker build --tag "formapp-agent:check-$SLOT" agent/ || return 1
  docker rm -f "$AGENT_CONTAINER" >/dev/null 2>&1 || true
  docker run --detach --name "$AGENT_CONTAINER" --publish "127.0.0.1:${AGENT_IMAGE_PORT}:8088" \
    --env FORMAPP_MCP_URL=https://mcp.example.invalid/mcp \
    --env FOUNDRY_PROJECT_ENDPOINT=https://foundry.example.invalid/api/projects/formapp \
    --env MODEL_DEPLOYMENT_NAME=synthetic-ci-deployment \
    "formapp-agent:check-$SLOT" >/dev/null
  wait_http http://127.0.0.1:${AGENT_IMAGE_PORT}/readiness "$AGENT_CONTAINER" 60 || return 1
  non_root "$AGENT_CONTAINER" || rc=1
  echo "-- a turn without a token gets the fixed reply"
  status="$(curl -sS --max-time 10 --output "$WORK/agent-reply.json" --write-out '%{http_code}' \
    -H 'content-type: application/json' -d '{"model":"m","input":"hi"}' http://127.0.0.1:${AGENT_IMAGE_PORT}/responses)"
  if [[ "$status" != "200" ]] || ! grep -qF "The AI couldn't finish" "$WORK/agent-reply.json"; then
    echo "POST /responses without a turn token returned ${status}, not the fixed reply." >&2; rc=1
  fi
  if docker logs "$AGENT_CONTAINER" 2>&1 | grep -q 'Traceback (most recent call last)'; then
    echo "The agent container logged a Python traceback." >&2; rc=1
  fi
  docker rm -f "$AGENT_CONTAINER" >/dev/null 2>&1 || true
  return "$rc"
}

check_web() {
  need node npm || return 1
  [[ "$(node --version)" == v22.* ]] || { echo "Node 22 is required." >&2; return 1; }
  local rc=0
  (cd web && npm ci) || return 1
  (cd web && npx --no-install tsc --noEmit) || rc=1
  (cd web && npx --no-install eslint .) || rc=1
  (cd web && npx --no-install prettier --check .) || rc=1
  (cd web && npm audit --omit=dev --audit-level=high) || rc=1
  echo "-- Vitest with coverage (60% minimum)"
  (cd web && npx --no-install vitest run --coverage) || rc=1
  return "$rc"
}

check_e2e() {
  need node npm uv docker || return 1
  [[ -d web/node_modules ]] || (cd web && npm ci) || return 1
  (cd web && npx --no-install playwright install chromium) || return 1
  (cd api && uv sync --locked) || return 1
  start_postgres || return 1
  (cd api && uv run --no-sync python scripts/e2e_bootstrap.py formapp_e2e) || return 1
  # CI=true: never reuse a server already listening (it could be another worktree's).
  (cd web && CI=true E2E_WEB_PORT="$WEB_PORT_FOR_E2E" E2E_API_PORT="$API_PORT_FOR_E2E" npx --no-install playwright test)
}

# ---------- run ----------
echo "Sections: ${sections[*]} (slot $SLOT)"
for s in "${sections[@]}"; do
  section "$s"
  rc=0
  case "$s" in
    secrets) check_secrets || rc=$? ;;
    infra) check_infra || rc=$? ;;
    plan) check_plan || rc=$? ;;
    api) check_api || rc=$? ;;
    api-image) check_api_image || rc=$? ;;
    agent) check_agent || rc=$? ;;
    agent-image) check_agent_image || rc=$? ;;
    web) check_web || rc=$? ;;
    e2e) check_e2e || rc=$? ;;
  esac
  record "$s" "$rc"
done

printf '\n==== summary (%s) ====\n' "$(git rev-parse --short HEAD)"
printf '%s\n' "${results[@]}"
exit "$failed"
