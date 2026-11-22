"""Pure calculation helpers (no Flask, no database) so they are easy to test and explain."""
import calendar
import datetime as dt

PER_YEAR = {"daily": 365, "weekly": 52, "monthly": 12, "quarterly": 4, "yearly": 1, "one-time": 1}
FREQUENCIES = tuple(PER_YEAR)
FREQ_ALIASES = {"annual": "yearly", "annually": "yearly", "onetime": "one-time", "one time": "one-time", "once": "one-time"}
PERSONAS = ("student", "salaried_employee", "freelancer", "business_owner", "homemaker")
PERSONA_ALIASES = {"salaried": "salaried_employee", "employee": "salaried_employee", "business": "business_owner"}


def norm_frequency(value):
    f = str(value or "monthly").strip().lower()
    f = FREQ_ALIASES.get(f, f)
    return f if f in PER_YEAR else None


def norm_persona(value):
    p = str(value or "").strip().lower().replace(" ", "_")
    return PERSONA_ALIASES.get(p, p) or None


def to_yearly(amount, frequency):
    return float(amount) * PER_YEAR[frequency]


def funds_totals(monthly, yearly, sources):
    """Total money available per year and per month.
    Rule used by the funds pages: a yearly amount equal to monthly x 12 is a duplicate and is ignored."""
    duplicate = yearly > 0 and monthly > 0 and abs(yearly - monthly * 12) < 1
    yearly_counted = 0.0 if duplicate else yearly
    extra = sum(to_yearly(s["amount"], s["frequency"]) for s in sources)
    total_year = monthly * 12 + yearly_counted + extra
    return {"yearly": round(total_year, 2), "monthly": round(total_year / 12, 2), "yearly_counted": not duplicate}


def add_months(iso_date, months):
    """Add whole months to a date string (YYYY-MM-DD); falls back to today if the date is missing."""
    try:
        d = dt.date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        d = dt.date.today()
    index = d.month - 1 + int(months)
    year, month = d.year + index // 12, index % 12 + 1
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1])).isoformat()


# ------------------------------------------------------------------ dashboard maths
EXPENSE_PER_YEAR = {"daily": 365, "weekly": 52, "monthly": 12, "quarterly": 4, "yearly": 1, "one-time": 1}


def expense_per_month(amount, period):
    """Convert an expense entered as daily / weekly / monthly / quarterly / yearly into its monthly cost."""
    if amount is None:
        return 0.0
    key = str(period or "monthly").strip().lower()
    key = {"annual": "yearly", "annually": "yearly", "one time": "one-time"}.get(key, key)
    return float(amount) * EXPENSE_PER_YEAR.get(key, 12) / 12


def months_between(start, end):
    """Whole months from start to end (never negative)."""
    return max(0, (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0))


def goal_monthly_need(target, saved, deadline_iso, today):
    """How much must be set aside each month to reach the target by the deadline."""
    if target is None:
        return 0.0
    left = max(0.0, float(target) - float(saved or 0))
    try:
        months_left = months_between(today, dt.date.fromisoformat(str(deadline_iso)[:10]))
    except ValueError:
        months_left = 1
    return left / max(1, months_left)


def month_label(today, offset):
    index = today.month - 1 + offset
    return f"{calendar.month_abbr[index % 12 + 1]} {today.year + index // 12}"


def build_summary(funds, expenses, goals, settings, period, today=None):
    """Everything the dashboard shows, from the user's saved data. Pure function: easy to test.
    funds    : dict from read_funds()      expenses : list of expense dicts      goals : list of goal dicts
    settings : budget_settings dict or None   period : 'monthly' | 'yearly'"""
    today = today or dt.date.today()
    k = 12 if period == "yearly" else 1

    total_m = float(funds.get("total_monthly_funds") or 0)
    total_y = float(funds.get("total_yearly_funds") or 0)
    funds_total = total_y if period == "yearly" else total_m
    extra_year = sum(to_yearly(s["amount"], norm_frequency(s["frequency"]) or "monthly") for s in funds.get("additional_income", []))
    additional = extra_year if period == "yearly" else extra_year / 12

    # Expenses: non-negotiable use the entered amount; negotiable ones use the amount planned in the budget planner
    nn_month, cats = 0.0, {}
    for e in expenses:
        if e.get("negotiable") is False:
            m = expense_per_month(e.get("amount"), e.get("period"))
            nn_month += m
            cats[e["category"]] = cats.get(e["category"], 0.0) + m
    neg_month = 0.0
    if settings:
        scale = 1 / 12 if settings.get("period") == "yearly" else 1      # planner stores values per its own period
        for key, item in (settings.get("items") or {}).items():
            if str(key).startswith("c:") and not item.get("nn") and item.get("estM") is not None:
                neg_month += float(item["estM"]) * scale
    if neg_month > 0:
        cats["Flexible spending (planned)"] = neg_month

    planned = (nn_month + neg_month) * k
    need_month = sum(goal_monthly_need(g.get("target"), g.get("saved"), g.get("deadline"), today) for g in goals)
    savings = need_month * k
    remaining = funds_total - planned - savings

    protected = None
    if settings and settings.get("protected_amount"):
        protected = float(settings["protected_amount"]) * (12 if (period == "yearly" and settings.get("period") != "yearly") else 1)
        if period == "monthly" and settings.get("period") == "yearly":
            protected = float(settings["protected_amount"]) / 12

    # 12-month outlook from today's plan: what is left each month after expenses (savings are counted as kept)
    surplus_month = total_m - nn_month - neg_month
    saved_so_far = sum(float(g.get("saved") or 0) for g in goals)
    timeline = [{"label": month_label(today, i + 1), "value": round(saved_so_far + surplus_month * (i + 1), 2)} for i in range(12)]
    has_data = total_m > 0
    return {
        "currency": "INR", "has_data": has_data,
        "funds_total": round(funds_total, 2), "additional_income": round(additional, 2),
        "planned_expenses": round(planned, 2), "non_negotiable": round(nn_month * k, 2), "negotiable": round(neg_month * k, 2),
        "expected_savings": round(savings, 2), "remaining": round(remaining, 2),
        "categories": [{"name": n, "amount": round(a * k, 2)} for n, a in sorted(cats.items(), key=lambda x: -x[1])],
        "buffer": {"target": round(protected, 2) if protected else None, "actual": None, "remaining": round(protected, 2) if protected else None},
        "predictions": {
            "actual": {
                "estimated_savings": round(surplus_month * 12, 2), "projected_balance": timeline[-1]["value"],
                "expected_expenses": round((nn_month + neg_month) * 12, 2), "surplus_deficit": round(surplus_month * 12, 2),
                "timeline": timeline,
            } if has_data else None,
            "whatif": None,
        },
    }


def build_insights(summary, goals):
    """Plain-language observations computed from the numbers (no AI involved)."""
    out = []
    if not summary["has_data"]:
        return [{"title": "Add your funds", "text": "Tell FinMate how much money you can use so it can build your plan.", "page": "profile"}]
    f, p = summary["funds_total"], summary["planned_expenses"]
    if summary["remaining"] < 0:
        out.append({"title": "Planned spending is above your funds",
                    "text": "Your planned expenses and savings add up to more than your available funds. Review flexible categories first.",
                    "amount": round(-summary["remaining"], 2), "page": "planner"})
    elif f > 0 and p / f < 0.5 and summary["remaining"] > 0:
        out.append({"title": "You have room in your budget",
                    "text": "Planned expenses use less than half of your funds. Consider raising a goal or building a buffer.",
                    "amount": summary["remaining"], "page": "goals"})
    top = summary["categories"][0] if summary["categories"] else None
    if top and p > 0:
        out.append({"title": f"{top['name']} is your biggest planned category",
                    "text": f"It makes up about {round(top['amount'] / p * 100)}% of your planned expenses.", "amount": top["amount"], "page": "planner"})
    if summary["non_negotiable"] > 0 and f > 0:
        share = summary["non_negotiable"] / f
        out.append({"title": "Essential expenses", "text": f"Essentials take about {round(share * 100)}% of your funds.",
                    "amount": summary["non_negotiable"], "page": "planner"})
    behind = [g for g in goals if g.get("target") and float(g.get("saved") or 0) < float(g["target"])]
    if behind:
        out.append({"title": f"{len(behind)} goal{'s' if len(behind) > 1 else ''} still in progress",
                    "text": "Saving a little every month keeps your goals on schedule.", "amount": summary["expected_savings"], "page": "goals"})
    if summary["buffer"]["target"] is None:
        out.append({"title": "No buffer set", "text": "A protected buffer is optional, but it keeps unexpected costs from derailing your plan.", "page": "planner"})
    return out[:5]
