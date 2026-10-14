"""Pure fee functions, one per provider term kind (data contract section 4.1).

Money is `int` minor units. Intermediate values are exact `Fraction`s and are
rounded once per component with the contract's rounding mode.
"""

from fractions import Fraction

ROUNDING_MODES = ("half_up", "half_even")


def round_minor(value: Fraction | int, mode: str) -> int:
    """Round an exact value to an integer; `half_up` rounds ties away from zero."""
    if mode not in ROUNDING_MODES:
        raise ValueError(f"unknown rounding mode: {mode!r}")
    value = Fraction(value)
    magnitude = abs(value)
    quotient, remainder = divmod(magnitude.numerator, magnitude.denominator)
    twice = 2 * remainder
    if twice > magnitude.denominator or (
        twice == magnitude.denominator and (mode == "half_up" or quotient % 2 == 1)
    ):
        quotient += 1
    return quotient if value >= 0 else -quotient


def bps_of(amount_minor: int, bps: int, mode: str) -> int:
    """round(amount × bps / 10000)."""
    return round_minor(Fraction(amount_minor * bps, 10000), mode)


def card_segment(card_type: str, card_region: str) -> str:
    """`eea_consumer` for consumer cards in the domestic or intra-EEA region, else `other`."""
    consumer = card_type in ("consumer_debit", "consumer_credit")
    eea = card_region in ("domestic", "intra_eea")
    return "eea_consumer" if consumer and eea else "other"


def tier_bps(volume_minor: int, tiers: list[dict]) -> int:
    """Bps of the tier the volume falls in; `up_to_minor` is an exclusive upper bound (None = open)."""
    for tier in tiers:
        if tier["up_to_minor"] is None or volume_minor < tier["up_to_minor"]:
            return tier["bps"]
    raise ValueError(f"no tier for volume {volume_minor}")


def pass_through(
    amount_minor: int,
    interchange_bps: int,
    scheme_fee_bps: int,
    scheme_fee_fixed_minor: int,
    mode: str,
) -> tuple[int, int]:
    """(interchange, scheme_fee) for a successful payment."""
    interchange = bps_of(amount_minor, interchange_bps, mode)
    scheme_fee = bps_of(amount_minor, scheme_fee_bps, mode) + scheme_fee_fixed_minor
    return interchange, scheme_fee


def markup_retroactive(amount_minor: int, month_volume_minor: int, tiers: list[dict], mode: str) -> int:
    """Markup at the tier of the whole month's processed volume."""
    return bps_of(amount_minor, tier_bps(month_volume_minor, tiers), mode)


def per_transaction_fixed(amount_minor: int) -> int:
    """Fixed fee per successful payment."""
    return amount_minor


def blended_rate(
    amount_minor: int, status: str, segment: str, segments: dict, failed_attempts: str, mode: str
) -> int:
    """All-in fee by segment for a succeeded payment; 0 for declined/failed under `no_fee`."""
    if status != "succeeded":
        if status not in ("declined", "failed"):
            raise ValueError(f"unknown payment status: {status!r}")
        if failed_attempts != "no_fee":
            raise ValueError(f"unsupported failed_attempts: {failed_attempts!r}")
        return 0
    rate = segments[segment]
    return bps_of(amount_minor, rate["bps"], mode) + rate["fixed_minor"]


def volume_adjustment(segment_volume_minor: int, tiers: list[dict], mode: str) -> int:
    """Monthly marginal discount: −round((V − threshold) × (bps1 − bps2) / 10000) above the threshold, else 0."""
    threshold = tiers[0]["up_to_minor"]
    if segment_volume_minor <= threshold:
        return 0
    return -bps_of(segment_volume_minor - threshold, tiers[0]["bps"] - tiers[1]["bps"], mode)


def refund(fee_minor: int, credit_original_markup: bool, original_expected_markup: int) -> tuple[int, int | None]:
    """(refund_fee, markup_credit); markup_credit is None when the term grants no credit."""
    if not credit_original_markup:
        return fee_minor, None
    return fee_minor, -original_expected_markup


def chargeback_fee(amount_minor: int) -> int:
    """Fixed fee per chargeback."""
    return amount_minor


def monthly_minimum(amount_minor: int, month_markup_minor: int) -> int:
    """Top-up to the minimum markup: max(0, minimum − month's expected markup)."""
    return max(0, amount_minor - month_markup_minor)


def eur_equivalent(amount_minor: int, mid: Fraction, mode: str) -> int:
    """round(amount / mid); mid is units of the payout currency per 1 EUR."""
    return round_minor(Fraction(amount_minor) / mid, mode)


def payout_fee(amount_minor: int, mid: Fraction, term: dict, mode: str) -> int:
    """Fixed fee, or clamp(round(E × bps / 10000), min, cap) on the EUR equivalent E."""
    if "fixed_minor" in term:
        return term["fixed_minor"]
    fee = bps_of(eur_equivalent(amount_minor, mid, mode), term["bps"], mode)
    return min(max(fee, term["min_minor"]), term["cap_minor"])


def fx_spread_cap(amount_minor: int, mid: Fraction, cap_bps: int, mode: str) -> int:
    """Largest EUR debit the cap allows: round(amount / (mid × (1 − cap_bps / 10000)))."""
    return round_minor(Fraction(amount_minor * 10000) / (mid * (10000 - cap_bps)), mode)
