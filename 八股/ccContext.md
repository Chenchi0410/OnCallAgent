# Claude Code（cc）上下文处理：四级渐进式 Context Window 管理（源码/文档综合版）

> 目标：把 cc 的“上下文处理四个级别”讲清楚：为什么要做、每级怎么做、触发阈值、对 Prompt Cache 的影响、/compact 后哪些东西会回来。
>
> 资料来源：
> - 你给的知乎源码解析（其中第 6 章明确写了“四级渐进式压缩流水线”）
> - Claude Code 官方文档：*Explore the context window*（包含 *What survives compaction* 表）

---

## 1) 一句话回答（面试口述）

cc 的上下文处理是 **四级渐进式压缩流水线**：每次请求前先做几乎零成本的 **Snip（裁剪历史）**，再做 **Micro（清理旧工具输出）**，再做 **Context Collapse（投影式折叠/摘要，占位不改原文）**，最后才进入 **Auto/Reactive Compact（不可逆全量摘要替换）**；设计目标是在 **不撞 context window** 的前提下，尽量 **保信息、保缓存、不中断交互**。

---

## 2) 为什么需要“分级”而不是一上来就 /compact

源码解析总结的约束（非常工程化）：
- **腾空间**：给后续对话 + 模型输出预留 token。
- **保关键信息**：当前任务状态、最近指令、未完成的工具链条不能丢。
- **尽量复用 Prompt Cache**：服务端对 system prompt + 对话前缀会做缓存（解析中提到 TTL 级别约 1 小时），压缩如果破坏前缀会让后续成本变高、延迟变大。
- **不阻塞用户**：能后台做就后台做，能“结构化删/清”就别动用一次大摘要。

所以它做成“从轻到重”的四级流水线：先用 cheap 的结构操作顶住，顶不住才上 LLM 全量摘要。

---

## 3) 四级渐进式压缩流水线（Level 1~4）

> 源码解析给的核心视图：每次 `query()` 调用前按固定顺序跑 Level 1→2→3→4。

### Level 1 — Snip Compact（裁剪历史，几乎 0 成本）

**做什么**：从对话历史“头部”删掉最旧的消息，直接释放 token。

**关键机制**（解析里很强调）：
- **protected tail**：末尾一段消息（尤其是最后一个 assistant 及其之后）不会被裁剪，避免把正在推进的链条剪断。
- **按 token 预算裁剪**：不是固定“删 N 条”，而是算出需要释放多少 token，返回 `tokensFreed`。
- **插入 snip boundary marker**：标记裁剪边界，便于后续逻辑/调试。
- **UI 不等于 API**：REPL/终端里仍可滚动看到完整历史，但发给 API 的消息数组变短。

**触发**：每次 query 前自动跑；也可手动（解析里提到 `/snip`）。

**工程细节**：`tokensFreed` 会参与后续 Level 4 的阈值判断（避免 token 估算偏差）。

**可用性提醒**：解析指出 Snip 可能属于内部/特定构建特性（外部 build 未必包含）。

---

### Level 2 — Micro Compact（压缩工具结果：清理旧 tool_result 大块输出）

**做什么**：把“很旧的工具输出”替换成类似占位文本（例如 `[Old tool result content cleared]`），保留消息结构但删内容。

**为什么这层很值**：真实会话里 token 大头通常是：
- Read/Grep/Glob 的大段文本
- Bash/PowerShell 输出
- WebFetch/WebSearch 结果
这些是“当时有用、过几轮就不再需要细节”的信息，非常适合先清掉。

**两条路径（解析明确拆分）**：
1) **Time-based Microcompact（基于时间间隙，优先）**
- 典型规则：若当前时间与最近 assistant 消息相隔 ≥ 60 分钟，则认为服务端缓存 TTL 也过期，此时清理不会额外破坏缓存收益。
- 一般会保留最近少量（例如 keepRecent=5）。

2) **Cached Microcompact（基于 cache_edits 的服务端删除）**
- 思路：不改本地消息正文，而是通过“缓存编辑”告诉服务端删掉某些缓存块，达到减少上下文占用/传输的目的。
- 这一条在不同构建中可能不是都可用（解析提到存在被编译期移除的情况）。

---

### Level 3 — Context Collapse（上下文折叠：投影式摘要，不改原始历史）

**一句话**：像 IDE 代码折叠：API 看到的是“摘要占位”，但原始消息在本地仍完整保留。

**做什么**：
- 维护一个 append-only 的“折叠 commit log”。
- 每次 query 前根据 commit log **重放投影视图**：把某段旧消息替换成一行摘要 `S1`，再把投影视图送去调用 API。

**触发阈值（解析给了双阈值）**：
- 到 **90%**：把旧消息段先放进 staged 队列（暂不折叠）。
- 到 **95%**：强制触发生成摘要，把 staged 队列 drain 掉，真正折叠。
- 若收到 prompt 太长类错误：可直接 drain staged 后重试（解析里有 recover 逻辑）。

**与 Level 4 的互斥**：解析强调当 Collapse 开启时，会抑制 Auto Compact（避免两个策略在相近阈值竞争同一块空间）。

**优缺点**：
- 优点：更可逆、更细粒度；原文仍在本地，必要时可以展开/恢复。
- 缺点：实现复杂，且通常是特定构建/特性开关下才存在。

---

### Level 4 — Auto Compact / Reactive Compact（全量压缩：不可逆替换旧消息）

当 Level 1~3 仍不足以把 token 控制在安全阈值内，进入 Level 4。

#### 4.1 Auto Compact（主动式：调用前检查并压缩）
解析给了一个很实用的“先轻后重”策略：

**Step A：Session Memory Compaction（SM Compact，优先尝试）**
- 前提：当前会话已经有 Session Memory（会话摘要）可用。
- 做法：读取 Session Memory 文件内容，对每个 section 截断到固定预算（解析里举例：每 section 有上限，总预算也有上限），然后用它作为压缩基底来替换更早的历史。
- **优点：不需要额外 LLM 摘要调用**（更快、更省）。

**Step B：Full Compact（Fork 子任务/子 Agent 做全量摘要）**
- 让一个 fork agent 生成结构化摘要（解析里给了“摘要 token 上限”等约束）。
- 将旧消息大段替换成摘要块（不可逆）。
- 之后会做“恢复/回填”动作（见第 4 节）。

#### 4.2 Reactive Compact（反应式：先发请求，失败再兜底）
解析描述的思路是：
- 先尽量不压缩，让模型看到尽可能多的原始上下文。
- 若 API 返回 `prompt_too_long`（或媒体过大类错误），再触发折叠/压缩并重试。

> 实际可用性依赖版本/构建；但理解它能帮助你解释“为什么有时看起来是先撞墙再压缩”。

---

## 4) /compact 之后：哪些上下文会“自动回来”（官方文档口径）

官方文档给了一个非常清晰的表（这里用面试版总结）：

- **System prompt / Output style**：不属于消息历史，**不变**。
- **项目根目录的 CLAUDE.md + 无 paths 的 rules**：会从磁盘 **重新注入**。
- **Auto memory**：会从磁盘 **重新注入**。
- **带 `paths:` 的 path-scoped rules**：会被 compact 总结掉，**直到你再次读取匹配文件才会重新加载**。
- **子目录（nested）的 CLAUDE.md**：同样会丢失，**直到读取该子目录下文件才会重新加载**。
- **Skill bodies**：会再注入，但有预算上限（官方文档强调会截断，且总量超预算时会丢最旧的）。

这套规则解释了常见困惑：
- “我明明有规则，compact 后 Claude 变得不听话了” → 很可能是规则属于 path-scoped 或 nested CLAUDE.md，触发条件没再次发生。

---

## 5) 四级之间如何协作（你可以用来答追问）

解析总结的协作要点可以背成一段：
- 顺序固定：**Snip → Micro → Collapse → Compact**。
- Snip 与 Micro 不互斥：一个删消息，一个清内容。
- Micro 放在 Snip 后：避免对已删消息做无用清理。
- Collapse 与 Auto Compact 存在互斥：Collapse 管 90~95% 区间时，Auto Compact 会被抑制，避免双策略抢空间。
- Compact 后通常需要重置一些状态（例如折叠日志、某些 prompt section 缓存），并重新回填启动期上下文（CLAUDE.md/auto memory 等）。

---

## 6) 你怎么验证/排查“上下文为何爆了”（实操）

官方文档给的两个命令非常关键：
- `/context`：实时查看当前上下文占用分类（并给优化建议）。
- `/memory`：确认本 session 到底加载了哪些 CLAUDE.md / auto memory。

如果你要“强制释放空间但不换会话”，用 `/compact`（官方文档也强调这一点）。

---

## 7) 结论（面试收尾）

cc 的上下文处理之所以分四级，是为了把“成本、信息保真、缓存复用、交互体验”这四件互相打架的事做平衡：
- 前三级尽量用 **结构性操作**（删/清/折叠投影）压住 token；
- 最后一层才用 **LLM 摘要替换**做不可逆的兜底；
- compact 后再按规则把“启动期应常驻”的指令/记忆回填，保证会话继续可用。
