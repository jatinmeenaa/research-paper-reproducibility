from collections import Counter

VERSION = '2.0'
LABELS = {
    'code': 'Source code',
    'dataset': 'Datasets',
    'documentation': 'Documentation',
    'supplementary': 'Supplementary material',
    'other': 'Other links',
}


def calculate_score(resources, applicable=None):
    """The legacy applicable argument is ignored; categories never affect scores."""
    unique = {}
    for resource in resources:
        unique.setdefault(resource['url'], resource)
    links = list(unique.values())
    counts = Counter(resource.get('status', 'unchecked') for resource in links)
    total = len(links)
    accessible = counts['accessible']
    checked = total - counts['unchecked']
    score = round(100 * accessible / total) if total and checked else None
    breakdown = []
    for category, label in LABELS.items():
        matches = [resource for resource in links
                   if resource.get('category', 'other') == category]
        if matches:
            breakdown.append({
                'category': category, 'label': label,
                'discovered': len(matches),
                'accessible': sum(resource.get('status') == 'accessible' for resource in matches),
            })
    return {
        'version': VERSION,
        'method': 'equal_link_availability',
        'score': score,
        'label': (f'{accessible} of {total} links verified accessible'
                  if score is not None else 'Not scored: no links checked'),
        'earned': accessible,
        'denominator': total,
        'accessible_count': accessible,
        'checked_count': checked,
        'resource_count': total,
        'status_counts': {status: counts[status] for status in (
            'accessible', 'missing', 'restricted', 'unresolved', 'blocked', 'unchecked'
        )},
        'breakdown': breakdown,
    }
