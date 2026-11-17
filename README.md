# claude-to-claude-migrate

把旧电脑 A 的 Claude Code / Claude 桌面 Code 本地历史、原标题、项目源码、memory、Skills、MCP 和插件资料，追加迁移到新电脑 B。**不覆盖 B 的现有会话和登录身份。**

这是独立的 Claude → Claude Skill，不是 Claude → ChatGPT 转换器，也不操作 WorkBuddy 数据库。当前脚本针对 Windows → Windows，Python 3.10+ 标准库；其他系统须先适配路径和远端 shell。

## 安装与使用

在 B 的 PowerShell 中运行（目标目录必须不存在）：

```powershell
git clone https://github.com/shaoyunhao0107/claude-to-claude-migrate.git "$env:USERPROFILE\.claude\skills\claude-to-claude-migrate"
```

如果由 Codex 执行，改放到 `%USERPROFILE%\.codex\skills\claude-to-claude-migrate`。也可以下载仓库 ZIP，解压后确保 `SKILL.md` 在该技能目录根部。已有安装先检查本地改动，干净的 Git 安装可 `git pull --ff-only`，不要直接覆盖。

重新打开会话，在 Claude Code 中调用 `/claude-to-claude-migrate`，或在 Codex 中调用 `$claude-to-claude-migrate`。给 Agent 这段提示并替换自己的信息：

```text
使用 claude-to-claude-migrate，将 A 的 Claude 本地Code数据追加迁移到本机 B。
A SSH别名：old-pc
A用户目录：C:\Users\olduser
A配置目录：C:\Users\olduser\.claude
先盘点所有主会话、桌面Code元数据和实际项目根目录，列出路径映射。
迁历史、原标题、源码、未提交文件、memory、Skills、MCP和插件资料。
相同内容跳过，不同内容隔离，保留B会话、身份和同名配置。
先预检/拉取/plan，协调双方Claude退出后apply，再检查标题、正文和可续聊状态。
```

更完整的交接提示见 [handoff-to-b.md](references/handoff-to-b.md)，操作约束见 [workflow.md](references/workflow.md)。需要先配置 B → A 的 OpenSSH 公钥认证，并核实主机指纹；私钥留在 B，不要公开凭据。

如果目标机同时安装了多个 Agent（例如 Claude Code、ChatGPT/Codex、WorkBuddy、Devin、AgentCli），使用[通用 Agent 提示词](references/universal-agent-prompt.md)。它要求 Agent 先自识别、安装本 Skill、执行 selftest，再进行 SSH 盘点、plan、追加 apply 和桌面验收；不依赖某个 Agent 的命令格式。目标是官方订阅登录时，提示词还会要求按 B 实际 account/org 目录处理，不复制源机 OAuth 或第三方 API 凭据。

## 工具与覆盖范围

`scripts/migrate.py` 支持 `inventory`、`export`、`plan`、`apply`。`scripts/pull_from_a.ps1` 自动通过已配置 SSH 别名拉取暂存包，不会自动应用。所有路径使用绝对路径，输出区不能位于源配置或项目内。

```text
python scripts/migrate.py inventory --profile <A用户目录> --config-dir <A配置目录> --out <新盘点目录>
python scripts/migrate.py export --profile <A用户目录> --config-dir <A配置目录> --projects <projects.json> --out <新导出目录>
python scripts/migrate.py plan --bundle <包.zip> --profile <B用户目录> --config-dir <B配置目录> --map <mapping.json> --out <新计划目录>
python scripts/migrate.py apply --bundle <包.zip> --profile <B用户目录> --config-dir <B配置目录> --map <mapping.json> --out <新应用目录> --writers-stopped
```

- 没有最近50条或30天截断；所有纳入范围的本地主会话均打包。
- 文件流式导出/验证/应用，单成员上限16GiB，支持Windows长路径。
- 文件及会话UUID单元冲突隔离，B原版保留；配置只补缺失项。
- 项目实体需要显式清单和映射，不仅创建空目录。生成依赖目录跳过并报告，之后重建。
- Git元数据、插件/权限/可执行设置先进入review，由Agent继续恢复和检查，不自动激活定时任务。
- MCP配置可能含密钥；迁移包和报告属于私有数据，不提交本仓库。

**桌面Code列表是单独一层数据。** Agent还需发现 `claude-code-sessions/<account>/<org>/local_<UUID>.json`，核对原标题、时间和对应主日志。当前 `migrate.py` 不自动迁这层，须按 workflow 另行追加并实际检查UI。只跑四个命令不等于桌面迁移全部完成；源端缺失的正文不能凭标题重建。

## 第三方API和官方订阅有什么区别

本地JSONL、源码、memory和Skills的迁移原则相同，但桌面存储位置及账户/组织命名空间可能不同。第三方API模式可能位于 `Claude-3p`，官方登录可能位于 `Claude-Data` 等实际资料区；目录名是线索，不能硬编码判断。

官方订阅目标先自行登录并初始化Code，再读取B实际生成的account/org。不照搬A身份目录，不复制OAuth、Cookies或API凭据来替换B登录。MCP仍需自己的授权，续聊模型也须由B当前登录方式支持。

本次实机测试为第三方API目标模式；官方订阅跨模式桌面UI兼容尚未实测，因此必须另行验收。此流程不是向官方账号云端上传聊天，也不含claude.ai普通网页聊天和云端专属附件。

## 权限与验收

默认不提升权限。只有用户本次明确授权，才备份后设置Claude的 `bypassPermissions`；不改Windows/UAC/SSH权限，不把一次授权变成今后默认值。

验收需覆盖：原包和新文件哈希、B原文件保留、标题/UUID/目录、原会话及迁入会话可打开、Skills发现、MCP连通、插件依赖及真实桌面显示。CLI可用不代表桌面列表已经收录。

运行模拟测试：

```powershell
python scripts/selftest.py
```

测试涵盖追加、UUID单元隔离、B身份保留、同名MCP原子冲突、路径保真、review设置、重复运行和不安全包路径拒绝；不读取真实Claude数据。

## License

[MIT](LICENSE)
