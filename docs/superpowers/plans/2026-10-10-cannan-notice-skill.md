# 迦南通知 CLI 与 Skill 可移植交付 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将程序和通知 Skill 一起发布，使另一台 Mac 可用账号密码独立初始化，查询通知并下载、阅读附件。

**Architecture:** 仓库根目录包含 SKILL.md 和单份 CLI 源码。启动器以自身位置找到程序，在用户缓存中准备依赖；私有配置与下载数据保存在用户目录。已有分页和状态协议保持不变，附件模块负责原件及 PDF 副本，独立渲染模块负责扫描页图像。

**Tech Stack:** Python 3.10+、curl、unittest、pypdf、pypdfium2、Pillow、POSIX shell、Git、通用 Agent Skills。

**Spec:** [已批准设计](../specs/2026-10-10-cannan-notice-skill-design.md)

## Global Constraints

- Python 最低版本为 3.10；curl 为启动器前置依赖；不静默安装系统工具。
- 默认 profile 为 `~/.config/cannan-notice/profile.json`；默认下载为 `~/Documents/Cannan Notices/`。
- `--profile`、`--directory` 优先；默认缺失不自动读取旧 `.local/profile.json`。
- Skill 默认 `unread,unreplied` 并集；CLI 默认 `all`。
- 通告目录为 `notice-<ID>-<安全标题>/`；PDF 原件保留，复制到同级 `pdfs/`。
- PDF 副本为 `notice-<ID>-<安全标题>-<序号>.pdf`；每条通告的 PDF 从 1 编号。
- 相同生成路径覆盖，旧目录/附件保留；index.json 仅描述本次结果。
- profile、下载 JSON、附件、提取文本和渲染图像权限为 0600；新建私有目录为 0700。
- TLS 校验及附件主机限制保持开启；不把临时解析 IP、凭据、真实通知内容提交到 Git。
- 详情会更新阅读时间；程序不确认查阅、不提交回条，不自动重试详情请求。
- 不使用外部 OCR；实际查阅扫描页和图片依赖目标 Agent 的图像读取能力。
- 退出码保持 0 完整、2 错误、3 已保存但文本或处理范围不完整；渲染不需要学生配置。
- 真实登录必须从不存在的独立 profile 开始，使用 `is_delete_user_push_token=0`；旧 profile 不能代替验收。
- 发布目标为 `TianLanhe/cannan-notice-skill` 的 main，正常推送，禁止强制覆盖。

## Review Focus

1. 标题包含 Unicode、分隔符、控制字符或超长字节序列：路径仍在输出目录内，名字不超过 255 字节。（任务 1）
2. 图片在 PDF 前、前一个 PDF 失败或标题改变：副本编号正确，历史文件保留，JSON 不混入旧结果。（任务 1、2）
3. 无 profile、无提取依赖或损坏/加密 PDF：渲染无需登录，错误分类准确，不伪报下载或文本完整。（任务 2、3）
4. 安装路径有空格、工作目录不同、两次首次调用并发或缓存创建失败：独立运行且不复用半成品环境。（任务 4）
5. 未导入任何学生上下文的新安装：只用账号密码即可获得能读列表和附件的新配置。（任务 6）

## 文件结构与责任

| 文件 | 责任 |
| --- | --- |
| cannan_cli/paths.py（新） | 用户默认路径、安全标题及通告路径 |
| cannan_cli/attachments.py | 下载原件、PDF 副本及文本提取 |
| cannan_cli/cli.py | 参数、单条/批量处理、JSON 与退出码 |
| cannan_cli/rendering.py（新） | 本地 PDF 页码选择和串行渲染 |
| scripts/cannan、scripts/bootstrap.py（新） | 解释器选择、独立虚拟环境及 CLI 启动 |
| SKILL.md、agents/openai.yaml（新） | 通知工作流程与 Codex 元数据 |
| references/cli.md（新） | 详细 CLI 使用参考 |
| README.md、AGENTS.md、VERIFICATION.md | 使用入口、仓库维护约束、脱敏验收记录 |
| tests/test_paths.py、test_rendering.py、test_bootstrap.py（新） | 新模块行为测试；沿用并扩展现有测试 |

执行期间保持小模块边界，不另建重复 CLI，不增加未要求的回条写入、定时任务或历史学年子系统。

## Task 0: 保留基线与安装文档技能

**Files:** 跟踪现有 cannan.py、cannan_cli/、tests/、requirements.txt、README.md、VERIFICATION.md、profile.example.json、.gitignore；产品文件此步不改。

**Interfaces:** 输入为已有源码与本设计；输出为可比较的基线提交和安装完成的 create-agentsmd。

- [ ] **Step 1:** 检查确切基线文件，不包含 .local、.venv、HAR、真实 PDF、截图或账户数据。运行现有 `.venv/bin/python -m unittest discover -s tests -v`；以实际通过数记录基线，不复用历史计数。
- [ ] **Step 2:** 只 git add 上述源码路径并提交 `chore: preserve existing Cannan CLI baseline`，保存提交号供最终审查。
- [ ] **Step 3:** 使用 skill-installer helper，以可用 Python 3.10+ 安装 `--repo github/awesome-copilot --path skills/create-agentsmd` 到 Codex 技能目录；若目标已有，先检查并复用符合请求的技能，不覆盖未知文件。
- [ ] **Step 4:** 读取安装后的 create-agentsmd/SKILL.md，核对入口存在及来源；尚不编写 AGENTS，不安装通知 Skill。

## Task 1: 默认路径、安全标题和 PDF 副本

**Files:** Create cannan_cli/paths.py、tests/test_paths.py；Modify cannan_cli/attachments.py、tests/test_attachments.py。

**Interfaces:**
- Produces `default_profile() -> Path`、`default_directory() -> Path`，调用时读取用户 home 并返回展开路径。
- Produces `safe_title(value: object, max_bytes: int = 180) -> str`、`notice_basename(detail: dict) -> str`、`notice_folder(detail: dict, directory: Path) -> Path`。
- Preserves `collect_attachments(transport, detail: dict, directory: Path) -> list[dict]`；PDF 结果新增 collection_path，不改变 local_path/text_path 语义。

- [ ] **Step 1:** 添加失败测试。核心断言：`notice_basename({'notice_id': 123, 'title': '家长会通知'}) == 'notice-123-家长会通知'`；空标题使用未命名通告；穿越字符不会产生额外路径层；长 CJK 标题的目录/副本名字均不超过 255 UTF-8 字节。Mock home 验证精确默认路径。
- [ ] **Step 2:** 添加混合附件与失败测试：JPEG、PDF、PDF 的两个副本必须是 `...-1.pdf`、`...-2.pdf`，字节与原件一致、权限 0600；已知 PDF 失败预留序号；副本写入失败进入错误；第二次相同同步不增加文件；标题改变保留旧目录。运行 `.venv/bin/python -m unittest discover -s tests -p 'test_paths.py' -v` 和对应 attachment 测试，确认新断言因未实现行为失败。
- [ ] **Step 3:** 实现路径模块及附件改动。路径模块采用 Unicode 规范化和字节预算；attachments 在有效 PDF 保存后复制至 pdfs/。`extract_pdf` 的 error 状态附脱敏错误，不与 dependency_missing 混淆；增加损坏 PDF 回归断言。PDF 类型未知且失败时仅记录错误，不猜测类型。
- [ ] **Step 4:** 运行 paths/attachments 测试，检查所有新行为通过，既有外部跳转和 TLS 相关测试仍有效。
- [ ] **Step 5:** 提交 `feat: name notice folders and collect PDF copies`，只加入该任务文件。

## Task 2: 默认配置切换与单条下载

**Files:** Modify cannan_cli/cli.py、tests/test_cli.py。

**Interfaces:**
- Consumes 任务 1 的 default_profile/default_directory/notice_folder 与 collect_attachments。
- Produces `process_notice(client, transport, notice_id: int, directory: Path) -> dict`，返回 detail、attachments、extracted_text、text_status、sync_status、errors、complete、text_complete；ClientError/TransportError 可由调用方按既有策略捕获。
- Produces `completion_code(result: dict) -> int`，错误为 2，无错但范围/文本不完整为 3，否则为 0；sync 与 download 共用。
- CLI 新增 `download NOTICE_ID [--directory DIR] [--output FILE]`；默认 JSON 为 notice_folder/notice.json。

- [ ] **Step 1:** 添加失败测试：默认 profile 缺失但 ROOT/.local/profile.json 存在时不读取旧文件；显式 --profile 保持可用；默认 CLI 状态仍 all。单条下载只调用目标详情一次，拒绝不在当前学生列表的 ID；默认 notice.json 存在且不覆盖已有 index.json。
- [ ] **Step 2:** 增加两种结果测试：文本 PDF 下载返回 0 且 collection_path 存在；扫描 PDF/图片保留原件并返回 3；副本失败/损坏 PDF 返回 2，消息不误报依赖缺失。验证 sync 的 index 只含本次结果，旧文件不删除。运行 `.venv/bin/python -m unittest discover -s tests -p 'test_cli.py' -v`，确认新行为失败。
- [ ] **Step 3:** 切换 parser/main 的隐式路径和帮助文本；抽取单条处理逻辑供 sync/download 共用，保留分页及合并字段、--limit 语义和 stderr 进度。写 JSON 仍使用原子私有文件写入；--profile/网络参数在命令前后均保持可用。
- [ ] **Step 4:** 运行 CLI 测试和完整离线套件，通过后核对 `cannan.py --help`、`download --help` 的命令参数与默认路径。
- [ ] **Step 5:** 提交 `feat: support standalone notice downloads and user defaults`。

## Task 3: 本地 PDF 渲染与页面阅读材料

**Files:** Create cannan_cli/rendering.py、tests/test_rendering.py；Modify cannan_cli/cli.py、requirements.txt、tests/test_cli.py。

**Interfaces:**
- Produces `select_pages(raw: str | None, total: int) -> list[int]`，输出去重且按页码递增的 1-based 页码。
- Produces `render_pdf(path: Path, directory: Path | None = None, pages: str | None = None) -> dict`，输出 source、total_pages、rendered_pages、images（page/local_path）、errors、complete。
- CLI 新增 `render LOCAL_PDF [--pages 1,3-5] [--directory DIR]`；不构造 CurlTransport，不读取学生 profile。成功 0、错误/部分生成 2。

- [ ] **Step 1:** 添加失败测试。核心断言：`select_pages('1,3-5,3', 5) == [1,3,4,5]`；省略选择全部页；0、倒置区间、越界和非法字符报 ClientError。无 profile 且阻止网络构造时 render 仍可执行。
- [ ] **Step 2:** 使用合成两页 PDF，断言页面数、PNG 能解码且非空、文件名/权限正确、范围只生成选定页；损坏/加密 PDF 返回脱敏错误；默认渲染目录处理长文件名。运行相关测试确认缺失行为失败，再按官方支持信息选择运行依赖版本范围并安装到现有隔离 .venv。
- [ ] **Step 3:** 用 pypdfium2/Pillow 实现串行渲染。默认目标分辨率为 144 DPI；每页上限 2000 万像素，极端页面按比例缩小并在 JSON 记录实际 scale。明确关闭页面、位图和文档资源，使用私有原子写入；逐页错误保留已生成文件并报告 complete=false。
- [ ] **Step 4:** 运行 rendering/CLI 测试；实际打开合成扫描页 PNG，检查文字可辨认、页序正确。完整离线测试通过后记录实际依赖版本。
- [ ] **Step 5:** 提交 `feat: render local PDFs for attachment reading`。

## Task 4: 可移植启动器与自动独立环境

**Files:** Create scripts/cannan、scripts/bootstrap.py、tests/test_bootstrap.py。

**Interfaces:**
- scripts/cannan 接收与 cannan.py 相同参数，选择 Python 后调用 bootstrap，最终透传 stdout/stderr 与退出码。
- Produces `cache_directory() -> Path`、`prepare_environment(root: Path, cache_root: Path, python_executable: str) -> Path`，返回缓存 venv 的 Python 路径。
- CANNAN_PYTHON 明确指定解释器；CANNAN_CACHE_DIR 明确指定缓存根目录；默认按平台使用设计中的用户缓存目录。

- [ ] **Step 1:** 添加失败测试：不支持的 Python/缺少 curl 报清楚错误；用户指定解释器不被悄悄忽略；从含空格的安装路径和不同 cwd 调用仍找到本包 cannan.py。用临时 HOME/缓存验证系统路径未被写入。
- [ ] **Step 2:** 添加行为测试：同一依赖清单二次调用不重新安装；清单变化使用正确的新环境；安装失败不得留下可复用的完成环境；两个并发首次调用只完成一次安装，二者均获得可用解释器。依赖安装过程使用合成的本地探针/可控 subprocess，测试不依赖外部网络。
- [ ] **Step 3:** 运行 `.venv/bin/python -m unittest discover -s tests -p 'test_bootstrap.py' -v` 确认新行为失败。
- [ ] **Step 4:** 实现 launcher 与 bootstrap。缓存键包含解释器及 requirements 摘要，使用文件锁保护环境准备，完成标记只在安装和依赖导入检查成功后写入。日志到 stderr，执行 CLI 使用参数数组/exec，路径含空格无需调用方额外修补；脚本设置可执行权限。
- [ ] **Step 5:** 测试通过后用临时 CANNAN_CACHE_DIR 从仓库外实际运行 `scripts/cannan --help`、`list --help`、`render --help`，再次执行验证缓存复用；提交 `feat: bootstrap an isolated portable CLI runtime`。

## Task 5: 编写 Skill 与职责清晰的文档

**Files:** Create SKILL.md、agents/openai.yaml、references/cli.md、AGENTS.md；Modify README.md、.gitignore、profile.example.json（仅有必要时）。

**Interfaces:** Consumes 前四步实际命令和输出；Produces 可安装且引用完整的 Skill 包、用户入口与维护约束。

- [ ] **Step 1:** 使用 skill-creator 写根 SKILL.md 和 Codex 元数据。description 精确匹配学校通知；写默认状态、只查列表不读取详情、单条/批量下载、退出码 3 后视觉阅读、页面覆盖和不自动回复。references/cli.md 是详细参数/JSON 说明唯一入口，不复制整套手册到 SKILL。
- [ ] **Step 2:** 使用 create-readme 编写 README，示例使用 scripts/cannan 和合成占位值，涵盖 Mac 前置依赖、完整包安装、终端首次登录、旧 profile 显式迁移和目录树。其他 Agent 安装使用自己的 skills 目录；Codex 说明完整仓库安装到 `$CODEX_HOME/skills/cannan-notice`（默认 ~/.codex/skills）。不依赖这台电脑的 .venv 或 .local。
- [ ] **Step 3:** 按已安装 create-agentsmd 写 AGENTS：源码职责、离线验证命令、协议/私有数据不变量、真实接口验收的范围和 README/AGENTS/SKILL 边界。只写实际可执行命令；不添加无关服务器、npm、发布 CI 或普遍委派要求。
- [ ] **Step 4:** 更新 .gitignore 排除私有配置和实际下载目录等已知本地输出，保留安全 profile.example.json 可跟踪。用 skill-creator 的 quick_validate.py 验证 Skill；逐条执行帮助与 README 快速示例中不需私密输入的命令，检查所有相对引用可解析。
- [ ] **Step 5:** 仅暂存本任务列出的公开文件；使用 `git checkout-index --all --prefix="${task_install_dir}/"` 在新建的临时目录导出完整暂存包（task_install_dir 为本次临时安装目录），包含本任务文件且排除全部未跟踪私有数据。在源码之外运行启动器，演练文本 PDF、扫描页渲染、图片读取流程。全部通过后提交 `docs: package the Cannan notice skill and usage guides`。

## Task 6: 全新登录、安装验收、独立审查与推送

**Files:** Modify VERIFICATION.md；需要修复时只修改发现问题对应的源码/测试。真实验收资料仅位于忽略的私有目录。

**Interfaces:** Consumes 已完成公开包；Produces 脱敏验收记录、安装的通知 Skill 和远端 main。

- [ ] **Step 1:** 在源码外组装已提交公开包，以临时缓存启动。创建不存在的独立 profile 路径并记录“初始不存在”；通过用户自己在终端隐藏输入账号密码，或已有明确授权且只在内存处理的凭据来源执行 login。凭据不写入临时脚本、argv、日志或设计文档。
- [ ] **Step 2:** 仅使用新 profile，依次执行完整分页 list、已取得列表内 detail、单条 download、unread/unreplied 并集 sync。检查 PDF 原件和副本字节、中文路径、权限、完整性与退出码；只保存脱敏结果计数。网络临时覆盖单独提供，不从旧 profile 导入学生上下文。如果独立登录失败，修复并重验或明确报告阻碍，不能标为通过。
- [ ] **Step 3:** 跑完整离线套件、Skill validator、shell 语法检查、git diff --check。更新 VERIFICATION.md：记录真实 login 结论、运行依赖版本、隔离安装验证、图片/扫描页实际演练及目标另一台 Mac 尚未亲测的限制。删除旧“无 Git/不推送/未验证 login”等已过时裁定，但不把未验证事项改写成成功。
- [ ] **Step 4:** 使用所选执行技能规定的最终独立审查，范围为基线至当前提交的公开源码与设计/计划；不向审查者提供凭据或真实内容。对重要问题修复并运行对应回归检查，再提交验收记录。
- [ ] **Step 5:** 审核确切 tracked 文件清单与已知私有身份/凭据、附件 URL 的泄露；检查 .local、.venv、HAR、真实附件未被跟踪。重新读取指定远端 refs，配置 origin 为 `git@github.com:TianLanhe/cannan-notice-skill.git`，正常推送 main；远端有新提交时先检查并整合，禁止 force。
- [ ] **Step 6:** 确认远端提交等于本地 main。使用 skill-installer helper 从 `TianLanhe/cannan-notice-skill --path . --name cannan-notice` 安装完整根目录 Skill 到 Codex 技能目录；默认公开下载方式，失败时按工具支持回退。安装后的文件再执行 --help 和读取配置的命令，核对来源及源码完整；已有目标目录时先核对，不能覆盖未知技能。
- [ ] **Step 7:** 报告仓库链接、安装位置、另一台 Mac 最短使用流程、实际测试结论和必要限制；说明技能在下一轮可用。只清理任务临时验证环境，不删除用户旧配置/下载，也不启动或接管模拟器。

## 计划自审与执行方式

设计覆盖映射：协议与状态保留→任务 0/2；默认路径→1/2；命名/PDF 副本→1；单条下载→2；扫描页→3；自动环境→4；Skill/文档职责→5；真实登录/安装/推送→6。Review Focus 五项均有对应测试或实测步骤。

默认采用用户先前选择的“在本聊天实现”：主代理按 executing-plans 逐项实施，最终按该技能要求进行一次独立审查。此计划不自动使用每任务实现/审查子代理，也不另开用户聊天。

本计划已由用户确认并在本聊天执行完成。任务 0–6 的全新登录、接口、离线回归、独立审查、远端推送与安装后验收均完成；具体证据及两个延后轻微问题见 VERIFICATION.md。
