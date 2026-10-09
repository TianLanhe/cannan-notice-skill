# CLI 命令参考

运行入口：`sh scripts/cannan COMMAND ...`，或在已有依赖环境中使用 `python cannan.py COMMAND ...`。在仓库外运行时使用启动器的绝对路径。启动器自动准备环境，CLI JSON 写 stdout，进度与环境准备日志写 stderr。

## 公共网络与配置参数

以下参数可在命令前或 login/import-profile/list/detail/download/sync 后使用。render 仅处理本地 PDF，不使用 profile 或网络设置。

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| --profile PATH | ~/.config/cannan-notice/profile.json | 私有学生上下文及网络配置；显式路径优先，不回退到旧 .local |
| --proxy URL | 无；也可来自 profile | 显式 HTTP/SOCKS 代理 |
| --ca-bundle PATH | 系统信任链 | 额外 CA PEM，保留 TLS 校验 |
| --resolve HOST=IP | 无；也可来自 profile | 临时指定域名解析；可重复，按 host 合并并覆盖配置 |
| --timeout SECONDS | 25 | 每次请求超时，必须为有效正数 |
| --max-bytes BYTES | 20971520（20 MiB） | 单次响应/附件大小上限，必须为正整数 |
| -h / --help | — | 显示当前命令帮助并退出 |

profile 的 network 可以包含 proxy、ca_bundle、resolve、timeout、max_bytes、allowed_hosts。命令中的标量覆盖配置；resolve 按主机合并。附件默认只允许 apps.cannan.edu.hk 的 HTTPS 443；确认其他主机来源后才加入 allowed_hosts。API 服务地址固定，附件重定向最多 3 次。不要关闭 TLS 校验或把本机临时 CDN IP 写入共享配置。

## login

`sh scripts/cannan login [--account ACCOUNT] [--student-index N] [--language CODE]`

| 参数 | 作用 |
| --- | --- |
| --account ACCOUNT | 账号；省略时在终端交互输入 |
| --student-index N | 选择登录返回的第 N 个学生，从 1 开始；多个学生时必须明确选择 |
| --language CODE | zh_HK（默认）、zh_CN、en_US |

密码使用终端隐藏输入，或从 CANNAN_PASSWORD 环境变量读取；不要把密码写入命令历史、脚本或聊天。POST signIn 使用 is_delete_user_push_token=0，取得学生上下文并保存 profile，不保存密码。初始化文件权限为 0600。账号错误、学生结构异常或未选择多个学生时，不覆盖配置。

## import-profile

`sh scripts/cannan import-profile --har /absolute/path/to/own.har [--student-index N]`

--har 为必填。只导入自己账号 HAR 中的登录响应学生上下文或列表查询上下文，不导入密码。多个可选学生使用 --student-index。真实 HAR 可能包含凭据和内容，应留在私有目录。

## list

`sh scripts/cannan list [--status STATUS] [--page-size N] [--output FILE]`

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| --status STATUS | all | unread、unreplied、all；可逗号分隔，也可重复参数 |
| --page-size N | 20 | 每页数量，1–1000；持续分页到末页，不限制总条数 |
| --output FILE | stdout | 将完整 JSON 保存到指定文件，stdout 改为保存路径摘要 |

多状态按并集查询并以 notice_id 去重，matched_statuses 保存匹配状态，by_status 保存各状态的统计。页码、重复项或唯一总数异常时失败，不把第一页当成完整列表。**Skill 默认会显式传 unread,unreplied，CLI 本身默认 all。**

状态映射来自 App：unread 为 has_reply_slip=0/is_confirmed=0，unreplied 为 1/0，all 两者为空；不是按 read_date_time 是否为空推断。

## detail

`sh scripts/cannan detail NOTICE_ID [--output FILE]`

NOTICE_ID 为当前学生列表里的正整数 ID。先核验归属，再读取详情；--output 可保存 JSON，省略时到 stdout。detail 只取得详情和附件元数据，不下载附件。返回 generated_at、reading_updates_timestamp=true 和 data。

## download

`sh scripts/cannan download NOTICE_ID [--directory DIR] [--output FILE]`

读取一条通知，下载全部附件、复制 PDF 并提取文本。--directory 默认为 ~/Documents/Cannan Notices/；--output 默认为该通知目录下的 notice.json，不覆盖批量 index.json。输出 detail、attachments、extracted_text、text_status、sync_status、errors、complete、text_complete，以及阅读时间副作用标记。

## sync

`sh scripts/cannan sync [--status STATUS] [--page-size N] [--directory DIR] [--output FILE] [--limit N]`

status/page-size 与 list 相同。directory 默认 ~/Documents/Cannan Notices/，output 默认该目录的 index.json。--limit 必须为正整数，只处理列表前 N 条；列表仍完整取得，未处理项保留 sync_status=not_processed。实际截断时 limited=true、complete=false、text_complete=false；N 大于或等于结果数时不算截断。

detail、download、sync 会更新服务端阅读时间，但不确认查阅或提交回条；详情请求不自动重试。

## render

`sh scripts/cannan render /absolute/path/to/file.pdf [--pages 1,3-5] [--directory DIR]`

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| LOCAL_PDF | 必填 | 本地 PDF；不读取 profile，不访问学校 API |
| --pages | 全部页 | 从 1 开始的页码、逗号及闭区间；去重并按页序输出，非法/越界报错 |
| --directory DIR | PDF 同级/<文件名>-pages/ | 页面 PNG 保存目录 |

默认目标为 144 DPI；单页最多 2000 万像素、单边最多 10000 像素，极端页面按比例缩小。JSON 包含 source、total_pages、rendered_pages、images（page、local_path、scale）、errors 和 complete。失败保留已经生成的页，complete=false；没有图像读取工具时，渲染成功不代表已经完成视觉阅读。

## 文件与结果状态

```text
目录/
├── index.json
├── notice-123-家长会通知/
│   ├── notice.json          # download 默认保存；sync 不生成此文件
│   ├── attachment-1.pdf
│   └── attachment-1.txt
└── pdfs/
    └── notice-123-家长会通知-1.pdf
```

标题保留中文，非法路径字符替换并按 UTF-8 字节限制长度；完整标题保留在 JSON。PDF 从 1 按每条通知编号，图片不占序号；已识别为 PDF 的失败项可能留下编号空位。相同路径重跑覆盖，标题变化或附件减少不会自动删除旧文件；以本次 JSON 引用判断本次范围。

attachments 保留 local_path、bytes、status，以及可用时的 text、pages、pages_without_text、text_path；PDF 新增 collection_path 指向独立副本。状态：ok 为所有页有文本层，partial 为部分页缺少文本，needs_ocr 为无文本层，not_pdf 为图片等非 PDF，dependency_missing 为缺提取依赖，error 为下载/复制/解析失败。needs_ocr 是待视觉阅读标记，程序不调用 OCR。

sync 继承 list 的 requested_statuses、by_status、notices、errors 等字段，增加 processed、list_complete、limited、text_complete；各条增加 detail、attachments、extracted_text、text_status、sync_status。无正文且无可提取文本的条目标记 no_body。

complete 表示请求范围处理完整且无错误；text_complete 表示自动文本提取完整。扫描件和图片可已下载完成但 text_complete=false。真正空白页也会保守标记，需要实际查看。

| 退出码 | 作用 |
| --- | --- |
| 0 | list/detail 请求成功，或 download/sync 范围与自动文本完整；render 所选页全部生成 |
| 2 | 输入、请求、文件处理或渲染失败；批量错误查看保存结果的 errors |
| 3 | download/sync 已保存但范围或文本不完整：扫描页、图片、无正文或实际 --limit 截断 |

## 环境变量

| 变量 | 作用 |
| --- | --- |
| CANNAN_PYTHON | 启动器明确使用的 Python 3.10+，错误时不会悄悄忽略 |
| CANNAN_CACHE_DIR | 覆盖缓存根目录；默认 macOS 为 ~/Library/Caches/cannan-notice/ |
| XDG_CACHE_HOME | 非 macOS 且未指定 CANNAN_CACHE_DIR 时的缓存基目录 |
| CANNAN_PASSWORD | login 的可选密码输入来源；不会保存 |

缓存按解释器和依赖清单区分；源码/Skill 更新不会删除用户配置或下载。旧 .local/profile.json 可用 --profile 显式指定，迁移时自行复制到新默认位置并保持 0600 权限。
