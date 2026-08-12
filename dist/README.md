# muteki_opencode 即开即用交付包

本目录是 `muteki_opencode`(以 muteki 为底座的 CTF agent,接入 opencode 引擎)
的**即开即用 docker 交付物**。

## 内容

| 文件 | 说明 |
|---|---|
| `muteki-worker-slim-opencode.tar.gz` | 交付镜像(opencode 引擎 + ctf-kb 知识 skill + 黑板 skill + supervisor),0.96GB(镜像层已压缩,再 gzip 无收益) |
| `load.sh` | 一键加载脚本(加载 + 打 tag + 验证) |

## 快速开始(目标机器)

```bash
# 1. 加载镜像(需要 docker)
./load.sh                        # 默认加载本目录的 tar.gz, tag 为 muteki-worker-slim-opencode:latest

# 2. 使用(两种方式)
#    a) 容器模式跑 batch 比赛(仓库代码在本地时)
MUTEKI_WORKER_IMAGE=muteki-worker-slim-opencode:latest \
MUTEKI_ACCOUNTS_ROOT=$PWD/sessions/_secrets/accounts \
  uv run python -m muteki.batch.ctf_runner manifest.json --report report.md

#    b) 或直接 docker 验证
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
