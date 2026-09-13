#!/usr/bin/env bash
#
# Build the linux/amd64 images for the packages changed in this fork's recent commits.
#
# Why: this repo's toolchain (Rush 5.158 + pnpm 10 + Node 22) does not install on this
# Mac, and the deployment images have to be x86_64. So the whole build runs inside a
# linux/amd64 Ubuntu container that starts its own Docker daemon (docker-in-docker) and
# builds the images natively -- `docker build` itself is never cross-arch.
#
# Images produced (the packages touched by HEAD~4..HEAD that build an image):
#   hardcoreeng/front   @hcengineering/pod-front   bundles document/love/view-resources
#   hardcoreeng/love    @hcengineering/pod-love    services/love (meeting presets)
#   huly-test-ingest    services/test-ingest       standalone, non-Rush Python service
#
# Usage:
#   tools/docker-x86/build-images.sh
#
# Env knobs:
#   TARGETS  Rush projects to build  (default: @hcengineering/pod-front @hcengineering/pod-love)
#   JOBS     rush parallelism        (default: 4 -- raise it only if the Docker VM has RAM to spare)
#   HULY_VERSION  release the rest of the deployment runs (default: 0.7.426, with or without the
#            leading "v"). The front advertises it as its app *and* model version, so it must
#            match the hardcoreeng/* images -- otherwise the front/server and front/workspace
#            version guards reject the front.
#   LOAD=0   keep the built images out of the host Docker daemon
#   CLEAN=1  drop the cached work volume and inner Docker state before building
#
# Output: .docker-x86/huly-x86-images.tar (`docker load -i` it on the target host),
# .docker-x86/build.log, and -- when the lockfile was stale -- .docker-x86/pnpm-lock.yaml.
# Images are exported tagged :<git-sha> only, so loading leaves any arm64 :latest you have
# locally untouched; deploy with :<git-sha>, or scp/push the tar from there.
#
# Re-runs are incremental: the repo is synced into Docker volumes (real ext4, where pnpm
# hardlinks work) and the inner Docker state is kept, so Rush's install state, tsc/webpack
# output and the pulled base images survive. The Ubuntu container itself is fresh every run,
# so the toolchain is reinstalled each time (~2-4 min). The working tree is mounted read-only
# and never written to; drop the volumes with CLEAN=1 for a from-scratch build.

set -euo pipefail

TARGETS=${TARGETS:-"@hcengineering/pod-front @hcengineering/pod-love"}
JOBS=${JOBS:-4}
# Release of the hardcoreeng/* images the deployment pins (huly-selfhost HULY_VERSION). The
# built front advertises exactly this, so bump it whenever the deployment's images are bumped.
HULY_VERSION=${HULY_VERSION:-0.7.426}
WORK_VOLUME=${WORK_VOLUME:-huly-x86-work}
DOCKER_VOLUME=${DOCKER_VOLUME:-huly-x86-docker}
BUILDER_NAME=huly-x86-builder

# ------------------------------------------------------------------ inside the container
build_inside_container() {
  export DEBIAN_FRONTEND=noninteractive
  local work=/work/src

  echo "==> [1/7] toolchain"
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    ca-certificates curl xz-utils git rsync python3 make g++ docker.io > /dev/null

  # Ubuntu 24.04 ships Node 18; rush.json wants >=20 <25 and .nvmrc says v22.
  local node_tar
  node_tar=$(curl -fsSL https://nodejs.org/dist/latest-v22.x/ |
    grep -o 'node-v22[0-9.]*-linux-x64\.tar\.xz' | head -1)
  curl -fsSL "https://nodejs.org/dist/latest-v22.x/$node_tar" |
    tar -xJ -C /usr/local --strip-components=1

  echo "==> [2/7] docker daemon"
  start_dockerd() {
    dockerd --host=unix:///var/run/docker.sock "$@" > /var/log/dockerd.log 2>&1 &
    local pid=$! i
    for i in $(seq 1 60); do
      docker info > /dev/null 2>&1 && return 0
      kill -0 "$pid" 2>/dev/null || return 1
      sleep 1
    done
    return 1
  }
  # /var/lib/docker is a Docker volume on the VM's native filesystem, so the image store
  # works and everything pulled stays for the next run. vfs is a slow but working fallback.
  start_dockerd || start_dockerd --storage-driver=vfs || { cat /var/log/dockerd.log; exit 1; }

  echo "==> [3/7] syncing $REV into $work"
  mkdir -p "$work"
  # Host-arch node_modules and Rush's temp dir must not leak into the x86 build; the
  # output directory must not be copied back into the build tree either.
  rsync -a --no-owner --no-group \
    --exclude=/common/temp --exclude=node_modules --exclude=/.docker-x86 \
    /src/ "$work/"

  cd "$work"
  git config --global --add safe.directory "$work"
  # V8 sizes its heap from total RAM, which leaves only ~2.2 GB here -- too tight for the
  # frontend's webpack production build (dev/prod), so raise it explicitly.
  # DOCKER_EXTRA is consumed by common/scripts/docker_build.sh. Do NOT set
  # DOCKER_BUILDKIT: Ubuntu's docker.io has no buildx component and would fail.
  export NODE_OPTIONS=${NODE_OPTIONS:---max-old-space-size=6144}
  export DOCKER_VERSION=$REV DOCKER_EXTRA=--platform=linux/amd64 DOCKER_CLI_HINTS=false

  echo "==> [4/7] rush update"
  # Deliberately `update`, not `install`: this fork's commits changed package.json files
  # without refreshing common/config/rush/pnpm-lock.yaml, and `rush install` refuses to
  # proceed on that drift (CI would fail identically). `rush update` reconciles the
  # lockfile; a refreshed copy is written to /out so it can be committed.
  node common/scripts/install-run-rush.js update 2>&1 | tee /out/build.log

  if ! git diff --quiet -- common/config/rush/pnpm-lock.yaml; then
    echo "==> pnpm-lock.yaml was out of date; refreshed copy:"
    git diff --stat -- common/config/rush/pnpm-lock.yaml
    cp common/config/rush/pnpm-lock.yaml /out/pnpm-lock.yaml
    echo "    commit it with:  cp .docker-x86/pnpm-lock.yaml common/config/rush/pnpm-lock.yaml"
  fi

  echo "==> [5/7] rush docker:build $TARGETS"
  local args=() target
  for target in $TARGETS; do args+=(--to "$target"); done
  node common/scripts/install-run-rush.js docker:build -p "$JOBS" "${args[@]}" 2>&1 |
    tee -a /out/build.log

  echo "==> [6/7] standalone service image"
  if [ -f services/test-ingest/Dockerfile ]; then
    docker build -q --platform=linux/amd64 \
      -t huly-test-ingest -t "huly-test-ingest:$REV" services/test-ingest 2>&1 |
      tee -a /out/build.log
  fi

  echo "==> [7/7] exporting images tagged :$REV"
  local saved
  saved=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep ":$REV\$" || true)
  if [ -z "$saved" ]; then
    echo "error: no image was tagged :$REV -- nothing got built" >&2
    exit 1
  fi
  # shellcheck disable=SC2086 # word splitting is what turns the list into docker args
  docker save -o /out/huly-x86-images.tar $saved
  # shellcheck disable=SC2086
  docker image inspect --format '{{index .RepoTags 0}} -> {{.Architecture}}/{{.Os}}' $saved

  if [ "${LOAD:-1}" = 1 ] && [ -S /host-docker.sock ]; then
    echo "==> loading into the host Docker daemon"
    docker -H unix:///host-docker.sock load -i /out/huly-x86-images.tar
  else
    echo "==> host daemon left alone; load manually with:"
    echo "    docker load -i .docker-x86/huly-x86-images.tar"
  fi
}

if [ "${1:-}" = "--in-container" ]; then
  build_inside_container
  exit 0
fi

# ------------------------------------------------------------------------ on the Mac
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
OUT="$ROOT/.docker-x86"
REV=${REV:-$(git -C "$ROOT" rev-parse HEAD)}

mkdir -p "$OUT"

if [ "${CLEAN:-0}" = 1 ]; then
  echo "==> dropping cached volumes"
  docker volume rm -f "$WORK_VOLUME" "$DOCKER_VOLUME" > /dev/null 2>&1 || true
fi

docker rm -f "$BUILDER_NAME" > /dev/null 2>&1 || true

MOUNTS=(
  -v "$ROOT:/src:ro"
  -v "$WORK_VOLUME:/work"
  -v "$DOCKER_VOLUME:/var/lib/docker"
  -v "$OUT:/out"
)
DOCKER_SOCK=${DOCKER_SOCK:-/var/run/docker.sock}
if [ -S "$DOCKER_SOCK" ]; then
  MOUNTS+=(-v "$DOCKER_SOCK:/host-docker.sock")
fi

echo "==> building $REV for linux/amd64 (front advertises HULY_VERSION=$HULY_VERSION, log: .docker-x86/build.log)"
exec docker run -i --rm --privileged --platform linux/amd64 \
  --name "$BUILDER_NAME" \
  "${MOUNTS[@]}" \
  -e REV="$REV" -e TARGETS="$TARGETS" -e JOBS="$JOBS" -e LOAD="${LOAD:-1}" -e HULY_VERSION="$HULY_VERSION" \
  ubuntu:24.04 bash /src/tools/docker-x86/build-images.sh --in-container
