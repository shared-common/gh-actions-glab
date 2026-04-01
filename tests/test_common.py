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


if __name__ == "__main__":
    unittest.main()
