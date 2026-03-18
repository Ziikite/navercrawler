import asyncio
import os
import re
import threading
from collections import Counter, defaultdict
from typing import Optional

import httpx

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SENTI_PATH = os.path.join(DATA_DIR, "SentiWord_Dict.txt")
SENTI_URL = "https://raw.githubusercontent.com/park1200656/KnuSentiLex/master/SentiWord_Dict.txt"

_okt = None
_okt_ready = False
_okt_error: Optional[str] = None
_okt_lock = threading.Lock()

def init_okt():
    global _okt, _okt_ready, _okt_error
    with _okt_lock:
        if _okt_ready:
            return
        try:
            from konlpy.tag import Okt
            _okt = Okt()
            _okt_ready = True
        except Exception as exc:
            _okt_error = str(exc)

def okt_status() -> dict:
    return {"ready": _okt_ready, "error": _okt_error}

_senti: dict[str, int] = {}
_senti_loaded = False
_senti_error: Optional[str] = None

async def load_senti():
    global _senti, _senti_loaded, _senti_error
    if _senti_loaded:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SENTI_PATH):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(SENTI_URL)
                r.raise_for_status()
                with open(SENTI_PATH, "wb") as f:
                    f.write(r.content)
        except Exception as exc:
            _senti_error = str(exc)
            return
    try:
        with open(SENTI_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                word = parts[0].strip()
                try:
                    pol = int(parts[-1].strip())
                except ValueError:
                    continue
                if word and pol != 0:
                    _senti[word] = pol
                    if word.endswith("다"):
                        _senti[word[:-1]] = pol
        _senti_loaded = True
    except Exception as exc:
        _senti_error = str(exc)

def senti_status() -> dict:
    return {"loaded": _senti_loaded, "size": len(_senti), "error": _senti_error}

STOPWORDS = {
    "것","수","등","때","더","이","그","저","안","못",
    "위","잘","일","면","중","후","내","년","월","일",
    "경우","지난","때문","통해","위해","대해","관련","대한",
    "따른","따라","대로","이후","이전","현재","이번","지금",
    "최근","오늘","내일","어제","관계","부분","방법","상황",
    "기자","뉴스","기사","보도","기준","사실","문제","내용",
    "결과","이유","측면","차원","가능","필요","정도","기간",
}

def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"&\w+;", " ", text)

def extract_nouns(text: str) -> list[str]:
    text = _strip_html(text)
    if _okt_ready and _okt:
        try:
            nouns = _okt.nouns(text)
            return [n for n in nouns if len(n) > 1 and n not in STOPWORDS]
        except Exception:
            pass
    return [w for w in re.findall(r"[가-힣]{2,}", text) if w not in STOPWORDS]

def pos_tag(text: str, stem: bool = True) -> list[tuple[str, str]]:
    text = _strip_html(text)
    if _okt_ready and _okt:
        try:
            return _okt.pos(text, stem=stem)
        except Exception:
            pass
    return [(w, "NNG") for w in re.findall(r"[가-힣]{2,}", text)]

def freq_analysis(items: list[dict], top_n: int = 30) -> list[dict]:
    counter: Counter = Counter()
    for item in items:
        text = item.get("title", "") + " " + item.get("description", "")
        counter.update(extract_nouns(text))
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]

def _score_text(text: str) -> int:
    tags = pos_tag(text, stem=True)
    score = 0
    for word, pos in tags:
        if word in _senti:
            score += _senti[word]
            continue
        if pos in ("VA", "VV", "VX") and (word + "다") in _senti:
            score += _senti[word + "다"]
    return score

def sentiment_analysis(items: list[dict]) -> dict:
    records = []
    for item in items:
        text = item.get("title", "") + " " + item.get("description", "")
        s = _score_text(text)
        label = "positive" if s > 0 else ("negative" if s < 0 else "neutral")
        records.append({
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "date": item.get("parsed_date", ""),
            "score": s,
            "label": label,
        })
    scores = [r["score"] for r in records]
    pos = sum(1 for s in scores if s > 0)
    neg = sum(1 for s in scores if s < 0)
    neu = len(scores) - pos - neg
    avg = round(sum(scores) / len(scores), 3) if scores else 0
    sorted_all = sorted(records, key=lambda x: x["score"], reverse=True)
    return {
        "positive": pos, "negative": neg, "neutral": neu,
        "average_score": avg,
        "top_positive": sorted_all[:5],
        "top_negative": sorted_all[-5:][::-1],
        "timeline": _sentiment_timeline(records),
    }

def _sentiment_timeline(records: list[dict]) -> list[dict]:
    by_date: dict[str, list[int]] = defaultdict(list)
    for r in records:
        d = r.get("date") or "unknown"
        by_date[d].append(r["score"])
    result = []
    for d in sorted(by_date):
        if d == "unknown":
            continue
        vals = by_date[d]
        result.append({"date": d, "avg": round(sum(vals)/len(vals), 2), "count": len(vals)})
    return result[-30:]

def network_analysis(items: list[dict], top_n: int = 30, min_edge: int = 2) -> dict:
    all_tokens: list[str] = []
    article_token_sets: list[set[str]] = []
    for item in items:
        text = item.get("title", "") + " " + item.get("description", "")
        tokens = extract_nouns(text)
        all_tokens.extend(tokens)
        article_token_sets.append(set(tokens))
    counter = Counter(all_tokens)
    top_words: set[str] = {w for w, _ in counter.most_common(top_n)}
    cooccur: dict[tuple[str, str], int] = defaultdict(int)
    for token_set in article_token_sets:
        filtered = sorted(token_set & top_words)
        for i, w1 in enumerate(filtered):
            for w2 in filtered[i+1:]:
                cooccur[(w1, w2)] += 1
    edges = [
        {"source": a, "target": b, "weight": c}
        for (a, b), c in cooccur.items() if c >= min_edge
    ]
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    nodes = [
        {"id": w, "label": w, "value": counter[w],
         "sentiment": _senti.get(w, _senti.get(w+"다", 0))}
        for w in top_words if w in connected
    ]
    return {"nodes": nodes, "edges": edges}
