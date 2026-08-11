#!/usr/bin/env bash
# 加载 muteki-worker-slim-opencode 交付镜像(即开即用)。
# 用法: ./load.sh [镜像.tar.gz 路径] [目标 tag]
#   默认: 当前目录的 muteki-worker-slim-opencode.tar.gz → muteki-worker-slim-opencode:latest
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARBALL="${1:-$HERE/muteki-worker-slim-opencode.tar.gz}"
TAG="${2:-muteki-worker-slim-opencode:latest}"

if [ ! -f "$TARBALL" ]; then
  echo "错误: 找不到镜像包 $TARBALL" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "错误: 需要 docker(docker --version)" >&2
  exit 1
fi

echo ">> 加载镜像 $TARBALL ..."
docker load -i "$TARBALL"

echo ">> 打上使用 tag: $TAG ..."
IMG="$(docker load -i "$TARBALL" --quiet 2>/dev/null | sed -n 's/^Loaded image: //p' | head -1 || true)"
if [ -z "$IMG" ]; then
  IMG="$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -i 'slim-opencode' | head -1)"
fi
if [ -n "$IMG" ] && [ "$IMG" != "$TAG" ]; then
  docker tag "$IMG" "$TAG"
fi

echo ">> 验证:"
docker run --rm --entrypoint sh "$TAG" -c 'which opencode claude codex; opencode --version; ls /home/kali/.config/opencode/skills/'
echo ">> 完成。把这个 tag 配给 muteki:MUTEKI_WORKER_IMAGE=$TAG"
