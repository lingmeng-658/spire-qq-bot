import json

from scripts import download_relics


ZH_ITEMS = [
    {
        "id": "RELIC_A",
        "name": "遗物甲",
        "description": "虚构描述甲",
        "tier": "common",
        "color": "red",
        "icon": "a-icon.png",
    },
    {
        "id": "RELIC_B",
        "name": "遗物乙",
        "description": "虚构描述乙",
        "tier": "rare",
        "color": "green",
    },
    {
        "id": "RELIC_C",
        "name": "遗物丙",
        "description": "虚构描述丙",
        "tier": "boss",
        "color": "blue",
    },
]

# 英文列表顺序故意与中文列表不同，验证按 id join。
EN_ITEMS = [
    {"id": "RELIC_C", "name": "Relic Cee", "description": "Desc C"},
    {"id": "RELIC_A", "name": "Relic Ay", "description": "Desc A"},
    {"id": "RELIC_B", "name": "Relic Bee", "description": "Desc B"},
]


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _make_pages(items, page_size=2):
    pages = {}
    offset = 0
    while offset < len(items):
        pages[offset] = items[offset : offset + page_size]
        offset += page_size
    pages[offset] = []
    return pages


def _make_fetcher(total):
    zh_pages = _make_pages(ZH_ITEMS)
    en_pages = _make_pages(EN_ITEMS)

    def fake_fetcher(url, params):
        lang = params["lang"]
        offset = params["offset"]
        page = zh_pages[offset] if lang == "zh" else en_pages[offset]
        return FakeResponse({"items": page, "total": total})

    return fake_fetcher


def test_download_relics_paginates_both_languages_and_writes_merged_json(tmp_path):
    download_relics.download_relics(
        "sts1",
        fetcher=_make_fetcher(total=len(ZH_ITEMS)),
        output_dir=str(tmp_path),
    )

    output_path = tmp_path / "sts1_relics.json"
    assert output_path.exists()

    records = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(records) == 3

    by_id = {record["id"]: record for record in records}
    assert list(by_id) == ["RELIC_A", "RELIC_B", "RELIC_C"]

    assert by_id["RELIC_A"]["name"] == "遗物甲"
    assert by_id["RELIC_A"]["name_en"] == "Relic Ay"
    assert by_id["RELIC_A"]["description_en"] == "Desc A"
    assert by_id["RELIC_A"]["icon"] == "a-icon.png"

    assert by_id["RELIC_C"]["name_en"] == "Relic Cee"
    assert by_id["RELIC_C"]["description_en"] == "Desc C"
    assert by_id["RELIC_C"]["tier"] == "boss"


def test_download_relics_merges_by_id_not_position(tmp_path):
    # 每页只返回一条：如果实现按数组顺序 zip 会错位。
    def single_item_fetcher(url, params):
        lang = params["lang"]
        offset = params["offset"]
        pool = ZH_ITEMS if lang == "zh" else EN_ITEMS
        if offset >= len(pool):
            return FakeResponse({"items": [], "total": len(pool)})
        return FakeResponse({"items": [pool[offset]], "total": len(pool)})

    download_relics.download_relics(
        "sts2",
        fetcher=single_item_fetcher,
        output_dir=str(tmp_path),
    )

    output_path = tmp_path / "sts2_relics.json"
    assert output_path.exists()

    records = json.loads(output_path.read_text(encoding="utf-8"))
    by_id = {record["id"]: record for record in records}

    assert by_id["RELIC_A"]["name_en"] == "Relic Ay"
    assert by_id["RELIC_B"]["name_en"] == "Relic Bee"
    assert by_id["RELIC_C"]["name_en"] == "Relic Cee"


def test_main_downloads_both_games(monkeypatch):
    calls = []

    def fake_download_relics(game):
        calls.append(game)
        return []

    monkeypatch.setattr(download_relics, "download_relics", fake_download_relics)

    download_relics.main()

    assert calls == ["sts1", "sts2"]
