# Claude Code（cc）记忆系统六层架构（源码/文档综合版）

> 目标：用“八股”方式把 cc 的记忆系统 **六层**讲清楚：每层是什么、存在哪里、谁写入、何时加载、如何被模型使用、常见坑。
>
> 资料来源：
> - 你给的知乎“Claude Code 源码深度解析：运行机制与 Memory 模块详解”（下文简称“源码解析文”）
> - Claude Code 官方文档（code.claude.com）关于 *How Claude remembers your project*、*Subagents persistent memory* 等页面（下文简称“官方文档”）

---

## 0. 一句话总览：六层分别在解决什么

cc 不是“只有一个 memory 文件”。从工程实现上，它把“长期规则、长期事实、会话摘要、离线巩固、子代理记忆、团队共享”拆成不同层，分别服务不同时间尺度：

1. **Auto Memory（跨会话、项目级、自动）**：Claude 自己写的项目记忆，默认每次会话启动加载入口索引。
2. **Session Memory（单会话内、自动摘要）**：同一会话越聊越长时，用结构化摘要稳定上下文，支撑 auto-compact。
3. **AutoDream（跨会话、离线巩固）**：隔一段时间把多个 session 的经验再“二次蒸馏”。
4. **Agent Memory（子代理专属、可持久化）**：给 subagent 单独配一套长期记忆，避免污染主会话。
5. **Team Memory（团队共享、同步）**：把可共享的记忆作为团队资产同步，外加安全扫描。
6. **CLAUDE.md（人写的规则/偏好、手动维护）**：你/团队写的“长期指令”，每次会话注入。

> 官方文档在概念上强调“两套互补系统”：`CLAUDE.md`（人写规则）+ Auto memory（Claude 写笔记）。
> 源码/逆向视角会把它细分成上面的六层（把会话摘要、离线巩固、subagent 记忆、团队同步也算进“记忆系统”）。

---

## 1. 记忆是怎么“进入模型上下文”的（非常关键，很多人搞混）

源码解析文强调：cc 把“记忆相关信息”分散在两个位置注入，职责不同：

### 1.1 位置 A：System Prompt 里放的是“记忆规则”（不是你的记忆内容）
- 这里注入的是一段固定的 **Memory mechanics / 行为规则模板**（大约3k tokens）。
- 内容偏“制度”：
  - 记忆的分类（常见为 `user/feedback/project/reference`）
  - 何时保存、何时读取、如何验证过期
  - 什么不应该被记忆（临时任务细节、可从仓库推断的内容等）

作用：告诉模型“**怎么用记忆系统**”。

### 1.2 位置 B：第一条 User Message 里放的是“记忆数据”（CLAUDE.md + MEMORY.md 等）
- cc 会把 `CLAUDE.md`、Auto Memory 的 `MEMORY.md` 索引等内容拼起来，用类似 `<system-reminder>` 的方式作为一条“元数据 user message”注入。
- 这条消息对模型来说就是“**这次会话可见的持久上下文**”。

作用：告诉模型“**记忆里目前有什么**”。

### 1.3 一个重要的工程后果：会话内通常是 memoize 的
源码解析文提到 `getUserContext()` / `getMemoryFiles()` 等会做会话内缓存：
- 同一会话中，即便后台抽取了新记忆写回磁盘，**本会话不一定立刻可见**。
- 更常见行为是：**下次启动/恢复会话时**才加载到“第一条 user message”的那份上下文里。

这也是为什么你会看到：
- “cc 写了 memory”但你感觉模型没用上——可能是因为它写在 topic 文件里，而入口索引没变；或索引变了但这轮上下文没重新注入。

---

## 2. 六层详解（逐层八股）

下面按“谁写、存哪、何时加载、主要用途、关键限制/坑”来总结。

---

### 层 6：CLAUDE.md（用户/团队手动维护的长期指令）

**定位**：长期规则、偏好、工作流、架构约束 —— 属于“指令/制度”，不是“事实笔记”。

**谁写**：人（你/团队/IT 管理）。

**存储位置与作用域（官方文档给得最清楚）**：
- **组织/托管策略（Managed policy）**：由 IT/DevOps 部署，组织级生效；Windows 例子：`C:\Program Files\ClaudeCode\CLAUDE.md`。
- **项目级**：`./CLAUDE.md` 或 `./.claude/CLAUDE.md`（可进版本控制，团队共享）。
- **用户级**：`~/.claude/CLAUDE.md`（你个人所有项目通用）。
- **本地私有**：`./CLAUDE.local.md`（建议 gitignore，不共享）。

**加载/优先级要点（官方文档）**：
- cc 会从当前工作目录向上走目录树，发现多份 `CLAUDE.md/CLAUDE.local.md`，并把它们 **拼接进上下文**（不是互相覆盖）。
- 同一目录内 `CLAUDE.local.md` 通常在 `CLAUDE.md` 之后拼接：冲突时本地更“靠后”，更容易生效。
- 子目录的 `CLAUDE.md` 可能采用 **按需加载**：只有当 cc 读到了那个子目录下的文件时，才把对应指令加入上下文。

**组织方式（官方文档）**：
- 支持 `@path/to/file` import（最大递归深度有限），便于拆分；但 import 进来的内容仍然会占用上下文。
- 支持 `.claude/rules/*.md`（可带 frontmatter `paths` 做按路径触发的规则）。

**与 compaction 的关系（官方文档）**：
- `/compact` 会压缩对话历史，但项目根部的 `CLAUDE.md` 通常会被重新读取并重新注入。
- 子目录的 `CLAUDE.md` 可能需要“再次读到该目录文件”才会重新加载。

**最佳实践（官方文档）**：
- 把你“第二次还要解释”的内容写进 `CLAUDE.md`。
- 目标 < 200 行/尽量简洁；冲突规则会显著降低遵循稳定性。

---

### 层 1：Auto Memory（跨会话、项目级、自动积累的记忆）

**定位**：Claude 自动写下的“以后可能用得上”的项目笔记：构建命令、调试线索、偏好、容易踩坑的点。

**谁写**：Claude（自动）或在你明确要求“记住”时写入。

**存储位置（官方文档）**：
- 每个项目一套目录：`~/.claude/projects/<project>/memory/`
- `<project>` 通常由 git 仓库/working tree 推导，所以同一 repo 的 worktree 往往共享同一套 auto memory。

**目录结构（源码解析文 + 官方文档一致）**：
- `MEMORY.md`：入口索引（简洁目录）
- `debugging.md` / `api-conventions.md` / `patterns.md` 等：topic 文件，存放细节

**加载规则（官方文档）**：
- 每次会话启动时，会把 `MEMORY.md` 的 **前 200 行或前 25KB（取先到者）** 注入上下文。
- topic 文件 **不会自动注入**，需要模型按需 Read。

**检索/召回（源码解析文）**：
- 会有“相关记忆召回”的阶段：扫描 memory 目录下的 `.md`（通常有数量上限，比如最多扫描 200 个文件），挑出相关项。
- `MEMORY.md` 的价值在于：让模型先快速看到“有哪些记忆主题”，决定是否去读具体 topic 文件。

**记忆类型（源码解析文）**：
- 常见 4 类：
  - `user`：用户画像、偏好、水平
  - `feedback`：你纠正/确认过的做法（例如“测试别 mock DB”）
  - `project`：代码里推不出的项目事实（deadline、冻结窗口等）
  - `reference`：外部系统/链接/工单位置等
- 类型通常通过每个记忆文件 frontmatter 的 `type:` 标注。

**开关与配置（官方文档）**：
- 默认开启，可用 `/memory` 里切换，或 settings 里设置 `autoMemoryEnabled`。
- 环境变量也可禁用：`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`。
- 可配置自定义目录 `autoMemoryDirectory`（但为安全起见，通常不允许由共享的项目设置把写入重定向到敏感位置）。

**典型坑**：
- `MEMORY.md` 有注入上限：超出就不会在启动时进入上下文，必须靠模型主动读取其它文件。
- 会话内上下文可能缓存：写入之后不一定马上“被看见”。

---

### 层 2：Session Memory（单会话内持久化的结构化摘要）

**定位**：同一个 session 聊很久时，靠对话历史撑不住上下文窗口，就需要把会话状态“摘要化、结构化”，以便继续工作。

**谁写**：Claude（自动）。

**存储位置（源码解析文）**：
- 类似：`~/.claude/session-<id>/memory/MEMORY.md`（会话级目录结构）

**内容形态（源码解析文）**：
- 结构化 Markdown，包含多个 section（源码解析文提到大约 9 个 section，例如：Session Title / Current State / Task Spec / Files ...）。

**触发与用途（源码解析文）**：
- 当 token 达到某个阈值时后台更新。
- 既用于“会话上下文保持”，也用于 **auto-compact 的压缩基底**（压缩后保留摘要+关键事实）。

**典型坑**：
- Session Memory 是“这一个 session 的”，换新会话不一定继承（继承的是 Auto Memory/CLAUDE.md 等跨会话机制）。

---

### 层 3：AutoDream（跨会话、离线巩固/二次蒸馏）

**定位**：把多个 session 的 transcript + 现有 memory 做更高层的 consolidation（更像“睡后总结/知识巩固”）。

**谁写**：Claude（自动后台任务）。

**触发条件（源码解析文）**：
- 典型门槛：距离上次 >= 24h 且新增 session 达到一定数量（源码解析文举例为 >= 5）。

**用途**：
- 把碎片化的 session 经验整合成更稳定、更抽象的长期记忆，减少重复踩坑。

**备注**：
- 这一层在官方文档中不一定以同名概念突出出现，但在源码/实现分析中经常作为“离线巩固机制”被单独提出来。

---

### 层 4：Agent Memory（子代理的持久化记忆：user/project/local 三个 scope）

**定位**：让 subagent/专用 agent 有自己的长期知识库，避免把大量探索/日志塞进主会话。

**谁写**：子代理自己（你也可以显式要求“把经验写入 agent memory”）。

**作用域与路径（官方文档）**：
- `user`：`~/.claude/agent-memory/<agent-name>/`
- `project`：`.claude/agent-memory/<agent-name>/`（推荐默认：可进版本控制，团队共享）
- `local`：`.claude/agent-memory-local/<agent-name>/`（不想进版本控制时用）

**启用方式（官方文档）**：
- 在 subagent 的 YAML frontmatter 里加：`memory: user|project|local`。

**启用后的行为（官方文档）**：
- 子代理系统提示会包含：如何读写该目录。
- 会自动把该目录下 `MEMORY.md` 的前 200 行或 25KB 注入子代理上下文。
- Read/Write/Edit 工具会被自动允许，以便它维护自己的记忆文件。

---

### 层 5：Team Memory（团队共享记忆 + 同步 + 安全扫描）

**定位**：把“团队共同需要的记忆”从个人/机器抽离出来，作为团队资产。

**谁写**：Claude/团队成员（取决于组织实践）。

**目录与同步机制（源码解析文）**：
- 目录通常在 Auto Memory 的子目录，如：`~/.claude/projects/<project>/memory/team/`。
- 可能存在与服务端/组织空间的同步逻辑（增量、校验和等）。
- 会做敏感信息扫描（例如用一套类似 gitleaks 的规则），降低把 secret 同步出去的风险。

**备注**：
- 这一层更偏“企业/团队功能”，不同发行版/开关可能会影响是否存在或是否启用。

---

## 3. 六层之间的关系：你应该把信息写到哪一层？

最实用的决策法（结合官方文档 + 源码解析文）：

- **要长期约束 Claude 的行为（规范、流程、架构原则）** → 写到 **CLAUDE.md / .claude/rules/**。
- **是 Claude 从你纠正中学到的“经验/偏好/坑点”（未来对话可能复用）** → 让它写入 **Auto Memory**。
- **只对当前 session 有用（当前任务状态、当前文件列表、当前计划）** → 交给 **Session Memory** 摘要即可。
- **属于专用角色的经验（例如“代码审查 agent”积累的评审清单）** → 写入 **Agent Memory**。
- **团队共同资产、可共享** → 考虑 **Team Memory** 或项目级 `CLAUDE.md`（取决于组织策略）。
- **多个 session 的碎片经验需要“更高层抽象”** → 依赖 **AutoDream**（如果该构建/版本启用）。

---

## 4. 记忆系统的“硬限制/软限制”清单（背诵点）

- **注入上限**：
  - Auto memory 的 `MEMORY.md`：启动只注入前 200 行或 25KB（官方文档）。
  - Agent memory 同理（官方文档）。
- **topic 文件默认不注入**：需要模型按需 Read。
- **会话缓存**：会话内 user context 可能 memoize，导致“刚写的新记忆”不一定立刻影响本轮。
- **指令不是强制执行**：官方文档明确 `CLAUDE.md` 是 context 而不是硬配置；要“硬约束”应靠 settings/permissions 等客户端强制层。
- **冲突会降低遵循**：多份 `CLAUDE.md`/rules 矛盾时，模型可能随机偏向。

---

## 5. 你可以用哪些操作验证/调试记忆（实操要点）

- `/memory`：
  - 查看本 session 加载了哪些 `CLAUDE.md/CLAUDE.local.md/rules`。
  - 开关 auto memory。
  - 打开 auto memory 目录，直接审计/编辑/删除记忆文件。
- 如果感觉“Claude 不听话”：
  - 先用 `/memory` 确认指令文件是否真的被加载。
  - 把模糊指令改成可验证的具体规则（官方文档强调）。

---

## 6. 结论：为什么 cc 要做六层

用工程视角总结：
- **不同时间尺度**需要不同存储与加载策略（秒级相关召回、回合级抽取、分钟级会话摘要、天级离线巩固、长期规则/长期经验）。
- **不同主体**需要不同边界（主会话 vs subagent vs 团队）。
- **成本/缓存**决定注入位置：规则放 System Prompt（可缓存/稳定），数据放 user context（因用户不同不适合全局缓存）。

这就是“六层记忆系统”的核心合理性。
