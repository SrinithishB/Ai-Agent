"""
jarvis/tools/web_tools.py

Web searching and page reading tools for JARVIS.
"""

import urllib.request
import urllib.parse
import re

def search_web(query: str) -> str:
    """
    Performs a DuckDuckGo search for the given query and returns a list of results.
    Each result contains a Title, a Link, and a Snippet of page content.
    Use this to get up-to-date information from the internet.

    Args:
        query (str): The search query keywords or question.

    Returns:
        str: A string summarizing search results.
    """
    import datetime
    current_year = datetime.datetime.now().year

    # Auto-append the current year to "who is" / "current X" style queries so
    # DuckDuckGo returns up-to-date results rather than stale articles.
    factual_triggers = {"who", "current", "cm", "president", "minister", "pm", "ceo", "head", "governor", "chief"}
    query_lower = query.lower()
    if any(t in query_lower for t in factual_triggers) and str(current_year) not in query_lower:
        query = f"{query} {current_year}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
            titles = re.findall(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
            snippets = re.findall(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL)
            
            results = []
            for t_match, s_match in zip(titles, snippets):
                link = t_match[0]
                if 'uddg=' in link:
                    link = urllib.parse.unquote(link.split('uddg=')[1].split('&')[0])
                
                title = re.sub(r'<[^>]+>', '', t_match[1]).strip()
                snippet = re.sub(r'<[^>]+>', '', s_match).strip()
                
                results.append(f"Title  : {title}\nLink   : {link}\nSnippet: {snippet}\n" + "-" * 40)
            
            if not results:
                return "No search results found."
                
            # Limit search outputs to avoid pre-fill prompt latency on CPU
            # Keeping only top 4 to reduce noise/conflicting snippets for small models
            return "\n\n".join(results[:4])
    except Exception as e:
        return f"Error searching the web: {str(e)}"


def read_web_page(url: str) -> str:
    """
    Fetches the content of a web page/URL and returns its clean readable text content.
    Use this to read specific articles or pages returned by search results to get detailed answers.

    Args:
        url (str): The absolute URL of the web page to retrieve.

    Returns:
        str: Plain text contents of the web page.
    """
    # Simple validation
    if not url.startswith("http://") and not url.startswith("https://"):
        return "Error: Invalid URL. URL must start with http:// or https://"
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            # Extract content from inside <body> if present
            body_match = re.search(r'<body.*?>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
            content = body_match.group(1) if body_match else html
            
            # Remove comments, scripts, styles, navigation, headers, footers, and other noise
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
            content = re.sub(r'<script.*?>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<style.*?>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<head.*?>.*?</head>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<nav.*?>.*?</nav>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<header.*?>.*?</header>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<footer.*?>.*?</footer>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<svg.*?>.*?</svg>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<noscript.*?>.*?</noscript>', '', content, flags=re.DOTALL | re.IGNORECASE)
            
            # Strip tags and normalize white space
            text = re.sub(r'<[^>]+>', '\n', content)
            lines = [line.strip() for line in text.splitlines()]
            clean_text = "\n".join([line for line in lines if line])
            
            # Limit the output length to avoid blowing model context window
            if len(clean_text) > 4000:
                clean_text = clean_text[:4000] + "\n\n...[content truncated to save space]..."
                
            return clean_text
    except Exception as e:
        return f"Error reading web page: {str(e)}"


# Expose tools for registration
TOOLS = [search_web, read_web_page]
