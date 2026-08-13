# muteki_opencode

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)

`muteki_opencode` 是以 [Project Muteki(無敵)](https://github.com/FishCodeTech/muteki)
为底座的 CTF 求解 agent,接入 **opencode** 引擎作为 worker 执行器。本文是它的部署与使用说明;
项目架构、架构图、测评与完整文档见 [README_CN.md](README_CN.md)。

Muteki 是**攻击性安全自动化工具** —— 它驱动 CLI agent 执行命令、访问目标服务,**不承诺隔离
恶意 challenge**。请只在专用、可丢弃的环境(VPS / throwaway VM)里运行,详见
[SECURITY.md](SECURITY.md)。

## 快速开始(容器模式)

```bash
# 1. 构建 worker 镜像(联网、耗时较长,在仓库根目录执行)
./docker/worker/build-slim-opencode.sh    # 产物 tag: muteki-worker-slim-opencode:latest

# 2. 容器模式跑 batch 比赛(仓库代码在本地时)
MUTEKI_WORKER_IMAGE=muteki-worker-slim-opencode:latest \
MUTEKI_ACCOUNTS_ROOT=$PWD/sessions/_secrets/accounts \
  uv run python -m muteki.batch.ctf_runner manifest.json --report report.md

# 3. 或直接 docker 验证
docker run --rm --entrypoint sh muteki-worker-slim-opencode:latest -c 'which opencode; ls /home/kali/.config/opencode/skills/'
```

## 与全量镜像的取舍(交付原则)

本镜像**刻意排除**了可联网/落地重建的重型内容,只保留"即开即用"的最小核心:

- **包含**: supervisor(runtime_agent)、opencode / claude / codex 引擎 CLI、
  muteki-blackboard skill、VulnClaw ctf-kb 知识 skill(crypto/misc/web/reverse)
- **排除(需要时在线安装)**: Kali 工具链(ghidra/sage/volatility3/pwntools 等)、
  离线知识库(PayloadsAllTheThings/hacktricks 等)、CTF Python 栈
  - worker 有 NOPASSWD sudo,需要时自行 `apt install` / `pip3 install` 即可

需要全量 Kali 工具链时,用官方镜像或本仓库的增量构建:
```bash
# 全量 Kali worker + opencode(镜像大,构建慢,首次需要网络)
./docker/worker/build-opencode.sh       # 基于 ghcr.io/fishcodetech/muteki-worker:latest
# 或 slim 版(0.48GB 基础)
./docker/worker/build-slim-opencode.sh  # 基于 ghcr.io/fishcodetech/muteki-worker-slim:latest
```

## 模型配置

默认模型:`opencode-go/deepseek-v4-flash`(走 opencode-go 网关)。
更换接口(4 层,优先级从高到低):
1. 运行环境变量 `MUTEKI_WORKER_MODEL=opencode-go/deepseek-v4-pro`
2. batch manifest 的 `"model"` 字段
3. worker profile 的 `model` 字段(web UI 设置)
4. `~/.config/opencode/opencode.jsonc` 的全局 `model`

## 认证(容器模式)

容器模式必须配账户:在 `MUTEKI_ACCOUNTS_ROOT/opencode-main/opencode-data/` 放
opencode 的 `auth.json`(从宿主 `~/.local/share/opencode/auth.json` 复制),
运行时经 XDG_DATA_HOME 投影注入容器。宿主本地模式则直接继承宿主登录。

## CLI 总览(本地模式)

所有命令统一用 `uv run` 执行。本地模式(local backend)让 worker 直接在
本机(WSL / Linux / macOS)内运行 opencode,不依赖 Docker / worker 镜像,最快上手。
需要:`MUTEKI_DEEPSEEK_API_KEY`(coordinator 推理,配在 `.env`)。

### TUI(推荐:单题交互式解题)

Textual 交互界面:实时事件流(推理/工具调用/flag)+ 状态条(成本/上下文)+
命令输入(HITL:提示/暂停/提交),适合边跑边看、人工干预。

| 命令 | 说明 |
|---|---|
| `uv run python -m apps.tui` | mock 演示模式:脚本化事件流,无需 key,纯看 UI |
| `uv run python -m apps.tui --swarm --desc "题目描述" --target http://host:port --category web` | 单题实战(无附件题),无需 manifest |
| `uv run python -m apps.tui --swarm --n-solvers 3` | 指定 swarm 并行 worker 数(默认 2) |
| `uv run python -m apps.tui --swarm --key <id>` | 按 NYU-bench 题目 key 解题 |

界面操作:
- 输入框输入命令,Enter 发送,语法 `[target] action text` 或 `/action text`
- 可用 action:`hint`(给提示)、`pause`(暂停)、`submit`(提交 flag)、`interrupt`(中断)
- `Esc` 中断当前 run;`Ctrl+C` 退出

### CLI 批量(ctf_runner:一次跑多题/附件题)

```bash
uv run python -m muteki.batch.ctf_runner manifest.json --report report.md
```

- `manifest.json`:题目清单(JSON),格式见 `muteki/batch/manifest.example.json`,
  字段:`engines`(目前填 `["opencode"]`)、`model`(worker 模型)、`timeout`
  (单题上限秒)、`backend`(`local`/`container`)、`challenges`(数组,每项
  `id`/`name`/`category`/`description`/`attachments`[附件路径列表])
- 需要手写 manifest 的场景:**一次跑多道题**或**题目带附件文件**
  (attachments 字段);远程靶机的单道描述题直接用上面的 TUI 一行命令即可
- `--report`:战报输出路径(默认 battle_report.md);`--workers`:并行数(当前固定 1)

## 实战流程(Windows + WSL,单题)

从打开 WSL 到解题完毕、用户检查结果的全过程。

### 第 0 步:启动 WSL 并进入仓库

```bash
# 开始菜单启动 kali-linux,或:
wsl -d kali-linux
cd /mnt/<盘符>/<仓库路径>        # 例如 /mnt/e/Repositories/muteki_opencode
```

### 第 1 步:一次性环境准备

```bash
# 1. 检查 Python ≥3.13 与 uv(没有 uv 则 pip install uv 或官方安装脚本)
python3 --version && uv --version

# 2. 安装依赖(注意 --extra dev,否则缺包)
uv sync --extra dev

# 3. 配置密钥:复制模板并填入 MUTEKI_DEEPSEEK_API_KEY
cp .env.example .env
#   编辑 .env,填:MUTEKI_DEEPSEEK_API_KEY=sk-你的key

# 4. 确认 WSL 原生 opencode(重要)
ls ~/.opencode/bin/opencode 2>/dev/null || which opencode
#   坑:若 which 指向 /mnt/c/.../npm/opencode(Windows npm shim),它读不到
#   Linux 路径,必须装 WSL 原生版:
curl -fsSL https://opencode.ai/install | bash
#   首次使用需登录(本地模式直接继承登录态):
opencode auth login

# 5. (可选)把 ctf-kb skill 部署到 WSL opencode(容器模式镜像已内置,此步仅本地模式需要)
mkdir -p ~/.config/opencode/skills/ctf-rev
cp skills/ctf-kb/ctf-rev/SKILL.md ~/.config/opencode/skills/ctf-rev/
```

### 第 2 步:开跑(无需 manifest)

```bash
export MUTEKI_OPENCODE_BIN=$HOME/.opencode/bin/opencode   # 钉住 WSL 原生 opencode
uv run python -m apps.tui --swarm --desc "完整题目描述,含目标地址" \
  --target http://192.168.x.x:8000 --category web
```

类别取值:web / crypto / reverse / forensics / misc / pwn。
带附件的题目见"CLI 批量"一节(manifest 的 `attachments` 字段)。

### 第 3 步:TUI 界面与干预

- 上方状态条显示 lineup、累计成本、上下文用量
- 主区实时滚动 worker 事件:推理、工具调用、事实、flag
- 输入框可随时发 HITL 命令(见 CLI 总览),如 `/hint 试试XX方向`

### 第 4 步:用户检查结果

1. **界面直接显示 flag**(`⚑ FLAG flag{...}` 行),复制到比赛平台提交即可
2. **验证 flag 真实性**:flag 只有出现在 worker 真实执行输出中才会被接受
   (provenance gate);想人工复核可查运行日志:
   ```bash
   rg -l "flag\{" work/sessions/ | tail -3     # 找到该 run 的日志
   rg "flag\{" <日志路径>                       # flag 出现在 worker 真实输出里
   ```
3. **未解的题**:看日志里 worker 卡在哪一步(探路/工具缺失/思路偏差),
   用 `/hint` 引导或调整描述后重跑

## 实战流程(Linux,单题)

Linux 原生环境的本地模式流程,与 WSL 一节等价,只是省去 WSL 引导。容器模式见
"快速开始"。注:项目官方只在 macOS 实测,Linux 路径代码已支持,首次使用建议先跑
一道简单题验证引擎认证链路(healthcheck 会先自检)。

### 第 0 步:环境与一次性准备

```bash
# 1. Python ≥3.13 与 uv
python3 --version && uv --version

# 2. 装 opencode(官方 installer 支持 Linux,装到 ~/.opencode/bin)
curl -fsSL https://opencode.ai/install | bash
~/.opencode/bin/opencode auth login

# 3. 依赖 + 密钥
uv sync --extra dev
cp .env.example .env        # 填 MUTEKI_DEEPSEEK_API_KEY=sk-你的key

# 4. (可选)ctf-kb skill 部署到 opencode 全局目录(容器镜像已内置,仅本地模式需要)
mkdir -p ~/.config/opencode/skills/ctf-rev
cp skills/ctf-kb/ctf-rev/SKILL.md ~/.config/opencode/skills/ctf-rev/
```

### 第 1 步:开跑

```bash
export MUTEKI_OPENCODE_BIN=$HOME/.opencode/bin/opencode   # 钉住 opencode
uv run python -m apps.tui --swarm --desc "完整题目描述,含目标地址" \
  --target http://host:port --category web
```

界面操作与 flag 验证同 WSL 一节的第 3/4 步。与 macOS 的差异:
- **claude 凭据**:Linux 无 Keychain,`claude setup-token` 写入
  `~/.claude/.credentials.json`,凭据探测会读该文件。
- **host.docker.internal**(容器模式):Linux 上不自动解析,代码已自动加
  `--add-host host.docker.internal:host-gateway`,无需手动配置。

## 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `ModuleNotFoundError` | 未装 dev 依赖 | `uv sync --extra dev` |
| worker 立即失败/找不到 opencode | which 解析到 Windows npm shim | 装 WSL 原生 opencode 并钉 `MUTEKI_OPENCODE_BIN` |
| 容器模式 supervisor 连不上 control receiver | Linux 的 `host.docker.internal` 不自动解析 | 代码已自动 `--add-host host.docker.internal:host-gateway`;手动 `docker run` 时保持 bridge 网络 |
| claude 登录探测不到 | Linux 无 macOS Keychain | 用 `claude setup-token` 写入 `~/.claude/.credentials.json` |
| `ghidra` 打开 GUI 卡住 | 直接运行了 `ghidra` 命令 | 用 `analyzeHeadless`(ctf-rev skill 已写明,勿直接跑 ghidra) |
| 网络题连不上靶机 | WSL 网络/代理问题 | 确认 WSL 能 curl 目标地址;`NO_PROXY` 必要时放行内网 |
| 成本担忧 | worker + coordinator 按 token 计费 | 演示题约几十秒/题;真实题每道几万~几十万 token,先跑 1 道观察 |

> 备注:`.env` 含真实密钥且已被 `.gitignore` 忽略,切勿提交;`work/`、
> `sessions/`、`artifacts/`、`attachments/` 均为运行产物,不入库。

## 许可证与第三方组件

- **本仓库**(muteki_opencode)以 [GNU AGPL-3.0](LICENSE) 许可发布。
- 依赖的**引擎 CLI 各有其自身许可**,且会向各自厂商回传数据:
  - `opencode` —— MIT License,© 2025 opencode,经 `npm install -g opencode-ai` 引入;
  - `claude` / `codex` / `cursor` —— 专有闭源,须自备订阅与认证。
- `skills/ctf-kb/` 下的 CTF 知识技能源自 [VulnClaw](https://github.com/Netw0rkNoob/VulnClaw)
  (MIT License,© 2026 UncleC),已做工具名通用化。
- 完整的三方版权声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与
  [skills/ctf-kb/NOTICE.md](skills/ctf-kb/NOTICE.md)。
