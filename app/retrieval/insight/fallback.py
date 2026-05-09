"""Fallback insight generation aligned with Knowledge Brief 6-section prompt structure."""

import re
from typing import Any

from app.retrieval.insight.content import (
    extract_data_fields,
    extract_module_entries,
    format_joined_list,
    infer_material_label,
    is_data_heavy_material,
)
from app.retrieval.insight.index import prepare_chunks_for_insight, trim_excerpt

_SUMMARY_HEADINGS = [
    "Document:",
    "1. Executive Mission:",
    "2. Stakeholder Matrix:",
    "3. Operational Pillars:",
    "4. Execution Roadmap:",
    "5. Critical Safety & Risk Gates:",
    "6. Lifecycle Triggers:",
]


def _format_bullets(items: list[str]) -> str:
    """Render non-empty items as a readable bullet list."""
    cleaned_items = [item.strip() for item in items if item and item.strip()]
    return "\n".join(f"- {item}" for item in cleaned_items)


def _compact_module_area(name: str, description: str) -> str:
    """Keep module descriptions readable by trimming extracted raw text."""
    compact_name = re.sub(r"\s+", " ", name).strip()
    compact_description = trim_excerpt(re.sub(r"\s+", " ", description).strip(" ."), limit=90)
    if compact_description:
        return f"{compact_name}: {compact_description}"
    return compact_name


def build_dynamic_questions(
    material_label: str,
    module_names: list[str],
    data_fields: list[str],
    data_heavy: bool,
) -> list[str]:
    """Build heuristic suggested questions based on content type.

    Args:
        material_label: Human-readable label for the material
        module_names: Detected module names
        data_fields: Detected data field names
        data_heavy: Whether the material is data/tabular heavy

    Returns:
        List of 8-12 suggested questions
    """
    modules_text = format_joined_list(module_names, limit=4)
    fields_text = format_joined_list(data_fields, limit=4)

    if data_heavy:
        questions = [
            f"Which sort or filter scenarios in {material_label} are highest priority to validate?",
            f"Which fields ({fields_text}) drive expected ordering and tie-break behavior?" if fields_text else "Which fields drive expected ordering and tie-break behavior?",
            "What output differences should trigger investigation of mapping, rule, or query logic defects?",
            "How should teams verify correctness of filtered and sorted result sets?",
            f"What baseline records or comparison datasets are provided in {material_label}?",
            "Where can teams find troubleshooting guidance for unexpected data behavior?",
        ]
        return questions[:6]

    questions = [
        f"Which modules ({modules_text}) in {material_label} should this role maintain regularly?" if modules_text else f"Which areas in {material_label} should this role maintain regularly?",
        f"What data or configuration changes are persisted through modules such as {modules_text}?" if modules_text else "What data or configuration changes are persisted by core workflows?",
        "Where can users review audit history or verification evidence after applying changes?",
        f"Which approvals or environment constraints apply to updates in {modules_text}?" if modules_text else "Which approvals or environment constraints apply to updates?",
        "How should teams validate changes after saving them?",
        "What are the most common troubleshooting paths when configuration changes produce unexpected results?",
        "Which dependencies must be checked before applying configuration updates?",
        "How is access controlled or provisioned within the system?",
    ]
    return questions[:8]


def build_knowledge_brief_summary(
    source: str,
    material_label: str,
    chunks: list[str],
    module_entries: list[tuple[str, str]],
    data_fields: list[str],
    data_heavy: bool,
) -> str:
    """Build a Knowledge Brief 6-section summary aligned with the prompt specification.

    Args:
        source: Material source path
        material_label: Human-readable label for material
        chunks: Text chunks
        module_entries: List of (module_name, description) tuples
        data_fields: List of data field names
        data_heavy: Whether material is data-heavy

    Returns:
        Knowledge Brief formatted summary string
    """
    combined = " ".join(chunks)
    lower_combined = combined.lower()
    module_names = [name for name, _ in module_entries]
    managed_areas = [_compact_module_area(name, description) for name, description in module_entries]
    managed_areas_text = format_joined_list(managed_areas, limit=4)
    module_names_text = format_joined_list(module_names, limit=4)

    # 1. Executive Mission (The Why)
    if data_heavy and not module_entries:
        executive_points = [
            f"{material_label} provides validation examples and result-set outputs for testing data behavior.",
            "Use it to verify sorting, filtering, and comparison rules before defects reach operations.",
        ]
    elif managed_areas_text:
        executive_points = [
            f"Enable users to manage {managed_areas_text} in {material_label}.",
            "Keep configuration data and operational settings current and consistent across the platform.",
        ]
    else:
        executive_points = [
            f"Empower users to maintain the configuration, workflows, and reference data required by {material_label}.",
            "Reduce operational drift by keeping setup steps and updates in one place.",
        ]

    # 2. Stakeholder Matrix (The Who) - with role/responsibility structure
    role_lines = []
    if data_heavy and not module_entries:
        role_lines = [
            "QA Engineer: Validate output ordering and field values across sort and filter scenarios.",
            "Developer: Troubleshoot mapping or rule defects exposed by failed validation runs.",
            "Data Analyst: Compare result sets against baseline expectations and investigate anomalies.",
        ]
    elif module_names_text:
        role_lines = [
            f"Administrator: Maintain {module_names_text} configuration in {material_label}.",
            "Support Specialist: Troubleshoot configuration issues and validate post-change behavior.",
            "Operator: Execute routine maintenance and update workflows.",
        ]
    else:
        role_lines = [
            "Administrator: Manage application configuration and operational settings.",
            "Support Specialist: Investigate and resolve configuration issues.",
            "User: Execute workflows and apply configuration changes.",
        ]
    stakeholder_matrix = _format_bullets(role_lines)

    # 3. Operational Pillars (The What) - list 3 critical functional areas
    operational_pillars_list = []
    if data_heavy and not module_entries:
        field_text = format_joined_list(data_fields, limit=6) if data_fields else "sorting, filtering fields"
        operational_pillars_list = [
            f"Data Validation: Test sort and filter behavior using {field_text}.",
            "Result Comparison: Validate output ordering and field values against expected baselines.",
            "Defect Investigation: Identify mapping, rule, or query-logic issues from failed checks.",
        ]
    elif managed_areas_text:
        operational_pillars_list = [
            f"Configuration Maintenance: {managed_areas_text}.",
            "Workflow Navigation: Use the dashboard to reach the right module and record.",
            "Change Verification: Review audit history and validate saved changes.",
        ]
    else:
        operational_pillars_list = [
            "Configuration Management: Update application settings and reference data.",
            "Workflow Execution: Access and navigate the relevant configuration areas.",
            "Change Verification: Validate the correctness of applied changes.",
        ]
    operational_pillars = _format_bullets(operational_pillars_list)

    # 4. Execution Roadmap (The How) - Preparation, Targeting, Action, Verification
    preparation_parts = []
    if "dashboard" in lower_combined or "login" in lower_combined:
        preparation_parts.append("Access the application dashboard and authenticate.")
    if module_names_text:
        preparation_parts.append(f"Identify which modules ({module_names_text}) require updates.")
    if not preparation_parts:
        preparation_parts.append("Gather requirements and identify the configuration areas to modify.")
    preparation = " ".join(preparation_parts)

    targeting = f"Navigate to and select the target modules or configuration areas. Locate the specific records or settings that require updates." if module_names_text else "Locate the configuration areas and records that require changes."

    action_parts = ["Apply the required changes (add, edit, or delete records)."]
    if "save" in lower_combined:
        action_parts.append("Save changes through the system interface.")
    if "audit" in lower_combined or "log" in lower_combined:
        action_parts.append("Review audit history to confirm the changes were persisted.")
    action = " ".join(action_parts)

    verification_parts = ["Compare post-change behavior against expected outcomes."]
    if "dependency" in lower_combined or "constraint" in lower_combined:
        verification_parts.append("Verify that dependent systems or configurations reflect the changes.")
    verification_parts.append("Document the validation results and any exceptions encountered.")
    verification = " ".join(verification_parts)

    execution_roadmap = _format_bullets([
        f"Preparation: {preparation}",
        f"Targeting: {targeting}",
        f"Action: {action}",
        f"Verification: {verification}",
    ])

    # 5. Critical Safety & Risk Gates (The Watch Out) - with [ ] checkbox format
    gates = [
        "[ ] Dependency Check: Confirm that all upstream/downstream dependencies have been validated and are ready",
        "[ ] Environment Sync: Verify that configuration matches the target environment and no conflicts exist",
        "[ ] Approval Clarity: Ensure that all required approvals are documented and stakeholders have signed off",
        "[ ] Rollback Ready: Confirm that a rollback plan exists and has been tested if needed",
    ]
    critical_safety_gates = _format_bullets(gates)

    # 6. Lifecycle Triggers (The When) - organized by Routine, Onboarding, Incident Response
    lifecycle_triggers = _format_bullets([
        "Routine: Use during regular maintenance, configuration updates, and operational data refreshes.",
        "Onboarding: Use when provisioning new users, setting roles, or preparing new environments.",
        "Incident Response: Use during urgent troubleshooting, disruption handling, and production hotfixes.",
    ])

    summary = "\n\n".join([
        f"Document: {material_label} | Knowledge Brief",
        f"1. Executive Mission:\n{_format_bullets(executive_points)}",
        f"2. Stakeholder Matrix:\n{stakeholder_matrix}",
        f"3. Operational Pillars:\n{operational_pillars}",
        f"4. Execution Roadmap:\n{execution_roadmap}",
        f"5. Critical Safety & Risk Gates:\n{critical_safety_gates}",
        f"6. Lifecycle Triggers:\n{lifecycle_triggers}",
    ])

    return summary


def fallback_material_insight(source: str, chunks: list[str]) -> dict[str, Any]:
    """Build a complete fallback insight result aligned with Knowledge Brief format.

    Args:
        source: Material source path
        chunks: Raw text chunks

    Returns:
        Insight dict with Knowledge Brief summary, key_topics, critical_points, suggested_questions
    """
    prepared_chunks = prepare_chunks_for_insight(chunks)
    combined = " ".join(prepared_chunks)
    lower_combined = combined.lower()

    if not combined.strip():
        return {
            "source": source,
            "summary": "Document: Material | Knowledge Brief\n\n1. Executive Mission:\n- No indexed content available for this material.",
            "key_topics": [],
            "critical_points": [],
            "suggested_questions": [],
        }

    module_entries = extract_module_entries(prepared_chunks)
    data_fields = extract_data_fields(combined)
    data_heavy = is_data_heavy_material(combined)
    module_names = [name for name, _ in module_entries]
    material_label = infer_material_label(source, module_entries, combined)

    summary = build_knowledge_brief_summary(
        source,
        material_label,
        prepared_chunks,
        module_entries,
        data_fields,
        data_heavy,
    )

    key_topics = module_names[:6] if module_names else []
    if not key_topics:
        key_topics = [
            topic
            for topic in ["Configuration", "Dashboard", "Workflow", "Audit Log"]
            if topic.lower() in lower_combined
        ][:6]

    critical_points = []
    if module_names:
        critical_points.append(f"{material_label} centralizes maintenance for {', '.join(module_names[:3])}.")
    if "dashboard" in lower_combined or "config" in lower_combined:
        critical_points.append("Users begin on the main configuration dashboard and navigate into specific modules to perform changes.")
    critical_points.append("All changes should be validated post-save and documented for audit and troubleshooting purposes.")
    if "authenticate" in lower_combined or "ldap" in lower_combined or "adfs/saml" in lower_combined:
        critical_points.append("Access depends on configured authentication, including enterprise identity providers when enabled.")
    critical_points = critical_points[:6]

    suggested_questions = build_dynamic_questions(material_label, module_names, data_fields, data_heavy)

    return {
        "source": source,
        "summary": summary,
        "key_topics": key_topics,
        "critical_points": critical_points,
        "suggested_questions": suggested_questions,
    }


def build_structured_fallback_details(source: str, chunks: list[str]) -> tuple[str, list[str], list[str], list[str]]:
    """Backward-compatible helper for callers that need tuple-style fallback parts.

    Returns:
        Tuple of (summary, key_topics, critical_points, suggested_questions)
    """
    insight = fallback_material_insight(source, chunks)
    summary = str(insight.get("summary", ""))
    key_topics = [str(item) for item in insight.get("key_topics", []) if str(item).strip()]
    critical_points = [str(item) for item in insight.get("critical_points", []) if str(item).strip()]
    suggested_questions = [str(item) for item in insight.get("suggested_questions", []) if str(item).strip()]
    return summary, key_topics, critical_points, suggested_questions


def extract_summary_sections(summary: str) -> dict[str, str]:
    """Parse a Knowledge Brief summary string into section dict.

    Args:
        summary: Summary string with Knowledge Brief structured headings

    Returns:
        Dict mapping heading to content, or empty dict if parsing fails
    """
    sections: dict[str, str] = {}
    for index, heading in enumerate(_SUMMARY_HEADINGS):
        start = summary.find(heading)
        if start == -1:
            return {}
        body_start = start + len(heading)
        next_starts = [summary.find(next_heading, body_start) for next_heading in _SUMMARY_HEADINGS[index + 1:]]
        next_positions = [position for position in next_starts if position != -1]
        body_end = min(next_positions) if next_positions else len(summary)
        sections[heading] = summary[body_start:body_end].strip()
    return sections


def summary_needs_fallback(summary: str) -> bool:
    """Detect if a summary is too poor to use.

    Checks for:
    - Missing required Knowledge Brief sections
    - Too many short sections (< 40 chars)
    - Step-like instructions instead of prose

    Args:
        summary: Generated summary string

    Returns:
        True if the summary should be replaced with fallback
    """
    sections = extract_summary_sections(summary)
    if len(sections) < 5:  # At least 5 of the 7 sections
        return True

    short_sections = sum(len(section) < 40 for section in sections.values())
    step_like_sections = sum(
        1
        for section in sections.values()
        if re.match(r"^(?:\d+[.)]?|click\b|select\b|to\s+\w+)", section.lower())
    )
    return short_sections >= 4 or step_like_sections >= 4
