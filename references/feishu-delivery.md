# 飞书云盘交付规则

本文件只管**模式 B 的专业类课程**（主技能称“专业大类”，如“电子信息类”）生成后的保存位置。研究、页面结构、写稿和事实核验继续按主技能原规则执行。普通咨询不生成文件；单个本科专业课程暂时只保存本地，不上传。

## 归档依据和位置

- [2026 年普通高等学校本科专业目录](2026年普通高等学校本科专业目录.md)按 `## 门类`、`### 专业类`、专业表格组织，只用于核对归档所需的门类和专业类代码、名称。专业内容研究仍需按主技能核验最新资料。
- [飞书目录快照](feishu-folder-map-2026.json)收录已核验的 13 个门类、92 个专业类及每个专业类下的“内容稿”“成品PPT”文件夹 token 和 URL。它是定位提示；真正上传前须重新读取飞书目录核对层级、名称与 token，不能只信静态快照。
- 快照中的 `catalog_sha256` 按目录文件的 Git 标准 LF 换行计算；校验器会先把 Windows 检出的 CRLF 转成 LF 再计算。因此同一目录在不同操作系统上的校验结果一致。目录内容变更后仍须重新生成快照或核对后更新指纹。
- 三份 Markdown 的目标统一是：`专业库资料制作过程文件夹 / <2 位代码> <门类名> / <4 位代码> <专业类名> / 内容稿`。例如电子信息类进入 `08 工学 / 0807 电子信息类 / 内容稿`。“成品PPT”用于以后保存 PPT 成品，本技能的三份 Markdown 不放那里，也不放在专业类根层。
- 飞书目标账号是格知教育的 `用户147236`（open ID `ou_96b49f9068b07cda299a45291051b7c5`）。本机 CLI 使用 `GEGZI` profile 和 `--as user`；其他环境需核对连接器当前账号属于同一用户。无法核对身份或目标目录不唯一时停止，不改用旧账号、bot 或其他目录。

## 每个环境都必须执行的保存流程

1. 从目录 Markdown 找到主题的专业类名称、四位代码及所属两位门类代码。不得只凭名称猜目录。该流程对全部 92 个专业类使用相同规则。
2. 在目录映射 JSON 中用门类代码和专业类代码找到**唯一**条目，并核对名称。读取该专业类的 `content.token` 和 `content.url`。每个专业类使用自己的 token；不复制其他专业类的目标。
3. 用已经授权的飞书能力按 `content.token` **列出目标文件夹已有文件**，从该专业类的 `V1.0`、`V2.0` 等文件取最高主版本号加一。新稿的三份文件使用同一版本，文件名严格为`<专业类名>-PPT内容稿-Vn.0.md`、`<专业类名>-逐字讲解稿-Vn.0.md`、`<专业类名>-资料来源与核验表-Vn.0.md`，无空格变体。未标版本的旧文件不占用 `V1.0`。
4. 上传时向飞书接口或连接器**传入精确的 `content.token` 作为父文件夹**。上传后重新列出该目标文件夹或读取每份文件的元数据，逐一核对文件名、类型、token 和 `parent_token == content.token`。只拿到“上传成功”消息或文件链接不足以确认归档正确。
5. 返回三份文件各自的飞书链接及目标`内容稿`文件夹链接。若无法访问映射、授权身份不符、上传接口无法指定父文件夹、核验失败或只有部分成功，说明实际结果，不得声称飞书交付完成；保留已有文件，不覆盖或盲目重传。

这套流程适用于所有 agent 和运行环境。任何 agent 都应使用当前环境已授权的飞书工具完成身份核对、列目录、上传和核验；不要求特定厂商的连接器。工具缺少必需的账号、目标文件夹或文件元数据时，停止保存并说明缺口。任何历史目录或默认目录都不能替代映射中的 `content.token`。

## 跨环境路由校验器

[`scripts/feishu_route_guard.py`](../scripts/feishu_route_guard.py)只使用 Python 标准库，不访问飞书、不自动上传；它从随技能附带的目录和映射计算目标，并检查 agent 提供的**实时飞书工具返回值**。若环境支持 Python，按以下顺序运行：

1. `python scripts/feishu_route_guard.py resolve --class-name <专业类名称或四位代码>`：校验整份目录与映射，返回该专业类唯一的目标 `folder_token`。
2. 用当前飞书账号读取身份，以及根目录、门类目录、专业类目录、`内容稿`目录四次完整清单。把工具实际返回的文件条目按下面格式保存为 `route-proof.json`；`has_more` 为 `true` 时继续翻页，直到完整。不得凭记忆编造证明数据。
3. `python scripts/feishu_route_guard.py plan --class-name <专业类名称或四位代码> --proof route-proof.json --files <原稿1.md> <原稿2.md> <原稿3.md> --out delivery-plan.json`：核对账号、实时目录层级、版本和原稿文件名，生成同版本的本地副本及交付计划。失败则停止，不能上传。
4. 用飞书工具逐份上传计划中的 `local_versioned` 文件，明确指定计划中的 `folder_token` 作为父文件夹。每上传一份，将该次工具返回的文件名和 token 保存为 `upload-result.json`，再次读取目标 `内容稿` 的完整清单并保存为 `after-list.json`。运行 `python scripts/feishu_route_guard.py verify --plan delivery-plan.json --results upload-result.json --after after-list.json --name <本次文件名>`。只有返回 `ok: true` 才上传下一份；失败立即停止，逐份报告状态。

`route-proof.json` 的结构如下。每个 `files` 数组保留飞书工具返回的 `name`、`type`、`token`、`parent_token`、`url`；`parent_token` 是**本次列出的文件夹** token，`identity_open_id` 来自当前登录账号的身份查询：

```json
{
  "identity_open_id": "<当前飞书用户 open ID>",
  "listings": {
    "root": {"parent_token": "<专业库根目录 token>", "has_more": false, "files": []},
    "category": {"parent_token": "<本专业类所属门类 token>", "has_more": false, "files": []},
    "class": {"parent_token": "<本专业类 token>", "has_more": false, "files": []},
    "content": {"parent_token": "<本专业类内容稿 token>", "has_more": false, "files": []}
  }
}
```

这里的空数组只是字段示意；正式执行必须填入完整实时清单。`upload-result.json` 格式为 `{"files":[{"name":"<计划中的文件名>","token":"<上传返回的文件 token>"}]}`；`after-list.json` 使用单个目录清单对象的格式。无法取得这些证据时，停止上传并向用户报告具体缺失项。没有 Python 的环境也必须执行前述同等的逐步校验与失败即停止规则。

## 本机 PowerShell 脚本

先完成原有三份本地 `.md` 的内容检查。仅在本机具备 `lark-cli` 和已授权账号时，从技能仓库目录调用 [`scripts/feishu_delivery.ps1`](../scripts/feishu_delivery.ps1)。以电子信息类为例，把 `$draftDir` 替换为实际稿件目录的绝对路径；其他专业类须从目录 Markdown 取其自己的四位代码及原始文件：

```powershell
$draftDir = '<稿件目录的绝对路径>'
$files = @(
  (Join-Path $draftDir '电子信息类-PPT内容稿.md'),
  (Join-Path $draftDir '电子信息类-逐字讲解稿.md'),
  (Join-Path $draftDir '电子信息类-资料来源与核验表.md')
)
& .\scripts\feishu_delivery.ps1 -Mode Upload -ClassCode 0807 -Files $files -DryRun
& .\scripts\feishu_delivery.ps1 -Mode Upload -ClassCode 0807 -Files $files
```

脚本接受 1 至 3 份用户实际要求的文件，文件名必须与官方专业类名称和交付类型一致。执行前它会读取目录 Markdown、快照、当前飞书账号及四层实时目录；缺层、重名、代码不符、快照过期或权限问题都停止。`-DryRun` 只读取和规划，不创建本地版本副本或上传。

正式执行时，脚本从目标“内容稿”和本地输出目录已有的 `Vn.0` 文件中取最高主版本号加 1，默认三份共用同一版本。未标版本的历史稿不占用 `V1.0`；例如旧文件 `电子信息类-PPT内容稿.md` 保留，新稿从 `电子信息类-PPT内容稿-V1.0.md` 开始。脚本在本地创建带版本号的副本，用 `lark-cli markdown +create` 上传原生 Markdown，不覆盖或删除旧稿。

每份文件创建后，脚本核对 CLI 返回的文件名、字节数、token，并重新读取目标“内容稿”目录验证文件的名称、类型、token 和父目录。若部分上传失败，保留本地文件和已经成功的云端文件，报告实际结果；不要盲目重复上传。结束时向用户提供本地文件路径、版本号、飞书文件链接和“内容稿”文件夹链接。没有实际上传成功时，不能声称云端交付完成。

飞书目录调整后，可在确认新结构确属同一目标账号后执行 `& .\scripts\feishu_delivery.ps1 -Mode Snapshot` 重新生成目录快照；该模式只读取飞书并更新仓库中的 JSON 文件，不创建或移动飞书资源。
