# Git & GitHub Engineering Workflow Best Practices

**Version:** 1.0

**Status:** Stable (Frozen)

**Scope:** Git · GitHub · Pull Requests · GitHub Actions · Rulesets · Code Review · Release Automation · Multi-Agent Development

**Last Verified:** 2026-08-15

**Primary Goal:** Short Lead Time · Low Merge Cost · Fast Review · Deterministic Quality · Clean History

---

## 0. 文档定位

Git 与 GitHub 的目标不应只是让团队“按照约定协作”，更成熟的目标是：

> **建立一条以 Pull Request 为原子交付单元、以 `main` 为集成事实、由自动化质量门禁驱动的软件交付流水线。**

本文同时覆盖两个核心层次：

1. **Git / GitHub 日常最佳实践**：分支创建、原子提交、主干同步、PR 流转、审查协作、冲突处理、`gh` CLI 与 `git worktree` 并行工作流。
2. **Repository Delivery Control Plane**：准入策略、确定性验证、审查职责划分、并发合流控制、质量策略保护与自动发布历史。

### 规范词约定（RFC 2119）

- **MUST**：强制要求；不满足即违反本标准，除非存在明确批准的例外机制。
- **SHOULD**：默认应采用；允许基于架构评估的合理例外。
- **MAY**：根据项目规模、并发度与成熟度可选。

---

## 1. 核心目标

一套优秀的 Git/GitHub 工作流，应同时优化以下指标：

- **Lead Time**（交付周期）
- **Review Latency**（审查耗时）
- **Merge Conflict Cost**（冲突解决成本）
- **CI Feedback Time**（门禁反馈速度）
- **Main Branch Stability**（主干稳定性）
- **Rollback Cost**（回滚成本）
- **Release Automation**（自动化发布度）
- **Developer Cognitive Load**（开发者认知负荷）

```text
Intent ──► Implementation ──► Verification ──► Review ──► Integration ──► main

```

核心追求不是形式上的 Commit 格式完美，而是**让一个正确的变更，以尽可能低的协调成本、经过充分验证后安全进入 `main`。**

---

## 2. 十条核心原则

- **Law 1 — `main` 是唯一权威集成状态**：`main` 分支 MUST 保持可构建且随时通过 Required Quality Gate；禁止直接推送与 Force Push；禁止将 `develop`/`staging` 作为长期代码分支。
- **Law 2 — Branch 是临时 Workspace**：分支生命周期 SHOULD 尽可能短；关注点是分支发散度与变更范围，一旦分支膨胀，应优先拆解 PR。
- **Law 3 — PR 是 Atomic Delivery Unit**：仓库正式交付单位是 PR 而非临时 Commit。一个 PR 对应一个清晰意图、一套验证证据、一个可独立理解的 Diff 与一次独立回滚操作。
- **Law 4 — Squash Commit 是长期历史单位**：仓库默认采用 Squash Merge，保持主干线性历史。开发过程历史（Working History）不等于永久仓库历史（Permanent History）。
- **Law 5 — Permanent History 表达 Integration Intent**：Conventional Commits 规范 SHOULD 主要约束 PR Title 与生成的 Squash Commit Subject，无需强求开发者维护每个中间 Commit 的完美规范。
- **Law 6 — Machine 验证已编码属性**：格式、Lint、编译、单测、契约测试、安全扫描均由机器闭环，人类审查者不应在此消耗精力。
- **Law 7 — Human Review 判断未编码假设**：人类审查者专注于意图（Intent）、系统架构（Architecture）、不变量（Invariants）、失效模式（Failure Modes）与可维护性。
- **Law 8 — Quality Gate 必须 Fail-Closed**：未知状态即为不通过（`Unknown is not Success`）。仅允许显式建模的通过与跳过，任何未捕获的异常、超时、取消均拒绝合入。
- **Law 9 — Integration Ordering 不应由开发者手工承担**：通过 Auto-merge 或 Merge Queue 解决并发合流问题，消除开发者不断手动 Rebase 的“循环税”。
- **Law 10 — Automation 消除协调成本，但不得隐藏不确定性**：杜绝盲目重跑测试直到绿灯的掩耳盗铃行为。偶发失败（Flaky Tests）必须隔离（Quarantine）并显式治理。

---

## 3. 推荐 Repository 状态机

```text
Intent / Issue
      │
      ▼
Worktree
      │
      ▼
Short-lived Branch
      │
      ▼
Draft PR ──────────────► Local Verification (`task quality:fast`)
      │
      ▼
Ready for Review ──────► Deterministic CI (`Delivery / Quality`)
      │                  Human Review (Architecture & Invariants)
      │                  Conversation Resolution
      ▼
Approved Candidate
      │
      ▼
Auto-merge / Merge Queue
      │
      ▼ (Integration Validation on merge_group)
main
      │
      ▼
Release Automation (Release Please ──► Tag / Changelog / Artifact)

```

---

## 4. Git 本地基础配置

### 4.1 推荐全局配置 Profile

```bash
git config --global init.defaultBranch main
git config --global fetch.prune true
git config --global rerere.enabled true
git config --global push.autoSetupRemote true
git config --global pull.ff only
git config --global merge.conflictStyle zdiff3

```

- `init.defaultBranch`：统一新建仓库主干为 `main`。
- `fetch.prune`：同步时自动清理远程已删除分支在本地的跟踪引用。
- `rerere.enabled`：记录已人工解决过的冲突并在未来 Rebase 中自动重用。
- `push.autoSetupRemote`：新分支首次推送时自动绑定 upstream。
- `pull.ff only`：禁止 `git pull` 隐式生成 Merge Commit。
- `merge.conflictStyle zdiff3`：冲突标记中显示共同祖先基线，提升冲突识别精度。

### 为什么不推荐全局配置 `pull.rebase=true`

`git pull` 会同时触发网络拉取与历史整合。更可控、更显式的方式是分步执行：

```bash
git fetch origin
git rebase origin/main

```

---

## 5. 日常 Git 快速检查

```bash
# 检查当前工作区与跟踪状态
git status --short --branch

# 同步远端分支与修剪失效引用
git fetch --prune origin

# 图形化查看提交拓扑
git log --graph --decorate --oneline --all --date-order

# 查看当前分支相对 main 的新增提交
git log --oneline origin/main..HEAD

# 查看当前分支相对 main 的 PR 级 Diff
git diff origin/main...HEAD

# 检查暂存区内容
git diff --cached

```

---

## 6. 创建工作分支

推荐显式基于 `origin/main` 建立分支：

```bash
git fetch origin
git switch -c feat/registry-validation origin/main

```

推荐的前缀规范：`feat/*`、`fix/*`、`refactor/*`、`docs/*`、`test/*`、`chore/*`、`spike/*`。

---

## 7. Worktree-First 并行开发

Git Worktree 允许在同一仓库对象数据库下检出多个独立的工作目录，完全消除 `stash`/`switch` 带来的上下文中断。

```text
Workspace/
├── atlas/                      (main)
├── atlas-registry-validation/  (feat/registry-validation)
└── repo-hotfix/                (fix/critical-auth)

```

### 7.1 创建与清理 Worktree

```bash
# 创建并切换到新 feature worktree
git fetch origin
git worktree add -b feat/registry-validation ../atlas-registry-validation origin/main

# 查看当前活跃的 worktree
git worktree list

# 完成并清理
git worktree remove ../atlas-registry-validation
git worktree prune  # 清理已丢失目录的元数据

```

### 7.2 缓存与构建状态隔离原则

- **共享不可变/内容寻址缓存**：Go Build Cache、pnpm store、Cargo registry、`sccache`、`ccache`、Docker Layer Cache。
- **隔离可变构建状态**：`target/`、`dist/`、`build/`、`node_modules/` 以及本地绑定的测试端口和临时数据库。

---

## 8. Commit 实践

### 8.1 暂存与原子化提交

新创建的未跟踪文件需显式纳入暂存区（或通过 `git add -N` 声明 Intent-to-add），已有文件的变更通过交互式暂存拆分 Hunk：

```bash
git status --short

# 1. 新建文件显式加入暂存区（或使用 git add -N 声明意图）
git add path/to/new-file

# 2. 对已有文件按 Hunk 原子化暂存
git add -p

# 3. 校验暂存候选集
git diff --cached
git diff --cached --check

# 4. 提交
git commit -m "refactor: isolate registry inventory"

```

### 8.2 允许过程性临时提交

在 Squash-Only 架构下，分支上的 `wip`、`fix test`、`address review` 不会进入 `main` 分支。无需过度执行本地 `rebase -i` 或频繁 `amend`。

---

## 9. Rebase 触发时机

不要无目的地频繁 Rebase。仅在以下场景主动 Rebase：

1. `main` 分支发生影响当前模块的结构性变更；
2. 即将准备处理显式冲突；
3. PR 生命周期较长需要确认最新集成状态；
4. 整理 Stacked PR 依赖拓扑。

```bash
git fetch origin
git rebase origin/main

```

---

## 10. 重写已 Push 分支的安全策略

重写本地历史后推送至个人特性分支时，MUST 使用：

```bash
git push --force-with-lease

```

`--force-with-lease` 在远端分支被意外更新时会主动拒绝覆盖，避免团队成员或自动化 Bot 的提交被悄然冲掉。

---

## 11. PR Title 规范

PR Title MUST 遵循 Conventional Commits 规范，作为生成最终 Commit 与 Release Notes 的核心依据：

- `feat(registry): validate node inventory atomically`
- `fix(ci): fail closed when heavy tests are cancelled`
- `refactor(bootstrap): separate artifact resolution`
- `docs(workflow): define merge queue policy`
- `chore(actions): pin checkout to immutable SHA`
- `feat(api)!: replace authentication contract`（Breaking Change）

---

## 12. Squash History 契约

在 GitHub 仓库设置中，MUST 配置：

- **Allow squash merging**: `Enabled`
- **Allow rebase merging**: `Disabled`
- **Allow merge commits**: `Disabled`
- **Default commit message**: **`Pull request title`**（推荐）或严格格式化后的 `Pull request title and description`。

> ⚠️ **严禁选择 `Pull request commit details`**，防止将开发分支中未整理的过程性 commit log 串联注入主干。

---

## 13. PR 创建：Draft First

在开始开发或需要早期反馈时创建 Draft PR：

```bash
git push
gh pr create --draft --title "feat(registry): validate node inventory atomically"

```

---

## 14. 推荐 PR Template

`.github/pull_request_template.md` 标准结构：

```markdown
## Why

为什么需要这次变更？它解决什么问题、技术债或业务诉求？

## What

简要列出核心变更点：

- Change A
- Change B

## Validation

说明验证方式与证据：

- [ ] Local quality gate passed (`task quality`)
- [ ] Unit tests added/updated
- [ ] Integration behavior verified
- [ ] `git diff --check origin/main...HEAD` passed

## Risk & Rollback

- **Risk**: 运行时行为 / 兼容性 / 性能潜在影响
- **Rollback**: 失败时的回滚方式与开关控制

## Notes for Reviewers

Reviewer 最需要关注的核心决策点与未编码假设。
```

---

## 15. PR 大小：Semantic Cohesion > LOC

不采用死板的 LOC 硬门禁，而以语义内聚性（Semantic Cohesion）作为第一准则：

> **One PR = One independently understandable and reversible change.**

- `~200–400 LOC`：通常极易理解与审查。
- `~800+ LOC`：应主动检查是否包含可拆解的重构或独立层级。
- `~1500+ LOC`：通常代表架构拆分不合理，除非大部分为自动生成的 Schema 或快照。

---

## 16. Author Self-Review 流程

在请求他人 Review 之前，作者 SHOULD 独立完成全量自检：

```bash
git fetch origin
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD

# 检查整个 PR Diff 是否引入空格与格式脏标记
git diff --check origin/main...HEAD

task quality

# 查看 PR 检查状态并持续监听
gh pr checks --required --watch --fail-fast

```

### Git Diff Check 的三个 Scope

- `git diff --check`：检查工作区未暂存修改（Unstaged working-tree changes）。
- `git diff --cached --check`：检查暂存区提交候选集（Staged commit candidate）。
- `git diff --check origin/main...HEAD`：检查完整 PR 相对主干引入的所有变更（Complete PR change）。

---

## 17. 转换为 Ready for Review

```bash
gh pr ready

```

---

## 18. Reviewer 审查优先级

```text
1. Intent (意图与合理性)
      ↓
2. Architecture (架构边界与依赖)
      ↓
3. Invariants & Correctness (正确性与不变量)
      ↓
4. Failure Modes & Edge Cases (失效模式与异常)
      ↓
5. Tests & Evidence (测试充分度与覆盖)
      ↓
6. Maintainability (可维护性)
      ↓
7. Style / Naming (风格与命名)

```

---

## 19. Review 批注严重级别约定

- `blocking:` 必须修复后方可合并（如并发竞争、内存泄露、架构违规）。
- `question:` 存在疑问，需要作者澄清，但不一定需要改动代码。
- `suggestion:` 优化建议，作者可自行评估是否采纳。
- `nit:` 细微风格建议，不阻塞合入。

---

## 20. Reviewer 本地验证操作

```bash
# 检出目标 PR
gh pr checkout 42

# 本地执行验证
task quality

# 提交审查意见
gh pr review 42 --approve
gh pr review 42 --request-changes --body "Inventory must be consumed from the validated snapshot."
gh pr review 42 --comment --body "Architecture looks good; one minor suggestion."

```

---

## 21. CODEOWNERS 策略

`.github/CODEOWNERS` 应该用来保护**关键控制面边界**，而不是制造全量审批瓶颈：

```text
/.github/                    @platform-team
/Taskfile.yml                @platform-team
/scripts/quality/            @platform-team
/security/                   @security-team
/bootstrap/                  @platform-team

```

> 💡 将 `/.github/` 纳入所有权约束，可确保 `.github/CODEOWNERS` 文件本身自动受保护。

---

## 22. 推荐 `main` 分支 Ruleset

- `[MUST]` Require a pull request before merging
- `[SHOULD]` Require at least 1 approval（团队协作仓库）
- `[SHOULD]` Require conversation resolution
- `[MUST]` **Require Code Owner review for Repository Policy Surface**
- `[MUST]` Require status check: **`Delivery / Quality`**
- `[MUST]` Block force pushes
- `[SHOULD]` Require linear history
- `[SHOULD]` Allowed merge methods: **Squash only**
- `[MUST]` Restrict deletion

---

## 23. Review Freshness 机制

- **高频迭代仓库**：启用 `Require approval of most recent reviewable push`。
- **强合规/金融/安全敏感仓库**：启用 `Dismiss stale pull request approvals when new commits are pushed`。

---

## 24. Signed Commits（可选安全 Profile）

`[MAY]` Signed Commits 作为高安全环境的可选控制项。

> ⚠️ **平台与自动化约束警告**：启用 Required Signed Commits 前 MUST 验证其与仓库 Squash / Merge Queue / Bot 合并模型的兼容性。在 GitHub 上对要求签名提交的受保护分支执行 Squash Merge 时，存在平台限制（如要求执行 Squash 合并者必须是 PR 作者等），不得假设配置自动化签名凭据即可消除所有 GitHub 平台约束。

---

## 25. Repository-Owned Quality Logic

> **CI 平台不应承载业务验证逻辑，CI 只是仓库自治门禁脚本的无状态执行器。**

```text
Local Dev   ──► task quality
Git Hook    ──► task quality:fast
CI Pipeline ──► task quality

```

质量逻辑在仓库内单一维护（如 `Taskfile.yml`、`Makefile` 或 `scripts/quality/`），CI 仅负责准备环境并调用。

---

## 26. 三层边界架构模型

```text
Repository-owned Policy (仓库自有策略)
        │
        ▼
CI Pipeline
= Authoritative Verification Evidence (权威验证证据)
        │
        ▼
Ruleset / Branch Protection
= Merge Admission Enforcement Boundary (合流准入强制边界)

```

- **Local Hook**：纯加速反馈层（Developer Feedback）。
- **CI Pipeline**：唯一的权威验证证据生产系统（Evidence Generator）。
- **GitHub Ruleset**：最终决定状态能否进入 `main` 的强制准入边界（Enforcement Gate）。

---

## 27. Quality Gate 聚合架构

```text
GitHub Ruleset ──► Requires: [Delivery / Quality]
                          │
                          ▼
            ┌─────────────┴─────────────┐
            │                           │
          Fast                        Heavy (Integration / E2E)

```

GitHub 保护策略仅需挂载聚合任务 `Delivery / Quality`，内部子任务的增减与重构完全对 Ruleset 透明。

---

## 28. 推荐 GitHub Actions 基础流水线

```yaml
name: Delivery

on:
  pull_request:
    branches:
      - main
  merge_group:

permissions:
  contents: read

concurrency:
  group: delivery-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  fast:
    name: Fast
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1 (由 Renovate/Dependabot 自动升级)
      - name: Fast quality
        run: task quality:fast

  heavy:
    name: Heavy
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Heavy quality
        run: task quality:heavy

  quality:
    name: Delivery / Quality
    needs:
      - fast
      - heavy
    if: ${{ !cancelled() }}
    runs-on: ubuntu-latest
    steps:
      - name: Evaluate
        env:
          FAST: ${{ needs.fast.result }}
          HEAVY: ${{ needs.heavy.result }}
        shell: bash
        run: |
          set -euo pipefail
          [[ "$FAST" == "success" ]] || { echo "Fast checks failed: $FAST"; exit 1; }
          [[ "$HEAVY" == "success" ]] || { echo "Heavy checks failed: $HEAVY"; exit 1; }
          echo "Delivery / Quality passed."
```

---

## 29. CI Concurrency 与调度责任划分

```text
Pull Request Freshness Cancellation  ──► Actions Concurrency Scheduler
Integration Ordering & Concurrency   ──► GitHub Merge Queue Policy

```

- **普通 PR 触发**：配置 `cancel-in-progress: true`，新提交主动终止旧任务，节约算力。
- **Merge Queue 触发**：关闭 Actions 层的 stale-run cancellation，避免 CI 调度器主动取消有效 `merge_group` 验证；Merge Group 的排序、分组与推测构建并发度由 GitHub Merge Queue 自身的 Build Concurrency 与 Queue Policy 统一管理。

---

## 30. Required Workflow 与 Paths 过滤的经典陷阱

> ⚠️ **严禁在顶层配置 `on.pull_request.paths` 并将其设为 Required Check**。当修改内容不匹配该路径时，Workflow 不会触发，导致 Required Check 永远处于 Pending 状态并死锁 PR。

---

## 31. Path-Aware Heavy Tests 正确实现

```yaml
jobs:
  changes:
    runs-on: ubuntu-latest
    outputs:
      backend: ${{ steps.scope.outputs.backend }}
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0 # 简单可靠方案；确保本地 diff/merge-base 所需历史对象可用
      - id: scope
        run: ./scripts/ci/detect-changes >> "$GITHUB_OUTPUT"

  fast:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - run: task quality:fast

  heavy:
    needs: changes
    if: ${{ needs.changes.outputs.backend == 'true' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - run: task quality:heavy

  quality:
    name: Delivery / Quality
    needs: [changes, fast, heavy]
    if: ${{ !cancelled() }}
    runs-on: ubuntu-latest
    steps:
      - name: Evaluate
        env:
          CHANGES: ${{ needs.changes.result }}
          FAST: ${{ needs.fast.result }}
          HEAVY: ${{ needs.heavy.result }}
          HEAVY_REQUIRED: ${{ needs.changes.outputs.backend }}
        shell: bash
        run: |
          set -euo pipefail
          [[ "$CHANGES" == "success" ]] || exit 1
          [[ "$FAST" == "success" ]] || exit 1
          if [[ "$HEAVY_REQUIRED" == "true" ]]; then
            [[ "$HEAVY" == "success" ]] || exit 1
          else
            [[ "$HEAVY" == "skipped" || "$HEAVY" == "success" ]] || exit 1
          fi
```

---

## 32. 质量策略防篡改

所有定义质量规则的文件（`.github/workflows/**`、`Taskfile.yml`、`scripts/quality/**`、`CODEOWNERS`）MUST 纳入 CODEOWNERS 受保护范围，防止普通 PR 篡改门禁指令。

---

## 33. Actions 最小权限原则

Workflow 默认配置只读权限：

```yaml
permissions:
  contents: read
```

仅在确实需要的具体 Job（如发布 Release）中单独提升权限。

---

## 34. Action SHA Pinning 供应链加固

所有外部 GitHub Actions（包括 GitHub 官方 Actions）MUST 固定至完整 Commit SHA，并通过 Renovate / Dependabot 自动维护版本更新：

```yaml
uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

---

## 35. 抵御不可信代码注入

严禁在 `on: pull_request_target` 下直接检出不可信 PR 分支并赋予写权限或 Secrets 注入。

---

## 36. PR Metadata 注入防御

不可信参数（如 PR Title、Branch Name）严禁直接拼接入 Shell：

```yaml
# 正确：使用中间环境变量传递
- name: Validate title
  env:
    PR_TITLE: ${{ github.event.pull_request.title }}
  run: ./scripts/ci/check-pr-title "$PR_TITLE"
```

---

## 37. Auto-Merge：低并发默认选择

```bash
gh pr merge --squash --auto

```

审批通过且 CI 变绿后自动由系统完成合并，消除“等待 CI 绿灯并手动点击”的协调耗时。

---

## 38. Merge Queue：什么时候启用

合流竞争度与以下核心变量成正比：

$$\text{Integration Contention} \propto \text{Concurrent Merge Candidates} \times \text{CI Latency} \times \text{Main Update Frequency}$$

当由此产生的重复验证、branch freshness churn 与人工协调成本达到实质性水平时 SHOULD 启用 Merge Queue。

---

## 39. Merge Queue 工作模型

```text
PR A ──┐
PR B ──┼──► Merge Queue ──► Speculative Validation (merge_group) ──► main
PR C ──┘

```

---

## 40. Merge Queue 与 CI 触发器

使用 Merge Queue 时，Required Check 的 Workflow MUST 同时监听：

```yaml
on:
  pull_request:
  merge_group:
```

---

## 41. 统一 Merge 交互

在启用 Merge Queue 的仓库中：

```bash
gh pr merge 42  # 自动进入排队或 auto-merge

```

严禁日常使用 `gh pr merge --admin` 绕过队列。

---

## 42. Merge Queue 与 Flaky Tests 治理

Flaky Tests 会被 Merge Queue 级联放大，导致推测批次频繁剔除重测。仓库 MUST 追踪 **Flaky Test Rate** 与 **Queue Ejection Rate**，不稳定的测试必须先隔离。

---

## 43. Stacked PR

针对庞大且具备天然分层的架构演进，使用依赖链 PR（Stacked PRs），而非将数百行异构变更堆积在一个 PR 中：

```bash
# PR 1
git switch -c refactor/storage-engine origin/main

# PR 2 (基于 PR 1)
git switch -c feat/storage-api
gh pr create --base refactor/storage-engine --title "feat(storage): expose new storage API"

```

---

## 44. Release Automation

结合 Conventional PR Title 与 Squash Merge，通过 **Release Please** 自动解析版本语义升级（SemVer）并生成规范 Changelog。

---

## 45. 自动化发布流转

```text
feature PR ──► main ──► Release Please PR ──► Merge ──► Tag / GitHub Release

```

开发者不应手动编辑 CHANGELOG 或手工执行打 Tag 操作。

---

## 46. 分支清理

- 启用 GitHub `Automatically delete head branches`。
- 本地使用 `git fetch --prune` 与 `git worktree remove`。
- 确认 Squash 合并后清理本地分支：`git branch -D feat/foo`。

---

## 47. 完整 Feature 生命周期实战

```bash
# 1. 同步最新状态并创建隔离工作区
git fetch --prune origin
git worktree add -b feat/registry-validation ../repo-registry-validation origin/main
cd ../repo-registry-validation

# 2. 开发与显式原子暂存
git status --short
git add path/to/new-file     # 新建文件显式加入
git add -p                   # 已有文件按 Hunk 暂存
git diff --cached --check
git commit -m "refactor: isolate validated inventory"

# 3. 本地门禁自检与 PR 级格式校验
task quality
git diff --check origin/main...HEAD

# 4. 推送并创建 Draft PR
git push
gh pr create --draft --title "feat(registry): validate node inventory atomically"

# 5. 监听 CI 并转为 Ready
gh pr checks --watch
gh pr ready

# 6. 注册自动合并 (Auto-Merge Registration)
gh pr merge --squash --auto

# 7. 后置清理：仅在 PR 确认真正合并后执行 (Post-Merge Cleanup Guard)
MERGED_AT="$(gh pr view --json mergedAt --jq '.mergedAt // empty')"

if [[ -z "$MERGED_AT" ]]; then
  echo "PR is not merged yet; skip local cleanup."
  exit 0
fi

cd ../repo
git worktree remove ../repo-registry-validation
git branch -D feat/registry-validation
git fetch --prune

```

---

## 48. Hotfix 应急工作流

```bash
git fetch origin
git worktree add -b fix/critical-crash ../repo-hotfix origin/main
cd ../repo-hotfix

# 修复并验证
git status --short
git add path/to/fix-file
git add -p
git commit -m "fix(runtime): prevent nil dereference"
task quality
git diff --check origin/main...HEAD

# 发起 PR
gh pr create --title "fix(runtime): prevent nil dereference"

```

---

## 49. 冲突解决标准流程

```bash
git fetch origin
git rebase origin/main
# 解决冲突文件...
git add <conflict-files>
git rebase --continue
task quality
git push --force-with-lease

```

---

## 50. Revert 优先原则

当生产环境发现缺陷时，优先通过 GitHub 原生按钮或 `git revert` 创建 Revert PR，严禁直接篡改主干提交历史。

---

## 51. Multi-Agent 并行协作模型

为 AI Agent 与人类开发者分配独立的 Worktree 与分支：

```text
Workspace/
├── repo/           (Human / main)
├── repo-agent-a/   (feat/storage-indexer)
└── repo-agent-b/   (fix/grpc-keepalive)

```

> ⚠️ **运行隔离提醒**：多 Agent 并发在本地拉起测试服务时，需确保本地端口、测试数据库名称及 Kubeconfig 上下文相互隔离。

---

## 52. Agent 准入权威

AI Agent 可以自主编写代码、补充测试并提交 PR，但最终合并的权威仲裁者永远是 **CI Quality Gate + Ruleset + 架构审查**。

---

## 53. GitHub CLI 推荐命令集

```bash
gh auth status                            # 检查登录状态
gh pr status                              # 查看与我相关的 PR 状态
gh pr create --draft                      # 创建 Draft PR
gh pr view --web                          # 浏览器打开当前 PR
gh pr diff                                # 终端快速查看 Diff
gh pr checks --required --watch           # 持续监听关键门禁
gh pr checkout <PR_NUMBER>                # 检出目标 PR
gh pr ready                               # 转换为 Ready 状态
gh pr review <PR_NUMBER> --approve        # 批准 PR
gh pr merge --squash --auto               # 开启自动合并

```

---

## 54. 常用 Git 命令速查

```bash
git status --short --branch               # 紧凑状态展示
git fetch --prune origin                  # 同步并清理失效引用
git switch -c <branch> origin/main        # 基于主干创建新分支
git worktree add -b <branch> <path> <ref> # 新建工作树
git worktree remove <path>                # 移除工作树
git add -p                                # 交互式暂存
git diff --cached --check                 # 检查暂存区脏标记
git diff origin/main...HEAD               # 查看分支 PR 级 Diff
git diff --check origin/main...HEAD       # 检查完整 PR 引入的格式问题
git rebase origin/main                    # 变基同步
git push --force-with-lease               # 安全推送重写历史
git branch -D <branch>                    # 强制删除已合并分支

```

---

## 55. 关键 Anti-Patterns 清单

1. **长期存在的 `develop` 分支**（制造集成壁垒与发版黑洞）。
2. **直接 Push 代码至 `main`**（绕过自动化安全审计）。
3. **在 `main` 分支执行 Force Push**（破坏历史一致性）。
4. **强迫每个 PR 在合并前反复手动 Rebase**（产生无意义的 Rebase Tax）。
5. **在 Required Workflow 顶层配置 `paths` 过滤**（导致门禁挂起死锁）。
6. **在 CI YAML 中直接维护全套 Lint/Test 脚本**（导致本地与 CI 逻辑脱节）。
7. **CODEOWNERS 范围过度扩大给少数核心成员**（成为全局审查瓶颈）。
8. **面对 Flaky Test 盲目重跑直到绿灯**（掩盖系统不确定性）。
9. **因“Commit 分得很清晰”而放任数千行大 PR 合入**（破坏 PR 原子交付属性）。
10. **手动在 YAML 中维护裸 SHA 字符串**（缺乏自动化版本更新追踪）。

---

## 56. 成熟度模型

| Stage       | 定位                                    | 核心能力                                                                         |
| ----------- | --------------------------------------- | -------------------------------------------------------------------------------- |
| **Stage 0** | **Local Discipline**                    | Clean workspace、`fetch --prune`、`rerere`、Atomic diff、本地 `task quality`     |
| **Stage 1** | **Repository Discipline**               | Short-lived branch、PR-only、Squash-only、Ruleset、PR Title 契约、对话闭环       |
| **Stage 2** | **Deterministic Quality Control Plane** | 仓库自治 Quality 逻辑、单聚合 `Quality` Gate、Action SHA Pinning、策略文件受保护 |
| **Stage 3** | **Automated Integration Control Plane** | Auto-merge、Merge Queue、Stacked PR、多 Agent 隔离、Release Please 自动化        |

---

## 57. Stage 0 — Local Discipline

- 团队成员统一配置 `fetch.prune`、`rerere`、`push.autoSetupRemote` 与 `pull.ff=only`。
- 养成基于 `git diff --check origin/main...HEAD` 与本地 `task quality:fast` 的自检习惯。

---

## 58. Stage 1 — Repository Discipline

- 确立 `main` 为唯一长期分支，全面推行 PR-only、Squash-only 与 PR Title 规范。
- 启用自动删除 head 分支与对话全部 resolved 方可合入的约束。

---

## 59. Stage 2 — Deterministic Quality

- CI 建立单一权威 `Delivery / Quality` 门禁。
- 实施 Job 级 Path-Aware 检查与 Fail-Closed 聚合逻辑。
- Action 全面 SHA Pinning，策略文件纳入 CODEOWNERS 保护。

---

## 60. Stage 3 — Automated Integration

- 全面接入 Auto-merge / Merge Queue。
- 采用 Worktree 进行多任务及 Multi-Agent 研发隔离。
- 接入 Release Please 实现主干全自动版本推导与发布。

---

## 61. 应追踪的工程效能指标

- **PR Lead Time**（从首次提交到最终合入的时长）
- **Time to First Review**（首次获得审查反馈的时长）
- **CI p50 / p95 Duration**（流水线耗时分布）
- **Flaky Test Rate**（偶发失败率）
- **Merge Queue Ejection Rate**（队列剔除率）
- **Change Failure Rate**（变更失败率）
- **Rollback Rate**（回滚率）

---

## 62. 推荐默认 Baseline

对于绝大多数现代项目，推荐以下起步组合：

$$\begin{aligned} &\text{main} + \text{Short-lived Branch} + \text{Draft PR} + \text{Squash Merge Only} \\ &+\text{PR Title Conventional Commits} + \text{Repository-owned task quality} \\ &+\text{Delivery / Quality Required Check} + \text{Conversation Resolution} \\ &+\text{Policy Surface CODEOWNERS} + \text{Action SHA Pinning} + \text{Auto-merge} + \text{Worktree} \end{aligned}$$

当并发合流冲突显著上升时，再开启 **Merge Queue**。

---

## 63. 最终工作流控制面

```text
Repository Policy
  │
  ▼
Intent
  │
  ▼
Worktree
  │
  ▼
Short-Lived Branch
  │
  ▼
Draft Pull Request
  │
  ├──────── Local Quality (`task quality:fast`)
  │
  ▼
Ready for Review
  │
  ├──────── Machine Verification (Deterministic CI Gate)
  ├──────── Human Review (Architecture & Invariants)
  ├──────── Policy Review (CODEOWNERS on Policy Surface)
  │
  ▼
Approved Integration Candidate
  │
  ▼
Auto-Merge / Merge Queue
  │
  ├──────── Integration Validation (`merge_group`)
  │
  ▼
main
  │
  ├──────── Release Please (SemVer & Changelog)
  ├──────── Artifact Build & Attestation
  └──────── Immutable Audit History

```

---

## 64. 终极结论

> **Branch is temporary.**
> **PR is the delivery unit.**
> **Quality is deterministic.**
> **Review is semantic.**
> **Integration is automated.**
> **`main` is truth.**
