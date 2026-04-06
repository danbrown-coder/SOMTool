"""Web discovery via DuckDuckGo search (demo)."""
from __future__ import annotations


def search_web_snippets(query: str, max_results: int = 10) -> list[dict[str, str]]:
    """Return title, url, snippet from DuckDuckGo."""
    try:
        from ddgs import DDGS
        results = list(DDGS().text(query, max_results=max_results))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in results
            if r.get("title") and r.get("href")
        ]
    except Exception:
        return _fallback_search(query, max_results)


def _fallback_search(query: str, max_results: int = 10) -> list[dict[str, str]]:
    """Fallback using requests + BeautifulSoup if ddgs isn't available."""
    try:
        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import unquote, urlparse, parse_qs

        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            timeout=15,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out: list[dict[str, str]] = []
        for div in soup.select(".result"):
            if len(out) >= max_results:
                break
            a = div.select_one(".result__a")
            if not a:
                continue
            title = a.get_text(strip=True)
            raw_href = a.get("href", "")
            href = raw_href
            if raw_href.startswith("//duckduckgo.com/l/"):
                parsed = parse_qs(urlparse(raw_href).query)
                uddg = parsed.get("uddg", [""])[0]
                if uddg:
                    href = unquote(uddg)
            if not title or not href:
                continue
            sn = div.select_one(".result__snippet")
            snippet = sn.get_text(" ", strip=True) if sn else ""
            out.append({"title": title, "url": href, "snippet": snippet})
        return out
    except Exception:
        return []


def build_search_queries(
    event_name: str,
    description: str,
    audience: str,
    target_role: str = "",
) -> list[str]:
    short = (description or "")[:100].strip()
    role_label = target_role.replace("_", " ") if target_role else "speaker panelist"
    return [
        f"{event_name} LinkedIn {role_label}",
        f"{audience} {role_label} professionals Thousand Oaks",
        f"Cal Lutheran School of Management {event_name} {role_label}",
        f"site:linkedin.com/in {event_name} {role_label}"[:80],
        f"{short} {role_label}" if short else f"{event_name} {role_label}",
    ]


def clean_queries(qs: list[str]) -> list[str]:
    return [q.strip() for q in qs if q and len(q.strip()) > 3][:5]
