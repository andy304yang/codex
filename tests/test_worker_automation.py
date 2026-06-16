import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "hermes-worker-qxun" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from hermes_worker_lib import (  # noqa: E402
    content_type_for,
    list_dist_files,
    parse_mapping,
    render_codex_task_prompt,
    resolve_project_context,
)
from init_worker import normalize_worker_id  # noqa: E402


class WorkerAutomationTests(unittest.TestCase):
    def test_normalize_worker_id_uses_feishu_nickname(self):
        self.assertEqual(normalize_worker_id(" Andy "), "andy")

    def test_parse_mapping_requires_name_value_pairs(self):
        self.assertEqual(parse_mapping(["qxun=pnpm build", "docs=make html"]), {
            "qxun": "pnpm build",
            "docs": "make html",
        })

        with self.assertRaises(SystemExit):
            parse_mapping(["broken"])

    def test_resolve_project_context_uses_task_project_and_build_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "QXunPortal"
            project.mkdir()
            config = {
                "local_projects": {"qxun": str(project)},
                "project_builds": {
                    "qxun": {
                        "build_command": "pnpm build",
                        "dist_dir": "web_dist",
                    }
                },
            }
            task = {"id": "task-1", "project": "qxun", "title": "加按钮"}

            context = resolve_project_context(task, config)

            self.assertEqual(context.project_key, "qxun")
            self.assertEqual(context.project_path, project)
            self.assertEqual(context.build_command, "pnpm build")
            self.assertEqual(context.dist_dir, "web_dist")

    def test_resolve_project_context_falls_back_to_single_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "OnlyProject"
            project.mkdir()
            config = {"local_projects": {"only": str(project)}}
            task = {"id": "task-2", "title": "修复样式"}

            context = resolve_project_context(task, config)

            self.assertEqual(context.project_key, "only")
            self.assertEqual(context.project_path, project)
            self.assertEqual(context.build_command, "npm run build")
            self.assertEqual(context.dist_dir, "dist")

    def test_list_dist_files_is_relative_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "assets").mkdir()
            (dist / "index.html").write_text("<html></html>", encoding="utf-8")
            (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
            (dist / "assets" / "style.css").write_text("body{}", encoding="utf-8")

            files = list_dist_files(dist)

            self.assertEqual([item.relative_path for item in files], [
                "assets/app.js",
                "assets/style.css",
                "index.html",
            ])

    def test_content_types_cover_static_preview_assets(self):
        self.assertEqual(content_type_for("index.html"), "text/html; charset=utf-8")
        self.assertEqual(content_type_for("assets/app.js"), "application/javascript")
        self.assertEqual(content_type_for("assets/style.css"), "text/css; charset=utf-8")
        self.assertEqual(content_type_for("assets/logo.svg"), "image/svg+xml")

    def test_render_codex_task_prompt_contains_task_and_followup_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            task = {"id": "task-3", "project": "qxun", "text": "加一个官网按钮"}
            config = {"worker_id": "jerry", "server_api": "http://example.test"}
            context = resolve_project_context(task, {
                "local_projects": {"qxun": str(project)},
                "project_builds": {"qxun": {"build_command": "pnpm build", "dist_dir": "dist"}},
            })

            prompt = render_codex_task_prompt(task, config, context, SCRIPTS)

            self.assertIn("task-3", prompt)
            self.assertIn("加一个官网按钮", prompt)
            self.assertIn("build_preview.py", prompt)
            self.assertIn("upload_preview.py", prompt)
            self.assertIn(json.dumps(task, ensure_ascii=False, indent=2), prompt)


if __name__ == "__main__":
    unittest.main()
