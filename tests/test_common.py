import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / ".github" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _common  # noqa: E402


class CommonTests(unittest.TestCase):
    def test_normalize_gitlab_project_url_adds_dot_git(self):
        self.assertEqual(
            _common.normalize_gitlab_project_url(
                "https://invent.kde.org/utilities/keepsecret",
                "source",
            ),
            "https://invent.kde.org/utilities/keepsecret.git",
        )

    def test_normalize_gitlab_project_url_preserves_existing_dot_git(self):
        self.assertEqual(
            _common.normalize_gitlab_project_url(
                "https://gitlab.com/top/project.git",
                "source",
            ),
            "https://gitlab.com/top/project.git",
        )

    def test_protected_branch_allows_sync_requires_exact_policy(self):
        good = {
            "push_access_levels": [{"access_level": 40}],
            "merge_access_levels": [{"access_level": 40}],
            "unprotect_access_levels": [{"access_level": 40}],
            "allow_force_push": True,
        }
        too_open = {
            "push_access_levels": [{"access_level": 30}, {"access_level": 40}],
            "merge_access_levels": [{"access_level": 40}],
            "unprotect_access_levels": [{"access_level": 40}],
            "allow_force_push": True,
        }
        wrong_merge = {
            "push_access_levels": [{"access_level": 40}],
            "merge_access_levels": [{"access_level": 30}],
            "unprotect_access_levels": [{"access_level": 40}],
            "allow_force_push": True,
        }
        self.assertTrue(_common.protected_branch_allows_sync(good))
        self.assertFalse(_common.protected_branch_allows_sync(too_open))
        self.assertFalse(_common.protected_branch_allows_sync(wrong_merge))

    def test_protected_tag_allows_sync_requires_exact_policy(self):
        good = {
            "create_access_levels": [{"access_level": 40}],
        }
        too_open = {
            "create_access_levels": [{"access_level": 30}, {"access_level": 40}],
        }
        self.assertTrue(_common.protected_tag_allows_sync(good))
        self.assertFalse(_common.protected_tag_allows_sync(too_open))

    def test_project_git_url_does_not_embed_credentials(self):
        client = _common.GitLabClient(
            base_url="https://gitlab.com",
            username="svc-user",
            token="secret-token",
        )
        self.assertEqual(
            client.project_git_url("top/sub/project"),
            "https://gitlab.com/top/sub/project.git",
        )


if __name__ == "__main__":
    unittest.main()
