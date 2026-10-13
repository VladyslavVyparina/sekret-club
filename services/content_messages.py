"""
Форматування та відправка матеріалів у Telegram (курси, уроки, ефіри тощо).
Ліміти Telegram: текст до 4096; підпис до фото/відео до 1024; розмір файлу до ~50 MB (залежить від типу).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import parse_qs, urlparse

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

try:
    from aiogram.types import LinkPreviewOptions
except ImportError:  # pragma: no cover
    LinkPreviewOptions = None  # type: ignore[misc, assignment]

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
# Для адмін-форми: зручно обмежити кількість файлів за один раз
MAX_ATTACHMENTS_PER_SAVE = 10

_TELEGRAM_HINT = (
    "Ліміти Telegram: текст повідомлення до 4096 символів; підпис до фото/відео до 1024; "
    "можна прикріпити до 10 файлів за раз (фото, відео, документи)."
)


def telegram_limits_hint() -> str:
    return _TELEGRAM_HINT


def parse_attachments_json(raw: str | None) -> list[dict[str, Any]]:
    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get("file_id")]
    except Exception:
        pass
    return []


def attachments_to_json(items: list[dict[str, Any]]) -> str | None:
    if not items:
        return None
    return json.dumps(items, ensure_ascii=False)


def clean_display_title(title: str | None) -> str:
    t = (title or "").strip()
    # «Курс "…"» у назві з БД — лишаємо лише саму назву
    t = re.sub(r"^(?i)курс\s+", "", t).strip()
    if len(t) >= 2 and t[0] in '"«' and t[-1] in '"»':
        t = t[1:-1].strip()
    t = re.sub(r"^\s*[^\w\s\u0400-\u04FF]*\s*", "", t)  # прибрати емодзі на початку
    t = re.sub(
        r"^(лекція|урок)\s*№?\s*\d+\s*[:.\-–]\s*",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    return t.strip() or "—"


def extract_urls(text: str | None) -> list[str]:
    if not text or not str(text).strip():
        return []
    return re.findall(r"https?://[^\s<]+", str(text))


def _first_streaming_url_for_preview(text: str | None) -> str | None:
    """Перше відео-посилання в тексті — для прев’ю, якщо в повідомленні кілька URL."""
    for u in extract_urls(text):
        if youtube_video_id(u):
            return u
    for u in extract_urls(text):
        lu = u.lower()
        if any(h in lu for h in ("vimeo.com", "rutube.ru", "tiktok.com")):
            return u
    return None


def message_kwargs_for_link_preview(
    text: str | None,
    *,
    default_protect_content: bool = False,
    for_edit_message: bool = False,
) -> dict[str, Any]:
    """
    Ключі для send_message / answer або edit_message_text:
    — якщо є http(s) URL: parse_mode=None (щоб не ламати прев’ю через HTML бота) + прев’ю;
    — для звичайних повідомлень: protect_content=False (Telegram стабільніше будує прев’ю);
    — для edit_message_text не передаємо protect_content (параметра немає в API).
    — link_preview_options.url: явно перше «відеохостингове» посилання, якщо в тексті кілька URL
      (інакше Telegram будує прев’ю для першого за порядком символів, зокрема з опису).
    """
    urls = extract_urls(text)
    if not urls:
        out: dict[str, Any] = {}
        if not for_edit_message:
            out["protect_content"] = default_protect_content
        return out
    out = {
        "parse_mode": None,
    }
    if not for_edit_message:
        out["protect_content"] = False
    preview_url = _first_streaming_url_for_preview(text) or urls[0]
    if LinkPreviewOptions is not None:
        out["link_preview_options"] = LinkPreviewOptions(
            is_disabled=False,
            url=preview_url,
            prefer_large_media=True,
        )
    else:
        out["disable_web_page_preview"] = False
    return out


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).strip()


def ordered_unique_urls(*parts: str | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        u = (p or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def youtube_video_id(url: str) -> str | None:
    """Ідентифікатор ролика YouTube для злиття різних форматів одного й того ж відео."""
    s = (url or "").strip()
    if not s:
        return None
    try:
        p = urlparse(s)
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (p.path or "").strip("/")
        segs = path.split("/") if path else []

        if host == "youtu.be" and segs:
            vid = segs[0].split("?")[0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                return vid

        if host == "m.youtube.com":
            host = "youtube.com"
        if host in ("youtube.com", "youtube-nocookie.com"):
            if segs and segs[0] == "watch":
                v = (parse_qs(p.query).get("v") or [None])[0]
                if v and re.fullmatch(r"[A-Za-z0-9_-]{11}", v):
                    return v
            if len(segs) >= 2 and segs[0] in ("embed", "shorts", "live"):
                vid = segs[1].split("?")[0]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                    return vid
    except Exception:
        return None
    return None


def _pick_preferred_youtube_url(candidates: list[str]) -> str:
    """Один канонічний вигляд без дубльованих query-параметрів."""
    if not candidates:
        return ""
    for c in candidates:
        vid = youtube_video_id(c)
        if vid:
            return f"https://youtu.be/{vid}"
    low = [c for c in candidates if "youtu.be/" in c.lower()]
    if low:
        return min(low, key=len)
    return min(candidates, key=len)


def merge_legacy_link_and_video_url(
    legacy_link: str | None,
    legacy_video_url: str | None,
    urls_in_desc: list[str],
) -> list[str]:
    """
    Якщо в адмінці заповнено «Посилання», а в БД лишилось старе поле video_url з іншим YouTube-ID
    (імпорт/чернетка), показуємо лише посилання з адмінки + URL з опису — без другого ролика.
    """
    link = (legacy_link or "").strip()
    vurl = (legacy_video_url or "").strip()
    if link and vurl:
        lid, vid = youtube_video_id(link), youtube_video_id(vurl)
        if lid and vid and lid != vid:
            return ordered_unique_urls(link, *urls_in_desc)
    return ordered_unique_urls(legacy_link, legacy_video_url, *urls_in_desc)


def dedupe_video_platform_urls(urls: list[str]) -> list[str]:
    """
    Одне посилання на одне YouTube-відео: у БД часто дублюються «Посилання» (watch?v=…)
    і старе поле video_url (youtu.be/…).
    """
    cleaned = [(u or "").strip() for u in urls if (u or "").strip()]
    if len(cleaned) < 2:
        return cleaned

    by_yt: dict[str, list[str]] = defaultdict(list)
    for u in cleaned:
        yid = youtube_video_id(u)
        if yid:
            by_yt[yid].append(u)

    canonical = {yid: _pick_preferred_youtube_url(lst) for yid, lst in by_yt.items()}

    out: list[str] = []
    seen_yt: set[str] = set()
    seen_other: set[str] = set()
    for u in cleaned:
        yid = youtube_video_id(u)
        if yid:
            if yid in seen_yt:
                continue
            seen_yt.add(yid)
            out.append(canonical[yid])
        else:
            ul = u.lower()
            if ul in seen_other:
                continue
            seen_other.add(ul)
            out.append(u)
    return out


def prioritize_rich_video_urls(urls: list[str]) -> list[str]:
    """
    Telegram будує одне прев’ю на перше посилання в тексті. Якщо в «link» додатковий
    матеріал (Диск, Notion, Zoom…), а YouTube у «video_url» — раніше YouTube йшов другим
    і залишалось слабке прев’ю або без великого відео. Ставимо відомі відеохости спочатку.
    """
    if len(urls) < 2:
        return urls

    def is_video_host(u: str) -> bool:
        lu = u.lower()
        return any(
            h in lu
            for h in (
                "youtu.be",
                "youtube.com",
                "youtube-nocookie.com",
                "vimeo.com",
                "rutube.ru",
                "tiktok.com",
            )
        )

    vids = [u for u in urls if is_video_host(u)]
    rest = [u for u in urls if not is_video_host(u)]
    return vids + rest


def description_for_display(raw: str | None, urls_to_strip: list[str]) -> str | None:
    """Текст для блоку «Опис:» без URL і без залишків «▶️ Відео:»."""
    t = raw or ""
    strip_ids = {i for u in urls_to_strip if (i := youtube_video_id(u))}
    for u in urls_to_strip:
        if u:
            t = t.replace(u, "")
    if strip_ids:
        for found in extract_urls(t):
            fid = youtube_video_id(found)
            if fid and fid in strip_ids:
                t = t.replace(found, "")
    t = re.sub(r"▶️\s*Відео\s*:\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"(?i)^\s*відео\s*:\s*", "", t)
    t = _normalize_ws(t)
    return t if t else None


def _join_top_desc_bottom(
    top_parts: list[str],
    desc_block: str | None,
    bottom: str,
) -> str:
    top = "\n\n".join(top_parts)
    chunks: list[str] = [top]
    if desc_block is not None:
        chunks.append(f"Опис: {desc_block}")
    if bottom:
        chunks.append(bottom)
    return "\n\n".join(chunks)


def _shrink_name_until_fits(top_parts: list[str], *, name: str, bottom: str) -> str:
    """Зберігає bottom (URL) повністю; скорочує лише рядок «Назва: …»."""
    tname = name
    min_name = 12
    while True:
        top_parts[-1] = f"Назва: {tname}"
        text = _join_top_desc_bottom(top_parts, None, bottom)
        if len(text) <= TEXT_LIMIT:
            return text
        if len(tname) <= min_name:
            return text
        cut = max(min_name - 1, len(tname) - max(8, (len(text) - TEXT_LIMIT) + 2))
        tname = tname[:cut].rstrip() + "…"


def format_entity_message(
    *,
    course: str | None,
    name: str,
    description: str | None,
    video_urls: list[str] | None = None,
) -> str:
    """
    Збирає текст картки матеріалу. Блоки з URL («▶️ Відео») ніколи не обрізаються посередині:
    спочатку відрізаємо/скорочуємо лише опис (за потреби — назву), щоб прев’ю посилань у Telegram
    залишалось валідним.
    """
    top_parts: list[str] = []
    if course:
        top_parts.append(f"Курс: «{course}»")
    top_parts.append(f"Назва: {name}")
    top = "\n\n".join(top_parts)

    video_lines = [
        f"▶️ Відео: {(u or '').strip()}"
        for u in (video_urls or [])
        if (u or "").strip()
    ]
    bottom = "\n\n".join(video_lines) if video_lines else ""

    desc = (description or "").strip()

    if not desc:
        text = _join_top_desc_bottom(top_parts, None, bottom)
        if len(text) <= TEXT_LIMIT:
            return text
        if not bottom:
            return text[:TEXT_LIMIT]
        return _shrink_name_until_fits(list(top_parts), name=name, bottom=bottom)

    # Є опис: підганяємо довжину опису, щоб URL у «▶️ Відео» потрапили в повідомлення повністю.
    sep_top_desc = 2 + len("Опис: ")
    sep_desc_bottom = 2 if bottom else 0
    fixed = len(top) + sep_top_desc + sep_desc_bottom + len(bottom)
    max_desc = TEXT_LIMIT - fixed
    if max_desc >= len(desc):
        return _join_top_desc_bottom(top_parts, desc, bottom)
    if max_desc < 1:
        # Опис не вміщується — показуємо топ + відео; назву звужуємо лише якщо треба.
        bare = _join_top_desc_bottom(top_parts, None, bottom)
        if len(bare) <= TEXT_LIMIT:
            return bare
        if not bottom:
            return bare[:TEXT_LIMIT]
        return _shrink_name_until_fits(list(top_parts), name=name, bottom=bottom)
    ellipsis = "…"
    keep = max_desc - len(ellipsis)
    if keep < 1:
        bare = _join_top_desc_bottom(top_parts, None, bottom)
        if len(bare) <= TEXT_LIMIT:
            return bare
        if not bottom:
            return bare[:TEXT_LIMIT]
        return _shrink_name_until_fits(list(top_parts), name=name, bottom=bottom)
    trimmed = desc[:keep].rstrip() + ellipsis
    return _join_top_desc_bottom(top_parts, trimmed, bottom)


async def send_content_bundle(
    bot: Bot,
    chat_id: int,
    *,
    course: str | None,
    title: str,
    description: str | None,
    attachments: list[dict[str, Any]],
    legacy_video_file_id: str | None,
    legacy_photo_file_id: str | None,
    legacy_video_url: str | None,
    legacy_link: str | None = None,
    reply_markup: InlineKeyboardMarkup | None,
    protect_content: bool = False,
) -> list[int]:
    sent_ids: list[int] = []

    desc_raw = description or ""
    urls_in_desc = extract_urls(desc_raw)
    preview_urls = dedupe_video_platform_urls(
        merge_legacy_link_and_video_url(legacy_link, legacy_video_url, urls_in_desc)
    )
    preview_urls = prioritize_rich_video_urls(preview_urls)

    body_desc = description_for_display(desc_raw, preview_urls)
    body = format_entity_message(
        course=course,
        name=clean_display_title(title),
        description=body_desc,
        video_urls=preview_urls if preview_urls else None,
    )

    text_kw: dict[str, Any] = {"reply_markup": reply_markup}
    text_kw.update(
        message_kwargs_for_link_preview(body, default_protect_content=protect_content)
    )
    msg = await bot.send_message(chat_id, body, **text_kw)
    sent_ids.append(msg.message_id)

    media_to_send: list[tuple[str, str]] = []
    for a in attachments:
        t = (a.get("type") or "").strip().lower()
        fid = a.get("file_id")
        if not fid:
            continue
        if t in ("photo", "video", "document"):
            media_to_send.append((t, str(fid)))

    if not media_to_send and legacy_video_file_id:
        media_to_send.append(("video", legacy_video_file_id))
    if not any(m[0] == "photo" for m in media_to_send) and legacy_photo_file_id:
        media_to_send.insert(0, ("photo", legacy_photo_file_id))

    for mtype, fid in media_to_send:
        if mtype == "photo":
            m = await bot.send_photo(chat_id, fid, protect_content=protect_content)
            sent_ids.append(m.message_id)
        elif mtype == "video":
            m = await bot.send_video(chat_id, fid, protect_content=protect_content)
            sent_ids.append(m.message_id)
        else:
            m = await bot.send_document(chat_id, fid, protect_content=protect_content)
            sent_ids.append(m.message_id)

    return sent_ids
