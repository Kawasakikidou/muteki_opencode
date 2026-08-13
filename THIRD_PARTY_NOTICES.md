# Third-Party Notices

Project Muteki(無敵)本身以 [GNU AGPL-3.0](LICENSE) 许可发布。以下第三方组件被本项目**引用、分发或随 worker 镜像交付**,各自保留其原始许可证与版权声明。它们均与本项目的 AGPL-3.0 相互独立,互不改变对方的许可条款。

## opencode

- 用途:CLI 推理引擎之一,worker 通过 `opencode run --format json` 无头调用。
- 来源:<https://github.com/sst/opencode>(npm 包 `opencode-ai`)
- 引入方式:worker 镜像内 `npm install -g opencode-ai`;本地模式由 operator 自行安装。
- 许可证:**MIT License**,版权 `Copyright (c) 2025 opencode`。

```
MIT License

Copyright (c) 2025 opencode

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## VulnClaw(ctf-kb 知识技能)

- 用途:`skills/ctf-kb/` 下的 CTF 知识技能(client-reverse / ctf-crypto / ctf-misc /
  ctf-rev / ctf-web)源自 VulnClaw 项目的 skills 内容,已做工具名通用化。
- 来源:<https://github.com/Netw0rkNoob/VulnClaw>(`skills/specialized`)
- 引入方式:源码内 `skills/ctf-kb/`,并随 worker 镜像 `COPY` 进
  `/home/kali/.config/opencode/skills/`。
- 许可证:**MIT License**,版权 `Copyright (c) 2026 UncleC`。
- 完整说明见 [`skills/ctf-kb/NOTICE.md`](skills/ctf-kb/NOTICE.md)。

## 其它运行时依赖

Python 依赖清单见 [`pyproject.toml`](pyproject.toml)(pydantic / fastapi / httpx /
textual 等),均按各自上游许可证(以 `uv.lock` 锁定的版本为准)引入,不属于本仓库分发内容。
