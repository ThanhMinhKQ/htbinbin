# Reservation Deposit Shift Cascade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep reservation confirmation deposits synchronized when their linked Shift Report row is edited or deleted.

**Architecture:** Add focused booking-deposit cascade helpers inside `app/api/shift_report.py` because the existing edit/delete endpoints already own Shift Report mutation and folio cascade warnings. The helpers detect linked booking deposits via `Booking.raw_data.deposit_shift_transaction_id`, update booking deposit metadata, and integrate with existing `confirm_cascade` behavior for folio/payment changes. No schema or cross-module refactor is required.

**Tech Stack:** Python, FastAPI, SQLAlchemy, PostgreSQL JSONB, pytest, GitNexus.

---

## Pre-Implementation Notes

- GitNexus impact analysis has already been run for the route handlers planned for edits:
  - `edit_shift_transaction_details`: LOW risk, 0 direct callers.
  - `delete_shift_transaction`: LOW risk, 0 direct callers.
  - `get_shift_edit_source`: LOW risk, 0 direct callers.
- Before editing any additional symbol not named above, run `mcp__gitnexus__impact` upstream for that symbol.
- Existing user changes are present in `AGENTS.md` and `CLAUDE.md`; do not stage or modify them.
- Design spec: `docs/superpowers/specs/2026-05-22-reservation-deposit-shift-cascade-design.md`.

## File Structure

- Modify: `app/api/shift_report.py`
  - Add booking-deposit helper functions near existing Shift Report helpers.
  - Extend `get_shift_edit_source()` response with booking deposit impact data.
  - Extend `edit_shift_transaction_details()` to cascade linked booking deposit edits only when `confirm_cascade` is truthy.
  - Extend `delete_shift_transaction()` to clear linked booking deposits; require `confirm_cascade` for already-applied folio deposits.
- Create: `tests/test_shift_report_booking_deposit_cascade.py`
  - Unit-style tests for the new helper behavior using small fake model objects, avoiding a full database setup.
- Do not modify reservation/check-in/folio services unless a failing test proves a missing boundary.

---

### Task 1: Add Helper Tests for Booking Deposit Detection and Metadata Updates

**Files:**
- Create: `tests/test_shift_report_booking_deposit_cascade.py`
- Target helpers to add later: `app/api/shift_report.py`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_shift_report_booking_deposit_cascade.py` with:

```python
from decimal import Decimal
from types import SimpleNamespace

from app.api import shift_report


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.result


class FakeDB:
    def __init__(self, booking):
        self.booking = booking

    def query(self, model):
        return FakeQuery(self.booking)


def make_booking(raw=None, deposit=100000, payment_method="CASH"):
    return SimpleNamespace(
        id=7,
        external_id="RSV-7",
        guest_name="Nguyen Van A",
        deposit_amount=Decimal(str(deposit)),
        payment_method=payment_method,
        raw_data=raw or {
            "deposit_shift_posted": True,
            "deposit_shift_transaction_id": 55,
            "deposit_shift_transaction_code": "B1-00055",
            "deposit_applied_to_folio": False,
        },
    )


def test_find_booking_deposit_by_shift_transaction_id_matches_raw_metadata(monkeypatch):
    booking = make_booking()
    monkeypatch.setattr(shift_report, "Booking", object())

    found = shift_report._find_booking_deposit_for_shift_tx(FakeDB(booking), 55)

    assert found is booking


def test_clear_booking_deposit_after_shift_delete_zeroes_amount_and_unposts_shift_metadata():
    booking = make_booking()

    summary = shift_report._clear_booking_deposit_after_shift_delete(booking)

    assert booking.deposit_amount == Decimal("0")
    assert booking.raw_data["deposit_applied_to_folio"] is False
    assert "deposit_shift_posted" not in booking.raw_data
    assert "deposit_shift_transaction_id" not in booking.raw_data
    assert "deposit_shift_transaction_code" not in booking.raw_data
    assert summary == {"booking_deposit": True, "booking_id": 7, "new_deposit_amount": 0.0}


def test_apply_booking_deposit_shift_edit_updates_amount_and_payment_method():
    booking = make_booking(payment_method="CASH")

    summary = shift_report._apply_booking_deposit_shift_edit(
        booking,
        new_amount=250000,
        new_payment_method="BANK_TRANSFER",
        shift_transaction_code="B1-12345",
    )

    assert booking.deposit_amount == Decimal("250000")
    assert booking.payment_method == "BANK_TRANSFER"
    assert booking.raw_data["deposit_shift_posted"] is True
    assert booking.raw_data["deposit_shift_transaction_id"] == 55
    assert booking.raw_data["deposit_shift_transaction_code"] == "B1-12345"
    assert summary == {
        "booking_deposit": True,
        "booking_id": 7,
        "new_deposit_amount": 250000.0,
        "payment_method": "BANK_TRANSFER",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_shift_report_booking_deposit_cascade.py -q
```

Expected: FAIL with `AttributeError` for missing `_find_booking_deposit_for_shift_tx`, `_clear_booking_deposit_after_shift_delete`, or `_apply_booking_deposit_shift_edit`.

- [ ] **Step 3: Commit failing tests only**

Do not commit if tests unexpectedly pass.

```bash
git add tests/test_shift_report_booking_deposit_cascade.py
git commit -m "test: cover booking deposit shift cascade"
```

---

### Task 2: Implement Booking Deposit Helper Functions

**Files:**
- Modify: `app/api/shift_report.py:21-44` imports
- Modify: `app/api/shift_report.py:119-163` helper area
- Test: `tests/test_shift_report_booking_deposit_cascade.py`

- [ ] **Step 1: Add imports**

In `app/api/shift_report.py`, extend the existing model import line so `Booking` is imported. The line should include `Booking` alongside the existing models:

```python
from ..db.models import User, ShiftReportTransaction, Branch, Department, ShiftReportStatus, TransactionType, ShiftCloseLog, User, Folio, FolioTransaction, Payment, ShiftPaymentMethod, Booking
```

- [ ] **Step 2: Add helper functions near `_shift_enum_value()`**

Insert this block after `_shift_enum_value()`:

```python
def _find_booking_deposit_for_shift_tx(db: Session, shift_tx_id: int):
    return db.query(Booking).filter(
        Booking.raw_data["deposit_shift_transaction_id"].astext == str(shift_tx_id)
    ).first()


def _booking_deposit_applied_to_folio(booking: Any) -> bool:
    raw = dict(getattr(booking, "raw_data", None) or {})
    return bool(raw.get("deposit_applied_to_folio"))


def _clear_booking_deposit_after_shift_delete(booking: Any) -> dict[str, Any]:
    raw = dict(getattr(booking, "raw_data", None) or {})
    for key in (
        "deposit_shift_posted",
        "deposit_shift_transaction_id",
        "deposit_shift_transaction_code",
    ):
        raw.pop(key, None)
    booking.deposit_amount = Decimal("0")
    booking.raw_data = raw
    return {
        "booking_deposit": True,
        "booking_id": int(booking.id),
        "new_deposit_amount": 0.0,
    }


def _apply_booking_deposit_shift_edit(
    booking: Any,
    *,
    new_amount: int,
    new_payment_method: str,
    shift_transaction_code: Optional[str],
) -> dict[str, Any]:
    raw = dict(getattr(booking, "raw_data", None) or {})
    booking.deposit_amount = Decimal(str(new_amount))
    booking.payment_method = new_payment_method
    raw["deposit_shift_posted"] = True
    if shift_transaction_code:
        raw["deposit_shift_transaction_code"] = shift_transaction_code
    booking.raw_data = raw
    return {
        "booking_deposit": True,
        "booking_id": int(booking.id),
        "new_deposit_amount": float(new_amount),
        "payment_method": new_payment_method,
    }
```

- [ ] **Step 3: Run helper tests**

Run:

```bash
pytest tests/test_shift_report_booking_deposit_cascade.py -q
```

Expected: PASS.

- [ ] **Step 4: Run Python syntax check**

Run:

```bash
python -m py_compile app/api/shift_report.py tests/test_shift_report_booking_deposit_cascade.py
```

Expected: no output and exit code 0.

- [ ] **Step 5: Commit helper implementation**

```bash
git add app/api/shift_report.py tests/test_shift_report_booking_deposit_cascade.py
git commit -m "fix: add booking deposit shift cascade helpers"
```

---

### Task 3: Extend Edit Source Response With Booking Deposit Impact

**Files:**
- Modify: `app/api/shift_report.py:917-1010`
- Test: `tests/test_shift_report_booking_deposit_cascade.py`

- [ ] **Step 1: Add failing serializer test**

Append to `tests/test_shift_report_booking_deposit_cascade.py`:

```python
def test_booking_deposit_impact_payload_describes_linked_booking():
    booking = make_booking(
        raw={
            "deposit_shift_posted": True,
            "deposit_shift_transaction_id": 55,
            "deposit_shift_transaction_code": "B1-00055",
            "deposit_applied_to_folio": True,
            "deposit_folio_id": 9,
            "deposit_folio_transaction_id": 10,
            "deposit_payment_id": 11,
        },
        deposit=300000,
        payment_method="CARD",
    )

    payload = shift_report._booking_deposit_impact_payload(booking)

    assert payload == {
        "id": 7,
        "external_id": "RSV-7",
        "guest_name": "Nguyen Van A",
        "deposit_amount": 300000.0,
        "payment_method": "CARD",
        "deposit_applied_to_folio": True,
        "deposit_folio_id": 9,
        "deposit_folio_transaction_id": 10,
        "deposit_payment_id": 11,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_shift_report_booking_deposit_cascade.py::test_booking_deposit_impact_payload_describes_linked_booking -q
```

Expected: FAIL with missing `_booking_deposit_impact_payload`.

- [ ] **Step 3: Add impact payload helper**

Insert after `_apply_booking_deposit_shift_edit()`:

```python
def _booking_deposit_impact_payload(booking: Any) -> dict[str, Any]:
    raw = dict(getattr(booking, "raw_data", None) or {})
    return {
        "id": int(booking.id),
        "external_id": booking.external_id,
        "guest_name": booking.guest_name,
        "deposit_amount": float(booking.deposit_amount or 0),
        "payment_method": booking.payment_method,
        "deposit_applied_to_folio": bool(raw.get("deposit_applied_to_folio")),
        "deposit_folio_id": raw.get("deposit_folio_id"),
        "deposit_folio_transaction_id": raw.get("deposit_folio_transaction_id"),
        "deposit_payment_id": raw.get("deposit_payment_id"),
    }
```

- [ ] **Step 4: Update `get_shift_edit_source()`**

Inside `get_shift_edit_source()`, after `payment_method_raw` is computed, add:

```python
    booking_deposit = _find_booking_deposit_for_shift_tx(db, item.id)
```

After the existing payment impact block:

```python
    if booking_deposit is not None:
        impacts.append("booking_deposit")
```

In the returned dictionary, add this key before `impacts`:

```python
        "booking_deposit": _booking_deposit_impact_payload(booking_deposit) if booking_deposit is not None else None,
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_shift_report_booking_deposit_cascade.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit edit-source extension**

```bash
git add app/api/shift_report.py tests/test_shift_report_booking_deposit_cascade.py
git commit -m "fix: expose booking deposit shift impact"
```

---

### Task 4: Cascade Shift Edit Back to Booking Deposit

**Files:**
- Modify: `app/api/shift_report.py:1013-1148`
- Test: `tests/test_shift_report_booking_deposit_cascade.py`

- [ ] **Step 1: Add decision helper tests**

Append to `tests/test_shift_report_booking_deposit_cascade.py`:

```python
def test_booking_deposit_edit_requires_confirmation_when_amount_changes():
    booking = make_booking(deposit=100000)

    assert shift_report._booking_deposit_edit_needs_cascade(
        booking,
        amount_changed=True,
        type_changed=False,
    ) is True


def test_booking_deposit_edit_does_not_require_confirmation_without_relevant_change():
    booking = make_booking(deposit=100000)

    assert shift_report._booking_deposit_edit_needs_cascade(
        booking,
        amount_changed=False,
        type_changed=False,
    ) is False
```

- [ ] **Step 2: Run new tests to verify failure**

Run:

```bash
pytest tests/test_shift_report_booking_deposit_cascade.py::test_booking_deposit_edit_requires_confirmation_when_amount_changes tests/test_shift_report_booking_deposit_cascade.py::test_booking_deposit_edit_does_not_require_confirmation_without_relevant_change -q
```

Expected: FAIL with missing `_booking_deposit_edit_needs_cascade`.

- [ ] **Step 3: Add decision helper**

Insert after `_booking_deposit_impact_payload()`:

```python
def _booking_deposit_edit_needs_cascade(
    booking: Any,
    *,
    amount_changed: bool,
    type_changed: bool,
) -> bool:
    return bool(booking is not None and (amount_changed or type_changed))
```

- [ ] **Step 4: Update `edit_shift_transaction_details()` cascade summary**

Replace the `cascade_summary` dict with:

```python
    cascade_summary = {
        "folio_transaction": False,
        "payment": False,
        "folio_rebalanced": False,
        "booking_deposit": False,
        "booking_deposit_amount": None,
        "skipped_reason": None,
    }
```

- [ ] **Step 5: Find linked booking before cascade decisions**

After `folio_tx_id = _model_value(item.folio_transaction_id)`, add:

```python
    booking_deposit = _find_booking_deposit_for_shift_tx(db, item.id)
    booking_deposit_needs_cascade = _booking_deposit_edit_needs_cascade(
        booking_deposit,
        amount_changed=amount_changed,
        type_changed=type_changed,
    )
```

Replace:

```python
    needs_cascade = folio_tx_id and (amount_changed or type_changed)
```

with:

```python
    needs_cascade = bool(folio_tx_id and (amount_changed or type_changed)) or booking_deposit_needs_cascade
```

- [ ] **Step 6: Apply booking deposit cascade after folio cascade**

Before `db.commit()`, add:

```python
    if booking_deposit_needs_cascade and cascade_requested and cascade_summary["skipped_reason"] is None:
        booking_summary = _apply_booking_deposit_shift_edit(
            booking_deposit,
            new_amount=new_amount,
            new_payment_method=new_shift_method.value if hasattr(new_shift_method, "value") else str(new_shift_method),
            shift_transaction_code=item.transaction_code,
        )
        cascade_summary["booking_deposit"] = booking_summary["booking_deposit"]
        cascade_summary["booking_deposit_amount"] = booking_summary["new_deposit_amount"]
```

Keep the existing behavior where Shift Report itself is updated even if cascade is not confirmed. The response must include `cascade_summary.skipped_reason = "Chưa xác nhận cascade — chỉ cập nhật giao ca."` when booking deposit cascade is needed but not confirmed.

- [ ] **Step 7: Run tests and syntax check**

Run:

```bash
pytest tests/test_shift_report_booking_deposit_cascade.py -q
python -m py_compile app/api/shift_report.py tests/test_shift_report_booking_deposit_cascade.py
```

Expected: tests PASS; syntax check exits 0.

- [ ] **Step 8: Commit edit cascade**

```bash
git add app/api/shift_report.py tests/test_shift_report_booking_deposit_cascade.py
git commit -m "fix: sync booking deposit on shift edit"
```

---

### Task 5: Require Cascade Confirmation and Clear Booking Deposit on Shift Delete

**Files:**
- Modify: `app/api/shift_report.py:1194-1285`
- Test: `tests/test_shift_report_booking_deposit_cascade.py`

- [ ] **Step 1: Add delete confirmation form parameter**

Change the `delete_shift_transaction()` signature from:

```python
async def delete_shift_transaction( # SỬA
    item_id: int, 
    request: Request, 
    db: Session = Depends(get_db),
    hard_delete: bool = Form(False) 
):
```

to:

```python
async def delete_shift_transaction( # SỬA
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    hard_delete: bool = Form(False),
    confirm_cascade: Optional[str] = Form("false"),
):
```

- [ ] **Step 2: Add delete decision helper tests**

Append to `tests/test_shift_report_booking_deposit_cascade.py`:

```python
def test_booking_deposit_delete_requires_confirmation_after_folio_application():
    booking = make_booking(raw={
        "deposit_shift_posted": True,
        "deposit_shift_transaction_id": 55,
        "deposit_shift_transaction_code": "B1-00055",
        "deposit_applied_to_folio": True,
    })

    assert shift_report._booking_deposit_delete_requires_confirmation(booking) is True


def test_booking_deposit_delete_does_not_require_confirmation_before_folio_application():
    booking = make_booking(raw={
        "deposit_shift_posted": True,
        "deposit_shift_transaction_id": 55,
        "deposit_shift_transaction_code": "B1-00055",
        "deposit_applied_to_folio": False,
    })

    assert shift_report._booking_deposit_delete_requires_confirmation(booking) is False
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
pytest tests/test_shift_report_booking_deposit_cascade.py::test_booking_deposit_delete_requires_confirmation_after_folio_application tests/test_shift_report_booking_deposit_cascade.py::test_booking_deposit_delete_does_not_require_confirmation_before_folio_application -q
```

Expected: FAIL with missing `_booking_deposit_delete_requires_confirmation`.

- [ ] **Step 4: Add delete decision helper**

Insert after `_booking_deposit_edit_needs_cascade()`:

```python
def _booking_deposit_delete_requires_confirmation(booking: Any) -> bool:
    return bool(booking is not None and _booking_deposit_applied_to_folio(booking))
```

- [ ] **Step 5: Gate delete cascade in `delete_shift_transaction()`**

After `now = datetime.now(VN_TZ)`, add:

```python
    cascade_requested = str(confirm_cascade).lower() in ("true", "1", "yes", "on")
    booking_deposit = _find_booking_deposit_for_shift_tx(db, item.id)
    if _booking_deposit_delete_requires_confirmation(booking_deposit) and not cascade_requested:
        return DecimalSafeJSONResponse({
            "status": "needs_confirmation",
            "message": "Giao dịch này là cọc đặt phòng đã áp vào folio. Vui lòng xác nhận cascade trước khi xoá.",
            "booking_deposit": _booking_deposit_impact_payload(booking_deposit),
            "impacts": ["booking_deposit", "folio_transaction", "payment", "folio_balance"],
        }, status_code=409)
```

- [ ] **Step 6: Clear booking deposit before final commit**

After the existing folio void block and before the hard-delete branch, add:

```python
    booking_deposit_summary = None
    if booking_deposit is not None:
        booking_deposit_summary = _clear_booking_deposit_after_shift_delete(booking_deposit)
```

In both delete responses, add:

```python
            "booking_deposit_cleared": bool(booking_deposit_summary),
            "booking_deposit_summary": booking_deposit_summary,
```

For the hard-delete response, place those keys after `cascade_folio_voided`. For the soft-delete response, place those keys after `cascade_folio_voided`.

- [ ] **Step 7: Run tests and syntax check**

Run:

```bash
pytest tests/test_shift_report_booking_deposit_cascade.py -q
python -m py_compile app/api/shift_report.py tests/test_shift_report_booking_deposit_cascade.py
```

Expected: tests PASS; syntax check exits 0.

- [ ] **Step 8: Commit delete cascade**

```bash
git add app/api/shift_report.py tests/test_shift_report_booking_deposit_cascade.py
git commit -m "fix: clear booking deposit on shift delete"
```

---

### Task 6: Verify Integration Scope and GitNexus Change Impact

**Files:**
- No new source edits expected unless verification finds a defect.

- [ ] **Step 1: Run targeted test suite**

Run:

```bash
pytest tests/test_shift_report_booking_deposit_cascade.py tests/test_booking_service_group_deposit.py tests/test_reservation_confirmation_print.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Python syntax check for touched runtime files**

Run:

```bash
python -m py_compile app/api/shift_report.py app/api/pms/reservation_api.py app/api/pms/folio_api.py
```

Expected: no output and exit code 0.

- [ ] **Step 3: Inspect git status and diff**

Run:

```bash
git status --short
git diff -- app/api/shift_report.py tests/test_shift_report_booking_deposit_cascade.py docs/superpowers/specs/2026-05-22-reservation-deposit-shift-cascade-design.md docs/superpowers/plans/2026-05-22-reservation-deposit-shift-cascade.md
```

Expected: only intentional changes in `app/api/shift_report.py`, test file, and plan/spec docs. Existing unrelated `AGENTS.md` and `CLAUDE.md` may remain modified but must not be staged unless the user explicitly requests it.

- [ ] **Step 4: Run GitNexus detect changes**

Run the MCP tool:

```text
mcp__gitnexus__detect_changes({repo: "binbinops", scope: "all"})
```

Expected: affected symbols are limited to `shift_report.py` helper/edit/delete source flows and the new test file. If GitNexus reports unrelated PMS reservation/folio changes, inspect diff before proceeding.

- [ ] **Step 5: Commit verification/doc plan if implementation is complete**

If all checks pass and the plan file itself is not committed yet:

```bash
git add docs/superpowers/plans/2026-05-22-reservation-deposit-shift-cascade.md
git commit -m "docs: plan reservation deposit shift cascade"
```

If implementation commits already include all code/tests, do not create extra code commits.

---

## Self-Review

- Spec coverage: the plan covers detection via booking raw metadata, edit-source impact payload, edit cascade, delete cascade, folio confirmation gating, tests, and GitNexus verification.
- Placeholder scan: no TBD/TODO/fill-later placeholders remain.
- Type consistency: helper names and response keys are consistent across tasks.
