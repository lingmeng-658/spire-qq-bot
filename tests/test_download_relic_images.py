from pathlib import Path

from scripts.download_relic_images import (
    build_relic_image_url,
    determine_relic_image_output_path,
    download_relic_images,
)


def test_build_relic_image_url_uses_game_and_catalog_icon():
    assert build_relic_image_url(
        {"game": "sts1", "id": "AKABEKO", "icon": "akabeko.png"}
    ) == "https://spire-archive.com/images/sts1/relics/akabeko.png"
    # 大小写按 catalog icon 原样保留（artOfWar.png 等混合大小写）
    assert build_relic_image_url(
        {"game": "sts1", "id": "ART_OF_WAR", "icon": "artOfWar.png"}
    ) == "https://spire-archive.com/images/sts1/relics/artOfWar.png"


def test_build_relic_image_url_prefers_explicit_image_url():
    relic = {
        "game": "sts1",
        "id": "AKABEKO",
        "icon": "akabeko.png",
        "image_url": "https://cdn.example.com/relics/akabeko.png",
    }
    assert build_relic_image_url(relic) == "https://cdn.example.com/relics/akabeko.png"


def test_local_output_path_uses_stable_relic_id():
    output_root = Path("/tmp/images")
    relic = {"game": "sts1", "id": "AKABEKO", "icon": "akabeko.png"}

    assert determine_relic_image_output_path(output_root, relic) == (
        output_root / "relics" / "sts1" / "AKABEKO.png"
    )


def test_download_relic_images_skips_existing_and_collects_failures(tmp_path):
    existing_path = tmp_path / "relics" / "sts1" / "EXISTING.png"
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_bytes(b"old")

    relics = [
        {"game": "sts1", "id": "EXISTING", "icon": "existing.png"},
        {"game": "sts1", "id": "OK_RELIC", "icon": "ok_relic.png"},
        {"game": "sts1", "id": "FAIL_RELIC", "icon": "fail_relic.png"},
    ]

    def fake_fetcher(url):
        if url.endswith("fail_relic.png"):
            raise OSError("network fail")
        return b"payload"

    summary = download_relic_images(relics, output_root=tmp_path, fetcher=fake_fetcher)

    assert summary["total"] == 3
    assert summary["success"] == 1
    assert summary["skipped"] == 1
    assert summary["failed"] == 1
    assert summary["failed_relics"] == ["sts1:FAIL_RELIC"]
    assert (tmp_path / "relics" / "sts1" / "OK_RELIC.png").read_bytes() == b"payload"
    assert (tmp_path / "relics" / "sts1" / "EXISTING.png").read_bytes() == b"old"
