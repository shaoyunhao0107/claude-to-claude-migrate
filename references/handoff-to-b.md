# 交给 B 电脑 Agent 的使用方法

把整个 `claude-to-claude-migrate` 文件夹交给 B，保留 SKILL.md、scripts、references 的相对结构。

- Claude Code/Claude 桌面 Code：放到 B 的 `~/.claude/skills/claude-to-claude-migrate/`，重新打开会话，用 `/claude-to-claude-migrate` 或让 Agent 读取 SKILL.md。
- Codex：放到 B 的 `~/.codex/skills/claude-to-claude-migrate/`，新会话调用 `$claude-to-claude-migrate`。
- 其他 Agent：明确让它先读完整 SKILL.md 及所指向的流程参考，再执行。

提供给 B Agent 的提示示例：

```text
使用 claude-to-claude-migrate，把 A 旧电脑的 Claude Code/Claude 桌面 Code 本地历史和能力配置追加迁移到本机 B。
A 的 SSH config 别名：old-pc
A 用户目录：C:\Users\olduser
A Claude 配置目录：C:\Users\olduser\.claude
B 项目路径原则：原D盘项目放到本机E:\work下，请先列出映射计划。
保留 B 所有原会话、账号身份和同名配置。相同内容跳过，不同内容隔离；逐项完成技能、MCP、插件和项目实体的迁移与实际核验。
先从 A 的项目登记和会话 cwd 盘点全部项目，把所有仍存在的项目实体通过 --projects 纳入SSH传输。B没有项目目录就创建；迁移源码、未提交文件、隐藏项目配置、历史和memory，不要只迁对话记录。缺失盘符自动提出映射到可用盘的计划并保持历史目录编码一致。
先完成 SSH 预检、源盘点、拉取和 plan。协调 A/B 停止写入后再 apply；若你运行在 B 的 Claude 自身，准备好独立应用命令，等待我退出 Claude 后执行。
不要将文件复制成功当作桌面 Code 标签页迁移成功，最终要实际检查原标题、历史和可继续会话。
```

A 的 SSH 服务与公钥认证提前配置好，双方 Python 3.10+、B Claude 已安装并登录。首次连接核对主机指纹。B 能访问 A 的 SSH 账号必须有源文件读取权限。不要关闭认证，不要把 B 私钥复制到 A。

整套流程没有最近50条或30天限制；迁移包保留所有纳入范围的原生会话。云端普通聊天、云端 Artifact 实体、尚未落盘的桌面会话和其他本机应用登录信息不能由此保证恢复。

工具会把 Git 元数据、项目MCP/可执行设置、插件登记和定时任务暂存到review；Agent必须继续处理这些待办并实测后再报告完整迁移。B没有新项目时可恢复独立.git；B已有仓库时隔离A元数据。依赖目录在B重新安装，不能丢掉未提交源文件。
