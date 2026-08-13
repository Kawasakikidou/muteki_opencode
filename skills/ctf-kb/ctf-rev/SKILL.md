---
name: ctf-rev
description: CTF 二进制逆向方法论 �?反编译优先(Decompiler-First):优先分析 Ghidra 反编译伪代码而非逐条读反汇编,适用于 ELF/PE crackme、算法还原、flag 校验逻辑分析
routing:
  target_types: [ctf, reverse, binary]
  task_types: [ctf, reverse]
  tooling: [ghidra, radare2, objdump]
---

# CTF 逆向方法论 �?反编译优先

针对 CTF 二进制逆向题的标准分析流程。**核心原则:优先分析反编译代码,而不是直接反汇编分析。**

## 核心原则

拿到二进制后,用反编译器(Ghidra)产出伪代码并优先阅读它,不要默认打开 objdump / radare2 逐条读汇编。

理由:

- 伪代码保留了高级语义:循环、结构体、字符串比较、函数调用关系一眼可见,CTF 题的答案(flag 校验、算法还原)几乎总在这一层
- 直接反汇编逐条分析慢、易在无关指令里迷失;伪代码先给出全局,需要精确语义时再下沉到汇编
- Ghidra headless(`analyzeHeadless`)对常见编译器产物反编译质量高,足够回答绝大多数问题

## 标准工作流

1. **快速侦察**:`file` / `strings` / `binwalk`(确认架构、加壳、是否静态链接)
2. **定位入口与关键点**:找 `main`、可疑符号、引用 flag 提示字符串/`printf`/`strcmp` 的交叉引用;`strings` 里出现 `flag`/`congrat`/`key` 等字样时,直接追踪其引用函数
3. **反编译关键函数**(首选 Ghidra headless):
   ```bash
   # 注意:不要直接运行 `ghidra` / `ghidraRun`(会打开 GUI 并卡死无界面环境;
   # 已部署环境会拒绝非 headless 调用并打印指引)
   # 必须用 analyzeHeadless(常见路径: /usr/share/ghidra/support/analyzeHeadless,
   # 也可能在 ~/ghidra*/support/ 或 /opt/ghidra/support/),或 `ghidra --headless`
   export GHIDRA_HB=$(command -v analyzeHeadless || echo /usr/share/ghidra/support/analyzeHeadless)
   mkdir -p /tmp/ghidra_proj
   "$GHIDRA_HB" /tmp/ghidra_proj proj -import ./chal \
     -postScript 导出伪代码脚本 -scriptPath <脚本目录>
   ```
   或在交互环境直接读目标函数的 Decompile 视图
4. **读伪代码还原逻辑**:理清输入变换、逐字节校验、加密/解密公式;把校验条件直接翻译成 solve 脚本
5. **仅在这些场景才下沉到反汇编**:
   - 伪代码缺失或乱(手写汇编、shellcode、被破坏的栈帧)
   - 需要精确字节级语义:自修改代码、指令级混淆、精确替换 patch
   - 与调试器(gdb)配合看寄存器/栈实际值
   - VM/解释器类题目:反汇编定位 dispatch 表,但 handler 逻辑仍以反编译后的每段 handler 伪代码为主
6. **验证**:用 solve 脚本或 `gdb` 单步确认还原的算法与二进制行为一致,再提交 flag

## 反汇编工具的定位

- `objdump -d` / `radare2` 是**验证与补充**手段,不是入口
- 需要交叉引用、重命名、类型修复时优先回 Ghidra(IDA 的 `decompile` 同理)
- 遇到 stripped 二进制:先看 `strings` + 交叉引用恢复关键函数,再反编译该函数,不要整体读汇编

## 常见坑

- 不要为了"看全"而通读整个二进制 —— 反编译只读与 flag/校验相关的函数
- 伪代码里出现的不明显常量(魔数、表)先用 `strings`/`radare2` 查引用,再回伪代码
- 反编译失败(如混淆)时才考虑动态分析(调试器/插桩),但先试不同函数的反编译质量,往往只是个别函数坏

## OLLVM / 控制流平展化专项(高频慢点,必读)

识别特征:单一巨大函数、状态变量 `x = x*M + C` / `x = (x & M) + N` 循环分发、
成串 CMOV、Ghidra 反编译出 `UNRECOVERED_JUMPTABLE`。

**关键原则:不要试图还原平展化 CFG。** 混淆不改变输入空间 —— 数字/短 key
校验题把时间花在"读懂状态机"上是最大的浪费(实测:硬啃 CFG 7 分钟 vs
提取校验逻辑暴力 0.04 秒)。

优先级(从上往下,每一级失败才进下一级):

1. **先动态看 I/O**:跑一遍程序,记输入格式与提示("Enter key"/"Wrong")。
   有 `sleep`/`usleep` 反调试或拖延:立刻 `LD_PRELOAD` 一个 noop.so 替换
   (几行 C,`gcc -shared -o noop.so noop.c`),不要对着 sleep 等待。
2. **提取校验函数 → C/Python harness 暴力**:用 gdb 找校验入口/返回点,
   或从 Ghidra 里直接把校验函数体抠出来编译成独立 C 文件(`check_flag(k)`
   返回 0/1);数字 key 百万级暴力在原生 C 下 <1 秒。这是 OLLVM 数字校验题
   **最快路径**。
3. 校验函数过大/难抠时才考虑 gdb 条件断点 dump 中间状态,或 angr 符号执行。
4. 只有 flag 校验是逐字节/密码学级(暴力空间不可行)才需要真正还原算法。

时间预算:静态分析超过 **5-8 分钟**没有输出可直接利用的东西(密钥/公式/分支),
立即切换到动态 + 暴力路径。
