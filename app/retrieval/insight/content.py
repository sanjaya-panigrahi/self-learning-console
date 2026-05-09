"""Content analysis for material insights - module detection, field extraction, data classification."""

import re


def format_joined_list(items: list[str], limit: int = 5) -> str:
    """Format a list of items into a natural-language joined string.

    Args:
        items: List of string items
        limit: Maximum items to include

    Returns:
        Oxford-comma formatted string (e.g. "A, B, and C")
    """
    selected = [item.strip() for item in items if item.strip()][:limit]
    if not selected:
        return ""
    if len(selected) == 1:
        return selected[0]
    if len(selected) == 2:
        return f"{selected[0]} and {selected[1]}"
    return f"{', '.join(selected[:-1])}, and {selected[-1]}"


def extract_module_entries(chunks: list[str]) -> list[tuple[str, str]]:
    """Extract module names and descriptions from bullet-point structured content.

    Args:
        chunks: Text chunks to scan

    Returns:
        List of (name, description) tuples for found modules
    """
    combined = " ".join(chunks)
    entries: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    for match in re.finditer(r"•\s*([^•]+?)(?=(?:•|Figure\s+\d|LOGIN|LOGOUT|NAVIGATION|To access|$))", combined):
        raw_entry = " ".join(match.group(1).split()).strip(" .")
        if not raw_entry:
            continue
        if " - " in raw_entry:
            name, description = raw_entry.split(" - ", 1)
        else:
            name, description = raw_entry, ""
        # Keep only the bare label — stop at colon-description, parenthetical, or long text
        name = re.split(r"\s+Note:\s|\s+\(|:\s+", name, maxsplit=1)[0].strip()
        name = name[:40].strip()  # hard cap: short enough for embedding in a sentence
        normalized_name = name.lower()
        if not normalized_name or normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        entries.append((name, description.strip()))
    return entries


def extract_data_fields(combined: str) -> list[str]:
    """Extract data field names from combined chunk text.

    Looks for patterns like "FieldName =" to identify configuration keys.

    Args:
        combined: Combined text content

    Returns:
        Ordered, deduplicated list of field names
    """
    field_matches = re.findall(r"([A-Za-z][A-Za-z0-9_]{2,})\s*=", combined)
    ordered_fields: list[str] = []
    seen: set[str] = set()
    for field in field_matches:
        normalized = field.strip()
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered_fields.append(normalized)
    return ordered_fields


def is_data_heavy_material(combined: str) -> bool:
    """Determine if content is primarily data/tabular rather than prose.

    Uses density heuristics for pipes (|), equals (=), braces ({}),
    and numeric token ratio.

    Args:
        combined: Combined text content

    Returns:
        True if the content appears data-heavy
    """
    if not combined.strip():
        return False
    non_space_chars = max(len(combined.replace(" ", "")), 1)
    pipe_density = combined.count("|") / non_space_chars
    equals_density = combined.count("=") / non_space_chars
    brace_density = (combined.count("{") + combined.count("}")) / non_space_chars
    token_count = max(len(combined.split()), 1)
    numeric_token_count = sum(1 for token in combined.split() if any(char.isdigit() for char in token))
    numeric_ratio = numeric_token_count / token_count
    return (
        pipe_density > 0.004
        or equals_density > 0.01
        or brace_density > 0.006
        or numeric_ratio > 0.35
    )


def infer_material_label(source: str, module_entries: list[tuple[str, str]], combined: str) -> str:
    """Infer a human-readable label for a material from its source path and content.

    Args:
        source: File source path
        module_entries: Extracted module (name, description) pairs
        combined: Combined text content

    Returns:
        Capitalized material label string
    """
    file_name = source.rsplit("/", 1)[-1]
    base_name = file_name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
    candidates = [token for token in base_name.split() if token]
    if candidates:
        normalized = " ".join(candidates)
        return normalized[:1].upper() + normalized[1:]

    if module_entries:
        return "the platform configuration guide"
    if "application" in combined.lower() or "dashboard" in combined.lower():
        return "the application"
    return "the material"
