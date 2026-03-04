#!/usr/bin/env python3
"""Validate JSON files in the igniter-governance repository.

Checks performed:
  1. Valid JSON syntax
  2. Correct formatting (2-space indent, trailing newline, no trailing whitespace)
  3. Schema validation (required fields, types, patterns)
  4. No duplicate names or identities within a file
"""

import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMAS_DIR = os.path.join(REPO_ROOT, "schemas")

ENVIRONMENTS = ["pocket", "pocket-alpha", "pocket-beta"]

IDENTITY_PATTERN = re.compile(r"^(02|03)[0-9a-f]{64}$")
URL_PATTERN = re.compile(r"^https://")

FILE_SCHEMA_MAP = {
    "provider.json": "provider.schema.json",
    "middleman.json": "middleman.schema.json",
}


def load_schema(schema_name):
    path = os.path.join(SCHEMAS_DIR, schema_name)
    with open(path, "r") as f:
        return json.load(f)


def check_formatting(file_path, content):
    """Check that the file is properly formatted with 2-space indent."""
    errors = []

    if not content.endswith("\n"):
        errors.append(f"{file_path}: file must end with a newline")

    for i, line in enumerate(content.split("\n"), start=1):
        if line != line.rstrip():
            errors.append(f"{file_path}:{i}: trailing whitespace detected")
        if "\t" in line:
            errors.append(f"{file_path}:{i}: tabs detected, use 2-space indent")

    try:
        data = json.loads(content)
        expected = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        if content != expected:
            errors.append(
                f"{file_path}: formatting does not match expected style "
                f"(2-space indent, consistent spacing). "
                f"Run: python3 -c \"import json,sys; "
                f"d=json.load(open(sys.argv[1])); "
                f"open(sys.argv[1],'w').write(json.dumps(d,indent=2,ensure_ascii=False)+'\\n')\" {file_path}"
            )
    except json.JSONDecodeError:
        pass  # syntax error caught elsewhere

    return errors


def check_syntax(file_path, content):
    """Check that the file contains valid JSON."""
    try:
        data = json.loads(content)
        return [], data
    except json.JSONDecodeError as e:
        return [f"{file_path}: invalid JSON syntax: {e}"], None


def validate_identity(identity, file_path, index):
    """Validate an identity string."""
    errors = []
    if not isinstance(identity, str):
        errors.append(f"{file_path}: item[{index}].identity must be a string")
    elif not IDENTITY_PATTERN.match(identity):
        errors.append(
            f"{file_path}: item[{index}].identity '{identity}' "
            f"is not a valid compressed secp256k1 public key "
            f"(expected 66 hex chars starting with 02 or 03)"
        )
    return errors


def check_schema(file_path, data, schema):
    """Validate data against schema rules."""
    errors = []

    if not isinstance(data, list):
        errors.append(f"{file_path}: root must be an array")
        return errors

    required_fields = schema.get("items", {}).get("required", [])
    properties = schema.get("items", {}).get("properties", {})
    allows_additional = schema.get("items", {}).get("additionalProperties", True)

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"{file_path}: item[{i}] must be an object")
            continue

        # Check required fields
        for field in required_fields:
            if field not in item:
                errors.append(f"{file_path}: item[{i}] missing required field '{field}'")

        # Check no extra fields
        if not allows_additional:
            allowed = set(properties.keys())
            extra = set(item.keys()) - allowed
            if extra:
                errors.append(
                    f"{file_path}: item[{i}] has unexpected fields: {', '.join(sorted(extra))}"
                )

        # Validate name
        if "name" in item:
            if not isinstance(item["name"], str) or len(item["name"]) == 0:
                errors.append(f"{file_path}: item[{i}].name must be a non-empty string")

        # Validate identity
        if "identity" in item:
            errors.extend(validate_identity(item["identity"], file_path, i))

        # Validate identityHistory
        if "identityHistory" in item:
            if not isinstance(item["identityHistory"], list):
                errors.append(f"{file_path}: item[{i}].identityHistory must be an array")
            else:
                for j, hist in enumerate(item["identityHistory"]):
                    if not IDENTITY_PATTERN.match(str(hist)):
                        errors.append(
                            f"{file_path}: item[{i}].identityHistory[{j}] '{hist}' "
                            f"is not a valid identity"
                        )

        # Validate url (only for providers)
        if "url" in properties and "url" in item:
            if not isinstance(item["url"], str) or not URL_PATTERN.match(item["url"]):
                errors.append(
                    f"{file_path}: item[{i}].url must be a valid HTTPS URL"
                )

    return errors


def check_duplicates(file_path, data):
    """Check for duplicate names or identities."""
    errors = []
    if not isinstance(data, list):
        return errors

    names = {}
    identities = {}

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue

        name = item.get("name")
        if name:
            if name in names:
                errors.append(
                    f"{file_path}: duplicate name '{name}' at items [{names[name]}] and [{i}]"
                )
            else:
                names[name] = i

        identity = item.get("identity")
        if identity:
            if identity in identities:
                errors.append(
                    f"{file_path}: duplicate identity '{identity[:16]}...' "
                    f"at items [{identities[identity]}] and [{i}]"
                )
            else:
                identities[identity] = i

    return errors


def main():
    all_errors = []
    files_checked = 0

    for env in ENVIRONMENTS:
        for json_file, schema_file in FILE_SCHEMA_MAP.items():
            file_path = os.path.join(REPO_ROOT, env, json_file)
            rel_path = os.path.join(env, json_file)

            if not os.path.exists(file_path):
                all_errors.append(f"{rel_path}: file not found")
                continue

            files_checked += 1
            print(f"Checking {rel_path}...")

            with open(file_path, "r") as f:
                content = f.read()

            # 1. Check formatting
            all_errors.extend(check_formatting(rel_path, content))

            # 2. Check syntax
            syntax_errors, data = check_syntax(rel_path, content)
            all_errors.extend(syntax_errors)

            if data is None:
                continue

            # 3. Check schema
            schema = load_schema(schema_file)
            all_errors.extend(check_schema(rel_path, data, schema))

            # 4. Check duplicates
            all_errors.extend(check_duplicates(rel_path, data))

    print(f"\nChecked {files_checked} files.")

    if all_errors:
        print(f"\nFound {len(all_errors)} error(s):\n")
        for error in all_errors:
            print(f"  ERROR: {error}")
        sys.exit(1)
    else:
        print("\nAll checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
