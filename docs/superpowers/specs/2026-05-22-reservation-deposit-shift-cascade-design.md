# Reservation Deposit Shift Cascade Design

## Goal

When a reservation confirmation deposit is edited or deleted from Shift Report, the reservation confirmation must stay financially consistent. If the shift row is removed, the booking deposit should become zero. If the shift row amount or payment type changes, the booking deposit should update to match. If that deposit has already been applied into a folio during check-in, the existing folio cascade warning/confirmation flow must protect the update.

## Scope

- Handle Shift Report rows that were created from booking confirmation deposits.
- Identify those rows through `Booking.raw_data.deposit_shift_transaction_id`.
- Update `Booking.deposit_amount` and booking deposit metadata when the linked shift row is edited or deleted.
- Reuse the existing folio warning/cascade confirmation model for linked folio/payment updates.
- Avoid changing unrelated reservation, check-in, checkout, pricing, or inventory behavior.

## Current Flow

- `BookingService._post_booking_deposit_once()` posts a positive booking deposit into Shift Report.
- It stores `deposit_shift_posted`, `deposit_shift_transaction_id`, and `deposit_shift_transaction_code` in `Booking.raw_data`.
- During check-in, reservation deposits can be applied into folio/payment and booking raw metadata records `deposit_applied_to_folio`, `deposit_folio_id`, `deposit_folio_transaction_id`, and `deposit_payment_id`.
- Shift Report edit/delete currently cascades only when `ShiftReportTransaction.folio_transaction_id` exists, so pre-check-in booking deposits can remain on the reservation after their shift row is edited or deleted.

## Proposed Backend Behavior

### Detect linked booking deposit

Add a small backend helper in the Shift Report flow to find a booking whose `raw_data.deposit_shift_transaction_id` equals the shift row id. This helper should be used by edit-source, edit, and delete endpoints.

### Edit Shift Report row

When `edit-details/{item_id}` changes a linked booking deposit:

- If amount changes and cascade is confirmed, set `Booking.deposit_amount` to the new amount.
- If transaction/payment type changes and cascade is confirmed, update booking payment metadata to match the new Shift Report payment method.
- Keep `deposit_shift_posted = true` and update `deposit_shift_transaction_code` if needed.
- If the booking deposit has already been applied to folio/payment, continue using the existing folio cascade logic to update `FolioTransaction`, `Payment`, and rebalance the folio.
- If cascade is needed but not confirmed, return a warning/skip reason instead of silently changing only Shift Report.

### Delete Shift Report row

When deleting a linked booking deposit:

- If the booking deposit has not been applied to folio, set `Booking.deposit_amount = 0`.
- Remove shift-post metadata from `Booking.raw_data`: `deposit_shift_posted`, `deposit_shift_transaction_id`, and `deposit_shift_transaction_code`.
- Keep folio metadata untouched when no folio exists.
- If the booking deposit has already been applied to folio, require cascade confirmation before voiding/updating folio/payment; otherwise return a clear warning.
- Preserve the existing soft-delete/hard-delete behavior for the Shift Report row itself.

## API/UI Contract

- `edit-source/{item_id}` should include booking deposit impact data when present, so the existing warning UI can show that editing affects a reservation deposit and possibly a folio.
- Edit/delete requests should use the existing confirmation flag pattern for cascade operations.
- Existing clients that do not confirm cascade should receive a safe response explaining that booking/folio updates were skipped.

## Data Integrity Rules

- Booking, shift, folio transaction, payment, and folio rebalance changes must happen in the same database transaction where practical.
- A deleted linked shift deposit means the reservation confirmation no longer has deposit money.
- A modified linked shift deposit means the reservation confirmation amount/payment metadata matches Shift Report.
- Do not recreate a shift row automatically during edit/delete.

## Verification

- Verify editing a linked pre-check-in booking deposit updates `Booking.deposit_amount`.
- Verify deleting a linked pre-check-in booking deposit sets `Booking.deposit_amount` to zero and removes shift-post metadata.
- Verify linked folio deposits require cascade confirmation before folio/payment changes.
- Run relevant Python syntax/tests and `gitnexus_detect_changes()` before considering implementation complete.
