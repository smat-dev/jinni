# tests/test_schema_safety.py
"""Schema regression tests to ensure MCP tool schemas remain Cursor-safe.

These tests enforce a "safe subset" of JSON Schema constructs that are known
to work reliably with Cursor and other MCP hosts that have issues with complex
parameter types.
"""

import pytest
import json
from mcp.server.fastmcp import FastMCP


# List of problematic JSON Schema constructs that should be avoided
DISALLOWED_CONSTRUCTS = {
    "anyOf",          # Union types cause issues
    "oneOf",          # Union types cause issues
    "allOf",          # Complex composition causes issues
    "$ref",           # References may not be resolved correctly
    "discriminator",  # Complex object discrimination
}

# Types that are safe for MCP tool parameters
SAFE_TYPES = {"string", "integer", "boolean", "array", "number"}


def get_tool_schema(server: FastMCP, tool_name: str) -> dict:
    """Extract the JSON schema for a tool's parameters."""
    for tool in server._tool_manager._tools.values():
        if tool.name == tool_name:
            # Parameters are already a dict (JSON schema)
            return tool.parameters
    raise ValueError(f"Tool '{tool_name}' not found")


def check_schema_safety(schema: dict, path: str = "") -> list:
    """
    Recursively check a JSON schema for problematic constructs.

    Returns a list of issues found.
    """
    issues = []

    # Check for disallowed top-level constructs
    for construct in DISALLOWED_CONSTRUCTS:
        if construct in schema:
            issues.append(f"{path}: contains disallowed construct '{construct}'")

    # Check property types
    if "properties" in schema:
        for prop_name, prop_schema in schema["properties"].items():
            prop_path = f"{path}.{prop_name}" if path else prop_name

            # Check for disallowed constructs in property
            for construct in DISALLOWED_CONSTRUCTS:
                if construct in prop_schema:
                    issues.append(f"{prop_path}: contains disallowed construct '{construct}'")

            # Check type safety
            prop_type = prop_schema.get("type")
            if prop_type and prop_type not in SAFE_TYPES:
                if prop_type == "object":
                    # Object types are problematic - check if it's a nested object
                    if "properties" in prop_schema or "additionalProperties" in prop_schema:
                        issues.append(f"{prop_path}: nested object types are not Cursor-safe")

            # Recurse into array items
            if prop_type == "array" and "items" in prop_schema:
                items = prop_schema["items"]
                items_type = items.get("type")
                if items_type == "object" and "properties" in items:
                    issues.append(f"{prop_path}: array of objects is not Cursor-safe")

    return issues


class TestReadContextSchema:
    """Test that read_context tool schema is Cursor-safe."""

    @pytest.fixture
    def server(self):
        """Import and return the jinni server."""
        from jinni.server import server
        return server

    def test_no_disallowed_constructs(self, server):
        """Test that the schema doesn't contain problematic constructs."""
        schema = get_tool_schema(server, "read_context")
        issues = check_schema_safety(schema)

        if issues:
            pytest.fail(
                "Schema safety violations found:\n" +
                "\n".join(f"  - {issue}" for issue in issues)
            )

    def test_no_nested_object_params(self, server):
        """Test that no parameters are nested objects (like the old 'exclusions' dict)."""
        schema = get_tool_schema(server, "read_context")

        for prop_name, prop_schema in schema.get("properties", {}).items():
            # Direct object type with properties = nested object
            if prop_schema.get("type") == "object" and "properties" in prop_schema:
                pytest.fail(
                    f"Parameter '{prop_name}' is a nested object, which is not Cursor-safe. "
                    "Use flat parameters instead."
                )

            # Check for dict/additionalProperties pattern
            if "additionalProperties" in prop_schema:
                pytest.fail(
                    f"Parameter '{prop_name}' uses additionalProperties (dict-like), "
                    "which is not Cursor-safe. Use flat parameters instead."
                )

    def test_array_params_are_simple(self, server):
        """Test that array parameters only contain simple types, not objects."""
        schema = get_tool_schema(server, "read_context")

        for prop_name, prop_schema in schema.get("properties", {}).items():
            if prop_schema.get("type") == "array":
                items = prop_schema.get("items", {})
                items_type = items.get("type")

                # Arrays of objects are problematic
                if items_type == "object":
                    pytest.fail(
                        f"Parameter '{prop_name}' is an array of objects, "
                        "which is not Cursor-safe. Use array of strings instead."
                    )

                # Arrays should contain simple types
                if items_type and items_type not in {"string", "integer", "boolean", "number"}:
                    pytest.fail(
                        f"Parameter '{prop_name}' is an array of '{items_type}', "
                        "which may not be Cursor-safe. Prefer arrays of strings."
                    )

    def test_no_anyof_union_types(self, server):
        """Test that no parameters use anyOf/oneOf union types."""
        schema = get_tool_schema(server, "read_context")

        def check_for_unions(obj, path=""):
            if isinstance(obj, dict):
                for key in ["anyOf", "oneOf", "allOf"]:
                    if key in obj:
                        return f"{path}: uses {key} union type"
                for key, value in obj.items():
                    result = check_for_unions(value, f"{path}.{key}" if path else key)
                    if result:
                        return result
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    result = check_for_unions(item, f"{path}[{i}]")
                    if result:
                        return result
            return None

        issue = check_for_unions(schema)
        if issue:
            pytest.fail(f"Schema uses union types which are not Cursor-safe: {issue}")

    def test_flat_exclusion_params_exist(self, server):
        """Test that the flat exclusion parameters exist."""
        schema = get_tool_schema(server, "read_context")
        properties = schema.get("properties", {})

        # Check that the old 'exclusions' dict is removed
        assert "exclusions" not in properties, (
            "The 'exclusions' dict parameter should be removed in favor of flat params"
        )

        # Check that the new flat params exist
        expected_params = ["not_keywords", "not_in", "not_files"]
        for param in expected_params:
            assert param in properties, f"Expected flat parameter '{param}' not found"
            # Each should be an array of strings
            param_schema = properties[param]
            assert param_schema.get("type") == "array", f"'{param}' should be an array"

    def test_optional_params_have_defaults(self, server):
        """Test that optional parameters have defaults (not required)."""
        schema = get_tool_schema(server, "read_context")
        required = set(schema.get("required", []))

        # Only project_root should be required
        assert "project_root" in required, "project_root should be required"

        # These should NOT be required (have defaults)
        optional_params = [
            "targets", "rules", "list_only", "size_limit_mb",
            "debug_explain", "not_keywords", "not_in", "not_files"
        ]
        for param in optional_params:
            if param in schema.get("properties", {}):
                assert param not in required, (
                    f"'{param}' should be optional with a default value"
                )


class TestUsageToolSchema:
    """Test that usage tool schema is also Cursor-safe."""

    @pytest.fixture
    def server(self):
        """Import and return the jinni server."""
        from jinni.server import server
        return server

    def test_usage_tool_exists(self, server):
        """Test that the usage tool exists and has a simple schema."""
        try:
            schema = get_tool_schema(server, "usage")
            # Usage tool should have no required parameters
            assert schema.get("required", []) == [] or "required" not in schema
        except ValueError:
            pytest.fail("usage tool not found")
