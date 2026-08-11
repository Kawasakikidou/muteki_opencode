#!/usr/bin/env bash
# 构建 slim-opencode 交付镜像(muteki-for-ctf)。
# 用法: ./docker/worker/build-slim-opencode.sh [repo] [version]
#   默认: muteki-worker-slim-opencode:ctf-0.1 + :latest
set -euo pipefail

REPO_IMAGE="${1:-muteki-worker-slim-opencode}"
VERSION="${2:-ctf-0.1}"
TAG="${REPO_IMAGE}:${VERSION}"
LATEST="${REPO_IMAGE}:latest"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

echo ">> syncing muteki-blackboard skill into docker build context..."
cp "$REPO/skills/muteki-blackboard/SKILL.md" "$HERE/blackboard.SKILL.md"
cp "$REPO/skills/muteki-blackboard/blackboard.py" "$HERE/blackboard.py"
chmod +x "$HERE/blackboard.py"

echo ">> syncing VulnClaw CTF knowledge skills (ctf-kb) into build context..."
rm -rf "$HERE/ctf-kb"
cp -r "$REPO/skills/ctf-kb" "$HERE/ctf-kb"

echo ">> docker build --platform linux/amd64 --load -f Dockerfile.slim-opencode -t $TAG -t $LATEST $HERE ..."
docker build --platform linux/amd64 --load \
  -f "$HERE/Dockerfile.slim-opencode" \
  -t "$TAG" -t "$LATEST" "$HERE"

echo ">> done: $TAG (+ $LATEST)"
echo ">> quick verify:"
echo "   docker run --rm --entrypoint sh $TAG -c 'which opencode; opencode --version; ls /home/kali/.config/opencode/skills/'"
