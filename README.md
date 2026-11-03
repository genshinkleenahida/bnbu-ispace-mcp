# bnbu-ispace-mcp

**中文** · [English](#english)

让 AI 助手（Claude、Cursor、Codex 等）直接读取你在 **北师香港浸会大学（BNBU）iSpace** 上的课程、课件和作业。提供 MCP 服务器和命令行两种用法，Windows、macOS、Linux 都能用。

> 非官方项目，与 BNBU 无关。只会访问你自己的 iSpace 账号能看到的内容。

## 功能

- **课程**：列出你已选的所有课程
- **课件**：查看每门课的内容和文件，并下载到本地
- **作业**：列出作业，查看提交状态
- **截止日期**：按时间从近到远列出即将到期的作业
- **提交作业**（默认关闭）：上传文件并提交。开启后也只会先预演，必须明确确认才会真正提交

## 安装

把下面这段话发给你的 AI agent，让它帮你装好：

> 请帮我安装 https://github.com/genshinkleenahida/bnbu-ispace-mcp ，按我的系统选合适的方式安装，把它配置成我所用 AI 客户端的 MCP 服务器，然后让我运行 `ispace-mcp login` 输入自己的 iSpace 账号和密码，最后用 `ispace-mcp deadlines` 验证能正常使用。

## 注意

- 本工具不会替你写作业或答题，请遵守学校的学术诚信规定。
- 密码只保存在你本机的系统钥匙串里，不会被打印或上传到别处。

## 许可证

MIT

---

## English

Lets AI assistants (Claude, Cursor, Codex, etc.) read your courses, materials and assignments on **BNBU iSpace**. Works as an MCP server or a CLI on Windows, macOS and Linux.

> Unofficial; not affiliated with BNBU. It only sees what your own iSpace account can see.

### Features

- **Courses**: list your enrolled courses
- **Materials**: browse each course's contents and download files
- **Assignments**: list assignments and check submission status
- **Deadlines**: upcoming due dates, soonest first
- **Submitting** (off by default): upload and submit files; even when enabled it only dry-runs until you explicitly confirm

### Install

Give this to your AI agent:

> Please install https://github.com/genshinkleenahida/bnbu-ispace-mcp using the right method for my OS, register it as an MCP server in the AI client I use, have me run `ispace-mcp login` to enter my own iSpace username and password, then verify it works with `ispace-mcp deadlines`.

### Notes

- It will not do your homework for you; follow your school's academic integrity rules.
- Your password stays in your OS keychain and is never printed or sent anywhere else.

### License

MIT
