#!/usr/bin/env bash
# Disposable hosted-CI preparation, never a product executor or host workaround.
set -euo pipefail
umask 077

[[ "${RUNNER_ENVIRONMENT:-}" == github-hosted ]]
[[ "${RUNNER_OS:-}" == Linux && "${RUNNER_ARCH:-}" == X64 ]]
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 && "${VERSION_CODENAME:-}" == noble ]]
[[ "$(/usr/bin/dpkg --print-architecture)" == amd64 ]]
[[ $# -gt 0 ]]
runner_user="$(id -un)"
runner_uid="$(/usr/bin/id -u)"
[[ "$runner_uid" != 0 ]]
[[ -d "$RUNNER_TEMP" && ! -L "$RUNNER_TEMP" ]]
python_binary="$(command -v python)"
node_binary="$(command -v node)"
[[ "$("$node_binary" --version)" == v22.23.3 ]]
test_path="$(dirname "$python_binary"):$(dirname "$node_binary"):/usr/bin:/bin"
profile_name="aioa-ci-offline-$runner_uid-$$"
policy_file="$(mktemp "$RUNNER_TEMP/aioa-ci-host.XXXXXX")"
test_home="$(mktemp -d "$RUNNER_TEMP/aioa-ci-home.XXXXXX")"
profile_loaded=0
linger_changed=0
cleanup() {
  status=$?
  trap - EXIT
  if [[ "$profile_loaded" == 1 ]]; then
    if ! sudo --non-interactive /usr/sbin/apparmor_parser --remove --skip-cache "$policy_file"; then status=1; fi
  fi
  if [[ "$linger_changed" == 1 ]]; then
    if ! sudo --non-interactive loginctl disable-linger "$runner_user"; then status=1; fi
  fi
  if ! rm -- "$policy_file"; then status=1; fi
  exit "$status"
}
trap cleanup EXIT
if ! linger_before="$(loginctl show-user "$runner_user" --property=Linger --value)"; then
  [[ ! -e "/var/lib/systemd/linger/$runner_user" ]]
  linger_before=no
fi
[[ "$linger_before" == yes || "$linger_before" == no ]]

# A pathname attachment misses the broker's hash-pinned sealed memfd. Select
# this named profile only for the trusted acceptance invocation, then drop to
# the original nonroot runner before executing any repository code. AppArmor
# remains enabled; no sysctl, namespace, seccomp, FD or broker pin is weakened.
cat > "$policy_file" <<APPARMOR
abi <abi/4.0>,
profile $profile_name flags=(unconfined) {
  userns,
}
# systemd --user launches the regular sandbox independently of this process;
# retain the pathname attachment for that existing execution path as well.
profile $profile_name-bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
}
APPARMOR
sudo --non-interactive /usr/sbin/apparmor_parser --add --skip-cache "$policy_file"
profile_loaded=1
if [[ "$linger_before" == no ]]; then
  sudo --non-interactive loginctl enable-linger "$runner_user"
  linger_changed=1
fi
sudo --non-interactive systemctl start "user@$runner_uid.service"
runtime_dir="/run/user/$runner_uid"
bus="unix:path=$runtime_dir/bus"
XDG_RUNTIME_DIR="$runtime_dir" DBUS_SESSION_BUS_ADDRESS="$bus" systemctl --user is-active default.target

# No -E or inherited token/environment forwarding. sudo performs only the
# explicit profile transition and runuser; the command runs with CapEff=0.
sudo --non-interactive /usr/bin/aa-exec --profile "$profile_name" -- \
  /usr/sbin/runuser --user "$runner_user" -- /usr/bin/env -i \
  "PATH=$test_path" "HOME=$test_home" LANG=C.UTF-8 "TMPDIR=$RUNNER_TEMP" \
  PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 \
  AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true \
  OTEL_TRACES_EXPORTER=none OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none \
  "XDG_RUNTIME_DIR=$runtime_dir" "DBUS_SESSION_BUS_ADDRESS=$bus" \
  "AIOA_TESTED_SHA=$AIOA_TESTED_SHA" "AIOA_CI_EXPECTED_PROFILE=$profile_name" \
  /usr/bin/bash --noprofile --norc -c '
    set -euo pipefail
    expected_uid=$1
    expected_profile=$2
    shift 2
    [[ "$(/usr/bin/id -u)" == "$expected_uid" && "$expected_uid" != 0 ]]
    [[ "$(/usr/bin/awk '\''/^CapEff:/ {print $2}'\'' /proc/$$/status)" == 0000000000000000 ]]
    [[ "$(/usr/bin/cat /proc/$$/attr/current)" == "$expected_profile (unconfined)" ]]
    printf "CI acceptance uid=%s profile=%s effective_caps=0\n" "$expected_uid" "$expected_profile"
    exec "$@"
  ' aioa-ci-unprivileged "$runner_uid" "$profile_name" "$@"
