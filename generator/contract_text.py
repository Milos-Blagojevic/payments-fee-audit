"""Renders every provider contract version (contracts/providers/*.yml) as legal prose in contracts/text/*.md.

Version 1 of a contract becomes a master agreement; every later version becomes an amendment letter that
replaces, inserts or deletes only the clauses whose wording changed. Deterministic templates, no LLM. Run
`python -m generator.contract_text` after changing a provider contract; the files are committed and a test
checks they equal a fresh render. The prose is the input of the LLM extraction (docs/llm-extraction.md).
"""

import argparse
import datetime as dt
from pathlib import Path

from feeaudit.contracts import load_contract_file

NOTICE = "*Illustrative contract text for a fictional company. Not a real agreement and not legal advice.*"
FERNWAY = "Fernway"

# ---- amounts, rates, dates and numbers as written in contracts -----------

_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n):
    """A non-negative integer in British English words: 1040 -> 'one thousand and forty'."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")
    if n < 1000:
        rest = n % 100
        return f"{_ONES[n // 100]} hundred" + (f" and {words(rest)}" if rest else "")
    for value, name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= value:
            head, rest = f"{words(n // value)} {name}", n % value
            if not rest:
                return head
            return head + (" and " if rest < 100 else " ") + words(rest)
    raise AssertionError(n)


def _plural(n, word):
    return word if n == 1 else f"{word}s"


def money_words(minor):
    euros, cents = divmod(minor, 100)
    if euros and cents:
        return f"{words(euros)} euro and {words(cents)} {_plural(cents, 'cent')}"
    if cents:
        return f"{words(cents)} euro {_plural(cents, 'cent')}"
    return f"{words(euros)} euro"


def amount(minor):
    """EUR minor units as in a contract: 250000 -> 'EUR 2,500.00 (two thousand five hundred euro)'."""
    return f"{amount_short(minor)} ({money_words(minor)})"


def amount_short(minor):
    euros, cents = divmod(minor, 100)
    return f"EUR {euros:,}.{cents:02d}"


def rate(bps):
    """Basis points as in a contract: 45 -> '0.45% (forty-five basis points)'."""
    return f"{rate_short(bps)} ({words(bps)} {_plural(bps, 'basis point')})"


def rate_short(bps):
    return f"{bps // 100}.{bps % 100:02d}%"


def days(n):
    return f"{words(n)} ({n}) {_plural(n, 'day')}"


def long_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d:%B %Y}"


# ---- providers: parties, wording and clause layout ----------------------

CARD_KINDS = {
    "pass_through", "markup_bps_tiered", "per_transaction_fixed", "blended_rate", "volume_discount", "refund",
    "chargeback_fee", "monthly_minimum",
}
TIME_ZONES = {
    "UTC": "Coordinated Universal Time (UTC)",
    "Europe/Berlin": (
        "the local time in Frankfurt am Main, Germany (IANA time zone Europe/Berlin, including summer time where "
        "it applies), so that a calendar month begins at 00:00 local time on its first day"
    ),
}
CURRENCIES = {"EUR": "euro (EUR)", "GBP": "pounds sterling (GBP)", "USD": "US dollars (USD)",
              "CHF": "Swiss francs (CHF)", "PLN": "Polish zloty (PLN)"}
# rail: (defined name with its article, the Payout it covers)
RAILS = {
    "sepa": ("a \"SEPA Payout\"", "Payout in euro executed as a SEPA credit transfer"),
    "faster_payments": ("a \"Faster Payments Payout\"", "Payout in pounds sterling executed through the UK Faster Payments scheme"),
    "swift": ("a \"SWIFT Payout\"", "Payout executed by international wire transfer through the SWIFT network"),
    "elixir": ("an \"Elixir Payout\"", "Payout in Polish zloty to a bank account in Poland executed through the Elixir domestic clearing system"),
}
SEGMENTS = {
    "eea_consumer": "EEA Consumer Cards",
    "other": "Other Cards (commercial cards, and consumer cards used in inter-regional Transactions)",
}

# Each article: (number, heading, [(clause, heading, renderer)]). Renderer "term" renders the YAML term with that
# clause and is skipped when the version has no such term; any other name is a fixed clause from CLAUSES below.
PROVIDERS = {
    "northgate": {
        "title": "Master Acquiring Services Agreement",
        "role": "Acquirer",
        "client_role": "Merchant",
        "events": "Transactions",
        "law": "the laws of the Federal Republic of Germany",
        "courts": "Frankfurt am Main",
        "recitals": [
            "The Acquirer provides card acquiring services for Visa and Mastercard payments.",
            "The Merchant operates an online marketplace and wishes to appoint the Acquirer to acquire card "
            "payments made by buyers on that marketplace, on interchange-plus-plus pricing.",
        ],
        "articles": [
            (1, "Definitions and interpretation", [("1.1", "Definitions", "definitions"), ("1.2", "Interpretation", "interpretation")]),
            (2, "Commencement and duration", [("2.1", "Commencement", "commencement"), ("2.2", "Duration", "duration")]),
            (3, "Interchange and scheme fees", [("3.1", "Pass-through fees", "term")]),
            (4, "Acquirer fees", [
                ("4.1", "Currency", "currency"), ("4.2", "Markup", "term"), ("4.3", "Fixed fee", "term"),
                ("4.4", "Calculation and rounding", "rounding"),
            ]),
            (5, "Refunds", [("5.1", "Refund fee and markup credit", "term")]),
            (6, "Chargebacks", [("6.1", "Chargeback fee", "term")]),
            (7, "Invoicing, disputes and minimum fee", [
                ("7.1", "Monthly invoice", "invoicing"), ("7.2", "Payment", "payment"), ("7.3", "Disputes", "disputes"),
                ("7.4", "Monthly minimum", "term"),
            ]),
            (8, "General", [("8.1", "Entire agreement", "entire"), ("8.2", "Variation", "variation"), ("8.3", "Governing law", "law")]),
        ],
    },
    "brightpay": {
        "title": "Payment Services Agreement",
        "role": "PSP",
        "client_role": "Merchant",
        "events": "Transactions",
        "law": "the laws of the Netherlands",
        "courts": "Amsterdam",
        "recitals": [
            "The PSP provides online card payment services to merchants on blended pricing.",
            "The Merchant operates an online marketplace and wishes to use the PSP's services for card payments "
            "made by buyers on that marketplace.",
        ],
        "articles": [
            (1, "Definitions and interpretation", [("1.1", "Definitions", "definitions"), ("1.2", "Interpretation", "interpretation")]),
            (2, "Commencement and duration", [("2.1", "Commencement", "commencement"), ("2.2", "Duration", "duration")]),
            (3, "Service fees", [
                ("3.1", "Service Fee", "term"), ("3.2", "Currency", "currency"), ("3.3", "Calculation and rounding", "rounding"),
                ("3.4", "Volume discount", "term"),
            ]),
            (4, "Invoicing and disputes", [("4.1", "Monthly invoice", "invoicing"), ("4.2", "Payment", "payment"), ("4.3", "Disputes", "disputes")]),
            (5, "Refunds", [("5.1", "Processing of Refunds", "refund_processing"), ("5.2", "Refund fee", "term")]),
            (6, "Chargebacks", [
                ("6.1", "Notification", "chargeback_notice"), ("6.2", "Representment", "representment"),
                ("6.3", "Chargeback fee", "term"),
            ]),
            (7, "General", [("7.1", "Entire agreement", "entire"), ("7.2", "Variation", "variation"), ("7.3", "Governing law", "law")]),
        ],
    },
    "kestrel": {
        "title": "Payout and Foreign Exchange Services Agreement",
        "role": "Provider",
        "client_role": "Customer",
        "events": "Payouts",
        "law": "the laws of England and Wales",
        "courts": "London",
        "recitals": [
            "The Provider executes payouts to bank accounts in several currencies and converts funds between "
            "currencies for that purpose.",
            "The Customer pays out marketplace sellers' funds and wishes to use the Provider's services to do so.",
        ],
        "articles": [
            (1, "Definitions and interpretation", [("1.1", "Definitions", "definitions"), ("1.2", "Interpretation", "interpretation")]),
            (2, "Payout fees", [
                ("2.1", "SEPA Payouts", "term"), ("2.2", "Faster Payments Payouts", "term"), ("2.3", "SWIFT Payouts", "term"),
                ("2.4", "Elixir Payouts", "term"),
            ]),
            (3, "Calculation of fees", [("3.1", "Currency", "currency"), ("3.2", "Calculation and rounding", "rounding")]),
            (4, "Foreign exchange", [("4.1", "Spread cap", "term"), ("4.2", "Rate disclosure", "rate_disclosure")]),
            (5, "Invoicing and disputes", [("5.1", "Monthly invoice", "invoicing"), ("5.2", "Payment", "payment"), ("5.3", "Disputes", "disputes")]),
            (6, "Commencement and duration", [("6.1", "Commencement", "commencement"), ("6.2", "Duration", "duration")]),
            (7, "General", [("7.1", "Entire agreement", "entire"), ("7.2", "Variation", "variation"), ("7.3", "Governing law", "law")]),
        ],
    },
}


class Ctx:
    """One contract version being rendered: the version, its master (version 1) and the provider's wording."""

    def __init__(self, doc, master):
        self.doc, self.master = doc, master
        self.p = PROVIDERS[doc["counterparty"]]
        self.role, self.client, self.events = self.p["role"], self.p["client_role"], self.p["events"]
        # Card payments count from when they are made, payouts from when they are executed.
        self.made = "made" if self.events == "Transactions" else "executed"
        self.kinds = {t["kind"] for t in doc["terms"]}
        self.fixed = {name: clause for _, _, entries in self.p["articles"] for clause, _, name in entries if name != "term"}

    def clause_of(self, kind):
        return next((t["clause"] for t in self.doc["terms"] if t["kind"] == kind), None)


# ---- defined terms --------------------------------------------------------

def _definitions(c):
    has = c.kinds.__contains__
    card = bool(c.kinds & CARD_KINDS)
    payout = has("payout_fee") or has("fx_spread_cap")
    swift_bps = any(t["kind"] == "payout_fee" and "bps" in t for t in c.doc["terms"])
    defs = [
        ("Agreement", "this agreement, including its Schedules, as amended from time to time"),
        ("Business Day", "a day other than a Saturday, a Sunday or a public holiday on which banks are open for general business"),
        ("Invoice", f"the monthly invoice issued by the {c.role} under clause {c.fixed['invoicing']}"),
    ]
    if card:
        defs += [
            ("Card Scheme", "Visa or Mastercard"),
            ("Transaction", f"a payment by card to the {c.client} submitted to the {c.role} for authorisation"),
            ("Successful Transaction", "a Transaction that is authorised by the card issuer and captured"),
        ]
    if has("blended_rate"):
        defs += [
            ("Declined or Failed Attempt", "a Transaction that is declined by the card issuer or fails for technical reasons and is not captured"),
            ("EEA Consumer Card", "a consumer debit or consumer credit card used in a domestic or intra-EEA Transaction"),
            ("Other Card", "any card that is not an EEA Consumer Card, including every commercial card"),
        ]
    if has("pass_through"):
        defs += [
            ("Interchange Fee", "the fee payable to the card issuer under the Card Scheme rules for a Transaction"),
            ("Scheme Fee", "the fee charged by a Card Scheme for a Transaction"),
        ]
    if has("markup_bps_tiered"):
        defs += [
            ("Markup", f"the {c.role}'s margin payable under clause {c.clause_of('markup_bps_tiered')}"),
            ("Monthly Processed Volume", f"the aggregate amount of all Successful Transactions processed by the {c.role} for the {c.client} in a calendar month, before deduction of any fee, Refund or Chargeback"),
        ]
    if has("volume_discount"):
        defs.append(("EEA Consumer Volume", "the aggregate amount of all Successful Transactions made with EEA Consumer Cards in a calendar month"))
    if has("refund"):
        defs.append(("Refund", f"the reversal, at the {c.client}'s request, of the whole amount of a Successful Transaction"))
    if has("chargeback_fee"):
        defs.append(("Chargeback", "the reversal of a Successful Transaction initiated by the card issuer under the Card Scheme rules"))
    if payout:
        defs += [
            ("Payout", f"a transfer of funds by the {c.role} from the {c.client}'s account to a bank account nominated by the {c.client}"),
            ("Execution Time", f"the time at which the {c.role} executes a Payout"),
            ("Execution Hour", "the clock hour (UTC) that contains the Execution Time"),
            ("Mid Rate", f"the mid-market exchange rate of a currency pair for a clock hour, as published for that hour in the hourly reference rate series maintained by the {c.role} and shown on its statements"),
        ]
    if swift_bps:
        defs.append(("EUR Equivalent", "the amount of a Payout converted into euro at the Mid Rate for its Execution Hour"))
    if has("fx_spread_cap"):
        defs += [
            ("Applied Rate", f"the exchange rate actually applied by the {c.role} to convert euro into the currency of a Payout"),
            ("Spread", "the amount by which the Applied Rate is less favourable to the Customer than the Mid Rate for the Execution Hour, expressed as a percentage of that Mid Rate"),
        ]
    lines = ["In this Agreement the following terms have the following meanings:", ""]
    lines += [f"- **\"{name}\"** means {text}." for name, text in sorted(defs)]
    return "\n".join(lines)


# ---- fixed clauses (header facts and boilerplate) ------------------------

def _interpretation(c):
    return (
        "(a) Headings do not affect the interpretation of this Agreement. (b) References to clauses and Schedules "
        "are to clauses of and Schedules to this Agreement. (c) Unless stated otherwise, every reference to a time, "
        f"a date or a calendar month is to {TIME_ZONES[c.doc['timezone']]}."
    )


def _commencement(c):
    return (
        f"This Agreement takes effect on {long_date(c.master['effective_from'])} (the \"Effective Date\") and applies to "
        f"all {c.events} {c.made} on or after the Effective Date."
    )


def _duration(c):
    return (
        "This Agreement continues for an initial term of twenty-four months from the Effective Date and afterwards "
        "until terminated by either party on three months' written notice to the other."
    )


def _currency(c):
    text = f"All fees, charges and credits under this Agreement are calculated, invoiced and payable in {CURRENCIES[c.doc['currency']]}"
    if c.events == "Payouts":
        text += ", including fees on Payouts made in other currencies"
    return text + "."


def _rounding(c):
    events = "Transaction" if c.events == "Transactions" else "Payout"
    level = {
        "transaction": (
            f"Each fee and each credit is calculated separately for each {events} and for each fee component, and is "
            "rounded to the nearest whole euro cent before fees are aggregated on the Invoice."
        ),
        "invoice_line": "Each line of the Invoice is calculated on the exact aggregate of its fees and is rounded once to the nearest whole euro cent.",
    }[c.doc["rounding"]["level"]]
    mode = {
        "half_up": "An amount of exactly half a cent is rounded up, away from zero.",
        "half_even": "An amount of exactly half a cent is rounded to the nearest even cent (banker's rounding).",
    }[c.doc["rounding"]["mode"]]
    return f"{level} {mode}"


def _invoicing(c):
    detail = "each fee for each Transaction" if c.events == "Transactions" else "each Payout with its fee and the euro debited for it"
    return (
        f"Within ten Business Days after the end of each calendar month the {c.role} shall issue an Invoice for the fees of "
        f"that month, together with a statement listing {detail}."
    )


def _payment(c):
    return (
        f"Each Invoice is payable within fourteen days of its date. The {c.role} may instead deduct the amount of an "
        f"Invoice from funds it holds for the {c.client}, provided the Invoice has been issued first."
    )


def _disputes(c):
    return (
        f"The {c.client} may dispute an Invoice, or any fee or charge shown on it or on the accompanying statement, by "
        f"written notice given within {days(c.doc['dispute_window_days'])} after the date of the Invoice. Any amount "
        f"found to have been overcharged shall be credited on the next Invoice. Fees not disputed within that period "
        "are deemed accepted, except in the case of manifest error or fraud."
    )


def _entire(c):
    return "This Agreement is the entire agreement between the parties on its subject matter and supersedes any earlier arrangement."


def _variation(c):
    return (
        "No variation of this Agreement is effective unless it is made in writing and signed by or on behalf of both "
        f"parties, including by an amendment letter from the {c.role} countersigned by the {c.client}. An amendment "
        "letter states the date from which it applies."
    )


def _law(c):
    return f"This Agreement is governed by {c.p['law']}. The courts of {c.p['courts']} have exclusive jurisdiction."


def _refund_processing(c):
    return (
        f"The {c.client} may request a Refund of a Successful Transaction through the {c.role}'s interface. The "
        f"{c.role} returns the Transaction amount to the cardholder and debits it from the {c.client}'s settlement funds."
    )


def _chargeback_notice(c):
    return f"The {c.role} shall notify the {c.client} of each Chargeback within two Business Days of receiving it from the Card Scheme."


def _representment(c):
    return (
        f"The {c.client} may provide evidence for the {c.role} to contest a Chargeback under the Card Scheme rules. "
        "The outcome of a representment does not affect the fee under clause "
        f"{c.clause_of('chargeback_fee')}."
    )


def _rate_disclosure(c):
    return (
        f"For each Payout in a currency other than euro the {c.role}'s statement shows the Applied Rate, the start of the "
        "hour whose Mid Rate was used and the euro debited."
    )


CLAUSES = {
    "definitions": _definitions, "interpretation": _interpretation, "commencement": _commencement,
    "duration": _duration, "currency": _currency, "rounding": _rounding, "invoicing": _invoicing,
    "payment": _payment, "disputes": _disputes, "entire": _entire, "variation": _variation, "law": _law,
    "refund_processing": _refund_processing, "chargeback_notice": _chargeback_notice,
    "representment": _representment, "rate_disclosure": _rate_disclosure,
}


# ---- fee terms --------------------------------------------------------------

def _band_table(tiers, label, column, value):
    rows = [f"| Band | {label} | {column} |", "|---|---|---|"]
    lower = None
    for i, tier in enumerate(tiers):
        upper = tier["up_to_minor"]
        if lower is None:
            bound = f"less than {amount_short(upper)}"
        elif upper is None:
            bound = f"{amount_short(lower)} or more"
        else:
            bound = f"{amount_short(lower)} or more but less than {amount_short(upper)}"
        rows.append(f"| {i + 1} | {bound} | {value(tier)} |")
        lower = upper
    return "\n".join(rows)


def _pass_through(c, t):
    markup = c.clause_of("markup_bps_tiered")
    extra = f" The Markup under clause {markup} is payable in addition." if markup else ""
    return (
        f"For each Successful Transaction the {c.client} shall pay the Interchange Fee and the Scheme Fee actually "
        f"incurred by the {c.role}, passed through at cost without any margin. The amounts charged shall not exceed "
        f"those in the interchange and scheme fee reference table designated \"{t['reference']}\" and described in "
        f"Schedule 1 (the \"Reference Table\").{extra}"
    )


def _markup(c, t):
    table = _band_table(t["tiers"], "Monthly Processed Volume", "Markup", lambda tier: rate(tier["bps"]))
    minimum = c.clause_of("monthly_minimum")
    subject = f"subject to the monthly minimum in clause {minimum} and " if minimum else ""
    return (
        f"(a) For each Successful Transaction the {c.client} shall pay a Markup equal to the percentage of the "
        "Transaction amount shown below for the band into which the Monthly Processed Volume of the calendar month "
        f"of the Transaction falls:\n\n{table}\n\n"
        "(b) The band is determined once the Monthly Processed Volume of the month is known, and its rate applies to "
        "every Successful Transaction of that month, including Transactions processed before the volume reached the "
        "lower limit of that band.\n\n"
        f"(c) The Markup is {subject}rounded in accordance with clause {c.fixed['rounding']}."
    )


def _fixed(c, t):
    return (
        f"In addition to the Markup, the {c.client} shall pay a fixed fee of {amount(t['amount_minor'])} for each "
        "Successful Transaction. No fixed fee is payable on a Transaction that is declined or fails."
    )


def _blended(c, t):
    rows = ["| Card | Percentage of the Transaction amount | Fixed amount per Transaction |", "|---|---|---|"]
    rows += [f"| {SEGMENTS[seg]} | {rate(p['bps'])} | {amount(p['fixed_minor'])} |" for seg, p in t["segments"].items()]
    table = "\n".join(rows)
    discount = c.clause_of("volume_discount")
    adjusted = f", subject to the volume discount in clause {discount}" if discount else ""
    return (
        f"(a) For each Successful Transaction the {c.client} shall pay a single all-inclusive service fee (the "
        f"\"Service Fee\") made of a percentage of the Transaction amount plus a fixed amount{adjusted}:\n\n{table}\n\n"
        "(b) The Service Fee includes all interchange, card scheme and processing fees; no other fee is payable on a "
        "Successful Transaction.\n\n"
        "(c) No Service Fee or other charge is payable for a Declined or Failed Attempt."
    )


def _volume_discount(c, t):
    first, second = t["tiers"]
    threshold = amount(first["up_to_minor"])
    fee = c.clause_of("blended_rate")
    return (
        f"(a) Where the EEA Consumer Volume of a calendar month exceeds {threshold}, the percentage element of the "
        f"Service Fee for EEA Consumer Cards is {rate(first['bps'])} on the first {amount_short(first['up_to_minor'])} "
        f"of that volume and {rate(second['bps'])} on the part of the EEA Consumer Volume in excess of "
        f"{amount_short(first['up_to_minor'])}. The reduced rate applies only to that excess, not to the whole volume.\n\n"
        f"(b) Transactions continue to be charged at the rate in clause {fee} when they are processed. The difference "
        f"is credited to the {c.client} as a single volume adjustment on the Invoice for that month.\n\n"
        "(c) The fixed amount of the Service Fee and the Service Fee for Other Cards are not affected."
    )


def _refund(c, t):
    text = f"(a) For each Refund the {c.client} shall pay a refund fee of {amount(t['fee_minor'])}.\n\n"
    if t["credit_original_markup"]:
        markup, fixed = c.clause_of("markup_bps_tiered"), c.clause_of("per_transaction_fixed")
        kept = f", the fixed fee under clause {fixed}" if fixed else ""
        text += (
            f"(b) On each Refund the {c.role} shall credit the {c.client} with the Markup under clause {markup} on the "
            f"refunded Successful Transaction. The Interchange Fee, the Scheme Fee{kept} and any other fee on that "
            "Transaction are not credited."
        )
    else:
        fee = c.clause_of("blended_rate")
        text += (
            f"(b) No fee paid on the refunded Transaction, including the Service Fee under clause {fee}, is credited "
            "or repaid when a Refund is made."
        )
    return text


def _chargeback(c, t):
    return (
        f"For each Chargeback the {c.client} shall pay a chargeback handling fee of {amount(t['amount_minor'])}, "
        "whatever the outcome of any representment."
    )


def _minimum(c, t):
    markup, refund = c.clause_of("markup_bps_tiered"), c.clause_of("refund")
    credits = f" Markup credits on Refunds under clause {refund} are disregarded for this purpose." if refund else ""
    return (
        f"If the total Markup under clause {markup} on the Successful Transactions of a calendar month is less than "
        f"{amount(t['amount_minor'])}, the {c.client} shall pay the difference as a minimum fee for that month, shown "
        f"as a separate line on the Invoice.{credits}"
    )


def _payout_fee(c, t):
    name, description = RAILS[t["rail"]]
    if "fixed_minor" in t:
        return f"For each {description} ({name}) the {c.client} shall pay a fee of {amount(t['fixed_minor'])}."
    return (
        f"For each {description} ({name}) the {c.client} shall pay a fee of {rate(t['bps'])} of the EUR "
        f"Equivalent of the Payout amount, subject to a minimum of {amount(t['min_minor'])} and a maximum of "
        f"{amount(t['cap_minor'])} per Payout."
    )


def _fx_cap(c, t):
    rows = ["| Payout currency | Maximum Spread |", "|---|---|"]
    rows += [f"| {CURRENCIES[cur]} | {rate(bps)} |" for cur, bps in t["caps_bps"].items()]
    table = "\n".join(rows)
    return (
        f"(a) For each Payout in a currency other than euro the {c.role} converts the euro debited from the "
        f"{c.client}'s account at the Applied Rate.\n\n"
        "(b) The Spread, measured against the Mid Rate for the Execution Hour of the Payout, shall not exceed the "
        f"maximum shown below for the Payout currency:\n\n{table}\n\n"
        f"(c) Where the Spread exceeds that maximum, the {c.role} shall refund to the {c.client} the euro debited in "
        "excess of the amount the maximum Spread allows."
    )


TERMS = {
    "pass_through": _pass_through, "markup_bps_tiered": _markup, "per_transaction_fixed": _fixed,
    "blended_rate": _blended, "volume_discount": _volume_discount, "refund": _refund, "chargeback_fee": _chargeback,
    "monthly_minimum": _minimum, "payout_fee": _payout_fee, "fx_spread_cap": _fx_cap,
}


# ---- documents --------------------------------------------------------------

def clauses(c):
    """{clause: (article number, article heading, markdown of the clause)} in document order."""
    terms = {t["clause"]: t for t in c.doc["terms"]}
    layout = {clause for _, _, entries in c.p["articles"] for clause, _, name in entries if name == "term"}
    unplaced = sorted(set(terms) - layout)
    if unplaced:
        raise ValueError(f"{c.doc['contract_id']} v{c.doc['version']}: no place in the layout for clauses {unplaced}")
    out = {}
    for number, heading, entries in c.p["articles"]:
        for clause, title, name in entries:
            if name == "term":
                if clause not in terms:
                    continue
                body = TERMS[terms[clause]["kind"]](c, terms[clause])
            else:
                body = CLAUSES[name](c)
            out[clause] = (number, heading, f"**{clause} {title}.** {body}")
    return out


def _signatures(c):
    lines = []
    for party, role in ((c.doc["name"], c.role), (FERNWAY, c.client)):
        lines += [f"Signed for and on behalf of **{party}** (the {role}):", "", "Name: ____________________  Title: ____________________  Date: __________", ""]
    return lines


def render_master(doc):
    c = Ctx(doc, doc)
    lines = [
        f"# {c.p['title']}", "", NOTICE, "",
        f"**Agreement reference:** {doc['contract_id']}", "",
        f"**Dated:** {long_date(doc['effective_from'])}", "",
        "**Between:**", "",
        f"1. **{doc['name']}** (the \"{c.role}\"); and",
        f"2. **{FERNWAY}**, a marketplace payments company (the \"{c.client}\").", "",
        "## Background", "",
    ]
    lines += [line for i, text in enumerate(c.p["recitals"]) for line in (f"({chr(65 + i)}) {text}", "")]
    lines += ["The parties agree as follows."]
    article = None
    for number, heading, text in clauses(c).values():
        if number != article:
            lines += ["", f"## {number}. {heading}"]
            article = number
        lines += ["", text]
    if "pass_through" in c.kinds:
        ref = next(t["reference"] for t in doc["terms"] if t["kind"] == "pass_through")
        lines += [
            "", "## Schedule 1: Reference Table", "",
            f"The Reference Table \"{ref}\" sets out the Interchange Fee and the Scheme Fee by Card Scheme, card type "
            f"and region. It is maintained by the {c.role}, made available to the {c.client} on request and "
            "incorporated in this Agreement by reference.",
        ]
    lines += ["", "## Signatures", ""] + _signatures(c)
    return "\n".join(lines).rstrip() + "\n"


def _quote(text):
    return "\n".join(f"> {line}" if line else ">" for line in text.split("\n"))


def render_amendment(doc, previous, master):
    """An amendment letter turning `previous` into `doc`: only clauses whose wording changed appear."""
    c, before = Ctx(doc, master), Ctx(previous, master)
    new, old = clauses(c), clauses(before)
    order = list(new)
    changes = []
    for clause in order:
        if clause not in old:
            after = order[order.index(clause) - 1]
            changes.append(f"the following new clause {clause} is inserted after clause {after}:\n\n{_quote(new[clause][2])}")
        elif new[clause][2] != old[clause][2]:
            changes.append(f"clause {clause} is deleted and replaced by the following:\n\n{_quote(new[clause][2])}")
    changes += [f"clause {clause} is deleted." for clause in old if clause not in new]
    if not changes:
        raise ValueError(f"{doc['contract_id']} v{doc['version']}: no clause changes from version {previous['version']}")
    number = doc["version"] - 1
    letter_date = (dt.date.fromisoformat(doc["effective_from"]) - dt.timedelta(days=21)).isoformat()
    title = c.p["title"]
    lines = [
        f"# Amendment No. {number} to the {title}", "", NOTICE, "",
        f"**From:** {doc['name']} (the \"{c.role}\")", "",
        f"**To:** {FERNWAY} (the \"{c.client}\")", "",
        f"**Date:** {long_date(letter_date)}", "",
        f"**Agreement reference:** {doc['contract_id']}", "",
        "Dear Sir or Madam,", "",
        f"**{title} dated {long_date(master['effective_from'])}, reference {doc['contract_id']} (the \"Agreement\")**", "",
        "We refer to the Agreement. Terms defined in the Agreement have the same meaning in this letter, and "
        f"references to clauses are to clauses of the Agreement. This letter is Amendment No. {number} to the "
        f"Agreement and is made under clause {c.fixed['variation']}.", "",
        f"1. **Amendment Effective Date.** The amendments in paragraph 2 take effect on {long_date(doc['effective_from'])} "
        f"(the \"Amendment Effective Date\") and apply to all {c.events} {c.made} on or after that date, determined in "
        f"accordance with clause {c.fixed['interpretation']}. {c.events} {c.made} before the Amendment Effective Date "
        "remain subject to the Agreement as it stood before this letter.", "",
        "2. **Amendments.** With effect from the Amendment Effective Date:",
    ]
    for i, change in enumerate(changes):
        lines += ["", f"({chr(97 + i)}) {change}"]
    lines += [
        "",
        "3. **Continuation.** Except as amended by this letter, the Agreement continues in full force and effect, "
        "and every other clause, including the fees, the rounding rules and the dispute period, applies unchanged. "
        "From the Amendment Effective Date, references to the Agreement are to the Agreement as amended by this letter.", "",
        "4. **Governing law.** This letter is governed by the law that governs the Agreement.", "",
        f"Please countersign this letter to confirm the {c.client}'s agreement.", "",
        "Yours faithfully,", "",
    ] + _signatures(c)
    return "\n".join(lines).rstrip() + "\n"


def render_all(providers_dir="contracts/providers"):
    """{file name: markdown} for every provider contract version: masters for version 1, letters otherwise."""
    by_contract = {}
    for path in sorted(Path(providers_dir).glob("*.yml")):
        doc = load_contract_file(path)
        by_contract.setdefault(doc["contract_id"], []).append((path.stem, doc))
    files = {}
    for versions in by_contract.values():
        versions.sort(key=lambda v: v[1]["version"])
        master = versions[0][1]
        files[f"{versions[0][0]}.md"] = render_master(master)
        for (_, previous), (stem, doc) in zip(versions, versions[1:]):
            files[f"{stem}.md"] = render_amendment(doc, previous, master)
    return dict(sorted(files.items()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--providers", default="contracts/providers")
    parser.add_argument("--out", default="contracts/text")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.md"):
        old.unlink()
    files = render_all(args.providers)
    for name, text in files.items():
        (out / name).write_text(text)
    print(f"{len(files)} contract text files written to {out}")


if __name__ == "__main__":
    main()
