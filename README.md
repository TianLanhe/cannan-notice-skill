# 迦南通告 Python CLI

读取自己账号对应学生的通告列表、详情和附件。支持未查阅、未回复、全部，以及多状态并集查询。列表逐页获取并校验完整性；PDF 附件保留原件，并提取文本层。

## 本机直接使用

本目录已有 `.venv` 和私有 `.local/profile.json`。进入此目录后运行：

```bash
.venv/bin/python cannan.py list --status unread
.venv/bin/python cannan.py list --status unreplied
.venv/bin/python cannan.py list --status all --output .local/all.json
.venv/bin/python cannan.py list --status unread,unreplied --output .local/pending.json
```

重复参数同样有效：

```bash
.venv/bin/python cannan.py list --status unread --status unreplied
```

多个状态分别查询和分页，结果按 `notice_id` 合并去重；`matched_statuses` 保留匹配的状态，`by_status` 提供各状态统计。默认 `all`。同时指定 `all,unread` 也不会重复输出通告。

详情和批量同步：

```bash
# 将 NOTICE_ID 换成 list 返回的真实 notice_id
.venv/bin/python cannan.py detail NOTICE_ID --output .local/detail.json

# 获取未查阅或未回复的详情、附件、PDF 文本
.venv/bin/python cannan.py sync --status unread,unreplied --directory .local/pending

# 全部通告；不加 --limit 才处理完整集合
.venv/bin/python cannan.py sync --status all --directory .local/all

# 仅处理第一条，用于验证；limited=true、complete=false
.venv/bin/python cannan.py sync --status all --limit 1 --directory .local/sample
```

`detail` 先核验 ID 属于本学生列表。`sync` 不自动回复或确认回条；调用详情接口会更新 `read_date_time`。**App“未查阅”状态不是“阅读时间为空”**：按 App 实际参数 `has_reply_slip=0,is_confirmed=0` 查询，详情读取不会调用确认接口。

## 在其他环境安装

需要 Python 3.10+ 和 curl。macOS 的系统 `python3` 可能仍是 3.9，创建虚拟环境时使用满足版本要求的 Python：

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python cannan.py login
```

`login` 交互输入账号、密码，密码不会显示或保存；也支持 `--account` 与环境变量 `CANNAN_PASSWORD`。不要把密码写入脚本或命令历史。登录请求使用 `is_delete_user_push_token=0`，避免复制抓包中清理手机推送 token 的设置。独立 login 流程和这个参数的服务器行为尚未实测；本机已导入的 profile 已用于真实列表、详情与附件读取。多学生使用 `--student-index 1`（索引从 1 开始）；未明确选择时不保存配置。

已有自己账号的 HAR 时，可无需密码导入：

```bash
.venv/bin/python cannan.py import-profile --har /absolute/path/to/own-capture.har
```

导入只读取登录响应的学生上下文或已有列表参数，不保存抓包中的密码。配置默认位于本目录 `.local/profile.json`，文件权限 0600。`profile.example.json` 使用空值占位，不含身份数据。

## 网络配置

默认直接联网并验证 TLS。可以在 profile 的 `network` 中配置 `proxy`、`ca_bundle`、`resolve`、`timeout`、`max_bytes`、`allowed_hosts`，或用命令参数覆盖：

```bash
.venv/bin/python cannan.py list --status all --proxy http://127.0.0.1:9090 --ca-bundle /path/to/proxyman-ca.pem
# 仅用于你已核实的临时地址；REPLACE_WITH_VERIFIED_IP 不是有效默认值
.venv/bin/python cannan.py list --resolve apps.cannan.edu.hk=REPLACE_WITH_VERIFIED_IP
```

本机 DNS 曾返回导致证书错误的地址；本机私有配置暂时使用已核验的域名解析地址，TLS 主机名和证书链仍校验。源码及示例没有写死 CDN IP。临时解析地址未来可能失效，应更新私有配置、使用显式可信代理或修正本机 DNS；**不要关闭证书校验**。

附件默认仅允许 `apps.cannan.edu.hk` 的 HTTPS（443）。如实际详情返回其他附件主机，先核验再加入 `network.allowed_hosts`，列表和详情服务地址仍固定。跳转最多 3 次，外部主机不会被静默访问。单次响应默认最大 20 MiB、超时 25 秒。

## 输出与完整性

- `list`：`requested_statuses`、`by_status`、`notices`、`errors`、`complete`。页码异常、重复页或唯一数与 `total` 不符时失败，避免把第一页当成完整结果。
- `sync`：在列表字段上增加 `detail`、`attachments`、`extracted_text`、`text_status`、`sync_status`，汇总有 `processed`、`list_complete`、`limited`、`text_complete`。
- `complete` 表示请求范围已全部处理且无失败；`text_complete` 单独反映正文提取是否完整。扫描 PDF 标记 `needs_ocr`；混合文字页与无文本页的 PDF 标记 `partial`，`pages_without_text` 列出无文本页（从 1 开始），已有文本仍保存。空白页也会保守标记为待检查；保留原件，本版本不调用 OCR。图片附件保留原文件并标为 `not_pdf`；没有正文或附件的条目标记 `no_body`。
- JSON 默认写入 `目录/index.json`，附件写入 `notice-ID/attachment-N.pdf`，文本写入同名 `.txt`；全部使用 0600 权限。附件标题不会被当成文件路径。
- `list/detail` 不带 `--output` 时向 stdout 输出 JSON；进度只写 stderr。完整成功退出码 0，输入/请求失败或部分同步失败为 2。同步结果已保存但范围或文本不完整时为 3（扫描页、图片、没有正文或主动 `--limit`）；自动化程序可处理保存的 JSON 后决定是否继续。`--limit` 会设置 `limited=true,complete=false`。
- 详情请求有阅读时间副作用，不自动重试。失败保留在 JSON 的 `errors`，可决定是否重跑。

当前只核验了登录响应的学生当前学年，不宣称覆盖历史所有学年。接口行为来自原版 App 的抓包及实请求，学校后续修改接口时可能需要调整客户端。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

离线测试使用合成数据与合成 PDF。真实抓包、账号上下文和下载结果在 `.local/` 或外层 `work/`，不会进入源文件与示例；分享程序时排除 `.local/`、`.venv/` 和 HAR。

本机实测及未验证边界见 [核验记录](VERIFICATION.md)。
