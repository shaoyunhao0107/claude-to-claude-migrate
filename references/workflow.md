# 跨电脑流程、范围和失败处理

## B Agent 的运行约定

所需输入：A 的 SSH 别名/主机端口与用户、A 用户目录、B 用户目录、项目路径映射。优先 SSH config 别名，不把密码/私钥写进参数或报告。用 `ssh -o BatchMode=yes A-alias whoami` 测试；首次主机指纹须和用户/可信来源核实，不能用 `StrictHostKeyChecking=no`。本 Skill 不负责打开公网22端口或降低SSH安全设置。

双方先检查 `claude --version`、`python --version`、实际配置目录及可读权限。B 的 Claude 推荐不旧于 A；内部格式没有跨版本稳定保证。仅检查注册表/环境/文件元数据，不输出密钥和 OAuth 内容。

Windows 远端 PowerShell 可用 UTF-16LE `-EncodedCommand` 传递固定代码。对所有路径做 PowerShell 单引号转义；使用本地 `subprocess.run(["ssh", "-o", "BatchMode=yes", alias, remoteCommand], check=True)`，不拼 shell 命令执行本地用户输入。`scp` 也用参数数组。旧版 scp/SFTP 对盘符路径处理不同，优先远端用户主目录下无空格相对路径 `claude-migrate-<runid>/`。脚本路径与输出目录来自受控的新运行目录；export 只向临时区写文件。

示例流程（路径按实际替换，不原样运行占位符）：

```powershell
scp -o BatchMode=yes <本地migrate.py> A-alias:claude-migrate-run/migrate.py
ssh -o BatchMode=yes A-alias '<正确引用的PowerShell调用python export命令>'
scp -o BatchMode=yes A-alias:claude-migrate-run/export/claude-transfer.zip <B暂存目录>
scp -o BatchMode=yes A-alias:claude-migrate-run/export/claude-transfer.zip.sha256 <B暂存目录>
```

实际先通过 SSH 创建远端 `claude-migrate-run`。需要时把编码命令生成在 B，再发送，不让用户手抄长命令。不要删除 A 的源文件或以 robocopy /MIR、rsync --delete 镜像到 B。

## 路径映射

```json
{
  "paths": {
    "C:\\Users\\olduser": "C:\\Users\\newuser",
    "D:\\work\\project": "E:\\work\\project"
  },
  "projectDirs": {
    "D--work-project": "E--work-project"
  },
  "workspaces": {
    "D:\\work\\project": "E:\\work\\project"
  }
}
```

`paths` 按最长前缀匹配，只用于结构化路径字段和配置；会话正文、提示快照、工具结果和历史文本保持原文，因而旧用户名在历史正文出现是正常的。路径匹配按边界，不能把 `D:\work\app` 错匹配 `D:\work\apple`。

`projectDirs` 是显式目录编码表，直接来自 A 实际项目历史目录和 B 的编码规则。Claude 会话通常在 `.claude/projects/<编码目录>/<UUID>.jsonl`，另有同 UUID 子目录存标题和子代理；memory 也在项目历史目录下。不要假定仅把盘符冒号变成连字符就适配所有中文/空格/UNC/长路径。先在 B 选定路径创建短测试会话确认编码；未映射且原项目路径不在 B 时，不宣称可 resume。

`workspaces` 将每个实体项目根目录精确映射到 B 的绝对路径。`--projects projects.json` 的格式是 `[{"source":"D:\\work\\project"}]`。源项目必须是实际项目根，不能选整个磁盘或用户主目录；多个实体根不能嵌套，否则去重合并为上级项目。每个入包实体必须有 workspaces 映射，否则 plan/apply 停止。B 没有目录时会自动创建，空子目录也保留。工作文件同名不同内容进入 conflicts；隐藏项目能力文件也会同步。

实体导出默认排除 node_modules、.venv、venv、__pycache__，在报告列明并在 B 重建；符号链接/目录联接列为待办，不偷偷跟随到项目外。源码、未提交文件、其他隐藏文件（可能含.env密钥）会保留，迁移包应仅通过SSH保密传输。文件以1MiB块导出、核验和应用，单个包成员上限16GiB；更大文件须另外评估。Windows长路径使用扩展路径读取，不能把FileNotFoundError直接当作源文件不存在。

## 受管Windows传输问题

如果源端脚本能由Python正常读取，SCP到B却变成不可解析字节，先比较应用读取字节的SHA-256与远端哈希。可能存在透明加密，不反复运行损坏脚本。可由源端Python以二进制读取，使用subprocess.Popen的stdin经SSH直接传给目标Python接收器；禁止PowerShell文本管道传ZIP。接收器独占创建.partial、流式核验长度与SHA-256后才改名到新暂存文件。先以小JSON测试，再传大包。PowerShell通过SSH读取大量stdin可能挂起，小接收脚本可通过编码命令分块bootstrap；不要把凭据编码进命令。

源端输出区放在空间充足且不属于项目的专用目录；含源码/日志的失败包也属敏感材料。失败包保留调查，不能当成功包apply。B如果已有一轮迁移，先比较原生history和项目实体，避免把仅创建了空目录称为已迁移源码。

`.git/`及worktree的`.git`指针完整放入 review。B 是全新目标时，Agent 可将独立仓库.git恢复到对应新项目并执行 git status/fsck；B 已有Git仓库时不合并元数据，保留 B 并隔离 A。`.git`为文件或有commondir/worktree外部引用时，需要同时迁公共仓库和修复引用，不能只移动指针。项目MCP/settings同样从review逐项审核恢复，避免项目一打开就执行未核实的hook。

项目 `sessions-index.json` 是可重建的派生索引，不覆盖 B 索引。迁移工具将 A 索引放到 review。若当前版本未自动发现新 JSONL，先用 `claude --resume <UUID>` 在映射目录验证，再检查对应版本的正式索引/桌面发现行为。不得伪造私有数据库记录。

## 桌面Code列表的第二层原生数据

不能只检查`%APPDATA%/Claude`。实际Windows安装可能将数据移到`%LOCALAPPDATA%/Claude-Data/claude_pzs8sxrjxfjjc`，第三方提供商模式可能使用`%LOCALAPPDATA%/Claude-3p`。Appx的`LocalCache/Roaming/Claude`可能只有迁移指向标记，实际数据已不在那里。

查找`claude-code-sessions/<account>/<org>/local_<UUID>.json`：这是桌面会话元数据，包含title、cliSessionId、cwd、时间、归档状态；JSONL完整存在也不代表桌面会显示。保留整层原件到私有备份，按cliSessionId关联主日志。元数据比日志多时逐条报告；源日志已经清理/不可用的记录不能声称已恢复正文。

不同账号/模式不能直接照搬account/org目录。先从B当前config的lastKnownAccountUuid以及已有profile-origin标记确认目标命名空间；不确定时暂停桌面层apply。仅把真实源会话记录追加到目标目录，保留title/UUID/时间/归档状态，不携带A的账户、OAuth、设备标识、权限授予、自动模式、定时任务或会话内远端MCP密钥。原始快照保存在备份，不伪造不存在的会话或数据库。缺失主日志的记录标为不可用并列报告。B已有同ID记录按完整单元隔离，不能覆盖。

应用后须重启桌面实际验证列表与正文；CLI可用或记录文件存在都不替代UI验收。跨模式/版本兼容是实测结果，不承诺所有版本均支持。

### 第三方API与官方订阅登录的区别

迁移核心仍是追加本机文件，不是把历史上传到新账户云端。Magpie等第三方API模式、官方订阅登录共用的部分可能包括本机Claude Code JSONL、项目源码和skills，但桌面资料区及account/org命名空间可能不同。观察到的Claude-3p、Claude-Data目录仅作发现线索，不按名称猜当前模式。

官方订阅目标先由用户登录并初始化Code，在实际生成的资料区确认B账户/组织目录，再按该版本的原生记录结构追加。不能把第三方模式的占位org或A的account目录直接搬去充当B身份，也不能复制Cookies、OAuth或第三方API凭据来替换B登录方式。官方→官方、第三方→官方、官方→第三方都应重新盘点并验证目标，而不是沿用上一台机器的命名空间。

MCP需要自己的服务认证；Claude官方订阅不会自动提供飞书等MCP的授权。项目、skills、插件的本地依赖也不会因订阅登录自动安装。迁移会话可能保留旧模型名称，实际续聊需选择B当前登录方式支持的模型。原Claude账号的网页版普通聊天、云端项目及附件不属于这个本地Code迁移流程。

本Skill的migrate.py处理CLI历史/项目/可迁配置，不会自动发现或应用上述桌面第二层元数据；Agent须按本节另行处理并检查UI，不能把运行四个子命令称为完整桌面迁移。正式订阅登录的跨模式UI兼容性尚未在本次实机中验证。

## 分层迁移和账户

1. 账户：B 自己登录 Claude。A 的 `.credentials.json`、`.claude.json` 中 oauthAccount/userID/machineID、系统凭据、桌面应用的 Cookies/Local Storage 不导入。更换订阅/组织不等于迁移云端历史。
2. 原生会话：完整项目历史目录，含 custom-title.json、JSONL custom-title/summary、subagents、memory、附件引用和 file-history。工具不截断最近天数或数量。外部图片/Artifact/云端文件引用可能仍依赖 A 账户；需另行导出实体。
3. 用户能力：skills、agents、commands、全局 CLAUDE.md，及可发现的共享 `.agents/skills`。符号链接不会默默解引用；报告跳过并检查链接实际资源是否要单独迁。
4. MCP：用户 `.claude.json` 的 mcpServers、已登记项目的 mcpServers，以及项目 `.mcp.json`。连接的 OAuth 通常需要 B 重登；npx/uvx/Python/Node 路径、代理、环境变量、公司网络均需实际测试。MCP条目应作为整体比较，同名不同配置隔离，不能合成混合服务器。
5. 配置：缺失的普通偏好可追加；hooks/permissions/env/插件启用状态需审核后启用。计划任务只能先备份，不默认激活，避免 A/B 重复触发。
   如果本次用户明确要求Claude最高权限，可在备份后设置`permissions.defaultMode=bypassPermissions`及迁入桌面记录的`permissionMode=bypassPermissions`，恢复所需项目权限；此选择只对当前授权生效，不成为未来迁移默认项，不改Windows/UAC/SSH权限，保留B其余配置及显式deny规则。
6. 插件：保留插件自定义源码与资源，重新安装或注册；已安装清单中的旧绝对 installPath 不直接当作 B 的有效安装。检查插件附带 MCP/Skills、hooks、市场 URL 与依赖。
7. 项目实体：用户明确希望“继续原项目”时，迁仓库文件、未提交文件、项目 .claude、CLAUDE.md、.mcp.json、git worktree关联。不要只 clone 远端而丢掉未提交文件。沿用追加策略，B 同名不同文件隔离；`.git`/worktree 采用新目录导出或 clone+独立未提交补丁，不能混合两个 `.git`。大依赖 node_modules/venv 重新安装；项目外引用必须列待办。

## 冲突与恢复

同路径同哈希跳过。同 UUID/同路径不同内容：B 文件保留，A 版本完整进入 conflicts，报告 UUID/路径，不自动改 UUID 制造“可继续”的假会话。一个 UUID 的标题/日志/子目录作为一个单元；主 JSONL冲突时整个来源附属单元也隔离。B 自有会话用文件哈希做迁移前后验证。

应用目录包含 apply-report.json、backups、conflicts、review；其中可能含提示正文/明文MCP密钥，应限制为当前用户可读，不提交GitHub。写入B前关闭所有写入者；小脚本无法锁住所有Claude进程，Agent必须协调。

回滚只按应用报告恢复本次备份配置、删除本次新增文件（删除前核对仍与应用后哈希一致）；后续用户修改过的文件不删除。原始 bundle 始终保留。禁止整目录回滚丢掉 B 后来的聊天。

## 完成说明

报告文件传输与应用、原UUID和标题、路径映射、Skills可发现、MCP连通、插件重建、账户重登、项目实体和桌面验证结果。文件级核验通过只能称“本地文件迁移通过”；真实 A/B OpenSSH 和桌面 Code 标签页测试未做时必须明确。
