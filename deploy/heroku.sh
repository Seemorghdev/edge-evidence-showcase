#!/usr/bin/env bash
set -euo pipefail

local_image="${1:?usage: heroku.sh LOCAL_IMAGE}"
app_name="${HEROKU_APP_NAME:?HEROKU_APP_NAME is required}"
api_key="${HEROKU_API_KEY:?HEROKU_API_KEY is required}"
region="${HEROKU_REGION:-eu}"
dyno_size="${HEROKU_DYNO_SIZE:-basic}"
registry_image="registry.heroku.com/${app_name}/web"

if [[ ! "${app_name}" =~ ^[a-z][a-z0-9-]{1,28}[a-z0-9]$ ]]; then
  echo "HEROKU_APP_NAME is invalid" >&2
  exit 2
fi

auth_header="Authorization: Bearer ${api_key}"
accept_header="Accept: application/vnd.heroku+json; version=3"
app_response="$(mktemp)"
trap 'rm -f "${app_response}"' EXIT

status="$(curl --silent --show-error \
  --output "${app_response}" \
  --write-out '%{http_code}' \
  "https://api.heroku.com/apps/${app_name}" \
  --header "${auth_header}" \
  --header "${accept_header}")"

if [[ "${status}" == "404" ]]; then
  create_payload="$(python3 - "${app_name}" "${region}" <<'PY'
import json
import sys
print(json.dumps({"name": sys.argv[1], "region": sys.argv[2], "stack": "container"}))
PY
)"
  curl --fail-with-body --silent --show-error \
    --request POST \
    "https://api.heroku.com/apps" \
    --header "${auth_header}" \
    --header "${accept_header}" \
    --header "Content-Type: application/json" \
    --data "${create_payload}" \
    --output "${app_response}"
elif [[ "${status}" != "200" ]]; then
  cat "${app_response}" >&2
  echo "unable to inspect Heroku app (HTTP ${status})" >&2
  exit 1
fi

python3 - "${app_response}" <<'PY'
import json
import sys
app = json.load(open(sys.argv[1], encoding="utf-8"))
if app.get("generation", {}).get("name") != "cedar":
    raise SystemExit("Heroku app must use the Cedar generation")
if app.get("stack", {}).get("name") != "container":
    raise SystemExit("Heroku app must use the container stack")
PY

echo "${api_key}" | docker login --username=_ --password-stdin registry.heroku.com >/dev/null
docker tag "${local_image}" "${registry_image}"
docker push "${registry_image}"
image_id="$(docker inspect "${local_image}" --format='{{.Id}}')"

release_payload="$(python3 - "${image_id}" <<'PY'
import json
import sys
print(json.dumps({"updates": [{"type": "web", "docker_image": sys.argv[1]}]}))
PY
)"

curl --fail-with-body --silent --show-error \
  --request PATCH \
  "https://api.heroku.com/apps/${app_name}/formation" \
  --header "${auth_header}" \
  --header "Accept: application/vnd.heroku+json; version=3.docker-releases" \
  --header "Content-Type: application/json" \
  --data "${release_payload}" >/dev/null

scale_payload="$(python3 - "${dyno_size}" <<'PY'
import json
import sys
print(json.dumps({"quantity": 1, "dyno_size": {"name": sys.argv[1]}}))
PY
)"

curl --fail-with-body --silent --show-error \
  --request PATCH \
  "https://api.heroku.com/apps/${app_name}/formation/web" \
  --header "${auth_header}" \
  --header "${accept_header}" \
  --header "Content-Type: application/json" \
  --data "${scale_payload}" >/dev/null

curl --fail-with-body --silent --show-error \
  "https://api.heroku.com/apps/${app_name}" \
  --header "${auth_header}" \
  --header "${accept_header}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["web_url"].rstrip("/"))'
