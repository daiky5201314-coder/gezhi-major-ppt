#!/usr/bin/env python3
"""Fail-closed route and upload verifier for Feishu professional-class drafts.

Uses only Python's standard library. It never calls Feishu or uploads files;
the calling AI must provide fresh tool responses as JSON evidence.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "references" / "2026年普通高等学校本科专业目录.md"
MAPPING = REPO / "references" / "feishu-folder-map-2026.json"
KINDS = ("PPT内容稿", "逐字讲解稿", "资料来源与核验表")


def fail(message):
    raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def catalog_digest(data):
    """Hash the Git LF representation, independent of checkout line endings."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def catalog_entries():
    entries = {}
    category = None
    categories = set()
    for line in CATALOG.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"## (\d{2}) (.+)", line)
        if match:
            category = match.groups()
            categories.add(category[0])
            continue
        match = re.fullmatch(r"### (\d{4}) (.+)", line)
        if match:
            code, name = match.groups()
            if category is None or not code.startswith(category[0]) or code in entries:
                fail(f"目录中的专业类层级或代码异常：{line}")
            entries[code] = (category[0], category[1], name)
    if len(categories) != 13 or len(entries) != 92:
        fail("2026 年目录的门类或专业类数量异常")
    return entries


def route(value):
    mapping = read_json(MAPPING)
    digest = catalog_digest(CATALOG.read_bytes())
    if mapping.get("catalog_sha256") != digest or mapping.get("catalog_year") != 2026:
        fail("目录与飞书映射不一致；停止上传并更新映射")
    entries = catalog_entries()
    matches = [code for code, (_, _, name) in entries.items() if value in (code, name)]
    if len(matches) != 1:
        fail(f"专业类名称或四位代码不能唯一定位：{value}")
    code = matches[0]
    cat_code, cat_name, class_name = entries[code]
    categories = mapping.get("categories", [])
    if len(categories) != 13 or sum(len(c.get("classes", [])) for c in categories) != 92:
        fail("飞书映射不是完整的 13 门类、92 专业类")
    seen_codes = set()
    seen_content_tokens = set()
    for mapped_category in categories:
        for mapped_class in mapped_category.get("classes", []):
            mapped_code = mapped_class.get("code")
            expected = entries.get(mapped_code)
            content_token = mapped_class.get("content", {}).get("token")
            content_url = mapped_class.get("content", {}).get("url")
            if (expected is None or expected != (mapped_category.get("code"), mapped_category.get("name"),
                                                 mapped_class.get("name"))
                    or mapped_code in seen_codes or not content_token or content_token in seen_content_tokens
                    or content_url != f"https://gezhiedu.feishu.cn/drive/folder/{content_token}"):
                fail(f"飞书映射中的专业类代码、名称或内容稿 token 异常：{mapped_code}")
            seen_codes.add(mapped_code)
            seen_content_tokens.add(content_token)
    if seen_codes != set(entries):
        fail("飞书映射未完整覆盖 2026 年全部专业类")
    selected_categories = [c for c in categories if c.get("code") == cat_code]
    if len(selected_categories) != 1 or selected_categories[0].get("name") != cat_name:
        fail("门类映射缺失或名称不符")
    category = selected_categories[0]
    selected_classes = [c for c in category["classes"] if c.get("code") == code]
    if len(selected_classes) != 1 or selected_classes[0].get("name") != class_name:
        fail("专业类映射缺失或名称不符")
    major_class = selected_classes[0]
    content = major_class.get("content", {})
    if not all([mapping.get("expected_user_open_id"), mapping.get("root", {}).get("token"),
                category.get("token"), major_class.get("token"), content.get("token"), content.get("url")]):
        fail("映射缺少账号或目录 token")
    return {
        "class_code": code, "class_name": class_name,
        "category_code": cat_code, "category_name": cat_name,
        "expected_user_open_id": mapping["expected_user_open_id"],
        "root": mapping["root"], "category": category,
        "major_class": major_class, "content": content,
    }


def one_folder(listing, parent, name, token):
    if listing.get("parent_token") != parent or listing.get("has_more") is not False:
        fail(f"{name}的实时目录清单不完整或父目录不符")
    hits = [item for item in listing.get("files", [])
            if item.get("name") == name and item.get("type") == "folder"
            and item.get("parent_token") == parent]
    if len(hits) != 1 or hits[0].get("token") != token:
        fail(f"实时目录中的{name}不存在、重复或 token 与映射不符")


def check_proof(proof, found):
    if proof.get("identity_open_id") != found["expected_user_open_id"]:
        fail("当前飞书账号与映射中的用户不符")
    lists = proof.get("listings", {})
    root, category, major_class, content = (lists.get(k, {}) for k in ("root", "category", "class", "content"))
    one_folder(root, found["root"]["token"],
               f'{found["category_code"]} {found["category_name"]}', found["category"]["token"])
    one_folder(category, found["category"]["token"],
               f'{found["class_code"]} {found["class_name"]}', found["major_class"]["token"])
    one_folder(major_class, found["major_class"]["token"], "内容稿", found["content"]["token"])
    if content.get("parent_token") != found["content"]["token"] or content.get("has_more") is not False:
        fail("内容稿目录清单不完整或目标 token 不符")
    files = content.get("files", [])
    if not isinstance(files, list) or any(item.get("parent_token") != found["content"]["token"] for item in files):
        fail("内容稿目录清单含有其他父目录的文件")
    return files


def make_plan(args):
    found = route(args.class_name)
    before = check_proof(read_json(args.proof), found)
    sources = [Path(value).resolve(strict=True) for value in args.files]
    if not 1 <= len(sources) <= 3 or len({str(p) for p in sources}) != len(sources):
        fail("必须提供 1 至 3 份不同的稿件")
    if len({str(p.parent) for p in sources}) != 1:
        fail("稿件必须位于同一本地目录")
    allowed = {f'{found["class_name"]}-{kind}.md' for kind in KINDS}
    if any(not p.is_file() or p.name not in allowed or p.stat().st_size == 0 for p in sources):
        fail("稿件名称必须与专业类和交付类型精确一致，且内容非空")
    pattern = re.compile(rf'^{re.escape(found["class_name"])}-(?:PPT内容稿|逐字讲解稿|资料来源与核验表)-V([1-9]\d*)\.0\.md$')
    numbers = [int(m.group(1)) for item in before if (m := pattern.fullmatch(item.get("name", "")))]
    numbers += [int(m.group(1)) for p in sources[0].parent.iterdir() if (m := pattern.fullmatch(p.name))]
    version = f'V{max(numbers, default=0) + 1}.0'
    planned = []
    for source in sources:
        name = f'{source.stem}-{version}.md'
        destination = source.with_name(name)
        if destination.exists() or any(item.get("name") == name for item in before):
            fail(f"同名版本已存在：{name}")
        planned.append({"source": str(source), "local_versioned": str(destination), "name": name,
                        "size_bytes": source.stat().st_size})
    plan = {"class_code": found["class_code"], "class_name": found["class_name"],
            "version": version, "folder_token": found["content"]["token"],
            "folder_url": found["content"]["url"], "before_tokens": [x.get("token") for x in before],
            "files": planned}
    output = Path(args.out).resolve()
    if output.exists():
        fail(f"计划文件已存在：{output}")
    created = []
    plan_created = False
    try:
        for item in planned:
            with open(item["source"], "rb") as src, open(item["local_versioned"], "xb") as dst:
                created.append(Path(item["local_versioned"]))
                shutil.copyfileobj(src, dst)
        with open(output, "x", encoding="utf-8") as handle:
            plan_created = True
            json.dump(plan, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except Exception:
        if plan_created:
            output.unlink(missing_ok=True)
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return {"ok": True, "plan": str(output), "folder_token": plan["folder_token"],
            "folder_url": plan["folder_url"], "version": version, "files": planned}


def verify(args):
    plan = read_json(args.plan)
    found = route(plan.get("class_code", ""))
    if plan.get("folder_token") != found["content"]["token"] or plan.get("class_name") != found["class_name"]:
        fail("计划中的专业类或目标文件夹与当前映射不符")
    version = plan.get("version", "")
    planned = plan.get("files", [])
    allowed_names = {f'{found["class_name"]}-{kind}-{version}.md' for kind in KINDS}
    if (not re.fullmatch(r"V[1-9]\d*\.0", version) or not isinstance(planned, list)
            or not 1 <= len(planned) <= 3 or len({item.get("name") for item in planned}) != len(planned)
            or any(item.get("name") not in allowed_names for item in planned)):
        fail("计划中的版本或稿件名称不符合本专业类交付规则")
    after = read_json(args.after)
    if after.get("parent_token") != plan["folder_token"] or after.get("has_more") is not False:
        fail("上传后的内容稿目录清单不完整或父目录不符")
    results = read_json(args.results).get("files", [])
    if not isinstance(results, list):
        fail("上传工具结果格式不正确")
    requested = [item for item in planned if not args.name or item["name"] == args.name]
    if not requested:
        fail("计划中没有指定的文件")
    confirmed = []
    for item in requested:
        matches = [x for x in results if x.get("name") == item["name"]]
        if len(matches) != 1 or not matches[0].get("token"):
            fail(f'上传工具未返回唯一文件 token：{item["name"]}；已核验：{confirmed}')
        token = matches[0]["token"]
        if token in plan.get("before_tokens", []):
            fail(f'返回的是上传前已有文件：{item["name"]}')
        hits = [x for x in after.get("files", []) if x.get("name") == item["name"]
                and x.get("token") == token and x.get("type") == "file"
                and x.get("parent_token") == plan["folder_token"]]
        if len(hits) != 1 or not hits[0].get("url", "").startswith("https://gezhiedu.feishu.cn/"):
            fail(f'文件不在目标内容稿目录中：{item["name"]}；已核验：{confirmed}')
        confirmed.append({"name": item["name"], "token": token, "url": hits[0].get("url")})
    return {"ok": True, "folder_url": plan["folder_url"], "confirmed": confirmed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    resolve_parser = sub.add_parser("resolve", help="Check catalog and map; return target folder")
    resolve_parser.add_argument("--class-name", required=True)
    plan_parser = sub.add_parser("plan", help="Check live route proof and make versioned local copies")
    plan_parser.add_argument("--class-name", required=True)
    plan_parser.add_argument("--proof", required=True)
    plan_parser.add_argument("--files", nargs="+", required=True)
    plan_parser.add_argument("--out", required=True)
    verify_parser = sub.add_parser("verify", help="Check tool result against a fresh target-folder listing")
    verify_parser.add_argument("--plan", required=True)
    verify_parser.add_argument("--after", required=True)
    verify_parser.add_argument("--results", required=True)
    verify_parser.add_argument("--name", help="Verify one file immediately after uploading it")
    args = parser.parse_args()
    try:
        if args.mode == "resolve":
            found = route(args.class_name)
            result = {"ok": True, "class_code": found["class_code"],
                      "class_name": found["class_name"], "category_code": found["category_code"],
                      "category_name": found["category_name"], "folder_token": found["content"]["token"],
                      "folder_url": found["content"]["url"],
                      "expected_user_open_id": found["expected_user_open_id"]}
        elif args.mode == "plan":
            result = make_plan(args)
        else:
            result = verify(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
