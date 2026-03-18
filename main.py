import asyncio
import csv
import io
import os
import smtplib
import ssl
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from naver import fetch_all, search_once
from nlp import (
    freq_analysis, init_okt, load_senti,
    network_analysis, okt_status,
    sentiment_analysis, senti_status,
)

app = FastAPI(title="Naver Search Dashboard", version="2.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, init_okt)
    try:
        await load_senti()
    except Exception as exc:
        print(f"[WARN] SentiLex: {exc}")


class LatestReq(BaseModel):
    client_id: str
    client_secret: str
    query: str
    search_type: str = "news"


class AnalyzeReq(BaseModel):
    client_id: str
    client_secret: str
    query: str
    search_type: str = "news"
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    max_items: int = 500


class EmailReq(BaseModel):
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender_email: str
    sender_password: str
    recipient_email: str
    subject: str
    query: str
    search_type: str
    total: int
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    frequency: list = []
    sentiment: dict = {}
    latest: list = []


@app.get("/api/status")
async def api_status():
    return {"konlpy": okt_status(), "sentilex": senti_status()}


@app.post("/api/latest")
async def api_latest(req: LatestReq):
    try:
        data = await search_once(req.client_id, req.client_secret,
                                 req.query, req.search_type, display=5, sort="date")
        return {"items": data.get("items", []), "total": data.get("total", 0)}
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 401:
            raise HTTPException(401, "API 인증 실패 — Client ID/Secret을 확인하세요")
        raise HTTPException(400, f"Naver API 오류: {code}")
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeReq):
    from datetime import date as date_type
    df = date_type.fromisoformat(req.date_from) if req.date_from else None
    dt = date_type.fromisoformat(req.date_to)   if req.date_to   else None
    try:
        items = await fetch_all(req.client_id, req.client_secret,
                                req.query, req.search_type,
                                df, dt, req.max_items)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 401:
            raise HTTPException(401, "API 인증 실패 — Client ID/Secret을 확인하세요")
        raise HTTPException(400, f"Naver API 오류: {code}")
    except Exception as exc:
        raise HTTPException(500, str(exc))

    if not items:
        raise HTTPException(404, "해당 기간에 검색 결과가 없습니다")

    loop = asyncio.get_event_loop()
    freq  = await loop.run_in_executor(None, freq_analysis, items)
    senti = await loop.run_in_executor(None, sentiment_analysis, items)
    net   = await loop.run_in_executor(None, network_analysis, items)

    dates = [i["parsed_date"] for i in items if i.get("parsed_date")]
    return {
        "query": req.query,
        "search_type": req.search_type,
        "total": len(items),
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "latest": items[:5],
        "frequency": freq,
        "sentiment": senti,
        "network": net,
    }


@app.post("/api/send-email")
async def send_email(req: EmailReq):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = req.subject
        msg["From"]    = req.sender_email
        msg["To"]      = req.recipient_email

        senti      = req.sentiment
        pos        = senti.get("positive", 0)
        neg        = senti.get("negative", 0)
        neu        = senti.get("neutral",  0)
        total_s    = pos + neg + neu or 1
        avg        = senti.get("average_score", 0)
        avg_str    = f"+{avg}" if avg > 0 else str(avg)
        scolor     = "#03c75a" if avg > 0 else ("#ff4757" if avg < 0 else "#7e8fa8")
        slabel     = "긍정 우세" if avg > 0 else ("부정 우세" if avg < 0 else "중립")
        stype_map  = {"news": "뉴스", "blog": "블로그", "web": "웹문서"}
        stype_label= stype_map.get(req.search_type, req.search_type)
        now        = datetime.now().strftime("%Y-%m-%d %H:%M")

        top_kw = req.frequency[:10]
        kw_rows = "".join(
            f"<tr><td style='padding:6px 12px;border-bottom:1px solid #1a2030;font-family:monospace;color:#7e8fa8'>{i+1}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #1a2030;color:#dde4f0;font-weight:500'>{kw['word']}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #1a2030;color:#03c75a;font-family:monospace'>{kw['count']}회</td></tr>"
            for i, kw in enumerate(top_kw)
        )

        latest_rows = "".join(
            f"<tr><td style='padding:8px 12px;border-bottom:1px solid #1a2030;color:#7e8fa8;font-family:monospace'>{i+1}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #1a2030'>"
            f"<a href='{it.get('link','')}' style='color:#3b82f6;text-decoration:none'>{it.get('title','')}</a>"
            f"<div style='font-size:11px;color:#3f4f66;margin-top:3px'>{it.get('description','')[:80]}...</div></td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #1a2030;color:#3f4f66;font-size:11px;white-space:nowrap'>{it.get('parsed_date','')}</td></tr>"
            for i, it in enumerate(req.latest[:5])
        )

        top_pos = senti.get("top_positive", [])[:3]
        top_neg = senti.get("top_negative", [])[:3]
        pos_rows = "".join(
            f"<div style='padding:6px 10px;border-left:2px solid #03c75a;margin-bottom:5px;background:#111620'>"
            f"<span style='color:#03c75a;font-family:monospace;margin-right:8px'>+{it['score']}</span>"
            f"<a href='{it.get('link','')}' style='color:#dde4f0;text-decoration:none;font-size:12px'>{it['title'][:70]}</a></div>"
            for it in top_pos
        )
        neg_rows = "".join(
            f"<div style='padding:6px 10px;border-left:2px solid #ff4757;margin-bottom:5px;background:#111620'>"
            f"<span style='color:#ff4757;font-family:monospace;margin-right:8px'>{it['score']}</span>"
            f"<a href='{it.get('link','')}' style='color:#dde4f0;text-decoration:none;font-size:12px'>{it['title'][:70]}</a></div>"
            for it in top_neg
        )

        html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"></head>
<body style="background:#070a0f;color:#dde4f0;font-family:Arial,sans-serif;padding:0;margin:0">
<div style="max-width:680px;margin:0 auto;padding:28px 20px">

  <div style="border-bottom:2px solid #03c75a;padding-bottom:14px;margin-bottom:22px">
    <span style="font-size:20px;font-weight:700;letter-spacing:.05em">NAVER <span style="color:#03c75a">ANALYST</span></span>
    <span style="float:right;font-size:11px;color:#3f4f66;font-family:monospace;line-height:2">{now}</span>
  </div>

  <div style="background:#0c1018;border:1px solid #1a2030;border-left:3px solid #03c75a;padding:16px 20px;margin-bottom:18px">
    <div style="font-size:10px;color:#3f4f66;letter-spacing:.12em;text-transform:uppercase;margin-bottom:10px;font-family:monospace">ANALYSIS SUMMARY</div>
    <table style="width:100%;border-collapse:collapse">
      <tr><td style="padding:4px 0;color:#7e8fa8;font-size:13px;width:80px">검색어</td><td style="padding:4px 0;color:#dde4f0;font-weight:700;font-size:15px">{req.query}</td></tr>
      <tr><td style="padding:4px 0;color:#7e8fa8;font-size:13px">유형</td><td style="padding:4px 0;color:#dde4f0">{stype_label}</td></tr>
      <tr><td style="padding:4px 0;color:#7e8fa8;font-size:13px">분석 기간</td><td style="padding:4px 0;color:#dde4f0">{req.date_min or '—'} ~ {req.date_max or '—'}</td></tr>
      <tr><td style="padding:4px 0;color:#7e8fa8;font-size:13px">수집 건수</td><td style="padding:4px 0;color:#03c75a;font-family:monospace;font-weight:700">{req.total:,}건</td></tr>
    </table>
  </div>

  <div style="background:#0c1018;border:1px solid #1a2030;padding:16px 20px;margin-bottom:18px">
    <div style="font-size:10px;color:#3f4f66;letter-spacing:.12em;text-transform:uppercase;margin-bottom:14px;font-family:monospace">SENTIMENT ANALYSIS · KNU SENTILEX</div>
    <table style="width:100%;border-collapse:collapse;margin-bottom:14px">
      <tr>
        <td style="width:25%;text-align:center;background:#111620;padding:12px;border-top:2px solid {scolor}">
          <div style="font-size:22px;font-weight:700;color:{scolor};font-family:monospace">{avg_str}</div>
          <div style="font-size:10px;color:#7e8fa8;margin-top:4px">{slabel}</div>
        </td>
        <td style="width:5%"></td>
        <td style="width:22%;text-align:center;background:#111620;padding:12px;border-top:2px solid #03c75a">
          <div style="font-size:20px;font-weight:700;color:#03c75a;font-family:monospace">{pos}</div>
          <div style="font-size:10px;color:#7e8fa8;margin-top:4px">긍정 {round(pos/total_s*100)}%</div>
        </td>
        <td style="width:5%"></td>
        <td style="width:22%;text-align:center;background:#111620;padding:12px;border-top:2px solid #ff4757">
          <div style="font-size:20px;font-weight:700;color:#ff4757;font-family:monospace">{neg}</div>
          <div style="font-size:10px;color:#7e8fa8;margin-top:4px">부정 {round(neg/total_s*100)}%</div>
        </td>
        <td style="width:5%"></td>
        <td style="width:22%;text-align:center;background:#111620;padding:12px;border-top:2px solid #3f4f66">
          <div style="font-size:20px;font-weight:700;color:#7e8fa8;font-family:monospace">{neu}</div>
          <div style="font-size:10px;color:#7e8fa8;margin-top:4px">중립 {round(neu/total_s*100)}%</div>
        </td>
      </tr>
    </table>
    {"<div style='margin-bottom:10px'><div style='font-size:10px;color:#03c75a;margin-bottom:6px;font-family:monospace'>▲ 긍정 상위</div>" + pos_rows + "</div>" if pos_rows else ""}
    {"<div><div style='font-size:10px;color:#ff4757;margin-bottom:6px;font-family:monospace'>▼ 부정 상위</div>" + neg_rows + "</div>" if neg_rows else ""}
  </div>

  <div style="background:#0c1018;border:1px solid #1a2030;padding:16px 20px;margin-bottom:18px">
    <div style="font-size:10px;color:#3f4f66;letter-spacing:.12em;text-transform:uppercase;margin-bottom:12px;font-family:monospace">TOP 10 KEYWORDS (전체 목록은 첨부 CSV 참조)</div>
    <table style="width:100%;border-collapse:collapse">
      <thead><tr style="background:#111620">
        <th style="padding:6px 12px;text-align:left;font-size:10px;color:#3f4f66;font-family:monospace;font-weight:400">#</th>
        <th style="padding:6px 12px;text-align:left;font-size:10px;color:#3f4f66;font-family:monospace;font-weight:400">키워드</th>
        <th style="padding:6px 12px;text-align:left;font-size:10px;color:#3f4f66;font-family:monospace;font-weight:400">빈도</th>
      </tr></thead>
      <tbody>{kw_rows}</tbody>
    </table>
  </div>

  {"<div style='background:#0c1018;border:1px solid #1a2030;padding:16px 20px;margin-bottom:18px'><div style='font-size:10px;color:#3f4f66;letter-spacing:.12em;text-transform:uppercase;margin-bottom:12px;font-family:monospace'>LATEST 5 ARTICLES</div><table style='width:100%;border-collapse:collapse'><thead><tr style='background:#111620'><th style='padding:6px 12px;text-align:left;font-size:10px;color:#3f4f66;font-family:monospace;font-weight:400'>#</th><th style='padding:6px 12px;text-align:left;font-size:10px;color:#3f4f66;font-family:monospace;font-weight:400'>제목</th><th style='padding:6px 12px;text-align:left;font-size:10px;color:#3f4f66;font-family:monospace;font-weight:400'>날짜</th></tr></thead><tbody>" + latest_rows + "</tbody></table></div>" if latest_rows else ""}

  <div style="text-align:center;padding-top:14px;border-top:1px solid #1a2030;font-size:11px;color:#3f4f66;font-family:monospace">
    Generated by NAVER ANALYST &nbsp;·&nbsp; {now}
  </div>
</div>
</body></html>"""

        msg.attach(MIMEText(html, "html", "utf-8"))

        if req.frequency:
            buf = io.StringIO()
            buf.write("\ufeff")
            w = csv.writer(buf)
            w.writerow(["순위", "키워드", "빈도"])
            for i, kw in enumerate(req.frequency, 1):
                w.writerow([i, kw["word"], kw["count"]])
            att = MIMEBase("application", "octet-stream")
            att.set_payload(buf.getvalue().encode("utf-8"))
            encoders.encode_base64(att)
            fname = f"keywords_{req.query}_{datetime.now().strftime('%Y%m%d')}.csv"
            att.add_header("Content-Disposition", f'attachment; filename="{fname}"')
            msg.attach(att)

        context = ssl.create_default_context()
        with smtplib.SMTP(req.smtp_host, req.smtp_port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(req.sender_email, req.sender_password)
            server.sendmail(req.sender_email, req.recipient_email, msg.as_string())

        return {"ok": True, "message": f"{req.recipient_email}으로 발송 완료"}

    except smtplib.SMTPAuthenticationError:
        raise HTTPException(401, "이메일 인증 실패 — Gmail 앱 비밀번호를 확인하세요")
    except smtplib.SMTPException as e:
        raise HTTPException(500, f"SMTP 오류: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"발송 오류: {str(e)}")


_frontend = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(_frontend):
    app.mount("/static", StaticFiles(directory=_frontend), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse(os.path.join(_frontend, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
