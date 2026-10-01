"""Keep the bilingual entry points small, safe, and connected to public guides."""

import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- benchmark-results:start -->"
END = "<!-- benchmark-results:end -->"


def authored_text(text):
    """Ignore the separately tested generated report, including its table/charts."""
    before, result = text.split(START)
    _, after = result.split(END)
    return before + after


def links(text):
    return re.findall(r"\[[^\]]*\]\(([^)]+)\)", text)


def anchors(text):
    """The simple ATX headings used by these guides use GitHub-style anchors."""
    return {
        re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        for heading in re.findall(r"(?m)^#{1,6} (.+)$", text)
    }


class ReadmeNavigationTests(unittest.TestCase):
    def test_both_languages_link_to_same_essential_public_guides(self):
        shared = {
            "docs/IMPLEMENTATIONS.md#registered-and-measured-implementations",
            "docs/API-CONTRACT.md",
            "docs/METHODOLOGY.md",
            "docs/BENCHMARK.md",
            "docs/AUTOMATION.md#when-to-request-an-official-benchmark",
            "docs/RELEASING.md",
            "CONTRIBUTING.md#shared-contract-checks",
        }
        for filename, guide in (
            ("README.md", "docs/LOCAL-DEVELOPMENT.md"),
            ("README.ja.md", "docs/LOCAL-DEVELOPMENT.ja.md"),
        ):
            with self.subTest(filename=filename):
                text = authored_text((ROOT / filename).read_text())
                self.assertTrue(shared.issubset(links(text)), shared - set(links(text)))
                self.assertIn(guide, links(text))

    def test_quick_start_commands_match_and_need_no_host_language_toolchain(self):
        commands = []
        for filename in ("README.md", "README.ja.md"):
            text = authored_text((ROOT / filename).read_text())
            blocks = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
            self.assertEqual(len(blocks), 1, filename)
            commands.append([line for line in blocks[0].splitlines() if line.strip()])
        self.assertEqual(commands[0], commands[1])
        self.assertEqual(
            commands[0][0],
            "docker compose --project-name sab-example up --detach --build --wait go-gin",
        )
        self.assertEqual(
            commands[0][-1],
            "docker compose --project-name sab-example down --remove-orphans --volumes",
        )
        self.assertEqual(
            commands[0][1:-1],
            [
                f"curl --fail http://127.0.0.1:8080/{endpoint}"
                for endpoint in ("health", "json", "db/42", "cpu")
            ],
        )

    def test_quick_start_explains_prerequisites_and_destructive_cleanup(self):
        for filename, words in (
            ("README.md", ("Docker", "Compose v2", "curl", "8080", "tmpfs", "deletes", "volumes")),
            ("README.ja.md", ("Docker", "Compose v2", "curl", "8080", "tmpfs", "削除", "volume")),
        ):
            with self.subTest(filename=filename):
                text = authored_text((ROOT / filename).read_text())
                for word in words:
                    self.assertIn(word, text)

    def test_moved_guides_preserve_setup_and_verification_entry_points(self):
        for filename in ("docs/LOCAL-DEVELOPMENT.md", "docs/LOCAL-DEVELOPMENT.ja.md"):
            with self.subTest(filename=filename):
                path = ROOT / filename
                self.assertTrue(path.is_file(), filename)
                text = path.read_text()
                for command in (
                    "make db-reset",
                    "make down",
                    "make test-go-gin",
                    "make test-go-echo",
                    "make test-rust-actix",
                    "make test-rust-axum",
                    "make test-node-fastify",
                    "make test-python-fastapi PYTHON=python3.14",
                    "make test-java-spring-boot",
                    "make test-contract",
                    "make benchmark",
                ):
                    self.assertIn(command, text)
                for guide in ("AXUM.md", "FLASK.md", "NODE-EXPRESS.md", "JAVA-SPRING-BOOT.md"):
                    self.assertIn(guide, links(text))
                self.assertIn("../CONTRIBUTING.md#shared-contract-checks", links(text))
                for invariant in (
                    "tmpfs",
                    "current_thread",
                    "Cargo.lock",
                    "DATABASE_PASSWORD",
                    "127.0.0.1:8080",
                    "SIGTERM",
                    "SHA256",
                ):
                    self.assertIn(invariant, text)

    def test_readme_and_moved_guide_local_links_and_anchors_resolve(self):
        for filename in (
            "README.md",
            "README.ja.md",
            "docs/LOCAL-DEVELOPMENT.md",
            "docs/LOCAL-DEVELOPMENT.ja.md",
        ):
            path = ROOT / filename
            self.assertTrue(path.is_file(), filename)
            for target in links(path.read_text()):
                with self.subTest(filename=filename, target=target):
                    url = urlsplit(target)
                    if url.scheme or url.netloc:
                        continue
                    destination = (path.parent / unquote(url.path)).resolve() if url.path else path
                    self.assertTrue(destination.exists(), target)
                    if url.fragment and destination.suffix == ".md":
                        self.assertIn(
                            unquote(url.fragment), anchors(destination.read_text()), target
                        )


if __name__ == "__main__":
    unittest.main()
