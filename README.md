# 迦南通知 · Cannan Notice

查询自己账号对应学生的迦南幼稚园通知、详情和附件。CLI 支持未查阅、未回复、全部与多状态并集；随附的通用 Agent Skill 支持阅读文本 PDF、扫描件和图片。日常查询无需手机、抓包代理或模拟器。

[安装与登录](#安装与首次登录) · [常用命令](#常用命令) · [附件与输出](#附件与输出) · [完整参数](references/cli.md) · [实测记录](VERIFICATION.md)

## 安装与首次登录

需要 macOS、Python 3.10+、curl 和 Git。启动器自动选择符合版本要求的 Python；缺少时会给出指引。若使用 Homebrew，可通过 `brew install python` 安装 Python。

将完整仓库安装为 Codex Skill：

```sh
git clone https://github.com/TianLanhe/cannan-notice-skill.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/cannan-notice"
cd "${CODEX_HOME:-$HOME/.codex}/skills/cannan-notice"
sh scripts/cannan login
```

第一次运行会在 `~/Library/Caches/cannan-notice/` 建立独立虚拟环境并安装依赖；之后复用。账号在终端输入，密码隐藏输入且不保存。多个学生时，用 `--student-index N` 明确选择，从 1 开始。不要把密码发送到聊天或写入命令历史。

下一轮 Codex 对话即可使用 `$cannan-notice`。其他支持 Agent Skills 的工具使用自己的 skills 目录，同样保留完整仓库。只使用 CLI 时，可克隆到普通目录。

默认私有配置为 `~/.config/cannan-notice/profile.json`，下载结果为 `~/Documents/Cannan Notices/`，均独立于源码。`--profile`、`--directory` 可以覆盖路径。旧 `.local/profile.json` 不会被自动读取：可显式指定 `--profile`，或自行迁移到新默认位置并保持文件权限 `0600`。自己的 HAR 也可通过 `import-profile` 导入，见 [参数参考](references/cli.md#import-profile)。

## 常用命令

以下命令在仓库根目录执行；其他目录用启动器绝对路径。

```sh
sh scripts/cannan list --status unread
sh scripts/cannan list --status unreplied
sh scripts/cannan list --status all
sh scripts/cannan list --status unread,unreplied

# NOTICE_ID 换成列表返回的真实 ID
sh scripts/cannan detail NOTICE_ID
sh scripts/cannan download NOTICE_ID
sh scripts/cannan sync --status unread,unreplied
sh scripts/cannan render "/absolute/path/to/notice.pdf"
```

CLI 默认状态是 `all`；Skill 在用户没有指定范围时显式查询 `unread,unreplied` 并集。自然语言示例：`使用 $cannan-notice 帮我查阅迦南通知，并完整查看附件。` 只查询列表不会顺带读取详情。附件视觉阅读需要 Agent 的图像读取能力，程序不接入外部 OCR 服务。

> [!NOTE]
> `detail`、`download`、`sync` 会更新服务端阅读时间，但不会确认查阅或提交回条。“未查阅”按 App 的状态参数查询，不按阅读时间是否为空推断。

七个命令及全部参数见 [CLI 参考](references/cli.md)。

## 附件与输出

```text
Cannan Notices/
├── index.json
├── notice-123-家长会通知/
│   ├── notice.json           # download 默认保存；sync 不生成此文件
│   ├── attachment-1.pdf
│   └── attachment-1.txt
└── pdfs/
    └── notice-123-家长会通知-1.pdf
```

通知目录和 PDF 副本保留中文标题，替换非法路径字符并限制长度；JSON 保留完整标题。原件保留在通知目录，每条通知的 PDF 从 1 编号，图片不占 PDF 序号。`pdfs/` 中是可独立移动和分享的副本。

相同路径重跑会覆盖；标题变化或附件减少不会自动删除旧文件。以本次 JSON 的附件路径判断本次范围。文件使用 `0600` 权限，新建的数据目录使用 `0700`。

`complete` 表示请求范围处理完整且无错误，`text_complete` 单独表示自动文本提取完整。扫描页为 `needs_ocr`，混合 PDF 为 `partial`，图片为 `not_pdf`；可通过 `render` 和 Agent 视觉继续阅读。退出码 `0` 为完整成功，`2` 为错误，`3` 为结果已保存但范围或文本不完整，**不等于下载失败**。`--limit` 也可能导致退出码 3，应查看保存的 JSON。

当前查询范围是登录返回学生的当前学年，未宣称覆盖历史所有学年。学校修改接口后可能需要调整客户端。默认验证 TLS；临时解析、可信代理及响应大小等配置见 [网络参数](references/cli.md#公共网络与配置参数)，不要关闭证书校验。

## 文档与维护

- [SKILL.md](SKILL.md)：Agent 查询与阅读流程。
- [references/cli.md](references/cli.md)：完整命令、参数和结果字段。
- [AGENTS.md](AGENTS.md)：修改代码时的维护规则与验证命令。
- [VERIFICATION.md](VERIFICATION.md)：已验证的范围与限制。

私有 profile、HAR、账号信息、真实通知和附件不进入仓库。`profile.example.json` 只有空值占位，不能代替登录。
