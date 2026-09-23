param(
    [Parameter(Mandatory = $true)][ValidateSet('Snapshot', 'Upload')][string]$Mode,
    [string]$ClassCode,
    [string[]]$Files,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$CatalogPath = Join-Path $Repo 'references/2026年普通高等学校本科专业目录.md'
$MapPath = Join-Path $Repo 'references/feishu-folder-map-2026.json'
$RootToken = 'FE7ofFTbwlTthEdwo1mcdrcknRc'
$ProfileName = 'GEGZI'
$ExpectedOpenId = 'ou_96b49f9068b07cda299a45291051b7c5'
$Domain = 'https://gezhiedu.feishu.cn'
$Kinds = @('PPT内容稿', '逐字讲解稿', '资料来源与核验表')

function Get-CatalogDigest {
    # Git stores this UTF-8 Markdown with LF; Windows may check it out with CRLF.
    $raw = [System.IO.File]::ReadAllBytes($CatalogPath)
    $normalized = [System.Collections.Generic.List[byte]]::new($raw.Length)
    for ($i = 0; $i -lt $raw.Length; $i++) {
        if ($raw[$i] -eq 13 -and $i + 1 -lt $raw.Length -and $raw[$i + 1] -eq 10) { continue }
        $normalized.Add($raw[$i])
    }
    $hash = [System.Security.Cryptography.SHA256]::HashData($normalized.ToArray())
    return [Convert]::ToHexString($hash).ToLowerInvariant()
}

function Invoke-Lark {
    param([string[]]$Arguments, [switch]$NoFormat)
    $argv = @($Arguments) + @('--profile', $ProfileName, '--as', 'user')
    if (-not $NoFormat) { $argv += @('--format', 'json') }
    $output = & lark-cli @argv
    if ($LASTEXITCODE -ne 0) {
        throw "飞书 CLI 命令失败（退出码 $LASTEXITCODE）：$($Arguments -join ' ')；详情：$(($output -join "`n"))"
    }
    try { $result = ($output -join "`n") | ConvertFrom-Json -Depth 100 }
    catch { throw '飞书 CLI 未返回有效 JSON' }
    if (-not $NoFormat -and ($result.ok -ne $true -or $result.identity -ne 'user')) {
        throw "飞书 CLI 返回未成功或身份不符：$($Arguments -join ' ')；详情：$(($result | ConvertTo-Json -Depth 8 -Compress))"
    }
    return $result
}

function Assert-Identity {
    $who = Invoke-Lark -Arguments @('whoami') -NoFormat
    if ($who.profile -ne $ProfileName -or $who.identity -ne 'user' -or $who.onBehalfOf.openId -ne $ExpectedOpenId) {
        throw '飞书当前账号不是已确认的 GEGZI / 用户147236，停止操作'
    }
}

function Get-Children {
    param([string]$Token)
    $items = [System.Collections.Generic.List[object]]::new()
    $pageToken = ''
    $seen = [System.Collections.Generic.HashSet[string]]::new()
    do {
        if (-not $seen.Add($pageToken)) { throw "文件夹 $Token 分页循环" }
        $params = @{ folder_token = $Token; page_size = 200 }
        if ($pageToken) { $params.page_token = $pageToken }
        $response = Invoke-Lark -Arguments @('drive', 'files', 'list', '--params', ($params | ConvertTo-Json -Compress))
        foreach ($item in @($response.data.files)) { if ($null -ne $item) { $items.Add($item) } }
        if (-not $response.data.has_more) { break }
        $pageToken = [string]$response.data.next_page_token
        if (-not $pageToken) { throw "文件夹 $Token 有下一页但缺少 page token" }
    } while ($true)
    return $items.ToArray()
}

function Find-Folder {
    param([object[]]$Items, [string]$Name, [string]$ParentToken)
    $matches = @($Items | Where-Object {
        $_.name -ceq $Name -and $_.type -eq 'folder' -and $_.parent_token -eq $ParentToken
    })
    if ($matches.Count -ne 1) { throw "父目录 $ParentToken 下的「$Name」匹配到 $($matches.Count) 个文件夹" }
    return $matches[0]
}

function Read-Catalog {
    $categories = [System.Collections.Generic.List[object]]::new()
    $current = $null
    foreach ($line in [System.IO.File]::ReadAllLines($CatalogPath, [System.Text.Encoding]::UTF8)) {
        if ($line -match '^## (\d{2}) (.+)$') {
            $current = [pscustomobject]@{ code = $Matches[1]; name = $Matches[2]; classes = [System.Collections.Generic.List[object]]::new() }
            $categories.Add($current)
        } elseif ($line -match '^### (\d{4}) (.+)$') {
            if ($null -eq $current -or -not $Matches[1].StartsWith($current.code)) { throw "目录层级错误：$line" }
            $current.classes.Add([pscustomobject]@{ code = $Matches[1]; name = $Matches[2] })
        }
    }
    $count = 0
    foreach ($category in $categories) { $count += $category.classes.Count }
    if ($categories.Count -ne 13 -or $count -ne 92) { throw '2026 年目录应有 13 个门类、92 个专业类' }
    return $categories.ToArray()
}

function New-Snapshot {
    Assert-Identity
    $catalog = @(Read-Catalog)
    $rootItems = @(Get-Children -Token $RootToken)
    $categories = [System.Collections.Generic.List[object]]::new()
    foreach ($category in $catalog) {
        $categoryFolder = Find-Folder -Items $rootItems -Name "$($category.code) $($category.name)" -ParentToken $RootToken
        $classItems = @(Get-Children -Token $categoryFolder.token)
        $classes = [System.Collections.Generic.List[object]]::new()
        foreach ($majorClass in $category.classes) {
            $classFolder = Find-Folder -Items $classItems -Name "$($majorClass.code) $($majorClass.name)" -ParentToken $categoryFolder.token
            $childItems = @(Get-Children -Token $classFolder.token)
            $content = Find-Folder -Items $childItems -Name '内容稿' -ParentToken $classFolder.token
            $ppt = Find-Folder -Items $childItems -Name '成品PPT' -ParentToken $classFolder.token
            $classes.Add([pscustomobject]@{
                code = $majorClass.code; name = $majorClass.name; token = $classFolder.token; url = $classFolder.url
                content = [pscustomobject]@{ token = $content.token; url = $content.url }
                ppt = [pscustomobject]@{ token = $ppt.token; url = $ppt.url }
            })
        }
        $categories.Add([pscustomobject]@{
            code = $category.code; name = $category.name; token = $categoryFolder.token; url = $categoryFolder.url
            classes = $classes.ToArray()
        })
    }
    $result = [pscustomobject]@{
        catalog_year = 2026
        catalog_sha256 = Get-CatalogDigest
        profile = $ProfileName
        expected_user_open_id = $ExpectedOpenId
        root = [pscustomobject]@{ name = '专业库资料制作过程文件夹'; token = $RootToken; url = "$Domain/drive/folder/$RootToken" }
        categories = $categories.ToArray()
    }
    $json = $result | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($MapPath, $json + "`n", [System.Text.UTF8Encoding]::new($false))
    return [pscustomobject]@{ ok = $true; categories = $categories.Count; classes = 92; map = $MapPath }
}

function Send-CourseFiles {
    if ($ClassCode -notmatch '^\d{4}$') { throw '须提供四位专业类代码，例如 0807' }
    if (-not $Files -or $Files.Count -gt 3) { throw '须提供 1 至 3 份稿件' }
    $catalog = @(Read-Catalog)
    $folderMap = Get-Content -LiteralPath $MapPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    $digest = Get-CatalogDigest
    if ($folderMap.catalog_sha256 -ne $digest -or $folderMap.root.token -ne $RootToken -or
        $folderMap.profile -ne $ProfileName -or $folderMap.expected_user_open_id -ne $ExpectedOpenId) {
        throw '目录 Markdown 与飞书映射不一致，须重新核对目录快照'
    }
    $category = $null; $majorClass = $null
    foreach ($entry in $catalog) {
        foreach ($item in $entry.classes) {
            if ($item.code -eq $ClassCode) { $category = $entry; $majorClass = $item; break }
        }
        if ($majorClass) { break }
    }
    if (-not $majorClass) { throw "2026 年目录中没有专业类代码 $ClassCode" }
    $mapCategory = @($folderMap.categories | Where-Object { $_.code -eq $category.code })
    if ($mapCategory.Count -ne 1) { throw '飞书映射缺少所属门类或存在重复' }
    $mapped = @($mapCategory[0].classes | Where-Object { $_.code -eq $ClassCode })
    if ($mapped.Count -ne 1 -or $mapped[0].name -cne $majorClass.name) { throw '飞书映射中的专业类缺失或名称不符' }

    $sources = @($Files | ForEach-Object { Get-Item -LiteralPath $_ -ErrorAction Stop })
    if (@($sources | Select-Object -ExpandProperty FullName -Unique).Count -ne $sources.Count) { throw '稿件路径不能重复' }
    if (@($sources | Select-Object -ExpandProperty DirectoryName -Unique).Count -ne 1) { throw '三份稿件须在同一本地目录' }
    $allowed = @($Kinds | ForEach-Object { "$($majorClass.name)-$_.md" })
    foreach ($source in $sources) {
        if (-not $source.PSIsContainer -and $source.Name -cin $allowed -and $source.Length -gt 0) { continue }
        throw "文件不是该专业类的非空课程稿件：$($source.FullName)"
    }

    Assert-Identity
    $categoryFolder = Find-Folder -Items @(Get-Children -Token $RootToken) -Name "$($category.code) $($category.name)" -ParentToken $RootToken
    if ($categoryFolder.token -ne $mapCategory[0].token) { throw '门类目录与快照不符' }
    $classFolder = Find-Folder -Items @(Get-Children -Token $categoryFolder.token) -Name "$ClassCode $($majorClass.name)" -ParentToken $categoryFolder.token
    if ($classFolder.token -ne $mapped[0].token) { throw '专业类目录与快照不符' }
    $contentFolder = Find-Folder -Items @(Get-Children -Token $classFolder.token) -Name '内容稿' -ParentToken $classFolder.token
    if ($contentFolder.token -ne $mapped[0].content.token) { throw '内容稿目录与快照不符' }

    $remote = @(Get-Children -Token $contentFolder.token)
    $pattern = '^' + [Regex]::Escape($majorClass.name) + '-(?:PPT内容稿|逐字讲解稿|资料来源与核验表)-V([1-9]\d*)\.0\.md$'
    $numbers = [System.Collections.Generic.List[int]]::new()
    foreach ($item in $remote) { if ($item.name -cmatch $pattern) { $numbers.Add([int]$Matches[1]) } }
    foreach ($item in Get-ChildItem -LiteralPath $sources[0].DirectoryName -File) {
        if ($item.Name -cmatch $pattern) { $numbers.Add([int]$Matches[1]) }
    }
    $next = 1
    if ($numbers.Count) { $next = ($numbers | Measure-Object -Maximum).Maximum + 1 }
    $version = "V$next.0"
    $planned = @($sources | ForEach-Object {
        [pscustomobject]@{ source = $_.FullName; name = "$($_.BaseName)-$version.md"; bytes = $_.Length }
    })
    $result = [pscustomobject]@{
        ok = $true; dry_run = [bool]$DryRun; class = "$ClassCode $($majorClass.name)"; version = $version
        folder_url = $contentFolder.url; files = $planned
    }
    if ($DryRun) { return $result }

    foreach ($item in $planned) {
        $destination = Join-Path $sources[0].DirectoryName $item.name
        if ((Test-Path -LiteralPath $destination) -or @($remote | Where-Object { $_.name -ceq $item.name }).Count) {
            throw "本地或飞书已有同名版本文件：$($item.name)"
        }
    }
    foreach ($item in $planned) {
        $destination = Join-Path $sources[0].DirectoryName $item.name
        Copy-Item -LiteralPath $item.source -Destination $destination -ErrorAction Stop
        $item | Add-Member -NotePropertyName local_versioned -NotePropertyValue $destination
    }

    $uploaded = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($item in $planned) {
            if (@(Get-Children -Token $contentFolder.token | Where-Object { $_.name -ceq $item.name }).Count) {
                throw "云端已出现同名文件：$($item.name)"
            }
            Push-Location -LiteralPath $sources[0].DirectoryName
            try {
                $response = Invoke-Lark -Arguments @('markdown', '+create', '--folder-token', $contentFolder.token, '--file', "./$($item.name)")
            } finally { Pop-Location }
            $data = $response.data
            if (-not $data.file_token -or $data.file_name -cne $item.name -or [long]$data.size_bytes -ne [long]$item.bytes) {
                throw "上传返回的文件名、token 或字节数不符：$($item.name)"
            }
            $found = @(Get-Children -Token $contentFolder.token | Where-Object {
                $_.name -ceq $item.name -and $_.token -eq $data.file_token -and $_.type -eq 'file' -and $_.parent_token -eq $contentFolder.token
            })
            if ($found.Count -ne 1) { throw "上传后未找到唯一文件：$($item.name)" }
            $uploaded.Add([pscustomobject]@{
                source = $item.source; local_versioned = $item.local_versioned; name = $item.name
                bytes = $item.bytes; token = $data.file_token; url = $found[0].url
            })
        }
    } catch {
        throw "上传或核验部分失败：$($_.Exception.Message)；已确认上传：$(($uploaded.ToArray() | ConvertTo-Json -Depth 5 -Compress))"
    }
    $result.files = $uploaded.ToArray()
    return $result
}

try {
    $result = if ($Mode -eq 'Snapshot') { New-Snapshot } else { Send-CourseFiles }
    $result | ConvertTo-Json -Depth 12
} catch {
    [Console]::Error.WriteLine((@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress -Depth 5))
    exit 1
}
