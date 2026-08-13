"""FCRA segregation rules.

Pure module: no frappe import. Ported from `validateFundSegregation` in
`src/lib/accounting.ts`, preserving all three rules and their reasoning.

In Frappe a Link field stores the target docname, so a fund's code *is* its
name and the separate id/code pair from the Prisma schema collapses into one
identifier. Callers pass plain mappings so this stays testable without an ORM.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

Line = Mapping[str, object]  # {"fund": str | None, "account": str | None}
FundRow = Mapping[str, object]  # {"name": str, "is_default": bool, "is_fcra": bool}
AccountRow = Mapping[str, object]  # {"name": str, "is_fcra": bool, "account_type": str}

#: Account types that actually hold money. An FCRA fund posting to one of these
#: that is not FCRA-designated commingles foreign contribution with the domestic
#: bank balance; an FCRA fund posting to an ordinary expense/income account is
#: not commingling by itself, so the reverse rule is limited to these types.
MONETARY_ACCOUNT_TYPES = frozenset({"Bank", "Cash"})


def _truthy(value: object) -> bool:
    """Frappe Check fields arrive as 0/1 ints, not bools."""
    return bool(value)


def resolve_line_fund(
    fund: object, funds_by_name: Mapping[str, FundRow], default_fund: FundRow | None
) -> FundRow | None:
    """Fund a line belongs to.

    An untagged line - or one naming a fund that has left the master - attributes
    to the company default fund, which mirrors how fund balances are built. The
    default fund is domestic by construction, so an untagged line can never be
    read as foreign contribution.
    """
    if isinstance(fund, str) and fund in funds_by_name:
        return funds_by_name[fund]
    return default_fund


def validate_fund_segregation(
    lines: Sequence[Line],
    funds: Iterable[FundRow],
    accounts: Iterable[AccountRow] = (),
) -> list[str]:
    """Return human-readable segregation errors for one voucher's lines.

    Rule 1 - mixing: every line in the voucher must resolve to funds with the
    same `is_fcra` value. Foreign and domestic money can never meet inside one
    journal entry. An untagged line follows the (domestic) default fund, so a
    half-tagged voucher touching an FCRA fund is reported as mixed rather than
    silently accepted.

    Rule 2 - unknown fund: a line naming a fund absent from the master is
    reported, because which side of the wall it belongs to cannot be proven.

    Rule 3 - account/fund pairing, only when `accounts` is supplied: a line
    posted to an FCRA-designated account must resolve to an FCRA fund. This is
    what stops a manual journal from debiting the FCRA bank account against a
    domestic credit - such a voucher tags no fund at all and would otherwise
    read as wholly domestic. Callers that prove the pairing themselves (the
    Donation doctype does) may omit `accounts` and take only rules 1 and 2.

    Rule 4 - the reverse of rule 3, monetary accounts only: a line resolving to
    an FCRA fund that posts to a Bank or Cash account must use an FCRA-designated
    one. Without this, a manual journal can debit an expense and credit a
    domestic bank account while tagging both legs to an FCRA fund - the voucher
    reads as wholly FCRA by fund, but the money lands in the domestic bank
    balance. Non-monetary accounts (expense, income, investment) are exempt: an
    FCRA fund legitimately spends through ordinary expense accounts, and
    requiring `is_fcra` on every one of those would be a different, unintended
    rule.
    """
    errors: list[str] = []
    funds_by_name = {str(fund["name"]): fund for fund in funds}
    accounts_by_name = {str(account["name"]): account for account in accounts}

    default_fund = next(
        (fund for fund in funds_by_name.values() if _truthy(fund.get("is_default"))),
        next(iter(funds_by_name.values()), None),
    )

    fcra_funds: set[str] = set()
    domestic_funds: set[str] = set()
    unknown_funds: set[str] = set()
    unpaired_fcra_accounts: set[str] = set()
    fcra_funds_in_domestic_accounts: set[str] = set()

    for line in lines:
        raw_fund = line.get("fund")

        if isinstance(raw_fund, str) and raw_fund and raw_fund not in funds_by_name:
            unknown_funds.add(raw_fund)
            continue

        fund = resolve_line_fund(raw_fund, funds_by_name, default_fund)
        raw_account = line.get("account")
        account = (
            accounts_by_name.get(raw_account) if isinstance(raw_account, str) else None
        )

        if account is not None and _truthy(account.get("is_fcra")):
            if fund is None or not _truthy(fund.get("is_fcra")):
                unpaired_fcra_accounts.add(str(account["name"]))

        if (
            account is not None
            and not _truthy(account.get("is_fcra"))
            and account.get("account_type") in MONETARY_ACCOUNT_TYPES
            and fund is not None
            and _truthy(fund.get("is_fcra"))
        ):
            fcra_funds_in_domestic_accounts.add(str(account["name"]))

        if fund is None:
            continue

        target = fcra_funds if _truthy(fund.get("is_fcra")) else domestic_funds
        target.add(str(fund["name"]))

    if unknown_funds:
        errors.append(
            "Journal line fund {} is not in the fund master, so FCRA segregation "
            "cannot be checked.".format(", ".join(sorted(unknown_funds)))
        )

    if fcra_funds and domestic_funds:
        errors.append(
            "FCRA and domestic money cannot mix in one journal entry: FCRA fund(s) "
            "{} and domestic fund(s) {}.".format(
                ", ".join(sorted(fcra_funds)), ", ".join(sorted(domestic_funds))
            )
        )

    if unpaired_fcra_accounts:
        codes = sorted(unpaired_fcra_accounts)
        plural = len(codes) > 1
        errors.append(
            "Account{} {} {} FCRA-designated; tag the line{} with an FCRA fund.".format(
                "s" if plural else "",
                ", ".join(codes),
                "are" if plural else "is",
                "s" if plural else "",
            )
        )

    if fcra_funds_in_domestic_accounts:
        codes = sorted(fcra_funds_in_domestic_accounts)
        plural = len(codes) > 1
        errors.append(
            "Account{} {} {} not FCRA-designated, so an FCRA fund cannot bank "
            "through {}. Foreign contribution must move through the "
            "FCRA-designated bank account only.".format(
                "s" if plural else "",
                ", ".join(codes),
                "are" if plural else "is",
                "it" if not plural else "them",
            )
        )

    return errors


def validate_corpus_outflow(
    from_fund: FundRow | None, to_fund: FundRow | None
) -> list[str]:
    """Corpus is one-way: money may enter a Corpus fund but never leave it.

    Section 11(1)(d) corpus is capital of the Trust, not spendable income, so a
    transfer out of it is refused. Transfers in are allowed.
    """
    errors: list[str] = []
    if from_fund is not None and str(from_fund.get("fund_class")) == "Corpus":
        errors.append(
            f"Fund {from_fund['name']} is Corpus class; corpus cannot be transferred out."
        )
    return errors
