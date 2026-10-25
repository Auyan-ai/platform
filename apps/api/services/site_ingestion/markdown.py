from __future__ import annotations

import asyncio

import lxml.html
import trafilatura
from lxml.etree import ParserError


def _page_to_markdown(html: str, url: str) -> tuple[str, str]:
    markdown = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=False,
        include_tables=True,
        favor_precision=True,
    )
    return markdown or "", _title(html)


def _title(html: str) -> str:
    """`<title>` de la página. No se usa `trafilatura.extract_metadata`: calcula también la
    fecha con dateparser, que tarda ~2,5 s en cargar la primera vez y aquí no hace falta."""
    try:
        return (lxml.html.fromstring(html).findtext(".//title") or "").strip()
    except (ParserError, ValueError):
        return ""


def _fragment_to_markdown(html: str) -> str:
    markdown = trafilatura.extract(
        f"<html><body><article>{html}</article></body></html>",
        output_format="markdown",
        include_links=False,
        include_tables=True,
        favor_recall=True,
    )
    return markdown or ""


async def page_to_markdown(html: str, url: str) -> tuple[str, str]:
    return await asyncio.to_thread(_page_to_markdown, html, url)


async def fragment_to_markdown(html: str) -> str:
    if not html.strip():
        return ""
    return await asyncio.to_thread(_fragment_to_markdown, html)
