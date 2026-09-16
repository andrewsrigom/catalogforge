import math
import re
from typing import Any

from .contracts import AttributeDefinition, ValidationResult

CONVERSIONS = {
    ("cm", "mm"): 10.0,
    ("m", "mm"): 1000.0,
    ("in", "mm"): 25.4,
    ("mm", "cm"): 0.1,
    ("m", "cm"): 100.0,
    ("in", "cm"): 2.54,
    ("mm", "m"): 0.001,
    ("cm", "m"): 0.01,
    ("g", "kg"): 0.001,
    ("kg", "g"): 1000.0,
}


def present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def normalize(raw: Any, attr: AttributeDefinition) -> ValidationResult:
    notes: list[str] = []
    if not present(raw):
        return ValidationResult(valid=False, errors=["Value is missing"])
    if attr.type == "number":
        match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z]+)?\s*", str(raw))
        if not match or isinstance(raw, bool):
            return ValidationResult(
                valid=False, errors=["Expected an explicit number and optional unit"]
            )
        value: Any = float(match.group(1))
        if not math.isfinite(value):
            return ValidationResult(valid=False, errors=["Number must be finite"])
        source_unit = (match.group(2) or "").lower()
        if source_unit and source_unit != attr.unit:
            factor = CONVERSIONS.get((source_unit, attr.unit or ""))
            if factor is None:
                return ValidationResult(
                    valid=False,
                    errors=["No supported conversion; packaging counts require explicit evidence"],
                )
            value *= factor
            notes.append(f"Converted {source_unit} to {attr.unit}")
        if not math.isfinite(value):
            return ValidationResult(valid=False, errors=["Converted number must be finite"])
        if attr.unit in {"items", "pairs"} and (value < 1 or not value.is_integer()):
            return ValidationResult(
                valid=False, errors=["Packaging count must be a positive whole number"]
            )
        if attr.minimum is not None and value < attr.minimum:
            return ValidationResult(valid=False, errors=[f"Below minimum {attr.minimum}"])
        if attr.maximum is not None and value > attr.maximum:
            return ValidationResult(valid=False, errors=[f"Above maximum {attr.maximum}"])
        value = round(value, 8)
    elif attr.type == "boolean":
        token = str(raw).strip().lower()
        if token not in {"true", "false", "yes", "no"}:
            return ValidationResult(valid=False, errors=["Expected true/false or yes/no"])
        value = token in {"true", "yes"}
    elif attr.type == "enum":
        values = {s.casefold(): s for s in attr.allowed_values}
        value = values.get(str(raw).strip().casefold())
        if value is None:
            return ValidationResult(valid=False, errors=["Value is outside allowed enum values"])
    else:
        value = str(raw).strip()
        if len(value) > 2000:
            return ValidationResult(valid=False, errors=["Value is too long"])
    return ValidationResult(valid=True, normalized=value, notes=notes)


def canonical(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip().casefold())


def parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and re.fullmatch(r"[\w /-]{1,60}", key.strip()):
            fields[key.strip().casefold().replace(" ", "_")] = value.strip()
    return fields


def identity_match(identity: dict[str, Any], identifiers: dict[str, Any]) -> dict[str, Any]:
    # Matching is deliberately conservative. Similarity ranks candidates but cannot authorize them.
    if identifiers.get("ambiguous"):
        return {
            "applies": False,
            "kind": "unresolved",
            "reason": "Passage contains multiple product identities; split into product-specific sections",
        }
    required = ["manufacturer", "model"]
    if not all(
        canonical(identity.get(k, ""))
        and canonical(identity.get(k, "")) == canonical(identifiers.get(k, ""))
        for k in required
    ):
        return {
            "applies": False,
            "kind": "similar",
            "reason": "Manufacturer/model not explicitly identical",
        }
    for key, value in identity.get("variant", {}).items():
        if present(value) and canonical(identifiers.get(key, "")) != canonical(value):
            # Family records must explicitly enumerate applicable variants.
            variants = [
                canonical(v) for v in str(identifiers.get(f"applicable_{key}s", "")).split(",")
            ]
            if canonical(value) not in variants:
                return {
                    "applies": False,
                    "kind": "similar",
                    "reason": f"Variant {key} is not explicitly applicable",
                }
    if present(identity.get("mpn")):
        evidence_mpn = identifiers.get("mpn", "")
        if evidence_mpn and canonical(evidence_mpn) != canonical(identity["mpn"]):
            return {"applies": False, "kind": "similar", "reason": "Part number differs"}
        if not evidence_mpn and identifiers.get("scope", "").casefold() != "family":
            return {"applies": False, "kind": "unresolved", "reason": "Part number missing"}
    return {
        "applies": True,
        "kind": "family" if identifiers.get("scope", "").casefold() == "family" else "exact",
        "reason": "Explicit manufacturer, model, part number and variant applicability",
        "identifiers": identifiers,
    }


def pdf_header_present(content: bytes) -> bool:
    # Some manufacturer generators prepend a short notice; preserve original bytes.
    # The worker still parses the full PDF and rejects unreadable/scanned content.
    return re.search(rb"%PDF-[12]\.\d", content[:1024]) is not None
