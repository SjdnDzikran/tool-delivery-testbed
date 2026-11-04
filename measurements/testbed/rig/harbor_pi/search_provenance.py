"""Derive top-result metadata from actual MCP results or captured bx stdout."""
import json
from pathlib import Path


def result_pairs(text):
    def walk(value):
        if isinstance(value, dict):
            # bx returns the complete Brave response: the knowledge-panel
            # infobox can precede web.results and is NOT the top web result.
            if isinstance(value.get('web'), dict):
                yield from walk(value['web'].get('results', []))
                return
            if isinstance(value.get('url'), str) and isinstance(value.get('title'), str):
                yield {'url': value['url'], 'title': value['title']}
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)
    decoder = json.JSONDecoder()
    pos = 0
    pairs = []
    while pos < len(text):
        starts = [p for ch in ('{', '[') if (p := text.find(ch, pos)) >= 0]
        if not starts:
            break
        start = min(starts)
        try:
            obj, end = decoder.raw_decode(text, start)
        except ValueError:
            pos = start + 1
            continue
        pairs.extend(walk(obj))
        pos = end
    return pairs


def derive(events, traces, mode):
    tops = []
    source = 'independently captured bx stdout' if mode == 'cli' else 'MCP brave_web_search tool result'
    if mode == 'cli':
        for path in sorted(Path(traces).glob('*.json')):
            meta = json.loads(path.read_text())
            if meta.get('program') == 'bx' and meta.get('subcommand') == 'web' and meta.get('returncode') == 0:
                pairs = result_pairs(path.with_suffix('.stdout').read_text())
                if pairs:
                    tops.append(pairs[0])
    else:
        for event in events:
            msg = event.get('message', {})
            if (event.get('type') == 'message_end' and msg.get('role') == 'toolResult'
                    and 'brave_web_search' in msg.get('toolName', '') and not msg.get('isError')):
                text = '\n'.join(b.get('text', '') for b in msg.get('content', []) if b.get('type') == 'text')
                pairs = result_pairs(text)
                if pairs:
                    tops.append(pairs[0])
    return {'source': source if tops else 'no independently observed search result',
            'top': tops[0] if tops else None, 'observed_tops': tops}
