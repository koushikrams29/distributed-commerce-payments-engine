#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu server (22.04 or 24.04, x86 or ARM):
# installs Docker, caps container log sizes, and opens ports 80 and 443 in the
# host firewall. Safe to run again.
#
#   bash scripts/deploy/setup_server.sh
set -euo pipefail

if [[ $EUID -eq 0 ]]; then sudo=(); else sudo=(sudo); fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker from Docker's own apt repository..."
  "${sudo[@]}" apt-get update
  "${sudo[@]}" apt-get install -y ca-certificates curl
  "${sudo[@]}" install -m 0755 -d /etc/apt/keyrings
  "${sudo[@]}" curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  "${sudo[@]}" chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck source=/dev/null
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
    | "${sudo[@]}" tee /etc/apt/sources.list.d/docker.list >/dev/null
  "${sudo[@]}" apt-get update
  "${sudo[@]}" apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# Without a cap, container logs grow until the disk is full.
if [[ ! -f /etc/docker/daemon.json ]]; then
  echo '{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}' \
    | "${sudo[@]}" tee /etc/docker/daemon.json >/dev/null
  "${sudo[@]}" systemctl restart docker
fi

if [[ $EUID -ne 0 ]] && ! id -nG "$USER" | grep -qw docker; then
  "${sudo[@]}" usermod -aG docker "$USER"
  needs_relogin=1
fi

# Oracle Cloud's Ubuntu images ship iptables rules that reject everything except
# SSH, in addition to the cloud firewall (the subnet's security list).
if command -v iptables >/dev/null 2>&1 && "${sudo[@]}" iptables -S INPUT | grep -q -- "-j REJECT"; then
  for spec in tcp:80 tcp:443 udp:443; do
    rule=(-p "${spec%%:*}" --dport "${spec##*:}" -m state --state NEW -j ACCEPT)
    if ! "${sudo[@]}" iptables -C INPUT "${rule[@]}" 2>/dev/null; then
      position=$("${sudo[@]}" iptables -L INPUT --line-numbers | awk '$2 == "REJECT" { print $1; exit }')
      "${sudo[@]}" iptables -I INPUT "$position" "${rule[@]}"
    fi
  done
  if command -v netfilter-persistent >/dev/null 2>&1; then
    "${sudo[@]}" netfilter-persistent save
  fi
fi

docker_version=$("${sudo[@]}" docker compose version --short)
echo "Server ready (Docker Compose ${docker_version})."
if [[ ${needs_relogin:-0} -eq 1 ]]; then
  echo "Log out and back in once, so you can run docker without sudo."
fi
