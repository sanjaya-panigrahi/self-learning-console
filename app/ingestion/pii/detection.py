"""PII (Personally Identifiable Information) detection logic."""

import re

# PII patterns to detect
PII_PATTERNS = {
    "password": re.compile(r"\bpassword\b", re.IGNORECASE),
}

# Severity levels for detected PII types
PII_SEVERITY = {
    "password": "critical",
}


def detect_pii(text: str) -> list[str]:
    """Detect PII types in text.

    Args:
        text: Text to scan for PII

    Returns:
        Sorted list of detected PII type names
    """
    matches = [name for name, pattern in PII_PATTERNS.items() if pattern.search(text)]
    return sorted(matches)


def build_pii_findings(text: str) -> list[dict[str, str]]:
    """Build detailed PII findings with severity and samples.

    Args:
        text: Text to analyze

    Returns:
        List of findings with type, severity, and masked sample
    """
    findings: list[dict[str, str]] = []
    for name, pattern in PII_PATTERNS.items():
        match = pattern.search(text)
        if not match:
            continue
        sample = match.group(0)
        masked = sample[:2] + "..." + sample[-2:] if len(sample) > 6 else "[redacted]"
        findings.append(
            {
                "type": name,
                "severity": PII_SEVERITY.get(name, "medium"),
                "sample": masked,
            }
        )
    return findings
