
#!/usr/bin/env python3
"""Update known model prices from LiteLLM's pricing catalog.

Existing model IDs are preserved. Unmatched models are left unchanged.
Only models with valid, non-negative input and output costs are updated.

pricing.json uses USD per 1,000 tokens.
LiteLLM costs are USD per token.
"""

import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PRICING_FILE = Path("pricing.json")

SOURCE_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/"
    "main/model_prices_and_costs.json"
)

# Optional aliases for models whose catalog IDs differ from yours.
ALIASES = {
    "gpt-4o": ["gpt-4o"],
    "gpt-4o-mini": ["gpt-4o-mini"],
    "gpt-4-turbo": ["gpt-4-turbo"],
    "gpt-3.5-turbo": ["gpt-3.5-turbo"],
    "claude-sonnet-4-20250514": ["claude-sonnet-4-20250514"],
    "claude-haiku-4-20250414": ["claude-haiku-4-20250414"],
    "deepseek-chat": ["deepseek-chat"],
    "deepseek-reasoner": ["deepseek-reasoner"],
    "gemini-2.0-flash": ["gemini-2.0-flash"],
    "gemini-2.0-flash-lite": ["gemini-2.0-flash-lite"],
}

def fetch_catalog():
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "daily-model-pricing-updater/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"Pricing source returned HTTP {response.status}")
        data = json.load(response)

    if not isinstance(data, dict) or not data:
        raise ValueError("Pricing catalog is empty or invalid")

    return data


def get_cost(entry, field):
    value = entry.get(field)
    if value is None or isinstance(value, bool):
        return None

    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    if value < 0:
        return None

    return value


def build_price(entry):
    if not isinstance(entry, dict):
        return None

    input_cost = get_cost(entry, "input_cost_per_token")
    output_cost = get_cost(entry, "output_cost_per_token")

    # Do not replace prices with incomplete metadata.
    if input_cost is None or output_cost is None:
        return None

    # Reject non-text generation models when the catalog identifies them.
    mode = entry.get("mode")
    if mode and mode not in ("chat", "completion"):
        return None

    # Convert USD/token to USD/1,000 tokens.
    return {
        "input": round(input_cost * 1000, 12),
        "output": round(output_cost * 1000, 12),
    }


def main():
    if not PRICING_FILE.exists():
        raise FileNotFoundError(f"Missing {PRICING_FILE}")

    with PRICING_FILE.open(encoding="utf-8") as file:
        current = json.load(file)

    if not isinstance(current, dict) or not current:
        raise ValueError("pricing.json must contain a non-empty JSON object")

    catalog = fetch_catalog()
    updated = dict(current)
    changes = []
    unmatched = []

    for model, old_price in current.items():
        candidates = ALIASES.get(model, [model])
        new_price = None

        for candidate in candidates:
            if candidate in catalog:
                new_price = build_price(catalog[candidate])
                if new_price is not None:
                    break

        if new_price is None:
            unmatched.append(model)
            continue

        if old_price != new_price:
            updated[model] = new_price
            changes.append((model, old_price, new_price))

    if not changes:
        print("No pricing changes found.")

    # Atomic write: don't leave a partially written JSON file.
    if changes:
        fd, temp_name = tempfile.mkstemp(
            dir=PRICING_FILE.parent, prefix=".pricing-"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(updated, file, indent=2, ensure_ascii=False)
                file.write("\n")
            os.replace(temp_name, PRICING_FILE)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    print(f"Checked {len(current)} models.")
    print(f"Updated {len(changes)} prices.")
    print(f"Unmatched or unverifiable: {len(unmatched)} models.")

    for model, old, new in changes:
        print(f"UPDATED {model}: {old} -> {new}")

    if unmatched:
        print("UNMATCHED:")
        for model in unmatched:
            print(f"  - {model}")

    # Fail visibly if the source stops matching the configured models.
    # This does not discard successful updates.
    if len(unmatched) == len(current):
        raise RuntimeError(
            "No configured models could be matched. "
            "Check the source schema and model aliases."
        )


if __name__ == "__main__":
    main()
