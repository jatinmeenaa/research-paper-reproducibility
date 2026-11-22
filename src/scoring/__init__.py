WEIGHTS = {
    "code": 40,
    "dataset": 30,
    "documentation": 20,
    "supplementary": 10,
}

LABELS = {
    "code": "Source code",
    "dataset": "Datasets",
    "documentation": "Documentation",
    "supplementary": "Supplementary material",
}


def calculate_score(resources, applicable=None):
    resources = list(resources)

    if applicable is None:
        selected = set(WEIGHTS)
    else:
        if isinstance(applicable, str):
            raise ValueError("Pass applicable categories as a list.")
        selected = set(applicable)

    if not selected:
        raise ValueError("Select at least one applicable category.")

    if selected - set(WEIGHTS):
        raise ValueError("Unknown applicable resource category.")

    breakdown = []

    for category, weight in WEIGHTS.items():
        matches = [
            resource
            for resource in resources
            if resource.get("category") == category
        ]

        accessible = sum(
            resource.get("status") == "accessible"
            for resource in matches
        )

        included = category in selected
        earned = weight if included and accessible else 0

        breakdown.append({
            "category": category,
            "label": LABELS[category],
            "weight": weight,
            "applicable": included,
            "discovered": len(matches),
            "accessible": accessible,
            "earned": earned,
        })

    earned = sum(row["earned"] for row in breakdown)
    denominator = sum(WEIGHTS[category] for category in selected)
    score = round(100 * earned / denominator)

    if earned == denominator:
        label = "All applicable resource categories accessible"
    elif earned:
        label = "Some applicable resource categories accessible"
    else:
        label = "No applicable resource links verified accessible"

    return {
        "version": "1.0",
        "score": score,
        "label": label,
        "earned": earned,
        "denominator": denominator,
        "applicable": [
            category for category in WEIGHTS
            if category in selected
        ],
        "breakdown": breakdown,
    }