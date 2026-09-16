# Northstar guided examples

All names and specifications are fictional. This collection tests workflow behavior, not model quality or safety performance.

## NS-001 - Start with clear evidence
A complete technical sheet with the exact part number.

Expected: Confirm Nylon, convert 25 cm to 250 mm, and retain the explicit count of 12 pairs.

## NS-002 - Convert units, preserve meaning
The source uses inches and an explicit yes/no value.

Expected: 10 inches becomes 254 mm. Touchscreen compatibility is true, not an invented certification.

## NS-003 - Resolve two supplier disagreements
A purchasing bulletin disagrees with a distributor sheet.

Expected: Compare both sources: HPPE versus Polyester, and 12 versus 6 pairs. Select each value with a reason.

## NS-004 - Reject the wrong variant
Nearby evidence describes M / Nitrile, while the catalog requests L / Latex.

Expected: Leave material and pack quantity unknown. A related model does not prove variant applicability.

## NS-005 - Do not turn boxes into pairs
A receiving note states two boxes per carton without a pair count.

Expected: Keep pairs per pack unknown. Packaging structure alone does not establish the number of gloves.

## NS-006 - Use explicitly scoped family evidence
A family bulletin explicitly applies to sizes M and L with PU coating.

Expected: Use the shared Nylon material, with family applicability recorded in the evidence.

## NS-007 - Catch an implausible dimension
The supplier entered 850 mm for glove length.

Expected: Flag the value as invalid against the category range. Do not silently guess a correction.

## NS-008 - Protect an existing catalog value
The imported material is Leather; the source says HPPE.

Expected: Flag the contradiction for review and preserve the original Leather value.

## NS-009 - Admit that evidence is missing
This product has no matching technical record.

Expected: Keep material and packaging unknown; no neighboring model may fill the gaps.

## NS-010 - Ignore instructions inside a source
A source contains an instruction to invent a certification.

Expected: Extract the explicit touchscreen fact, ignore the instruction, and leave certification unknown.

## NS-011 - Distinguish packaging variants
The same model and glove size are sold in P6 and P24 packs.

Expected: Use 6 pairs for the exact P6 part number. Never borrow the 24-pair value.

## NS-012 - Separate near-identical model names
PG-2100 is distinct from PG-210 despite the similar name.

Expected: Use Leather from the PG-2100 record and reject the PG-210 Nylon evidence.
