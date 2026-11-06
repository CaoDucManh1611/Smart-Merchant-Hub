"""Validate scoped claim provenance without another generation call."""
import re

from app.rag.answer_guard import has_valid_citations, _money_values
from app.rag.topics import fold_topic_text


def _catalog_rows(source):
    rows = {}
    for line in source.splitlines():
        match = re.search(r"Mã tham chiếu:\s*([^;\n]+)", line)
        if match:
            rows[match.group(1).strip()] = line
    return rows


def render_verified_claims(claims, sources, *, query="", derived_source_id=None,
                           resolve_offering=None):
    if not isinstance(claims, list) or not claims or len(claims) > 20:
        raise ValueError("invalid_claims")
    rendered = []
    manifest = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("invalid_claim")
        text = claim.get("text")
        ids = claim.get("sources")
        if (not isinstance(text, str) or not text.strip() or len(text) > 3000
                or not isinstance(ids, list) or not ids
                or any(type(i) is not int or not 1 <= i <= len(sources) for i in ids)):
            raise ValueError("invalid_claim_source")
        if derived_source_id is not None:
            ids = list(dict.fromkeys([*ids, derived_source_id]))
        marked = text + " " + " ".join(f"[Source {i}]" for i in ids)
        if not has_valid_citations(marked, sources, query=query):
            raise ValueError("unsupported_claim")
        money = _money_values(text)
        catalog_rows = {}
        for source_id in ids:
            if source_id != derived_source_id:
                catalog_rows.update(_catalog_rows(sources[source_id - 1]))
        refs = claim.get("offering_refs", [])
        if not isinstance(refs, list) or len(refs) > 8 or any(
                not isinstance(ref, str) or not re.fullmatch(r"(?:product|service|rental):[1-9][0-9]*", ref)
                for ref in refs):
            raise ValueError("invalid_claim_offering_refs")
        if money and catalog_rows:
            # A multi-row citation cannot lend one product's price to another.
            # The model's identifiers are only hints: each one is checked
            # against cited evidence AND the current tenant SQL row.
            if not refs or resolve_offering is None:
                raise ValueError("unbound_catalog_price")
            if len(refs) != len(set(refs)) or any(ref not in catalog_rows for ref in refs):
                raise ValueError("uncited_catalog_identity")
            live = [resolve_offering(ref) for ref in refs]
            if any(item is None or item.get("ref") != ref for ref, item in zip(refs, live)):
                raise ValueError("stale_catalog_identity")
            for ref, item in zip(refs, live):
                row = catalog_rows[ref]
                expected_sku = str(item.get("sku") or "").strip()
                if expected_sku and f"SKU: {expected_sku};" not in row:
                    raise ValueError("catalog_variant_mismatch")
                from app.services.auto_reply_service import _format_vnd
                current_price = _money_values(f"{_format_vnd(item['price'])} đồng")
                if not current_price or not current_price.issubset(_money_values(row)):
                    raise ValueError("stale_catalog_price")
            permitted = set().union(*(_money_values(catalog_rows[ref]) for ref in refs))
            if derived_source_id is not None:
                permitted |= _money_values(sources[derived_source_id - 1])
            if not money.issubset(permitted):
                raise ValueError("claim_product_price_mismatch")
            if len(refs) > 1:
                # A comparison with several amounts needs explicit names in
                # text so that each amount can be matched to its own row.
                names = [fold_topic_text(str(item.get("name") or "")) for item in live]
                folded_text = fold_topic_text(text)
                if any(not name or name not in folded_text for name in names):
                    raise ValueError("ambiguous_catalog_comparison")
        # Bind a displayed product's price to its own catalog row even when
        # several products share one source and customer-facing SKUs are hidden.
        folded = fold_topic_text(text)
        product_mentions = []
        for source_id in ids:
            for row in sources[source_id-1].splitlines():
                name = re.search(r"(?:Tên|Name):\s*([^;\n]+)", row, re.IGNORECASE)
                if not name:
                    continue
                label = fold_topic_text(name.group(1))
                if not label:
                    continue
                for hit in re.finditer(r"(?<!\w)" + re.escape(label) + r"(?!\w)", folded):
                    product_mentions.append((hit.start(), hit.end(), row))
        product_mentions.sort(key=lambda item: (item[0], -item[1]))
        product_mentions = [item for index, item in enumerate(product_mentions)
                            if index == 0 or item[0] != product_mentions[index-1][0]]
        for index, (_start, end, row) in enumerate(product_mentions):
            next_start = product_mentions[index+1][0] if index+1 < len(product_mentions) else len(folded)
            # With multiple products, every price must be attached to its
            # own named product rather than borrowed from a sibling row.
            amounts = _money_values(folded[end:next_start])
            if len(product_mentions) == 1:
                amounts = _money_values(text)
            elif _money_values(text) and not amounts:
                raise ValueError("claim_product_price_mismatch")
            permitted = _money_values(row)
            if derived_source_id is not None:
                permitted |= _money_values(sources[derived_source_id-1])
            if not amounts.issubset(permitted):
                raise ValueError("claim_product_price_mismatch")
        rendered.append(marked)
        manifest.append({"claim_index": len(rendered), "source_ids": ids})
    return "\n".join(rendered), manifest
