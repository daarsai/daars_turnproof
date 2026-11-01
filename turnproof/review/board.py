"""Station board: the numbers a station manager runs on, computed from the run folders.

Every figure here is derived from run_summary.json, review.json and the packets; nothing is
estimated. Money uses the SLA penalty rate declared in each scenario (synthetic in the demo).
"""

from __future__ import annotations

from collections import Counter


def _rate(card: dict) -> tuple[float | None, str]:
    meta = card.get("meta") or {}
    r = meta.get("sla_penalty_per_min")
    return (float(r) if r is not None else None), meta.get("currency") or ""


def station_board(cards: list[dict], claims: list[dict]) -> dict:
    """cards: run_card() dicts (newest first); claims: airline_claim dicts per card (same order)."""
    n_runs = len(cards)
    candidates = [c for c in cards if c["status"] in ("candidate", "candidate_unsynced")]
    states = Counter(c["review"]["state"] for c in cards)
    claimed_min = sum(int((cl or {}).get("minutes") or 0) for cl in claims)
    supported_min, unsupported_min, exposure, currency = 0, 0, 0.0, ""
    computable = 0
    for c, cl in zip(cards, claims, strict=True):
        p = c.get("proposed") or {}
        sup = p.get("minutes_supported_by_video")
        if sup is None or not cl:
            continue
        computable += 1
        claimed = int(cl.get("minutes") or 0)
        supported_min += int(sup)
        unsupported_min += max(0, claimed - int(sup))
        rate, cur = _rate(c)
        if rate is not None:
            exposure += max(0, claimed - int(sup)) * rate
            currency = currency or cur
    spark = [c for c in cards if c.get("spark_ok")]
    agree = sum(1 for c in spark if c.get("spark_agree") is True)
    cost = sum(float(c.get("cost") or 0) for c in cards)
    sent_like = states["SENT"] + states["ACKNOWLEDGED"] + states["DISPUTED"] + states["RESOLVED"]
    return {
        "runs": n_runs,
        "candidates": len(candidates),
        "no_candidate": n_runs - len(candidates),
        "claims": sum(1 for cl in claims if cl),
        "claimed_min": claimed_min,
        "supported_min": supported_min,
        "unsupported_min": unsupported_min,
        "computable": computable,
        "exposure": round(exposure, 2),
        "currency": currency,
        "sent": sent_like,
        "acknowledged": states["ACKNOWLEDGED"] + states["RESOLVED"],
        "disputed": states["DISPUTED"],
        "rejected": states["REJECTED"],
        "under_review": states["UNDER_REVIEW"] + states["CONFIRMED"],
        "spark_checked": len(spark),
        "spark_agree": agree,
        "model_spend": round(cost, 3),
        "spend_per_run": round(cost / n_runs, 3) if n_runs else 0.0,
    }
