import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / ".github" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _common  # noqa: E402


class CommonTests(unittest.TestCase):
    def test_normalize_gitlab_project_url_preserves_https_url_without_rewrite(self):
        self.assertEqual(
            _common.normalize_gitlab_project_url(
                "https://invent.kde.org/utilities/keepsecret",
                "source",
            ),
            "https://invent.kde.org/utilities/keepsecret",
        )

    def test_normalize_gitlab_project_url_preserves_existing_dot_git(self):
        self.assertEqual(
            _common.normalize_gitlab_project_url(
                "https://gitlab.com/top/project.git",
                "source",
            ),
            "https://gitlab.com/top/project.git",
        )

    def test_canonicalize_remote_mirror_url_strips_credentials(self):
        self.assertEqual(
            _common.canonicalize_remote_mirror_url(
                "https://user:secret@gitlab.example:8443/group/project.git",
                "mirror",
            ),
            "https://gitlab.example:8443/group/project.git",
        )

    def test_inject_basic_auth_into_url_quotes_credentials(self):
        self.assertEqual(
            _common.inject_basic_auth_into_url(
                "https://gitlab.example/group/project.git",
                "svc-user",
                "tok:en/with spaces",
                "mirror",
            ),
            "https://svc-user:tok%3Aen%2Fwith%20spaces@gitlab.example/group/project.git",
        )

    def test_find_gitlab_remote_mirror_matches_scrubbed_url(self):
        mirror = _common.find_gitlab_remote_mirror(
            [
                {
                    "id": 7,
                    "url": "https://*****:*****@gitlab.example/group/project.git",
                }
            ],
            "https://svc-user:secret@gitlab.example/group/project.git",
        )
        self.assertIsNotNone(mirror)
        self.assertEqual(mirror["id"], 7)

    def test_ensure_gitlab_push_mirror_creates_when_missing(self):
        client = _common.GitLabClient(
            base_url="https://gitlab.com",
            username="svc-user",
            token="secret-token",
        )
        with unittest.mock.patch.object(_common, "list_gitlab_remote_mirrors", return_value=[]):
            with unittest.mock.patch.object(
                _common,
                "gitlab_request",
                return_value={"id": 11, "url": "https://*****:*****@gitlab.com/group/project.git"},
            ) as request:
                payload, created = _common.ensure_gitlab_push_mirror(
                    client,
                    42,
                    "https://svc-user:secret@gitlab.com/group/project.git",
                )
        self.assertTrue(created)
        self.assertEqual(payload["id"], 11)
        request.assert_called_once_with(
            client,
            "POST",
            "/projects/42/remote_mirrors",
            {
                "url": "https://svc-user:secret@gitlab.com/group/project.git",
                "auth_method": "password",
                "enabled": True,
                "only_protected_branches": True,
            },
        )

    def test_ensure_gitlab_push_mirror_updates_existing_match(self):
        client = _common.GitLabClient(
            base_url="https://gitlab.com",
            username="svc-user",
            token="secret-token",
        )
        with unittest.mock.patch.object(
            _common,
            "list_gitlab_remote_mirrors",
            return_value=[{"id": 15, "url": "https://*****:*****@gitlab.com/group/project.git"}],
        ):
            with unittest.mock.patch.object(
                _common,
                "gitlab_request",
                return_value={"id": 15, "url": "https://*****:*****@gitlab.com/group/project.git"},
            ) as request:
                payload, created = _common.ensure_gitlab_push_mirror(
                    client,
                    42,
                    "https://svc-user:secret@gitlab.com/group/project.git",
                )
        self.assertFalse(created)
        self.assertEqual(payload["id"], 15)
        request.assert_called_once_with(
            client,
            "PUT",
            "/projects/42/remote_mirrors/15",
            {
                "url": "https://svc-user:secret@gitlab.com/group/project.git",
                "auth_method": "password",
                "enabled": True,
                "only_protected_branches": True,
            },
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
