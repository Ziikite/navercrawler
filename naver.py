import httpx
import re
import asyncio
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Optional

BASE = "https://openapi.naver.com/v1/search/{type}.json"

TYPE_MAP = {"news": "news", "blog": "blog", "web": "webkr"}


def _headers(client_id: str, client_secret: str) -> dict:
    return {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&[a-zA-Z#\d]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(item: dict, stype: str) -> Optional[date]:
    try:
        if stype == "blog":
            d = item.get("postdate", "")
            if d and len(d) == 8:
                return date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        else:
            pub = item.get("pubDate", "")
            if pub:
                return parsedate_to_datetime(pub).date()
    except Exception:
        pass
    return None


async def search_once(
    client_id: str,
    client_secret: str,
    query: str,
    stype: str = "news",
    display: int = 5,
    start: int = 1,
    sort: str = "date",
) -> dict:
    url = BASE.format(type=TYPE_MAP.get(stype, "news"))
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            url,
            headers=_headers(client_id, client_secret),
            params={"query": query, "display": min(display, 100),
                    "start": start, "sort": sort},
        )
        r.raise_for_status()
    return r.json()


async def fetch_all(
    client_id: str,
    client_secret: str,
    query: str,
    stype: str = "news",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    max_items: int = 500,
) -> list[dict]:
    results: list[dict] = []
    start = 1

    while start <= 1000 and len(results) < max_items:
        batch = await search_once(client_id, client_secret, query, stype,
                                  display=100, start=start, sort="date")
        items = batch.get("items", [])
        if not items:
            break

        stop = False
        for item in items:
            item["title"] = _clean(item.get("title", ""))
            item["description"] = _clean(item.get("description", ""))
            d = _parse_date(item, stype)
            item["parsed_date"] = d.isoformat() if d else None

            if date_from and date_to:
                if d is None:
                    continue
                if d < date_from:
                    stop = True
                    break
                if d <= date_to:
                    results.append(item)
            else:
                results.append(item)

        if stop or len(items) < 100:
            break
        start += 100
        await asyncio.sleep(0.1)   # gentle pacing

    return results[:max_items]
