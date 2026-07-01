#!/usr/bin/env python3
"""
Парсер Telegram-проекта через веб-версию (web.telegram.org).

Не требует api_id / api_hash с my.telegram.org — только номер телефона
и код из Telegram (как при обычном входе в веб-версию).
"""

from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

from tg_utils import (
    BOT_COMMANDS,
    EntityRecord,
    build_report,
    entity_key,
    extract_links_from_text,
    normalize_telegram_url,
    parse_telegram_target,
    register_links,
    save_entities_csv,
    save_json,
    save_summary_md,
    slugify_seed,
)

WEB_URL = "https://web.telegram.org/k/"
LOGIN_TEXTS = [
    "Log in by phone Number",
    "LOG IN BY PHONE NUMBER",
    "Войти по номеру телефона",
    "Войти по номеру",
    "Phone Number",
]
NEXT_TEXTS = ["Next", "Далее", "NEXT"]
PASSWORD_TEXTS = ["Password", "Пароль", "Enter your password", "Введите пароль"]


def click_first_visible(page: Page, texts: list[str], timeout_ms: int = 5000) -> bool:
    for text in texts:
        loc = page.get_by_text(text, exact=False)
        try:
            if loc.count() > 0:
                loc.first.click(timeout=timeout_ms)
                return True
        except PlaywrightTimeout:
            continue
    return False


def is_logged_in(page: Page) -> bool:
    try:
        if page.locator("#column-left").count() > 0:
            return True
        if page.locator(".sidebar-left").count() > 0:
            return True
        if page.locator(".chat-list").count() > 0:
            return True
    except Exception:
        pass
    return False


def fill_code(page: Page, code: str) -> None:
    code = re.sub(r"\D", "", code)
    inputs = page.locator("input.input-field-input")
    if inputs.count() >= len(code) and len(code) in {5, 6}:
        for idx, digit in enumerate(code):
            inputs.nth(idx).fill(digit)
        return
    single = page.locator('input[type="tel"], input.input-field-input').last
    single.fill(code)


def login_web(
    page: Page,
    phone: str,
    code: str = "",
    password: str = "",
    wait_code_seconds: int = 180,
    request_code_only: bool = False,
) -> None:
    page.goto(WEB_URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)

    if is_logged_in(page):
        print("Уже вошли в Telegram Web.")
        return

    if not click_first_visible(page, LOGIN_TEXTS):
        page.get_by_role("button", name=re.compile("phone|телефон|log in|войти", re.I)).first.click(
            timeout=8000
        )

    page.wait_for_timeout(1000)
    phone_input = page.locator('input[type="tel"]').first
    phone_input.click()
    phone_input.fill(phone)
    click_first_visible(page, NEXT_TEXTS) or page.keyboard.press("Enter")
    page.wait_for_timeout(2000)

    if request_code_only and not code:
        print(f"Код отправлен на {phone}. Пришлите код в чат.")
        return

    if code:
        fill_code(page, code)
        click_first_visible(page, NEXT_TEXTS) or page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
    else:
        print(f"Код отправлен на {phone}. Жду код до {wait_code_seconds}s...")
        deadline = time.time() + wait_code_seconds
        while time.time() < deadline:
            env_code = os.getenv("TG_CODE", "").strip()
            if env_code:
                code = env_code
                break
            page.wait_for_timeout(1000)
        if not code:
            raise SystemExit("Код не получен. Запустите с --code КОД или TG_CODE=КОД")

    if password or os.getenv("TG_PASSWORD", "").strip():
        pwd = password or os.getenv("TG_PASSWORD", "").strip()
        try:
            pwd_input = page.locator('input[type="password"]').first
            pwd_input.wait_for(timeout=5000)
            pwd_input.fill(pwd)
            click_first_visible(page, NEXT_TEXTS) or page.keyboard.press("Enter")
        except PlaywrightTimeout:
            pass

    page.locator("#column-left, .sidebar-left, .chat-list").first.wait_for(timeout=120000)
    print("Вход в Telegram Web выполнен.")


def parse_members_count(text: str) -> int | None:
    if not text:
        return None
    normalized = text.lower().replace("\xa0", " ").replace(",", "").replace(" ", "")
    match = re.search(r"(\d+(?:\.\d+)?)(k|m|тыс|млн)?", normalized)
    if not match:
        return None
    value = float(match.group(1))
    suffix = match.group(2) or ""
    if suffix in {"k", "тыс"}:
        value *= 1000
    elif suffix in {"m", "млн"}:
        value *= 1_000_000
    return int(value)


def scrape_public_preview(page: Page, username: str) -> dict[str, Any]:
    url = f"https://t.me/s/{username}"
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(1500)

    return page.evaluate(
        """() => {
            const title = document.querySelector('meta[property="og:title"]')?.content || '';
            const desc = document.querySelector('.tgme_channel_info_description')?.innerText || '';
            const members = document.querySelector('.tgme_channel_info_counter .counter_value')?.innerText || '';
            const messages = Array.from(document.querySelectorAll('.tgme_widget_message_text'))
                .map(n => n.innerText.trim()).filter(Boolean);
            const links = Array.from(document.querySelectorAll('a[href*="t.me"]'))
                .map(a => a.href);
            return { title, desc, members, messages, links };
        }"""
    )


def scrape_web_chat(page: Page, username: str, max_messages: int, scroll_rounds: int) -> dict[str, Any]:
    page.goto(f"{WEB_URL}#@{username}", wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)

    title = ""
    subtitle = ""
    try:
        title = page.locator(".chat-info .peer-title, .person .peer-title").first.inner_text(timeout=5000)
        subtitle = page.locator(".chat-info .header-subtitle, .chat-info-subtitle").first.inner_text(
            timeout=3000
        )
    except PlaywrightTimeout:
        pass

    description = ""
    try:
        page.locator(".chat-info-container, .chat-info").first.click(timeout=3000)
        page.wait_for_timeout(800)
        bio = page.locator(".profile-content .bio, .profile-name .bio, .sidebar-right .bio")
        if bio.count():
            description = bio.first.inner_text(timeout=2000)
        page.keyboard.press("Escape")
    except PlaywrightTimeout:
        pass

    for _ in range(scroll_rounds):
        page.evaluate(
            """() => {
                const el = document.querySelector('.bubbles-inner')
                    || document.querySelector('.scrollable-y')
                    || document.querySelector('.bubbles');
                if (el) el.scrollTop = 0;
            }"""
        )
        page.wait_for_timeout(700)

    payload = page.evaluate(
        """(limit) => {
            const nodes = Array.from(document.querySelectorAll('.bubble-content-wrapper, .message'));
            const texts = nodes.map(n => (n.innerText || '').trim()).filter(t => t.length > 0);
            const uniq = [];
            const seen = new Set();
            for (const t of texts) {
                if (seen.has(t)) continue;
                seen.add(t);
                uniq.push(t);
            }
            const buttons = Array.from(document.querySelectorAll(
                '.reply-markup-button, .keyboard-button, .btn-menu-item'
            )).map(b => ({
                text: (b.innerText || '').trim(),
                url: b.getAttribute('href') || ''
            })).filter(b => b.text || b.url);
            const links = Array.from(document.querySelectorAll('a[href*="t.me"]'))
                .map(a => a.href);
            return {
                messages: uniq.slice(-limit),
                buttons,
                links
            };
        }""",
        max_messages,
    )
    payload["title"] = title
    payload["subtitle"] = subtitle
    payload["description"] = description
    return payload


def send_bot_commands(page: Page, username: str, wait_seconds: float) -> list[dict[str, Any]]:
    page.goto(f"{WEB_URL}#@{username}", wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2000)
    replies: list[dict[str, Any]] = []

    for command in BOT_COMMANDS:
        try:
            editor = page.locator('[contenteditable="true"]').last
            editor.click(timeout=5000)
            editor.fill(command)
            page.keyboard.press("Enter")
            page.wait_for_timeout(int(wait_seconds * 1000))
            chunk = page.evaluate(
                """() => {
                    const nodes = Array.from(document.querySelectorAll('.bubble-content-wrapper, .message'));
                    const last = nodes.slice(-8).map(n => (n.innerText || '').trim()).filter(Boolean);
                    const buttons = Array.from(document.querySelectorAll('.reply-markup-button, .keyboard-button'))
                        .map(b => ({ text: (b.innerText || '').trim(), url: b.getAttribute('href') || '' }));
                    const links = Array.from(document.querySelectorAll('a[href*="t.me"]')).map(a => a.href);
                    return { messages: last, buttons, links };
                }"""
            )
            chunk["trigger"] = command
            replies.append(chunk)
        except PlaywrightTimeout:
            continue
    return replies


class WebProjectParser:
    def __init__(
        self,
        page: Page,
        *,
        max_depth: int = 2,
        max_messages: int = 200,
        max_sample_messages: int = 15,
        scroll_rounds: int = 12,
        bot_wait_seconds: float = 4.0,
        use_public_fallback: bool = True,
        delay_seconds: float = 1.0,
    ) -> None:
        self.page = page
        self.max_depth = max_depth
        self.max_messages = max_messages
        self.max_sample_messages = max_sample_messages
        self.scroll_rounds = scroll_rounds
        self.bot_wait_seconds = bot_wait_seconds
        self.use_public_fallback = use_public_fallback
        self.delay_seconds = delay_seconds
        self.records: dict[str, EntityRecord] = {}
        self.queue: list[tuple[str, int, str]] = []
        self.visited: set[str] = set()

    def enqueue(self, url: str, depth: int, parent: str) -> None:
        if depth > self.max_depth:
            return
        try:
            kind, value, canonical = parse_telegram_target(url)
        except ValueError:
            return
        key = entity_key(kind, value)
        if key in self.visited:
            if key in self.records and parent and parent not in self.records[key].discovered_from:
                self.records[key].discovered_from.append(parent)
            return
        self.visited.add(key)
        self.queue.append((canonical, depth, parent))

    def crawl(self, seed_url: str) -> list[EntityRecord]:
        self.enqueue(normalize_telegram_url(seed_url), 0, "")
        while self.queue:
            url, depth, parent = self.queue.pop(0)
            self._process(url, depth, parent)
            if self.delay_seconds > 0:
                time.sleep(self.delay_seconds)
        return list(self.records.values())

    def _process(self, url: str, depth: int, parent: str) -> None:
        try:
            kind, value, canonical = parse_telegram_target(url)
        except ValueError:
            return

        key = entity_key(kind, value)
        record = EntityRecord(
            key=key,
            url=canonical,
            username=value if kind == "username" else "",
            invite_hash=value if kind == "invite" else "",
            depth=depth,
            discovered_from=[parent] if parent else [],
        )
        self.records[key] = record

        if kind == "invite":
            record.entity_type = "invite"
            record.errors.append("Инвайт-ссылка — нужен ручной вход в чат")
            return

        username = value.lower()
        if username.endswith("bot"):
            record.is_bot = True
            record.entity_type = "bot"

        try:
            data = scrape_web_chat(self.page, username, self.max_messages, self.scroll_rounds)
        except Exception as exc:
            record.errors.append(f"web: {exc}")
            data = {}

        if (not data.get("messages")) and self.use_public_fallback:
            try:
                public = scrape_public_preview(self.page, username)
                data = {**data, **public}
                if public.get("messages"):
                    record.entity_type = record.entity_type or "channel"
            except Exception as exc:
                record.errors.append(f"public: {exc}")

        record.title = data.get("title", "") or username
        record.description = data.get("description") or data.get("desc", "") or ""
        members_raw = data.get("subtitle", "") or data.get("members", "")
        record.members_count = parse_members_count(members_raw)

        messages = data.get("messages", []) or []
        record.messages_scanned = len(messages)
        for text in messages[-self.max_sample_messages :]:
            record.sample_messages.append({"text": text, "links": sorted(extract_links_from_text(text))})

        all_text = "\n".join(messages + [record.title, record.description])
        register_links(record, all_text, depth, self.enqueue)

        for link in data.get("links", []) or []:
            if "t.me" in link:
                self.enqueue(link, depth + 1, record.url)

        for button in data.get("buttons", []) or []:
            record.inline_buttons.append(button)
            btn_url = button.get("url", "")
            if btn_url and "t.me" in btn_url:
                self.enqueue(btn_url, depth + 1, record.url)

        if record.is_bot:
            try:
                replies = send_bot_commands(self.page, username, self.bot_wait_seconds)
                record.bot_replies = replies
                for reply in replies:
                    for text in reply.get("messages", []):
                        register_links(record, text, depth, self.enqueue)
                    for button in reply.get("buttons", []):
                        record.inline_buttons.append(button)
                        btn_url = button.get("url", "")
                        if btn_url and "t.me" in btn_url:
                            self.enqueue(btn_url, depth + 1, record.url)
            except Exception as exc:
                record.errors.append(f"bot: {exc}")

        if not record.entity_type:
            record.entity_type = "chat"


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Парсер Telegram через web.telegram.org (без api_id).")
    p.add_argument("--url", help="Стартовая ссылка, напр. https://t.me/instachat6")
    p.add_argument("--phone", help="Телефон +79...")
    p.add_argument("--code", help="Код из Telegram")
    p.add_argument("--password", help="Пароль 2FA (если есть)")
    p.add_argument("--login-only", action="store_true", help="Только войти, без парсинга")
    p.add_argument("--request-code", action="store_true", help="Только запросить код и выйти")
    p.add_argument("--max-depth", type=int, default=2)
    p.add_argument("--max-messages", type=int, default=200)
    p.add_argument("--max-sample-messages", type=int, default=15)
    p.add_argument("--scroll-rounds", type=int, default=12)
    p.add_argument("--bot-wait-seconds", type=float, default=4.0)
    p.add_argument("--delay", type=float, default=1.5)
    p.add_argument("--headless", action="store_true", help="Без окна браузера")
    p.add_argument("--profile-dir", default="sessions/tg_web_profile")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--out-dir", default="output")
    p.add_argument("--wait-code-seconds", type=int, default=180)
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    load_dotenv(args.env_file)

    phone = (args.phone or os.getenv("TG_PHONE", "")).strip()
    code = (args.code or os.getenv("TG_CODE", "")).strip()
    password = (args.password or os.getenv("TG_PASSWORD", "")).strip()

    if not phone:
        raise SystemExit("Укажите --phone или TG_PHONE в .env")

    profile_dir = Path(args.profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=args.headless,
            viewport={"width": 1400, "height": 900},
            locale="ru-RU",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        login_web(
            page,
            phone,
            code=code,
            password=password,
            wait_code_seconds=args.wait_code_seconds,
            request_code_only=args.request_code,
        )

        if args.request_code or args.login_only:
            print(f"Сессия сохранена в {profile_dir}")
            context.close()
            return

        if not args.url:
            raise SystemExit("Для парсинга укажите --url")

        parser = WebProjectParser(
            page,
            max_depth=args.max_depth,
            max_messages=args.max_messages,
            max_sample_messages=args.max_sample_messages,
            scroll_rounds=args.scroll_rounds,
            bot_wait_seconds=args.bot_wait_seconds,
            delay_seconds=args.delay,
        )
        entities = parser.crawl(args.url)
        context.close()

    report = build_report(normalize_telegram_url(args.url), entities, parser_mode="telegram_web")
    out_dir = Path(args.out_dir)
    slug = slugify_seed(args.url)
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = out_dir / f"{slug}_web_{ts}"

    save_json(report, base.with_suffix(".json"))
    save_entities_csv(report, base.with_name(base.name + "_entities").with_suffix(".csv"))
    save_summary_md(report, base.with_name(base.name + "_summary").with_suffix(".md"))

    elapsed = time.time() - started
    print(f"Готово за {elapsed:.1f}s")
    print(f"Сущностей: {report.total_entities}")
    print(f"JSON: {base.with_suffix('.json')}")
    print(f"CSV:  {base.with_name(base.name + '_entities').with_suffix('.csv')}")
    print(f"MD:   {base.with_name(base.name + '_summary').with_suffix('.md')}")


if __name__ == "__main__":
    main()
