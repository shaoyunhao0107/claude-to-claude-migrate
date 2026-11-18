---
name: claude-to-claude-migrate
description: 将 A 旧电脑的 Claude Code 或 Claude 桌面 Code 标签页的本地历史、标题、记忆、Skills、MCP 和项目配置，通过 OpenSSH 追加迁移到 B 新电脑的 Claude。保留 B 的现有会话与同名配置，支持路径映射、哈希核验、冲突隔离和重复运行。用于 Claude 到 Claude 跨电脑迁移，不用于 Claude 到 ChatGPT、普通 Claude 网页聊天或 Cowork 云端迁移。
---

# Claude → Claude：A 到 B 追加迁移

在 B 执行此 Skill。A 是数据源，B 是目标。默认 Windows→Windows。其他系统先适配路径、配置位置和 SSH 远端 shell，不直接套用 Windows 命令。

首次交付/安装步骤与给 B Agent 的完整提示见 [handoff-to-b.md](references/handoff-to-b.md)。本地工具可用 `python scripts/selftest.py` 在临时模拟 A/B 目录中验证，不读取真实 Claude 数据。

用户说“全部迁移”表示追加合并：保留 B 的会话、标题、配置、登录身份和项目文件。不能清空或整目录覆盖 B 的 `.claude`。不把本任务等同于上一个 Claude→ChatGPT 导入器；这里保存 Claude 原生格式，没有 50 条/30 天截断。

## 开始前

读 [迁移流程和兼容边界](references/workflow.md)。需要用户提供 A 的 SSH 别名（推荐）、旧 Windows 用户目录和项目存放约定；可从 SSH 配置、只读远端检查中发现就自行发现。B→A 应使用 SSH 公钥认证；“免密钥”通常指“密钥认证免密码”，不是关闭 SSH 认证。私钥留在 B，只将公钥加入 A。

1. 确认 SSH 主机指纹、`BatchMode=yes` 连接、A/B Python 3.10+ 和 Claude 版本。
2. 检查 A 的实际 `CLAUDE_CONFIG_DIR` 及登录用户。桌面 Code 标签页还可能在 Claude-Data/Claude-3p 的 claude-code-sessions 存储列表标题和会话元数据；按参考的“桌面Code列表的第二层原生数据”核对。只有实际可发现的本地文件可迁移，勿把 `.claude/projects` 文件复制成功称为整个桌面 UI 已迁移。
3. 在 A 的写入者停止/空闲后导出；B 的 Claude CLI/桌面写入者也应关闭后再应用。若 B Agent 本身运行在 Claude 中，先完成拉取和 plan，交给独立脚本在退出后应用；不要自动杀死活动任务。
4. 运行 `inventory` 从 A 的项目登记和主会话结构化 cwd 找出项目候选。为项目建立显式 A→B 路径映射；用户要求全部迁移时，把所有实际存在的项目根目录加入 `--projects`，B 缺失目录自动创建。嵌套项目归并到一个实体根目录，历史 cwd 仍逐项映射。缺盘符时映射到 B 可用磁盘，不能只迁历史而不迁项目实体。

## 工具流程

工具 `scripts/migrate.py` 只依赖 Python 标准库，支持 `inventory`、`export`、`plan`、`apply`。使用绝对路径，所有输出目录都放在 `.claude` 与项目根目录之外且使用新的运行目录。

```text
python migrate.py inventory --profile <A用户目录> --config-dir <A实际.claude目录> --out <新建盘点目录>
python migrate.py export --profile <A用户目录> --config-dir <A实际.claude目录> --projects <projects.json> --out <新建导出目录>
python migrate.py plan --bundle <迁移包.zip> --profile <B用户目录> --config-dir <B实际.claude目录> --map <mapping.json> --out <新建核验目录>
python migrate.py apply --bundle <迁移包.zip> --profile <B用户目录> --config-dir <B实际.claude目录> --map <mapping.json> --out <新建应用目录> --writers-stopped
```

通过 `scp` 把脚本送到 A 的专用临时目录，在 A 执行 export，然后从 B 拉回 zip 和旁边的 `.sha256`。通过 SSH 取到的哈希与 B 本地计算一致后才能 plan。传输命令、远端 PowerShell 安全引用示例见流程参考。不要经第三方网盘中转私有迁移包。

双方都是 Windows 时可运行 `scripts/pull_from_a.ps1 -SshAlias <SSH别名> -SourceProfile <A用户目录> -SourceConfigDir <A配置目录> -ProjectsFile <本地projects.json> -OutDir <B新暂存目录>`，它通过已核实主机指纹的公钥认证自动上传工具与项目清单、远端导出、拉包并校验 SHA-256；仅暂存，不自动应用。执行前协调 A 停止写入。使用非默认端口/私钥时写入 SSH config 别名，脚本不接受明文密码。

`mapping.json` 示例见参考。`plan` 核验包的每个文件并预测新增/跳过/冲突。`apply` 再次核验包，新增文件独占创建；已有不同文件不替换，完整来源版本存入运行目录的 `conflicts/`。活动 JSON 配置仅递归增加缺失键，相同键不同值保留 B 并记录冲突；先备份再写入。已有 JSONL 不拼接、不重排、不修改 UUID、时间、消息正文或标题。

## 配置与能力恢复

- Skills/commands/agents、项目 memory、子代理日志、标题 sidecar、file-history 随目录保留。项目目录编码必须与目标路径一致，并用 B 上新建的短会话验证编码规则。
- MCP 来自用户 `.claude.json` 和项目 `.mcp.json`，会迁配置，不会迁 OAuth/系统凭据；逐个检查 command/args/env 和本地依赖。新 MCP 配置可能包含明文 API key，迁移包按敏感数据处理。
- Hooks、permissions、env、enabledPlugins、市场注册信息暂存在 `review/`，Agent 审核依赖与路径后再合并/安装。已存在同名 MCP、Skill、插件配置以 B 为准，不自动启用新的权限和定时任务。
- 插件目录作为文件资源备份，但安装登记与缓存不等于可运行插件。用 B 的 Claude 官方插件命令/界面重建登记并验证。不要覆盖 B 的安装登记文件。
- 项目实体、未提交文件、项目 `.claude/`、CLAUDE.md 和空目录通过 `--projects` 一起迁移。项目 `.mcp.json`/settings 和 Git 元数据先进入 review；Agent 在 B 完成配置合并/Git恢复后才可验收。生成依赖目录跳过并记录，不能据此声称项目已可运行。

## 验收

核对应用报告及包哈希、全部主会话 UUID 和明确标题、附属文件数量、B 原有文件未被替换、重复运行新增为零。打开 B 的原会话和 A 的至少一条旧会话，核对标题、消息、时间、目录、memory；检查 Skills 可发现、MCP 实际连通和插件依赖。桌面 Code 标签页必须实际显示并可继续；CLI `claude --resume` 可用不代表桌面 UI 一定收录。

同一 Windows 用户的 Claude Code CLI 主历史通常在实际 `CLAUDE_CONFIG_DIR`（默认 `~/.claude/projects`）下；官方订阅 CLI 和第三方 API CLI 不应仅凭登录方式推断为两套历史。桌面 Code 的列表索引另存于当前应用资料区，不同模式可能有不同索引。定位实际目录和验证 CLI 导入按钮的办法见 [桌面 Code 列表](references/workflow.md#桌面code列表的第二层原生数据)。导入按钮显示的候选数不是写入数，也不能证明 A 的缺失记录已收录。

只在所有目标项通过时称“全部迁移完成”。将冲突、重登、依赖缺失、未复制项目、桌面未显示列为待办。重复运行对变更了的既有 UUID 仍隔离，不做双向同步或历史覆盖。
