"""Docs are part of the skill: agents follow them, so losing a section breaks real use."""
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("path,min_lines", [("SKILL.md", 100), ("README.md", 100), ("i18n/SKILL_zh.md", 60),
                                            ("i18n/README_zh.md", 60)])
def test_docs_are_not_truncated(path, min_lines):
    assert len(read(path).splitlines()) >= min_lines


@pytest.mark.parametrize("heading", ["## Reboot Rules", "## Residential and Relay Exits", "reality-self",
                                     "exit_proxy", "cdn_transport", "manage_dns"])
def test_skill_keeps_its_key_sections(heading):
    assert heading in read("SKILL.md")


def test_agent_skill_entry_is_the_same_file():
    assert read(".agents/skills/vps-deployer/SKILL.md") == read("SKILL.md")
