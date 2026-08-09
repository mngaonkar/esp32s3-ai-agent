"""Tavily web search client.

Tavily is used rather than a raw HTTP fetch because it returns short extracted
snippets instead of full pages. A microcontroller has no HTML parser and no
reason to pull a megabyte of markup across the radio to answer one question.
"""

import gc

from . import httpc

_ENDPOINT = "https://api.tavily.com/search"


class SearchError(Exception):
    pass


class TavilyClient:
    def __init__(self, cfg, cadata=None):
        self.api_key = cfg.get("tavily_api_key", "")
        self.endpoint = cfg.get("tavily_endpoint", _ENDPOINT)
        self.default_results = int(cfg.get("tavily_max_results", 5))
        self.depth = cfg.get("tavily_search_depth", "basic")
        self.timeout = int(cfg.get("request_timeout", 45))
        self.cadata = cadata

    @property
    def enabled(self):
        return bool(self.api_key)

    def search(self, query, max_results=None, topic="general", days=None,
               include_answer=True, include_domains=None):
        if not self.api_key:
            raise SearchError(
                "no tavily_api_key configured; set it in /config.json")
        if not query:
            raise SearchError("query is empty")

        payload = {
            "query": query,
            "max_results": max(1, min(int(max_results or self.default_results), 10)),
            "search_depth": self.depth,
            "include_answer": include_answer,
            # Raw page content would be tens of KB per result and is never
            # worth the radio time here; the snippets are enough.
            "include_raw_content": False,
            "include_images": False,
            "topic": topic,
        }
        if topic == "news" and days:
            payload["days"] = int(days)
        if include_domains:
            payload["include_domains"] = include_domains

        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }

        gc.collect()
        try:
            resp = httpc.post(self.endpoint, headers=headers, body=payload,
                              timeout=self.timeout, cadata=self.cadata)
        except OSError as exc:
            raise SearchError("network error reaching Tavily: %s" % exc)

        if resp.status_code == 401:
            raise SearchError("Tavily rejected the API key (HTTP 401)")
        if resp.status_code == 432 or resp.status_code == 429:
            raise SearchError("Tavily quota or rate limit reached (HTTP %d)"
                              % resp.status_code)
        if resp.status_code != 200:
            raise SearchError("Tavily returned HTTP %d: %s"
                              % (resp.status_code, resp.text[:200]))

        try:
            data = resp.json()
        except Exception as exc:
            raise SearchError("could not parse Tavily response: %s" % exc)
        finally:
            resp.content = b""
            gc.collect()

        return data


def format_results(data, snippet_chars=400):
    """Render Tavily JSON as compact text for the model."""
    lines = []
    answer = data.get("answer")
    if answer:
        lines.append("Answer: %s" % answer.strip())
        lines.append("")

    results = data.get("results") or []
    if not results:
        lines.append("No results.")
        return "\n".join(lines)

    lines.append("Sources:")
    for i, item in enumerate(results, 1):
        title = (item.get("title") or "untitled").strip()
        url = (item.get("url") or "").strip()
        content = (item.get("content") or "").strip()
        if len(content) > snippet_chars:
            content = content[:snippet_chars].rstrip() + "..."
        lines.append("[%d] %s" % (i, title))
        lines.append("    %s" % url)
        if content:
            lines.append("    %s" % content)
    return "\n".join(lines)
