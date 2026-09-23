import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import feishu_route_guard as guard


class RouteGuardTests(unittest.TestCase):
    def test_every_catalog_class_has_unique_target(self):
        mapping = guard.read_json(guard.MAPPING)
        routes = [guard.route(item["code"]) for category in mapping["categories"] for item in category["classes"]]
        self.assertEqual(len(routes), 92)
        self.assertEqual(len({item["content"]["token"] for item in routes}), 92)

    def test_wrong_folder_stops_before_copy_and_wrong_upload_fails_verification(self):
        found = guard.route("1201")
        root = found["root"]["token"]
        category = found["category"]["token"]
        major_class = found["major_class"]["token"]
        content = found["content"]["token"]

        def listing(parent, files):
            return {"parent_token": parent, "has_more": False, "files": files}

        def folder(name, token, parent):
            return {"name": name, "token": token, "parent_token": parent, "type": "folder"}

        proof = {"identity_open_id": found["expected_user_open_id"], "listings": {
            "root": listing(root, [folder("12 管理学", category, root)]),
            "category": listing(category, [folder("1201 管理科学与工程类", major_class, category)]),
            "class": listing(major_class, [folder("内容稿", content, major_class)]),
            "content": listing(content, []),
        }}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "管理科学与工程类-PPT内容稿.md"
            source.write_text("# 测试内容\n", encoding="utf-8")
            proof_path = directory / "proof.json"
            proof_path.write_text(json.dumps(proof, ensure_ascii=False), encoding="utf-8")
            plan_path = directory / "plan.json"
            args = SimpleNamespace(class_name="1201", proof=str(proof_path), files=[str(source)], out=str(plan_path))

            proof["identity_open_id"] = "wrong-user"
            proof_path.write_text(json.dumps(proof, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                guard.make_plan(args)
            self.assertFalse(plan_path.exists())
            proof["identity_open_id"] = found["expected_user_open_id"]

            proof["listings"]["content"]["has_more"] = True
            proof_path.write_text(json.dumps(proof, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                guard.make_plan(args)
            proof["listings"]["content"]["has_more"] = False

            proof["listings"]["class"]["files"][0]["token"] = "wrong-folder"
            proof_path.write_text(json.dumps(proof, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                guard.make_plan(args)
            self.assertFalse(plan_path.exists())
            self.assertEqual(list(directory.glob("*-V*.md")), [])

            proof["listings"]["class"]["files"][0]["token"] = content
            proof_path.write_text(json.dumps(proof, ensure_ascii=False), encoding="utf-8")
            guard.make_plan(args)
            plan = guard.read_json(plan_path)
            self.assertEqual(plan["version"], "V1.0")
            self.assertTrue(Path(plan["files"][0]["local_versioned"]).exists())

            name = plan["files"][0]["name"]
            results_path = directory / "results.json"
            results_path.write_text(json.dumps({"files": [{"name": name, "token": "uploaded-token"}]}), encoding="utf-8")
            after_path = directory / "after.json"
            after_path.write_text(json.dumps(listing(content, [
                {"name": name, "token": "uploaded-token", "type": "file", "parent_token": "wrong-folder"}
            ])), encoding="utf-8")
            verify_args = SimpleNamespace(plan=str(plan_path), after=str(after_path), results=str(results_path), name=name)
            with self.assertRaises(ValueError):
                guard.verify(verify_args)

            after_path.write_text(json.dumps(listing(content, [
                {"name": name, "token": "uploaded-token", "type": "file", "parent_token": content,
                 "url": "https://gezhiedu.feishu.cn/file/uploaded-token"}
            ])), encoding="utf-8")
            self.assertTrue(guard.verify(verify_args)["ok"])


if __name__ == "__main__":
    unittest.main()
