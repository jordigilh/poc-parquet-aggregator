"""Test JSON format output matches Trino/PostgreSQL expectations."""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from utils import labels_to_json_string, parse_json_labels


def test_empty_labels():
    """Test empty labels produce '{}'."""
    result = labels_to_json_string({})
    assert result == '{}', f"Expected '{{}}', got {result}"
    print("✓ Empty labels: {}")


def test_single_label():
    """Test single label."""
    result = labels_to_json_string({"app": "nginx"})
    expected = '{"app":"nginx"}'
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Single label: {result}")


def test_multiple_labels_sorted():
    """Test multiple labels are sorted by key."""
    result = labels_to_json_string({
        "environment": "prod",
        "app": "nginx",
        "version": "1.0"
    })

    # Keys should be sorted alphabetically
    parsed = json.loads(result)
    keys = list(parsed.keys())
    assert keys == ["app", "environment", "version"], f"Keys not sorted: {keys}"
    print(f"✓ Multiple labels sorted: {result}")


def test_special_characters():
    """Test special characters are properly escaped."""
    result = labels_to_json_string({
        "name": 'test"quote',
        "path": "some/path\\with\\backslash",
        "unicode": "emoji-🚀"
    })

    # Should be valid JSON
    parsed = json.loads(result)
    assert parsed["name"] == 'test"quote'
    assert parsed["path"] == "some/path\\with\\backslash"
    assert parsed["unicode"] == "emoji-🚀"
    print(f"✓ Special characters: {result}")


def test_roundtrip():
    """Test parse and format roundtrip."""
    original = {"app": "test", "env": "dev", "version": "2.0"}
    json_str = labels_to_json_string(original)
    parsed = parse_json_labels(json_str)
    assert parsed == original, f"Roundtrip failed: {original} -> {json_str} -> {parsed}"
    print(f"✓ Roundtrip: {original} -> {json_str} -> {parsed}")


def test_null_none_handling():
    """Test NULL/None handling."""
    # None should return empty dict
    result = labels_to_json_string(None)
    assert result == '{}', f"None should produce '{{}}', got {result}"

    # Empty string parsing
    parsed = parse_json_labels('')
    assert parsed == {}, f"Empty string should parse to {{}}, got {parsed}"

    # 'null' string parsing
    parsed = parse_json_labels('null')
    assert parsed == {}, f"'null' string should parse to {{}}, got {parsed}"

    print("✓ NULL/None handling")


def test_postgresql_jsonb_compatibility():
    """Test output is compatible with PostgreSQL JSONB."""
    labels = {
        "app": "web-server",
        "tier": "frontend",
        "env": "production"
    }

    result = labels_to_json_string(labels)

    # PostgreSQL JSONB requirements:
    # 1. Valid JSON
    parsed = json.loads(result)
    assert isinstance(parsed, dict)

    # 2. Keys are strings
    assert all(isinstance(k, str) for k in parsed.keys())

    # 3. Values are strings (in our case)
    assert all(isinstance(v, str) for v in parsed.values())

    # 4. No trailing commas, proper escaping
    assert result.count('{') == result.count('}')
    assert result.count('[') == result.count(']')

    print(f"✓ PostgreSQL JSONB compatible: {result}")


def run_all_tests():
    """Run all JSON format tests."""
    print("\n" + "=" * 60)
    print("JSON Format Validation Tests")
    print("=" * 60 + "\n")

    try:
        test_empty_labels()
        test_single_label()
        test_multiple_labels_sorted()
        test_special_characters()
        test_roundtrip()
        test_null_none_handling()
        test_postgresql_jsonb_compatibility()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(run_all_tests())


