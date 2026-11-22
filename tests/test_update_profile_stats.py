"""Offline regression tests for profile GitHub stats."""

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from update_profile_stats import calculate_metrics, paginate, render_readme

SAMPLE = """# Portfolio

## Open-source impact

| Metric | Verified on 2026-11-22 |
| --- | ---: |
| Stars across public repositories | **48** |
| GitHub Release asset downloads | **347** |
| Public repositories | **20** |

These totals are a dated snapshot.

## Technologies

Keep *all* this text.
"""


def repo(name, stars=1, private=False):
    return {"name": name, "stargazers_count": stars, "private": private, "owner": {"login": "maximsokal"}}


class ProfileStatsTests(unittest.TestCase):
    def test_pagination_and_downloads_across_releases(self):
        calls = []
        def fake(url):
            parsed = urlparse(url)
            page = int(parse_qs(parsed.query)["page"][0])
            calls.append((parsed.path, page))
            if parsed.path == "/users/maximsokal/repos":
                if page == 1:
                    return [repo(f"repo{i}", 1) for i in range(100)]
                return [repo("maximsokal", 5)]
            if parsed.path.endswith("/repo0/releases"):
                return [{"assets": [{"download_count": 2}]} for _ in range(100)] if page == 1 else [{"assets": [{"download_count": 3}]}]
            return []
        result = calculate_metrics("maximsokal", fake)
        self.assertEqual(result, {"stars": 105, "downloads": 203, "repositories": 101})
        self.assertIn(("/users/maximsokal/repos", 2), calls)
        self.assertIn(("/repos/maximsokal/repo0/releases", 2), calls)

    def test_private_repositories_do_not_contribute(self):
        def fake(url):
            return [repo("public", 2), repo("private", 999, True)] if "/users/" in url else []
        self.assertEqual(calculate_metrics("maximsokal", fake), {"stars": 2, "downloads": 0, "repositories": 1})

    def test_update_preserves_other_sections_and_updates_date(self):
        updated = render_readme(SAMPLE, {"stars": 49, "downloads": 350, "repositories": 21}, "2026-11-23")
        self.assertIn("| Stars across public repositories | **49** |", updated)
        self.assertIn("| GitHub Release asset downloads | **350** |", updated)
        self.assertIn("| Public repositories | **21** |", updated)
        self.assertIn("| Metric | Verified on 2026-11-23 |", updated)
        self.assertTrue(updated.startswith("# Portfolio\n"))
        self.assertTrue(updated.endswith("## Technologies\n\nKeep *all* this text.\n"))

    def test_unchanged_values_do_not_update_date_or_content(self):
        self.assertEqual(render_readme(SAMPLE, {"stars": 48, "downloads": 347, "repositories": 20}, "2027-01-01"), SAMPLE)

    def test_incomplete_table_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exactly one row"):
            render_readme(SAMPLE.replace("Public repositories", "Public repos"), {"stars": 48, "downloads": 347, "repositories": 21}, "2026-11-23")

    def test_duplicate_table_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exactly one row"):
            render_readme(SAMPLE.replace("| Public repositories | **20** |", "| Public repositories | **20** |\n| Public repositories | **20** |"), {"stars": 48, "downloads": 347, "repositories": 21}, "2026-11-23")

    def test_api_failure_propagates(self):
        def fake(_url):
            raise RuntimeError("rate limited")
        with self.assertRaisesRegex(RuntimeError, "rate limited"):
            calculate_metrics("maximsokal", fake)

    def test_malformed_counts_fail_closed(self):
        def fake(url):
            return [repo("broken", -1)] if "/users/" in url else []
        with self.assertRaisesRegex(ValueError, "Invalid star count"):
            calculate_metrics("maximsokal", fake)

    def test_malformed_release_downloads_fail_closed(self):
        def fake(url):
            return [repo("withrelease", 1)] if "/users/" in url else [{"assets": [{"download_count": None}]}]
        with self.assertRaisesRegex(ValueError, "Invalid release download count"):
            calculate_metrics("maximsokal", fake)

    def test_non_list_api_response_fails(self):
        with self.assertRaisesRegex(ValueError, "Unexpected GitHub API response"):
            paginate("/users/maximsokal/repos", lambda url: {"message": "error"})

    def test_invalid_username_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid GitHub username"):
            calculate_metrics("../another", lambda url: [])


if __name__ == "__main__":
    unittest.main()
