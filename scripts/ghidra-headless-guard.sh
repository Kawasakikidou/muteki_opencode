#!/bin/bash
# ghidra GUI 防护 wrapper —— 部署到 /usr/bin/ghidra(替换原命令)。
#
# 背景:headless worker 直接运行 `ghidra` 会打开 GUI(WSLg)并卡死无界面会话。
# 本 wrapper 只放行 headless 模式调用(--headless / -import / -postScript 等),
# 其余调用直接拒绝并打印正确用法。
#
# 部署(需要 root,原命令备份为 /usr/bin/ghidra-gui):
#   sudo mv /usr/bin/ghidra /usr/bin/ghidra-gui
#   sudo cp scripts/ghidra-headless-guard.sh /usr/bin/ghidra
#   sudo chmod +x /usr/bin/ghidra
#
# 验证:
#   ghidra          # -> ERROR 指引(拒绝 GUI)
#   ghidra --headless <projDir> <projName> -import <file>   # 正常转发
set -u

HEADLESS=0
for a in "$@"; do
  case "$a" in
    --headless|-headless|-import|-postScript|-scriptPath|-project|-process|-analyze) HEADLESS=1 ;;
  esac
done
if [ "$HEADLESS" = "1" ]; then
  exec /usr/bin/ghidra-gui "$@"
fi

echo "ERROR: direct 'ghidra' invocation opens the GUI (disabled in headless environments)." >&2
echo "Use: /usr/share/ghidra/support/analyzeHeadless <projDir> <projName> -import <file> -postScript ..." >&2
echo "or:  ghidra --headless <projDir> <projName> -import <file> ..." >&2
exit 1
