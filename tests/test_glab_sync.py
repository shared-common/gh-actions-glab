import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / ".github" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import glab_sync  # noqa: E402
from _common import GitLabClient  # noqa: E402
from branch_policy import BranchPolicy, BranchSpec  # noqa: E402


def make_policy() -> BranchPolicy:
    mirrors = (
        BranchSpec("GIT_BRANCH_MAIN", "main", "gitlab/mcr/main", True, True),
        BranchSpec("GIT_BRANCH_STAGING", "staging", "gitlab/mcr/staging", True, True),
    )
    snapshot = BranchSpec("GIT_BRANCH_SNAPSHOT", "snapshot", "mcr/snapshot", False, False)
    return BranchPolicy(prefix="mcr", mirror_prefix="gitlab", mirrors=mirrors, snapshot=snapshot)


class GlabSyncTests(unittest.TestCase):
    def test_load_targets_external_uses_group_prefix(self):
        values = {
            "GL_FORKS_EXT_JSON": '{"keepsecret":"https://invent.kde.org/utilities/keepsecret"}',
            "GL_GROUP_TOP_UPSTREAM": "top",
            "GL_GROUP_SUB_MAINLINE": "sub",
        }
        with mock.patch.object(glab_sync, "optional_secret", side_effect=lambda name: values.get(name, "")):
            with mock.patch.object(glab_sync, "require_secret", side_effect=lambda name: values[name]):
                targets = glab_sync.load_targets("external")

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].target_project_path, "top/sub/keepsecret")
        self.assertEqual(targets[0].source, "https://invent.kde.org/utilities/keepsecret.git")

    def test_target_spec_requires_repo_name_to_match_target_path(self):
        with self.assertRaises(SystemExit):
            glab_sync.TargetSpec.from_payload(
                {
                    "mode": "internal",
                    "target_project_path": "top/sub/demo",
                    "source": "top/source/demo",
                    "repo_name": "other",
                }
            )

    def test_target_spec_rejects_internal_self_sync(self):
        with self.assertRaises(SystemExit):
            glab_sync.TargetSpec.from_payload(
                {
                    "mode": "internal",
                    "target_project_path": "top/sub/demo",
                    "source": "top/sub/demo",
                    "repo_name": "demo",
                }
            )

    def test_external_payload_normalizes_git_url(self):
        target = glab_sync.TargetSpec.from_payload(
            {
                "mode": "external",
                "target_project_path": "top/sub/demo",
                "source": "https://invent.kde.org/utilities/keepsecret",
                "repo_name": "demo",
            }
        )
        self.assertEqual(target.source, "https://invent.kde.org/utilities/keepsecret.git")

    def test_load_targets_internal_returns_empty_for_blank_secret(self):
        with mock.patch.object(glab_sync, "optional_secret", return_value=""):
            targets = glab_sync.load_targets("internal")
        self.assertEqual(targets, [])

    def test_inspect_target_flags_missing_project(self):
        client = GitLabClient(base_url="https://gitlab.com", username="svc", token="token")
        target = glab_sync.TargetSpec(
            mode="external",
            target_project_path="top/sub/demo",
            source="https://gitlab.example/group/demo",
            repo_name="demo",
        )
        with mock.patch.object(glab_sync, "build_source_git_url", return_value="https://gitlab.example/group/demo"):
            with mock.patch.object(glab_sync, "git_source_head", return_value=("main", "a" * 40)):
                with mock.patch.object(glab_sync, "get_gitlab_project", return_value=None):
                    planned = glab_sync.inspect_target(target, make_policy(), client)

        self.assertTrue(planned["needs_reconcile"])
        self.assertEqual(planned["reasons"], ["project_missing"])
        self.assertTrue(planned["target_id"].startswith("target-"))

    def test_inspect_target_flags_drift_and_protection(self):
        client = GitLabClient(base_url="https://gitlab.com", username="svc", token="token")
        target = glab_sync.TargetSpec(
            mode="internal",
            target_project_path="top/sub/demo",
            source="top/upstream/demo",
            repo_name="demo",
        )
        project = {"id": 77, "default_branch": "main"}

        def branch_sha_side_effect(_client, _project_id, branch):
            if branch == "gitlab/mcr/main":
                return "b" * 40
            if branch == "gitlab/mcr/staging":
                return "a" * 40
            if branch == "mcr/snapshot":
                return None
            raise AssertionError(f"unexpected branch: {branch}")

        with mock.patch.object(glab_sync, "build_source_git_url", return_value="https://gitlab.com/top/upstream/demo.git"):
            with mock.patch.object(glab_sync, "git_source_head", return_value=("main", "a" * 40)):
                with mock.patch.object(glab_sync, "get_gitlab_project", return_value=project):
                    with mock.patch.object(glab_sync, "get_gitlab_branch_sha", side_effect=branch_sha_side_effect):
                        with mock.patch("glab_sync.get_gitlab_protected_branch", return_value=None):
                            planned = glab_sync.inspect_target(target, make_policy(), client)

        self.assertIn("sha_diverged:gitlab/mcr/main", planned["reasons"])
        self.assertIn("protection_missing:gitlab/mcr/main", planned["reasons"])
        self.assertIn("branch_missing:mcr/snapshot", planned["reasons"])
        self.assertIn("default_branch_mismatch:gitlab/mcr/main", planned["reasons"])

    def test_inspect_target_flags_protected_snapshot(self):
        client = GitLabClient(base_url="https://gitlab.com", username="svc", token="token")
        target = glab_sync.TargetSpec(
            mode="internal",
            target_project_path="top/sub/demo",
            source="top/upstream/demo",
            repo_name="demo",
        )
        project = {"id": 77, "default_branch": "gitlab/mcr/main"}

        def branch_sha_side_effect(_client, _project_id, branch):
            if branch == "mcr/snapshot":
                return "a" * 40
            return "a" * 40

        def protected_branch_side_effect(_client, _project_id, branch):
            if branch == "mcr/snapshot":
                return {"name": "mcr/snapshot"}
            return {
                "push_access_levels": [{"access_level": 40}],
                "merge_access_levels": [{"access_level": 40}],
                "unprotect_access_levels": [{"access_level": 40}],
                "allow_force_push": True,
            }

        with mock.patch.object(glab_sync, "build_source_git_url", return_value="https://gitlab.com/top/upstream/demo.git"):
            with mock.patch.object(glab_sync, "git_source_head", return_value=("main", "a" * 40)):
                with mock.patch.object(glab_sync, "get_gitlab_project", return_value=project):
                    with mock.patch.object(glab_sync, "get_gitlab_branch_sha", side_effect=branch_sha_side_effect):
                        with mock.patch("glab_sync.get_gitlab_protected_branch", side_effect=protected_branch_side_effect):
                            planned = glab_sync.inspect_target(target, make_policy(), client)

        self.assertIn("protection_present:mcr/snapshot", planned["reasons"])

    def test_render_plan_summary_counts_actionable_items(self):
        summary = glab_sync.render_plan_summary(
            "external",
            [
                {"target_id": "target-111111111111", "target_project_path": "a/b/demo", "source": "https://example/demo", "needs_reconcile": True, "reasons": ["project_missing"]},
                {"target_id": "target-222222222222", "target_project_path": "a/b/clean", "source": "https://example/clean", "needs_reconcile": False, "reasons": []},
            ],
            [{"target_id": "target-333333333333", "error": "boom"}],
        )
        self.assertIn("- inspected: 2", summary)
        self.assertIn("- actionable: 1", summary)
        self.assertIn("- errors: 1", summary)
        self.assertNotIn("a/b/demo", summary)
        self.assertNotIn("https://example/demo", summary)

    def test_render_reconcile_summary_redacts_target_identity(self):
        summary = glab_sync.render_reconcile_summary(
            {
                "target_id": "target-aaaaaaaaaaaa",
                "target_project_path": "top/sub/demo",
                "source": "https://gitlab.example/top/demo.git",
                "mode": "external",
                "source_default_branch": "main",
                "source_sha": "a" * 40,
                "results": {
                    "created": ["gitlab/mcr/main"],
                    "updated": [],
                    "skipped": [],
                    "protected": [],
                    "unprotected": [],
                },
            }
        )
        self.assertIn("target-aaaaaaaaaaaa", summary)
        self.assertNotIn("top/sub/demo", summary)
        self.assertNotIn("https://gitlab.example/top/demo.git", summary)

    def test_load_gitlab_client_uses_mode_specific_secret_names(self):
        values = {
            "GL_BASE_URL": "https://gitlab.com",
            "GL_BRIDGE_FORK_USER_SEEDBED": "seedbed",
            "GL_PAT_FORK_SEEDBED_SVC": "seedbed-token",
            "GL_BRIDGE_FORK_USER_GLAB": "glab",
            "GL_PAT_FORK_GLAB_SVC": "glab-token",
        }
        with mock.patch.object(glab_sync, "require_secret", side_effect=lambda name: values[name]):
            external = glab_sync.load_gitlab_client("external")
            internal = glab_sync.load_gitlab_client("internal")
        self.assertEqual((external.username, external.token), ("seedbed", "seedbed-token"))
        self.assertEqual((internal.username, internal.token), ("glab", "glab-token"))


if __name__ == "__main__":
    unittest.main()
