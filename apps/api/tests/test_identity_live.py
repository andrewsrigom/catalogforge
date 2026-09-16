"""Regression checks for real-source identification, with no provider/network calls."""

import pytest
from catalogforge import enrichment, providers
from catalogforge.config import settings
from catalogforge.contracts import AttributeDefinition, ExtractionOutput, ProposedValue
from catalogforge.domain import identity_match


@pytest.fixture
def real_identity(monkeypatch):
    monkeypatch.setenv("AI_MODE", "real")
    settings.cache_clear()
    yield
    settings.cache_clear()


@pytest.mark.asyncio
async def test_printed_brand_and_style_with_title_remain_exact(real_identity, monkeypatch):
    async def output(*args):
        return providers.Identifiers(manufacturer="Northstar", model="NX-42"), {}

    monkeypatch.setattr(providers, "structured", output)
    found = await providers.identify("Northstar Safety Ltd\nNX-42 - Thermal glove")
    assert identity_match({"manufacturer": "Northstar", "model": "NX-42", "variant": {}}, found)[
        "applies"
    ]
    assert not identity_match({"manufacturer": "Northstar", "model": "NX-4", "variant": {}}, found)[
        "applies"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["Westport A0400", "Westport A040-N", "Westport X/A040"])
async def test_model_and_brand_substrings_cannot_prove_identity(real_identity, monkeypatch, source):
    async def output(*args):
        return providers.Identifiers(manufacturer="West", model="A040"), {}

    monkeypatch.setattr(providers, "structured", output)
    found = await providers.identify(source)
    assert "manufacturer" not in found and "model" not in found
    assert not identity_match({"manufacturer": "West", "model": "A040", "variant": {}}, found)[
        "applies"
    ]


@pytest.mark.asyncio
async def test_multi_product_unlabeled_passage_cannot_authorize_evidence(
    real_identity, monkeypatch
):
    async def output(*args):
        return providers.Identifiers(manufacturer="Northstar", model="NX-42", ambiguous=True), {}

    monkeypatch.setattr(providers, "structured", output)
    found = await providers.identify("Northstar NX-42 and NX-43 technical specifications")
    assert not identity_match(
        {"manufacturer": "Northstar", "model": "NX-42", "variant": {}}, found
    )["applies"]


@pytest.mark.asyncio
async def test_family_sizes_are_grounded_individually(real_identity, monkeypatch):
    async def output(*args):
        return providers.Identifiers(
            manufacturer="Northstar", model="NX-42", scope="family", applicable_sizes="S, M, L"
        ), {}

    monkeypatch.setattr(providers, "structured", output)
    found = await providers.identify("Northstar NX-42 available sizes: S / M / L")
    assert identity_match(
        {"manufacturer": "Northstar", "model": "NX-42", "variant": {"size": "M"}}, found
    )["applies"]
    assert not identity_match(
        {"manufacturer": "Northstar", "model": "NX-42", "variant": {"size": "XL"}}, found
    )["applies"]
    unsupported = await providers.identify("Northstar NX-42 available sizes: S / M")
    assert "applicable_sizes" not in unsupported


@pytest.mark.asyncio
async def test_same_retrieved_evidence_is_not_extracted_twice(monkeypatch):
    calls = []

    async def step(*args):
        pass

    async def extract(payload):
        calls.append(payload)
        return ExtractionOutput(
            values=[
                ProposedValue(
                    attribute_key="material",
                    raw_value="Cotton",
                    chunk_id="a",
                    quote="Material: Cotton",
                )
            ]
        ), {"model_calls": 1, "tokens": {"input_tokens": 10, "output_tokens": 5}}

    monkeypatch.setattr(enrichment, "step", step)
    monkeypatch.setattr(enrichment, "extract", extract)
    state = {
        "passages": [{"id": "a"}],
        "identity": {},
        "attributes": [],
        "extracted": [],
        "metrics": {"model_calls": 0},
    }
    state.update(await enrichment.extract_values(state))
    state["passages"] = [{"id": "a"}]
    assert await enrichment.extract_values(state) == {}
    assert len(calls) == 1 and len(state["extracted"]) == 1
    state["passages"] = [{"id": "a"}, {"id": "b"}]
    state.update(await enrichment.extract_values(state))
    assert len(calls) == 2 and state["extracted_passages"] == ["a", "b"]
    assert len(state["extracted"]) == 1


@pytest.mark.parametrize(
    "title,expected",
    [
        ("A060 - Impact Cotton Hot Mill A2", "A060"),
        ("NX-42-B - Thermal glove", "NX-42-B"),
        ("NX-42-B", "NX-42-B"),
        ("NX-42 Blue", "NX-42 Blue"),
    ],
)
def test_model_heading_preserves_code_suffix(title, expected):
    assert providers.model_reference(title, "Northstar\n" + title) == expected
    assert providers.model_reference(title, "Unrelated source") == title


@pytest.mark.parametrize(
    "raw,quote,expected",
    [
        (12.0, "Inner Pack:  12", True),
        (12, "Pack: 12.00", True),
        (12, "Pack: 120", False),
        (12, "Pack: 12.5", False),
        ("12", "Pack: 12.5", False),
        (12, "Pack: -12", False),
        (12, "Code A12", False),
        (0.25, "Length: 0.25 m", True),
    ],
)
def test_numeric_provider_values_need_complete_matching_numbers(raw, quote, expected):
    assert enrichment.literal_value_supported(raw, quote) is expected


def test_layout_whitespace_is_grounded_in_the_original_source():
    assert (
        enrichment.grounded_quote("Inner Pack: 12", "Header\nInner Pack:  12\nFooter")
        == "Inner Pack:  12"
    )
    assert (
        enrichment.grounded_quote("Materials: Cotton Nylon", "Materials: Cotton\nNylon")
        == "Materials: Cotton\nNylon"
    )
    for quote, passage in [
        ("Pack: 12", "Pack: 120"),
        ("Pack: 12", "Pack: 12.5"),
        ("12", "-12"),
        ("Cotton", "Cottonseed"),
        ("Material: Silk", "Material: Cotton"),
    ]:
        assert enrichment.grounded_quote(quote, passage) is None


def test_prefixed_pdf_keeps_original_bytes_and_is_readable():
    import io

    from catalogforge.domain import pdf_header_present
    from catalogforge.ingestion import extract_sections
    from reportlab.pdfgen.canvas import Canvas

    stream = io.BytesIO()
    pdf = Canvas(stream)
    pdf.drawString(30, 700, "Manufacturer: Northstar / Model: NX-42 / Material: Cotton")
    pdf.save()
    original = b"2777/24960-01/E00-00" + stream.getvalue()
    assert pdf_header_present(original)
    sections = extract_sections(original, "pdf")
    assert len(sections) == 1 and "Material: Cotton" in sections[0]["text"]
    assert original.startswith(b"2777/")
    assert not pdf_header_present(b"not a PDF")
    assert not pdf_header_present(b"x" * 1024 + stream.getvalue())


@pytest.mark.parametrize(
    "quote",
    [
        "NX-42M Orange 60.0 25.0 52.0 0.0780",
        "Carton Dimensions/Weight\nItem Colour Len Wid Hgt\nNX-42M Orange 60.0 25.0 52.0",
        "Box length: 60 cm",
        "Packaging length: 60 cm",
        "Comprimento da caixa: 60 cm",
        "Width: 60 mm",
    ],
)
def test_product_length_cannot_use_ambiguous_or_packaging_measurements(quote):
    attribute = AttributeDefinition(key="length_mm", label="Glove length", type="number", unit="mm")
    assert not enrichment.measurement_quote_supported(attribute, quote)


@pytest.mark.parametrize("quote", ["Length: 230 mm", "Glove length: 10 in", "Comprimento: 23 cm"])
def test_explicit_product_lengths_remain_eligible(quote):
    attribute = AttributeDefinition(key="length_mm", label="Glove length", type="number", unit="mm")
    assert enrichment.measurement_quote_supported(attribute, quote)


def test_explicit_packaging_attribute_can_use_packaging_measurement():
    attribute = AttributeDefinition(
        key="carton_length", label="Carton length", type="number", unit="cm"
    )
    assert enrichment.measurement_quote_supported(attribute, "Carton length: 60 cm")
    count = AttributeDefinition(key="outer_carton_count", label="Outer Carton", type="number")
    assert enrichment.measurement_quote_supported(count, "Outer Carton: 120")


def test_cropping_packaging_table_title_cannot_change_measurement_subject():
    attribute = AttributeDefinition(key="length_mm", label="Glove length", type="number", unit="mm")
    quote = "Item Colour Len Wid Hgt\nNX-42M Orange 61.0 26.0 38.0"
    passage = "Northstar NX-42\nCarton Dimensions/Weight\n" + quote
    assert not enrichment.measurement_quote_supported(attribute, quote, passage)
    explicit = "Glove length: 230 mm"
    assert enrichment.measurement_quote_supported(attribute, explicit, passage + "\n" + explicit)
    assert enrichment.measurement_quote_supported(
        attribute, "Length: 230 mm", "Length: 230 mm\n" + passage
    )
