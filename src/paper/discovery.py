import hashlib
import json
import re
import time
import uuid
from urllib.parse import urlsplit

import requests
from flask import current_app

from src.database.db import connection, decode
from src.paper.arxiv_client import search_arxiv
from src.paper.semantic_scholar_client import search_semantic_scholar

CACHE_TTL = 600


def identity(paper):
    if paper.get('upload_hash'):
        return 'upload:' + paper['upload_hash']
    if paper.get('arxiv_id'):
        return 'arxiv:' + re.sub(r'v\d+$', '', paper['arxiv_id'])
    url = paper.get('paper_url') or ''
    if 'arxiv.org/abs/' in url:
        return 'arxiv:' + re.sub(r'v\d+$', '', url.split('/abs/')[-1])
    title = re.sub(r'[^\w]', '', paper['title'].casefold())
    return 'title:' + hashlib.sha256(title.encode()).hexdigest()


def public_url(value):
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in ('http', 'https') and parsed.hostname else None
    except ValueError:
        return None


def search_semantic(query, limit=10):
    return search_semantic_scholar(
        query, limit, api_key=current_app.config.get('SEMANTIC_SCHOLAR_API_KEY')
    )


def _query_key(query):
    return ' '.join(query.casefold().split())


def _tokens(query):
    if _query_key(query) == 'ml':
        query = 'machine learning'
    return set(re.findall(r'\w+', query.casefold())) - {
        'the', 'a', 'an', 'of', 'for', 'in', 'on', 'and', 'paper', 'papers', 'research'
    }


def _matches(paper, tokens):
    words = _tokens(' '.join(str(paper.get(field) or '')
                            for field in ('title', 'abstract', 'area')))
    return bool(tokens) and tokens <= words


def _cached(provider, query):
    with connection() as db:
        row = db.execute(
            'SELECT fetched_at,results FROM discovery_cache WHERE provider=? AND query=?',
            (provider, _query_key(query)),
        ).fetchone()
    if row:
        return row['fetched_at'], json.loads(row['results'])
    return None


def _cache_results(provider, query, results):
    with connection() as db:
        db.execute(
            '''INSERT INTO discovery_cache(provider,query,fetched_at,results) VALUES(?,?,?,?)
               ON CONFLICT(provider,query) DO UPDATE SET
               fetched_at=excluded.fetched_at,results=excluded.results''',
            (provider, _query_key(query), time.time(), json.dumps(results)),
        )
        db.execute(
            '''DELETE FROM discovery_cache WHERE provider=? AND query NOT IN
               (SELECT query FROM discovery_cache WHERE provider=?
                ORDER BY fetched_at DESC LIMIT 100)''',
            (provider, provider),
        )


def _saved_results(provider, query):
    tokens = _tokens(query)
    with connection() as db:
        rows = db.execute(
            'SELECT * FROM papers WHERE source=? ORDER BY id DESC', (provider,)
        ).fetchall()
        caches = db.execute(
            'SELECT query,results FROM discovery_cache WHERE provider=? ORDER BY fetched_at DESC',
            (provider,),
        ).fetchall()
    matches = [decode(row) for row in rows if _matches(dict(row), tokens)]
    for row in caches:
        cached_papers = json.loads(row['results'])
        if tokens and tokens <= _tokens(row['query']):
            matches.extend(cached_papers)
        else:
            matches.extend(paper for paper in cached_papers if _matches(paper, tokens))
    return _unique(matches)[:10]


def _fallback(provider, query, cached):
    if cached and cached[1]:
        return cached[1], 'Showing previously saved results for this search.'
    related = _saved_results(provider, query)
    if related:
        return related, 'Showing related papers from previous searches and your saved library.'
    machine_learning = _saved_results(provider, 'machine learning')
    if machine_learning:
        return machine_learning, (
            'Showing previously saved machine-learning papers as a fallback; '
            'these may not match your current query.'
        )
    return [], 'No previously saved matching or machine-learning papers are available yet.'


def _claim_provider(provider):
    now = time.time()
    token = uuid.uuid4().hex
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute(
            'INSERT OR IGNORE INTO discovery_provider_state(provider) VALUES(?)', (provider,)
        )
        state = db.execute(
            'SELECT * FROM discovery_provider_state WHERE provider=?', (provider,)
        ).fetchone()
        if state['retry_at'] > now:
            return None, 'is temporarily paused after a provider error or rate limit'
        if state['lease_until'] > now:
            return None, 'already has a search in progress'
        db.execute(
            'UPDATE discovery_provider_state SET lease_until=?,lease_token=? WHERE provider=?',
            (now + 90, token, provider),
        )
    return token, None


def _release_provider(provider, token, cooldown=0):
    with connection() as db:
        db.execute(
            '''UPDATE discovery_provider_state SET retry_at=?,lease_until=0,lease_token=''
               WHERE provider=? AND lease_token=?''',
            (time.time() + cooldown if cooldown else 0, provider, token),
        )


def _unique(papers):
    results, seen, titles = [], set(), set()
    for paper in papers:
        key = identity(paper)
        title = re.sub(r'\W', '', paper['title'].casefold())
        if key not in seen and title not in titles:
            seen.add(key)
            titles.add(title)
            results.append(paper)
    return results


def discover(query, source='arXiv'):
    providers = {'arXiv': search_arxiv, 'Semantic Scholar': search_semantic}
    if source not in (*providers, 'both'):
        raise ValueError('Invalid search provider.')
    selected = list(providers) if source == 'both' else [source]
    papers, notices = [], []
    for name in selected:
        cached = _cached(name, query)
        if cached and time.time() - cached[0] < CACHE_TTL:
            papers.extend(cached[1])
            continue
        token, reason = _claim_provider(name)
        if not token:
            results, message = _fallback(name, query, cached)
            papers.extend(results)
            notices.append(f'{name} {reason}. {message}')
            continue
        cooldown = 0
        try:
            results = _unique(providers[name](query, 10))
            _cache_results(name, query, results)
            papers.extend(results)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            response = getattr(exc, 'response', None)
            rate_limited = response is not None and response.status_code == 429
            cooldown = 300 if rate_limited else 30
            if rate_limited:
                retry_after = response.headers.get('Retry-After', '')
                if retry_after.isdigit():
                    cooldown = max(1, int(retry_after))
            current_app.logger.warning('Discovery failed for %s: %s', name, type(exc).__name__)
            results, message = _fallback(name, query, cached)
            papers.extend(results)
            reason = 'is rate-limited' if rate_limited else 'is unavailable'
            notices.append(f'{name} {reason}. {message}')
        finally:
            _release_provider(name, token, cooldown)
    return _unique(papers), notices
