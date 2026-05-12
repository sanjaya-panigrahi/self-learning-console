"""Validation tests for prompt catalog and schema compliance."""

from pathlib import Path
from app.core.prompts import load_prompt_catalog, get_prompt_spec, prompt_catalog_summary


def test_prompt_catalog_loads_successfully():
    """Confirm prompt catalog can be loaded without errors."""
    catalog = load_prompt_catalog()
    assert isinstance(catalog, dict)
    assert "prompts" in catalog
    assert isinstance(catalog["prompts"], list)


def test_prompt_catalog_has_required_structure():
    """Check that each prompt has required fields."""
    catalog = load_prompt_catalog()
    prompts = catalog.get("prompts", [])
    assert len(prompts) > 0, "Catalog should have at least one prompt"
    
    required_fields = {"id", "owner", "why", "template"}
    for prompt in prompts:
        assert isinstance(prompt, dict), f"Prompt must be dict, got {type(prompt)}"
        for field in required_fields:
            assert field in prompt, f"Prompt missing required field: {field}"
            assert isinstance(prompt[field], str), f"Field {field} must be string"
            assert prompt[field].strip(), f"Field {field} cannot be empty"


def test_prompt_ids_are_unique():
    """Ensure no duplicate prompt IDs."""
    catalog = load_prompt_catalog()
    prompts = catalog.get("prompts", [])
    ids = [p.get("id", "") for p in prompts if isinstance(p, dict)]
    assert len(ids) == len(set(ids)), f"Found duplicate prompt IDs: {[id for id in ids if ids.count(id) > 1]}"


def test_prompt_ids_follow_naming_convention():
    """Check prompt IDs follow pattern: domain.purpose.version."""
    catalog = load_prompt_catalog()
    prompts = catalog.get("prompts", [])
    
    for prompt in prompts:
        prompt_id = prompt.get("id", "").strip()
        parts = prompt_id.split(".")
        assert len(parts) >= 3, f"Prompt ID '{prompt_id}' should have at least 3 parts (domain.purpose.version)"
        assert parts[-1].startswith("v"), f"Prompt ID '{prompt_id}' version part should start with 'v'"


def test_get_prompt_spec_returns_valid_entry():
    """Verify get_prompt_spec returns correct prompt."""
    catalog = load_prompt_catalog()
    prompts = catalog.get("prompts", [])
    if prompts:
        first_prompt_id = prompts[0].get("id", "")
        spec = get_prompt_spec(first_prompt_id)
        assert spec is not None, f"get_prompt_spec should find prompt {first_prompt_id}"
        assert spec.get("id") == first_prompt_id


def test_get_prompt_spec_returns_none_for_unknown_id():
    """Verify get_prompt_spec returns None for non-existent IDs."""
    spec = get_prompt_spec("nonexistent.prompt.v99")
    assert spec is None


def test_prompt_catalog_summary_includes_all_prompts():
    """Verify summary includes all prompts."""
    catalog = load_prompt_catalog()
    summary = prompt_catalog_summary()
    
    catalog_count = len(catalog.get("prompts", []))
    summary_count = summary.get("prompt_count", 0)
    assert catalog_count == summary_count, f"Catalog has {catalog_count} prompts but summary shows {summary_count}"


def test_prompt_templates_do_not_have_unterminated_placeholders():
    """Check templates don't have malformed placeholder syntax."""
    catalog = load_prompt_catalog()
    prompts = catalog.get("prompts", [])
    
    for prompt in prompts:
        template = prompt.get("template", "")
        # Check for orphaned opening braces
        assert template.count("{{") == template.count("}}"), \
            f"Prompt {prompt.get('id')} has mismatched {{ }} braces in template"


def test_all_prompts_have_optimization_scope_if_defined():
    """If optimization_scope is present, it should be properly structured."""
    catalog = load_prompt_catalog()
    prompts = catalog.get("prompts", [])
    
    for prompt in prompts:
        scope = prompt.get("optimization_scope")
        if scope is not None:
            assert isinstance(scope, dict), \
                f"Prompt {prompt.get('id')} optimization_scope should be dict or null"


def test_catalog_file_exists():
    """Verify catalog file is physically present."""
    from app.core.config.settings import PROJECT_ROOT
    catalog_path = PROJECT_ROOT / "prompts" / "prompt_catalog.toon"
    assert catalog_path.exists(), f"Prompt catalog file not found at {catalog_path}"
    assert catalog_path.is_file(), f"Prompt catalog is not a file: {catalog_path}"
    assert catalog_path.stat().st_size > 0, f"Prompt catalog is empty: {catalog_path}"
