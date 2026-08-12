# muteki_opencode 

本文是 `muteki_opencode`(以 muteki 为底座的 CTF agent,接入 opencode 引擎)的部署简介。

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

## 实战测试完整流程(Windows + WSL 本地模式)

从打开 WSL 到解题完毕、用户检查结果的全过程。本地模式(local backend)让
worker 直接在 WSL 内运行 opencode,不依赖 Docker / worker 镜像,最快上手。
需要:`MUTEKI_DEEPSEEK_API_KEY`(coordinator 推理)与 WSL2(kali-linux)。

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

# 2. 安装依赖(注意 --extra dev,否则 ctf_runner 缺包)
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

### 第 2 步:编写 manifest.json(题目清单)

```json
{
  "engines": ["opencode"],
  "model": "opencode-go/deepseek-v4-flash",
  "timeout": 600,
  "backend": "local",
  "challenges": [
    {
      "id": "chal-1",
      "name": "我的第一道题",
      "category": "web",
      "description": "完整题目描述,含目标地址,例如:flag 在 http://192.168.x.x:8000/admin 的响应头里",
      "attachments": []
    },
    {
      "id": "chal-2",
      "name": "附件题",
      "category": "rev",
      "description": "逆向附件,还原 flag 校验逻辑",
      "attachments": ["attachments/chal2.zip"]
    }
  ]
}
```

字段说明:
- `engines`:目前填 `["opencode"]`(worker 引擎)
- `model`:worker 模型,默认 `opencode-go/deepseek-v4-flash`,可换 `.../deepseek-v4-pro`
- `timeout`:单题上限(秒),难题建议 600-900
- `backend`:本地模式填 `local`(容器模式填 `container`)
- `attachments`:附件相对仓库根的文件路径;远程靶机题留空

### 第 3 步:运行

```bash
export MUTEKI_OPENCODE_BIN=$HOME/.opencode/bin/opencode   # 钉住 WSL 原生 opencode
uv run python -m muteki.batch.ctf_runner manifest.json --report report.md
```

每道题会输出类似:
```
[1/2] 我的第一道题 (web) 开始...
[1/2] 我的第一道题: ✅ 解出 flag{...} (45s)
[2/2] 附件题 (rev) 开始...
```

### 第 4 步:用户检查结果

1. **看战报** `report.md`:每题 解出/未解、flag、用时
2. **验证 flag 真实性**:flag 只有出现在 worker 真实执行输出中才会被接受
   (provenance gate),把报告中的 flag 粘贴到比赛平台提交即可确认;
   想人工复核可查运行日志:
   ```bash
   rg -l "flag\{" sessions/ | tail -3        # 找到该 run 的日志
   rg "flag\{" <日志路径>                      # flag 出现在 worker 真实输出里
   ```
3. **未解的题**:到 `sessions/` 对应 run 的日志里看 worker 卡在哪一步
   (探路/工具缺失/思路偏差),调整描述或 `timeout` 后重跑

### 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `ModuleNotFoundError` | 未装 dev 依赖 | `uv sync --extra dev` |
| worker 立即失败/找不到 opencode | which 解析到 Windows npm shim | 装 WSL 原生 opencode 并钉 `MUTEKI_OPENCODE_BIN` |
| 演示题报文件不存在 | 示例 manifest 的 `/tmp/...` 演示文件需自行创建 | 换真实题目,或先 `echo 'flag{...}' > /tmp/batch_demo_flag.txt` |
| 网络题连不上靶机 | WSL 网络/代理问题 | 确认 WSL 能 curl 目标地址;`NO_PROXY` 必要时放行内网 |
| 单题耗时长 | `timeout` 太小或题难 | 调大 `timeout`,难题给 600-900s |
| 成本担忧 | worker + coordinator 按 token 计费 | 演示题约几十秒/题;真实题每道几万~几十万 token,先跑 1 道观察 |

> 备注:`.env` 含真实密钥且已被 `.gitignore` 忽略,切勿提交;`report.md`、
> `sessions/`、`artifacts/` 均为运行产物,不入库。
