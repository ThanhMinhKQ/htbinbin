# Inventory Shared Modal Table Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve shared inventory ticket detail tables so product names get the most space, compact numeric columns scan cleanly, and long item lists scroll inside the table area instead of dragging the full modal.

**Architecture:** Keep the existing Jinja + Tailwind table structure and only adjust shared modal templates. Preserve Alpine status-driven columns and the existing capture pipeline, which already expands scroll areas when taking screenshots.

**Tech Stack:** Jinja templates, TailwindCSS utility classes, Alpine.js expressions, FastAPI-served templates.

---

## File Structure

- Modify `app/templates/inventory/shared/requests/modal_request_detail.html`: request-side detail modal table layout, column widths, alignment, and item-list scroll area.
- Modify `app/templates/inventory/shared/approvals/modal_approval_detail.html`: manager approval detail modal table layout, column widths, alignment, and item-list scroll area.
- Modify `tests/test_inventory_capture_modal.js`: add static regression coverage that verifies the shared modal tables keep product-name-first column sizing and scroll containers compatible with capture.

---

### Task 1: Add Static Layout Regression Coverage

**Files:**
- Modify: `tests/test_inventory_capture_modal.js`

- [ ] **Step 1: Add assertions for shared modal table layout**

Append this block after the existing shared/reception utility assertions:

```js
const requestDetailSource = fs.readFileSync('app/templates/inventory/shared/requests/modal_request_detail.html', 'utf8');
const approvalDetailSource = fs.readFileSync('app/templates/inventory/shared/approvals/modal_approval_detail.html', 'utf8');

for (const [name, source] of [
  ['request detail modal', requestDetailSource],
  ['approval detail modal', approvalDetailSource],
]) {
  assert(
    source.includes('max-h-[42vh] overflow-y-auto') && source.includes('min-w-[760px]'),
    `${name} must keep long item lists scrollable inside the table area while preserving desktop column widths`,
  );

  assert(
    source.includes('<col class="w-[30px]">') && source.includes('<col class="w-auto">'),
    `${name} must make the row number column compact and reserve remaining width for product names`,
  );

  assert(
    source.includes('>Thực xuất</th>') && source.includes('x-text="item.approved_quantity !== null ? item.approved_quantity : \'--\'"'),
    `${name} must keep the Thực xuất column present and data-bound`,
  );

  assert(
    !source.includes('Thực xuất</th>') || !source.includes('Thực xuất</th>\n                                    <td'),
    `${name} must not accidentally remove existing table structure around Thực xuất`,
  );
}
```

- [ ] **Step 2: Run the regression test and verify it fails**

Run:

```bash
node tests/test_inventory_capture_modal.js
```

Expected: FAIL because the two shared modal templates do not yet include `max-h-[42vh] overflow-y-auto`, `min-w-[760px]`, compact `w-[30px]`, and `w-auto` product-name column markers.

---

### Task 2: Update Request Detail Modal Table Layout

**Files:**
- Modify: `app/templates/inventory/shared/requests/modal_request_detail.html:65-132`

- [ ] **Step 1: Replace the table section wrapper and table header layout**

Change the section starting at the existing `Danh sách vật tư` block to use a scrollable table body wrapper:

```html
<section class="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
    <div class="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <h3 class="text-xs font-black uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">Danh sách vật tư</h3>
        <span class="text-xs font-semibold text-slate-500" x-text="(viewingRequestTicket?.items || []).length + ' dòng'"></span>
    </div>
    <div class="max-h-[42vh] overflow-y-auto">
        <table class="min-w-[760px] w-full table-fixed border-collapse text-left text-sm">
            <colgroup>
                <col class="w-[30px]">
                <col class="w-auto">
                <col class="w-[56px]">
                <col x-show="!getRequestStatusInfo().isShipping" class="w-[76px]">
                <col x-show="getRequestStatusInfo().isShipping || getRequestStatusInfo().isCompleted" class="w-[76px]">
                <col x-show="getRequestStatusInfo().isCompleted" class="w-[76px]">
                <col x-show="getRequestStatusInfo().isCompleted" class="w-[124px]">
            </colgroup>
            <thead class="sticky top-0 z-10">
                <tr class="bg-slate-100 text-[11px] font-bold uppercase tracking-wide text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                    <th class="border-b border-r border-slate-200 px-1 py-2 text-center text-slate-400 dark:border-slate-800 dark:text-slate-500">#</th>
                    <th class="border-b border-r border-slate-200 px-4 py-2 text-left text-slate-700 dark:border-slate-800 dark:text-slate-200">Tên hàng hóa / Vật tư</th>
                    <th class="border-b border-r border-slate-200 px-2 py-2 text-center text-slate-500 dark:border-slate-800 dark:text-slate-400">ĐVT</th>
                    <th x-show="!getRequestStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-2 text-center text-slate-500 dark:border-slate-800 dark:text-slate-400">Yêu cầu</th>
                    <th x-show="getRequestStatusInfo().isShipping || getRequestStatusInfo().isCompleted" class="border-b border-r border-slate-200 px-2 py-2 text-center text-slate-500 dark:border-slate-800 dark:text-slate-400">Thực xuất</th>
                    <th x-show="getRequestStatusInfo().isCompleted" class="border-b border-r border-slate-200 px-2 py-2 text-center text-slate-500 dark:border-slate-800 dark:text-slate-400">Thực nhận</th>
                    <th x-show="getRequestStatusInfo().isCompleted" class="border-b border-slate-200 px-2 py-2 text-left text-slate-500 dark:border-slate-800 dark:text-slate-400">Tình trạng</th>
                </tr>
            </thead>
```

- [ ] **Step 2: Update request quantity cell alignment**

Replace these three quantity cell classes inside the request detail table body:

```html
<td x-show="!getRequestStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-3 text-center font-mono text-sm font-black tabular-nums text-slate-900 dark:border-slate-800 dark:text-white" x-text="item.request_quantity"></td>
<td x-show="getRequestStatusInfo().isShipping || getRequestStatusInfo().isCompleted" class="border-b border-r border-slate-200 px-2 py-3 text-center font-mono text-sm font-black tabular-nums text-slate-900 dark:border-slate-800 dark:text-white" x-text="item.approved_quantity !== null ? item.approved_quantity : '--'"></td>
<td x-show="getRequestStatusInfo().isCompleted" class="border-b border-r border-slate-200 px-2 py-3 text-center font-mono text-sm font-black tabular-nums dark:border-slate-800" :class="(item.received_quantity < item.approved_quantity) ? 'text-red-600 dark:text-red-400' : 'text-slate-900 dark:text-white'" x-text="item.received_quantity !== undefined ? item.received_quantity : 'Chưa nhận'"></td>
```

- [ ] **Step 3: Close the new scroll wrapper after the table**

After the existing `</table>` for the item list, add the matching wrapper close:

```html
        </table>
    </div>
</section>
```

- [ ] **Step 4: Run regression test and expect partial failure**

Run:

```bash
node tests/test_inventory_capture_modal.js
```

Expected: FAIL because the approval detail modal has not been updated yet.

---

### Task 3: Update Approval Detail Modal Table Layout

**Files:**
- Modify: `app/templates/inventory/shared/approvals/modal_approval_detail.html:67-134`

- [ ] **Step 1: Replace the approval table section wrapper and table header layout**

Use the same structure as request detail, with approval-specific Alpine expressions:

```html
<section class="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
    <div class="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <h3 class="text-xs font-black uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">Danh sách vật tư</h3>
        <span class="text-xs font-semibold text-slate-500" x-text="(viewingApprovalTicket?.items || []).length + ' dòng'"></span>
    </div>
    <div class="max-h-[42vh] overflow-y-auto">
        <table class="min-w-[760px] w-full table-fixed border-collapse text-left text-sm">
            <colgroup>
                <col class="w-[30px]">
                <col class="w-auto">
                <col class="w-[56px]">
                <col x-show="!getStatusInfo().isShipping" class="w-[76px]">
                <col x-show="!getStatusInfo().isPending" class="w-[76px]">
                <col x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="w-[76px]">
                <col x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="w-[124px]">
            </colgroup>
            <thead class="sticky top-0 z-10">
                <tr class="bg-slate-100 text-[11px] font-bold uppercase tracking-wide text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                    <th class="border-b border-r border-slate-200 px-1 py-2 text-center text-slate-400 dark:border-slate-800 dark:text-slate-500">#</th>
                    <th class="border-b border-r border-slate-200 px-4 py-2 text-left text-slate-700 dark:border-slate-800 dark:text-slate-200">Tên hàng hóa / Vật tư</th>
                    <th class="border-b border-r border-slate-200 px-2 py-2 text-center text-slate-500 dark:border-slate-800 dark:text-slate-400">ĐVT</th>
                    <th x-show="!getStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-2 text-center text-slate-500 dark:border-slate-800 dark:text-slate-400">Yêu cầu</th>
                    <th x-show="!getStatusInfo().isPending" class="border-b border-r border-slate-200 px-2 py-2 text-center text-slate-500 dark:border-slate-800 dark:text-slate-400">Thực xuất</th>
                    <th x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-2 text-center text-slate-500 dark:border-slate-800 dark:text-slate-400">Thực nhận</th>
                    <th x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="border-b border-slate-200 px-2 py-2 text-left text-slate-500 dark:border-slate-800 dark:text-slate-400">Tình trạng</th>
                </tr>
            </thead>
```

- [ ] **Step 2: Update approval quantity cell alignment**

Replace these three quantity cells inside the approval detail table body:

```html
<td x-show="!getStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-3 text-center font-mono text-sm font-bold tabular-nums text-slate-900 dark:border-slate-800 dark:text-white" x-text="item.request_quantity"></td>
<td x-show="!getStatusInfo().isPending" class="border-b border-r border-slate-200 px-2 py-3 text-center font-mono text-sm font-bold tabular-nums text-slate-900 dark:border-slate-800 dark:text-white" x-text="item.approved_quantity !== null ? item.approved_quantity : '--'"></td>
<td x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-3 text-center font-mono text-sm font-bold tabular-nums dark:border-slate-800" :class="(item.received_quantity < item.approved_quantity) ? 'text-red-600 dark:text-red-400' : 'text-slate-900 dark:text-white'" x-text="item.received_quantity !== undefined ? item.received_quantity : 'Chưa nhận'"></td>
```

- [ ] **Step 3: Close the approval scroll wrapper after the table**

After the existing `</table>` for the item list, add:

```html
        </table>
    </div>
</section>
```

- [ ] **Step 4: Run regression test and verify it passes**

Run:

```bash
node tests/test_inventory_capture_modal.js
```

Expected: PASS with no output.

---

### Task 4: Browser Verification

**Files:**
- No code changes in this task.

- [ ] **Step 1: Start the app**

Run:

```bash
uvicorn app.main:app --reload
```

Expected: server starts on `http://127.0.0.1:8000`.

- [ ] **Step 2: Open and verify completed approval detail modal**

In browser:

1. Log in with an authorized test user.
2. Open `http://127.0.0.1:8000/inventory/manager`.
3. Open `Duyệt yêu cầu`.
4. Open `Lịch sử`.
5. Open a completed ticket detail.

Expected visual results:

- Product name column is visibly the widest column.
- `#` column is compact.
- `Yêu cầu`, `Thực xuất`, and `Thực nhận` values are centered.
- Long item lists scroll inside the table area.
- Modal header and footer stay stable.
- Capture button remains present and usable.

- [ ] **Step 3: Verify request detail modal when available**

In browser, open a request detail modal from the `Yêu cầu` tab if records are available.

Expected visual results match Step 2 for the request-side detail table.

- [ ] **Step 4: Run GitNexus change detection**

Run GitNexus detect changes with scope `all` for repo `binbinops`.

Expected: changed scope includes only the intended shared modal templates and the static regression test, plus any unrelated pre-existing workspace changes already present before this task.

---

## Self-Review

- Spec coverage: The plan covers compact `#`, expanded product-name column, centered `Thực xuất`, internal long-list scrolling, request and approval shared templates, and browser verification.
- Placeholder scan: No TBD/TODO placeholders remain.
- Type consistency: File paths and Alpine expressions match the current shared modal templates.
