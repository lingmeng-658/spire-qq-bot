import tempfile
from pathlib import Path

from scripts.download_card_images import (
    build_image_url,
    determine_local_output_path,
    download_card_images,
)


def test_build_image_url_uses_stable_id_for_each_game():
    assert build_image_url({"game": "sts1", "id": "ACCURACY"}) == (
        "https://www.spirecodex.com/images/cards/ACCURACY.webp"
    )
    assert build_image_url({"game": "sts2", "id": "ACCELERANT"}) == (
        "https://www.spirecodex.com/images/cards/ACCELERANT.webp"
    )


def test_local_output_path_uses_game_and_stable_id():
    output_root = Path("/tmp/images")
    card = {"game": "sts2", "id": "ABRASIVE"}

    assert determine_local_output_path(output_root, card) == (
        output_root / "sts2" / "ABRASIVE.webp"
    )


def test_download_card_images_skips_existing_and_collects_failures():
    with tempfile.TemporaryDirectory(dir=".") as tmpdir:
        tmp_path = Path(tmpdir)
        existing_path = tmp_path / "sts1" / "EXISTING.webp"
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        existing_path.write_bytes(b"old")

        cards = {
            "sts1": [
                {"game": "sts1", "id": "EXISTING"},
                {"game": "sts1", "id": "OK_CARD"},
                {"game": "sts1", "id": "FAIL_CARD"},
            ],
            "sts2": [],
        }

        def fake_fetcher(url):
            if url.endswith("FAIL_CARD.webp"):
                raise OSError("network fail")
            return b"payload"

        summary = download_card_images(cards, output_root=tmp_path, fetcher=fake_fetcher)

        assert summary["total"] == 3
        assert summary["success"] == 1
        assert summary["skipped"] == 1
        assert summary["failed"] == 1
        assert summary["failed_cards"] == ["sts1:FAIL_CARD"]
        assert (tmp_path / "sts1" / "OK_CARD.webp").read_bytes() == b"payload"
        assert (tmp_path / "sts1" / "EXISTING.webp").read_bytes() == b"old"
