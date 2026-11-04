# bnbu-portal-mcp

**中文** · [English](#english)

让 AI 助手（Claude、Cursor、Codex 等）直接读取你在 **北师香港浸会大学（BNBU）iSpace** 上的课程、课件和作业。提供 MCP 服务器和命令行两种用法，Windows、macOS、Linux 都能用。

> 非官方项目，与 BNBU 无关。只会访问你自己的 iSpace 账号能看到的内容。

## 功能

- **课程**：列出你已选的所有课程
- **课件**：查看每门课的内容和文件，并下载到本地
- **作业**：列出作业，查看提交状态
- **截止日期**：按时间从近到远列出即将到期的作业
- **MIS**：查看课表、成绩和 GPA（只读）
- **请假（Leave Application）**：查看你的请假记录和审批进度，以及请假表单需要填哪些项（只读，不能代你提交）
- **公告和文字信息**：读取老师发的公告、课程页面文字（考试时间、考试范围等）、通知和消息，并可按关键词搜索（默认搜“考试/期中/期末/exam/quiz”等）
- **新通知提醒**：只显示你还没看过的新通知（`portal-mcp new-notices`）；`portal-mcp watch` 会定时检查并弹出桌面通知（Windows / macOS / Linux），可加 `--deadlines 24`（小时） 提醒临近的截止日期。已读记录只保存在本机配置目录
- **教学评估（MIS）**：查看待评估的课程（只读；没有开放时就是空列表）
- **提交作业**（默认关闭，设置 `ISPACE_ALLOW_WRITE=1` 开启）：上传文件并提交。开启后也只会先预演，必须明确确认才会真正提交
- **填写教学评估**（默认关闭）：开启后默认只预演，会列出课程和将提交的答案（每题选最高档，评语默认留空），必须明确确认才会提交

## 安装

把下面这段话发给你的 AI agent，让它帮你装好：

> 请帮我安装 https://github.com/genshinkleenahida/bnbu-portal-mcp ，按我的系统选合适的方式安装，把它配置成我所用 AI 客户端的 MCP 服务器，然后让我运行 `portal-mcp login` 输入自己的 iSpace 账号和密码，最后用 `portal-mcp upcoming-deadlines` 验证能正常使用。

## 注意

- 本工具不会替你写作业或答题，请遵守学校的学术诚信规定。
- 密码只保存在你本机的系统钥匙串里（Windows 凭据管理器 / macOS 钥匙串 / Linux Secret Service），也可用环境变量 `ISPACE_USERNAME` / `ISPACE_PASSWORD` 代替；不会被打印或上传到别处。
- 命令行：每个工具都是同名命令（下划线换成连字符），输出 JSON，例如 `portal-mcp search-text`。

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
- **MIS**: class timetable, grades and GPA (read-only)
- **Leave Application**: your leave requests with approval status, and the fields of the leave form (read-only; it never submits one for you)
- **Announcements & course text**: read teachers' announcements, course page text (exam dates, scope, etc.), notifications and messages; search by keyword (defaults to exam / midterm / final / quiz and similar)
- **New-notice reminders**: show only notices you haven't seen (`portal-mcp new-notices`); `portal-mcp watch` polls and pops up a desktop notification (Windows / macOS / Linux), and `--deadlines 24` (hours) also reminds you of upcoming due dates. The seen-list is kept only in your local config folder
- **Teaching evaluation (MIS)**: lists the courses waiting to be evaluated (read-only; an empty list just means none is listed right now)
- **Submitting** (off by default): upload and submit files; even when enabled it only dry-runs until you explicitly confirm
- **Filling in evaluations** (off by default): when enabled it only dry-runs, showing the courses and the answers it would send (highest option for every question, comment left empty), until you explicitly confirm

### Install

Give this to your AI agent:

> Please install https://github.com/genshinkleenahida/bnbu-portal-mcp using the right method for my OS, register it as an MCP server in the AI client I use, have me run `portal-mcp login` to enter my own iSpace username and password, then verify it works with `portal-mcp upcoming-deadlines`.

### Notes

- It will not do your homework for you; follow your school's academic integrity rules.
- Your password stays in your OS keychain (Windows Credential Manager / macOS Keychain / Linux Secret Service); the `ISPACE_USERNAME` / `ISPACE_PASSWORD` environment variables work instead (e.g. headless Linux). It is never printed or sent anywhere else.
- CLI: every tool is a command of the same name (underscores become hyphens) that prints JSON, e.g. `portal-mcp search-text`.

### License

MIT
