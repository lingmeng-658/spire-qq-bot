"""QQ Ancient NPC overview collage: local image resolution and route attach."""

from __future__ import annotations

from card_guess.qq import bot, renderer, sessions
from card_guess.qq.renderer import RenderedReply


def make_overview_image(root):
    image = root / "data" / "images" / "ancients" / "sts2" / "ancient_overview.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"fake-overview-png")
    return image


def test_resolve_local_overview_image_returns_one_local_path(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    image = make_overview_image(root)
    monkeypatch.setattr(renderer, "REPO_ROOT", root)

    assert renderer.resolve_local_ancient_overview_image() == image


def test_resolve_local_overview_image_returns_none_when_missing(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    monkeypatch.setattr(renderer, "REPO_ROOT", root)

    assert renderer.resolve_local_ancient_overview_image() is None


def test_overview_command_attaches_single_image_when_local_file_exists(
    monkeypatch, tmp_path
):
    root = tmp_path / "repo"
    image = make_overview_image(root)
    monkeypatch.setattr(renderer, "REPO_ROOT", root)
    monkeypatch.setattr(sessions, "get", lambda group_id: None)

    reply = bot.route_group_command(101, "先古遗民")

    assert isinstance(reply, RenderedReply)
    assert str(reply).startswith("先古遗民\n\n")
    assert reply.image_path == image
    assert reply.image_paths == (image,)


def test_overview_command_stays_text_only_when_collage_is_missing(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(renderer, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(sessions, "get", lambda group_id: None)

    reply = bot.route_group_command(101, "先古遗民")

    assert isinstance(reply, RenderedReply)
    assert "先古遗民" in str(reply)
    assert reply.image_path is None
    assert reply.image_paths == ()
