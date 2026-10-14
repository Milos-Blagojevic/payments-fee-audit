"""Differential check between the reference table and a (hand-made) dbt table."""

import duckdb
import pytest

from feeaudit import verify

COLUMNS = (
    "event_type varchar, event_id varchar, provider varchar, month date, component varchar,"
    " contract_id varchar, contract_version integer, clause varchar, expected_minor bigint, currency varchar"
)

BASE_ROWS = [
    ("payment", "p1", "northgate", "2026-04-01", "markup", "NG-2025-01", 2, "4.2", 320, "EUR"),
    ("payment", "p1", "northgate", "2026-04-01", "fixed_fee", "NG-2025-01", 2, "4.3", 4, "EUR"),
    ("refund", "r1", "northgate", "2026-04-01", "markup_credit", "NG-2025-01", 2, "5.1", -90, "EUR"),
    ("provider_month", None, "northgate", "2026-03-01", "monthly_minimum", "NG-2025-01", 1, "7.4", 249_910, "EUR"),
    ("provider_month", None, "northgate", "2026-04-01", "monthly_minimum", "NG-2025-01", 2, "7.4", 0, "EUR"),
]


def _db(reference_rows, dbt_rows, con=None):
    con = con or duckdb.connect()
    con.execute("create schema reference")
    for table, rows in (("reference.expected_charges", reference_rows), ("main.int_expected_charges", dbt_rows)):
        con.execute(f"create table {table} ({COLUMNS})")
        if rows:
            con.executemany(f"insert into {table} values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return con


def test_identical_tables_have_no_differences():
    assert verify.compare(_db(BASE_ROWS, list(reversed(BASE_ROWS)))) == []


def test_amount_and_missing_rows():
    dbt_rows = list(BASE_ROWS)
    dbt_rows[0] = dbt_rows[0][:8] + (321,) + dbt_rows[0][9:]  # markup 320 → 321
    del dbt_rows[3]  # March minimum missing in dbt
    dbt_rows.append(("chargeback", "c9", "northgate", "2026-04-01", "chargeback_fee", "NG-2025-01", 2, "6.1", 1500, "EUR"))
    differences = verify.compare(_db(BASE_ROWS, dbt_rows))
    assert sorted(differences) == sorted(
        [
            verify.Difference("amount", "northgate", "markup", "payment", "p1", 320, 321),
            verify.Difference("missing_in_dbt", "northgate", "monthly_minimum", "provider_month", "2026-03-01", 249_910, None),
            verify.Difference("missing_in_reference", "northgate", "chargeback_fee", "chargeback", "c9", None, 1500),
        ]
    )


def test_provider_month_rows_are_keyed_by_month():
    # Same provider × component, different months: only the month distinguishes them.
    dbt_rows = [r for r in BASE_ROWS if r[1] is not None]
    dbt_rows.append(BASE_ROWS[3][:8] + (0,) + BASE_ROWS[3][9:])  # March minimum 249,910 → 0
    dbt_rows.append(BASE_ROWS[4])
    assert verify.compare(_db(BASE_ROWS, dbt_rows)) == [
        verify.Difference("amount", "northgate", "monthly_minimum", "provider_month", "2026-03-01", 249_910, 0)
    ]


def test_duplicate_keys_are_reported():
    differences = verify.compare(_db(BASE_ROWS, BASE_ROWS + [BASE_ROWS[1]]))
    assert [d.kind for d in differences] == ["duplicate_in_dbt"]
    assert differences[0].event_key == "p1" and differences[0].component == "fixed_fee"


def test_rejects_non_identifier_table_names():
    with pytest.raises(ValueError):
        verify.compare(_db(BASE_ROWS, BASE_ROWS), dbt_table="main.t; drop table x")


def test_main_exit_codes_and_report(tmp_path, capsys):
    same = tmp_path / "same.duckdb"
    with duckdb.connect(str(same)) as con:
        _db(BASE_ROWS, BASE_ROWS, con)
    assert verify.main(["--db", str(same)]) == 0

    different = tmp_path / "different.duckdb"
    many = [("payment", f"p{i:02d}", "brightpay", "2026-03-01", "transaction_fee", "BP-2025-07", 1, "3.1", i, "EUR") for i in range(12)]
    with duckdb.connect(str(different)) as con:
        _db(many, [r[:8] + (r[8] + 1,) + r[9:] for r in many], con)
    capsys.readouterr()
    assert verify.main(["--db", str(different)]) == 1
    out = capsys.readouterr().out
    assert "FAIL: 12 differences (amount: 12)" in out
    assert out.count("reference=") == 10  # only the first ten are printed
    assert "p00 transaction_fee: reference=0 dbt=1" in out
    assert "p10" not in out
