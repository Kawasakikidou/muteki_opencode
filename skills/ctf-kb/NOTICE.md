# NOTICE — VulnClaw ctf-kb skills

本目录(`skills/ctf-kb/`)下的 CTF 知识技能源自开源项目
[VulnClaw](https://github.com/Netw0rkNoob/VulnClaw)(`skills/specialized`),本仓库
对其做了**工具名通用化**(去掉对 VulnClaw 特有工具的依赖),并调整为 opencode/claude/codex
的 skill 格式(带 frontmatter 路由)。

VulnClaw 以 **MIT License** 发布:

```
MIT License

Copyright (c) 2026 UncleC

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

本目录会随 worker 镜像构建脚本(`docker/worker/build-*.sh` 的 `cp -r skills/ctf-kb …`)
整体复制进镜像,本 NOTICE 一并分发。
