# Inventory Modal Table Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve inventory detail modal item tables so the item-name column has more usable space, numeric/status columns are easier to scan, and status cells use colored SVG badges.

**Architecture:** This is a surgical Jinja/Tailwind markup update in shared inventory modal partials. No API, Alpine state, or business logic changes are required; the existing `x-show` conditions and quantity comparisons remain the source of truth.

**Tech Stack:** FastAPI/Jinja templates, TailwindCSS utility classes, Alpine.js directives already present in the templates, pytest/Node-based syntax checks already used by the project.

---

## File Structure

- Modify: `app/templates/inventory/shared/requests/modal_request_detail.html:70-117`
  - Request-detail modal item table used by request viewing flows.
  - Responsible for displaying item index, product/category, unit, requested/exported/received quantities, and completion status.
- Modify: `app/templates/inventory/shared/approvals/modal_approval_detail.html:72-119`
  - Approval-detail modal item table used by approval viewing flows.
  - Responsible for the same visual table structure with approval-specific status visibility rules.
- No new files.
- No backend changes.
- No documentation update required because behavior and business rules do not change.

## Current Markup Notes

Both target tables already use `table-fixed` and `colgroup` widths. The current `#` columns are `w-[46px]` and `w-[44px]`, the product column is flexible but loses space to wider numeric/status columns, and the status cell is text-only:

```html
<span class="text-red-600 dark:text-red-400">Thiếu <span x-text="Math.round(item.approved_quantity - item.received_quantity)"></span></span>
<span class="text-slate-700 dark:text-slate-200">Đủ hàng</span>
<span class="text-slate-400">Chưa nhận</span>
```

The implementation should preserve all existing Alpine conditions:

```html
getRequestStatusInfo().isShipping
getRequestStatusInfo().isCompleted
getStatusInfo().isPending
getStatusInfo().isShipping
item.received_quantity !== undefined
item.approved_quantity !== null
item.received_quantity < item.approved_quantity
item.received_quantity >= item.approved_quantity
```

---

### Task 1: Update Request Detail Modal Table Layout

**Files:**
- Modify: `app/templates/inventory/shared/requests/modal_request_detail.html:70-117`

- [ ] **Step 1: Inspect current request table block**

Read `app/templates/inventory/shared/requests/modal_request_detail.html:70-117` and confirm the block still starts with:

```html
<table class="w-full table-fixed border-collapse text-left text-sm">
```

and contains this request-only loop:

```html
<template x-for="(item, idx) in (viewingRequestTicket?.items || [])" :key="item.id">
```

Expected: both strings are present before editing.

- [ ] **Step 2: Replace the request table block**

Replace the full table block from `<table class="w-full table-fixed border-collapse text-left text-sm">` through its matching `</table>` with this markup:

```html
<table class="w-full table-fixed border-collapse text-left text-sm">
    <colgroup>
        <col class="w-[34px]">
        <col class="min-w-[240px]">
        <col class="w-[62px]">
        <col x-show="!getRequestStatusInfo().isShipping" class="w-[88px]">
        <col x-show="getRequestStatusInfo().isShipping || getRequestStatusInfo().isCompleted" class="w-[88px]">
        <col x-show="getRequestStatusInfo().isCompleted" class="w-[88px]">
        <col x-show="getRequestStatusInfo().isCompleted" class="w-[126px]">
    </colgroup>
    <thead>
        <tr class="bg-slate-100 text-[11px] font-bold uppercase tracking-wide text-slate-600 dark:bg-slate-900 dark:text-slate-300">
            <th class="border-b border-r border-slate-200 px-1.5 py-2 text-center text-slate-400 dark:border-slate-800 dark:text-slate-500">#</th>
            <th class="border-b border-r border-slate-200 px-4 py-2 text-left text-slate-700 dark:border-slate-800 dark:text-slate-200">Tên hàng hóa / Vật tư</th>
            <th class="border-b border-r border-slate-200 px-2 py-2 text-center text-slate-500 dark:border-slate-800 dark:text-slate-400">ĐVT</th>
            <th x-show="!getRequestStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-2 text-right text-slate-500 dark:border-slate-800 dark:text-slate-400">Yêu cầu</th>
            <th x-show="getRequestStatusInfo().isShipping || getRequestStatusInfo().isCompleted" class="border-b border-r border-slate-200 px-2 py-2 text-right text-slate-500 dark:border-slate-800 dark:text-slate-400">Thực xuất</th>
            <th x-show="getRequestStatusInfo().isCompleted" class="border-b border-r border-slate-200 px-2 py-2 text-right text-slate-500 dark:border-slate-800 dark:text-slate-400">Thực nhận</th>
            <th x-show="getRequestStatusInfo().isCompleted" class="border-b border-slate-200 px-2 py-2 text-left text-slate-500 dark:border-slate-800 dark:text-slate-400">Tình trạng</th>
        </tr>
    </thead>
    <tbody>
        <template x-for="(item, idx) in (viewingRequestTicket?.items || [])" :key="item.id">
            <tr class="bg-white hover:bg-slate-50 dark:bg-slate-950 dark:hover:bg-slate-900/70">
                <td class="border-b border-r border-slate-200 px-1.5 py-3 text-center font-mono text-xs text-slate-400 dark:border-slate-800 dark:text-slate-500" x-text="idx + 1"></td>
                <td class="border-b border-r border-slate-200 px-4 py-3 dark:border-slate-800">
                    <div class="whitespace-normal break-words text-[13px] font-semibold leading-snug text-slate-950 dark:text-white" x-text="item.product_name"></div>
                    <div class="mt-1 text-xs font-medium text-slate-500 dark:text-slate-400" x-text="item.category_name || 'Khác'"></div>
                </td>
                <td class="border-b border-r border-slate-200 px-2 py-3 text-center text-xs font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-300" x-text="item.request_unit || '---'"></td>
                <td x-show="!getRequestStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-3 text-right font-mono text-sm font-black tabular-nums text-slate-900 dark:border-slate-800 dark:text-white" x-text="item.request_quantity"></td>
                <td x-show="getRequestStatusInfo().isShipping || getRequestStatusInfo().isCompleted" class="border-b border-r border-slate-200 px-2 py-3 text-right font-mono text-sm font-black tabular-nums text-slate-900 dark:border-slate-800 dark:text-white" x-text="item.approved_quantity !== null ? item.approved_quantity : '--'"></td>
                <td x-show="getRequestStatusInfo().isCompleted" class="border-b border-r border-slate-200 px-2 py-3 text-right font-mono text-sm font-black tabular-nums dark:border-slate-800" :class="(item.received_quantity < item.approved_quantity) ? 'text-red-600 dark:text-red-400' : 'text-slate-900 dark:text-white'" x-text="item.received_quantity !== undefined ? item.received_quantity : 'Chưa nhận'"></td>
                <td x-show="getRequestStatusInfo().isCompleted" class="border-b border-slate-200 px-2 py-3 text-xs font-semibold dark:border-slate-800">
                    <template x-if="item.received_quantity !== undefined && item.approved_quantity !== null && item.received_quantity < item.approved_quantity">
                        <span class="inline-flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-2 py-1 text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300">
                            <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                                <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.19-1.458-1.516-2.625L8.485 2.495ZM10 6a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 10 6Zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
                            </svg>
                            <span>Thiếu <span x-text="Math.round(item.approved_quantity - item.received_quantity)"></span></span>
                        </span>
                    </template>
                    <template x-if="item.received_quantity !== undefined && item.approved_quantity !== null && item.received_quantity >= item.approved_quantity">
                        <span class="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300">
                            <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                                <path fill-rule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm3.857-9.809a.75.75 0 0 0-1.214-.882l-3.236 4.45-1.674-1.674a.75.75 0 1 0-1.06 1.06l2.3 2.3a.75.75 0 0 0 1.137-.089l3.747-5.165Z" clip-rule="evenodd" />
                            </svg>
                            <span>Đủ hàng</span>
                        </span>
                    </template>
                    <template x-if="item.received_quantity === undefined">
                        <span class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
                            <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                                <path fill-rule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm.75-12.25a.75.75 0 0 0-1.5 0V10c0 .199.079.39.22.53l2.25 2.25a.75.75 0 1 0 1.06-1.06l-2.03-2.03V5.75Z" clip-rule="evenodd" />
                            </svg>
                            <span>Chưa nhận</span>
                        </span>
                    </template>
                </td>
            </tr>
        </template>
    </tbody>
</table>
```

- [ ] **Step 3: Verify the template still parses**

Run:

```bash
python - <<'PY'
from pathlib import Path
from jinja2 import Environment
path = Path('app/templates/inventory/shared/requests/modal_request_detail.html')
Environment().parse(path.read_text())
print('request detail modal template parses')
PY
```

Expected output:

```text
request detail modal template parses
```

---

### Task 2: Update Approval Detail Modal Table Layout

**Files:**
- Modify: `app/templates/inventory/shared/approvals/modal_approval_detail.html:72-119`

- [ ] **Step 1: Inspect current approval table block**

Read `app/templates/inventory/shared/approvals/modal_approval_detail.html:72-119` and confirm the block still starts with:

```html
<table class="w-full table-fixed border-collapse text-left text-sm">
```

and contains this approval-only loop:

```html
<template x-for="(item, idx) in (viewingApprovalTicket?.items || [])" :key="item.id">
```

Expected: both strings are present before editing.

- [ ] **Step 2: Replace the approval table block**

Replace the full table block from `<table class="w-full table-fixed border-collapse text-left text-sm">` through its matching `</table>` with this markup:

```html
<table class="w-full table-fixed border-collapse text-left text-sm">
    <colgroup>
        <col class="w-[34px]">
        <col class="min-w-[240px]">
        <col class="w-[62px]">
        <col x-show="!getStatusInfo().isShipping" class="w-[88px]">
        <col x-show="!getStatusInfo().isPending" class="w-[88px]">
        <col x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="w-[88px]">
        <col x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="w-[126px]">
    </colgroup>
    <thead>
        <tr class="bg-slate-100 text-[11px] font-bold uppercase tracking-wide text-slate-600 dark:bg-slate-900 dark:text-slate-300">
            <th class="border-b border-r border-slate-200 px-1.5 py-2 text-center text-slate-400 dark:border-slate-800 dark:text-slate-500">#</th>
            <th class="border-b border-r border-slate-200 px-4 py-2 text-left text-slate-700 dark:border-slate-800 dark:text-slate-200">Tên hàng hóa / Vật tư</th>
            <th class="border-b border-r border-slate-200 px-2 py-2 text-center text-slate-500 dark:border-slate-800 dark:text-slate-400">ĐVT</th>
            <th x-show="!getStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-2 text-right text-slate-500 dark:border-slate-800 dark:text-slate-400">Yêu cầu</th>
            <th x-show="!getStatusInfo().isPending" class="border-b border-r border-slate-200 px-2 py-2 text-right text-slate-500 dark:border-slate-800 dark:text-slate-400">Thực xuất</th>
            <th x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-2 text-right text-slate-500 dark:border-slate-800 dark:text-slate-400">Thực nhận</th>
            <th x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="border-b border-slate-200 px-2 py-2 text-left text-slate-500 dark:border-slate-800 dark:text-slate-400">Tình trạng</th>
        </tr>
    </thead>
    <tbody>
        <template x-for="(item, idx) in (viewingApprovalTicket?.items || [])" :key="item.id">
            <tr class="bg-white hover:bg-slate-50 dark:bg-slate-950 dark:hover:bg-slate-900/70">
                <td class="border-b border-r border-slate-200 px-1.5 py-3 text-center font-mono text-xs text-slate-400 dark:border-slate-800 dark:text-slate-500" x-text="idx + 1"></td>
                <td class="border-b border-r border-slate-200 px-4 py-3 dark:border-slate-800">
                    <div class="whitespace-normal break-words text-[13px] font-semibold leading-snug text-slate-950 dark:text-white" x-text="item.product_name"></div>
                    <div class="mt-1 text-xs font-medium text-slate-500 dark:text-slate-400" x-text="item.category_name || 'Khác'"></div>
                </td>
                <td class="border-b border-r border-slate-200 px-2 py-3 text-center text-xs font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-300" x-text="item.request_unit || '---'"></td>
                <td x-show="!getStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-3 text-right font-mono text-sm font-bold tabular-nums text-slate-900 dark:border-slate-800 dark:text-white" x-text="item.request_quantity"></td>
                <td x-show="!getStatusInfo().isPending" class="border-b border-r border-slate-200 px-2 py-3 text-right font-mono text-sm font-bold tabular-nums text-slate-900 dark:border-slate-800 dark:text-white" x-text="item.approved_quantity !== null ? item.approved_quantity : '--'"></td>
                <td x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="border-b border-r border-slate-200 px-2 py-3 text-right font-mono text-sm font-bold tabular-nums dark:border-slate-800" :class="(item.received_quantity < item.approved_quantity) ? 'text-red-600 dark:text-red-400' : 'text-slate-900 dark:text-white'" x-text="item.received_quantity !== undefined ? item.received_quantity : 'Chưa nhận'"></td>
                <td x-show="!getStatusInfo().isPending && !getStatusInfo().isShipping" class="border-b border-slate-200 px-2 py-3 text-xs font-semibold dark:border-slate-800">
                    <template x-if="item.received_quantity !== undefined && item.approved_quantity !== null && item.received_quantity < item.approved_quantity">
                        <span class="inline-flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-2 py-1 text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300">
                            <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                                <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.19-1.458-1.516-2.625L8.485 2.495ZM10 6a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 10 6Zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
                            </svg>
                            <span>Thiếu <span x-text="Math.round(item.approved_quantity - item.received_quantity)"></span></span>
                        </span>
                    </template>
                    <template x-if="item.received_quantity !== undefined && item.approved_quantity !== null && item.received_quantity >= item.approved_quantity">
                        <span class="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300">
                            <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                                <path fill-rule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm3.857-9.809a.75.75 0 0 0-1.214-.882l-3.236 4.45-1.674-1.674a.75.75 0 1 0-1.06 1.06l2.3 2.3a.75.75 0 0 0 1.137-.089l3.747-5.165Z" clip-rule="evenodd" />
                            </svg>
                            <span>Đủ hàng</span>
                        </span>
                    </template>
                    <template x-if="item.received_quantity === undefined">
                        <span class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
                            <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                                <path fill-rule="evenodd" d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm.75-12.25a.75.75 0 0 0-1.5 0V10c0 .199.079.39.22.53l2.25 2.25a.75.75 0 1 0 1.06-1.06l-2.03-2.03V5.75Z" clip-rule="evenodd" />
                            </svg>
                            <span>Chưa nhận</span>
                        </span>
                    </template>
                </td>
            </tr>
        </template>
    </tbody>
</table>
```

- [ ] **Step 3: Verify the template still parses**

Run:

```bash
python - <<'PY'
from pathlib import Path
from jinja2 import Environment
path = Path('app/templates/inventory/shared/approvals/modal_approval_detail.html')
Environment().parse(path.read_text())
print('approval detail modal template parses')
PY
```

Expected output:

```text
approval detail modal template parses
```

---

### Task 3: Verify Shared Inventory Modal Rendering Safety

**Files:**
- Verify: `app/templates/inventory/shared/requests/modal_request_detail.html`
- Verify: `app/templates/inventory/shared/approvals/modal_approval_detail.html`

- [ ] **Step 1: Run combined Jinja parse check**

Run:

```bash
python - <<'PY'
from pathlib import Path
from jinja2 import Environment
for file_name in [
    'app/templates/inventory/shared/requests/modal_request_detail.html',
    'app/templates/inventory/shared/approvals/modal_approval_detail.html',
]:
    Environment().parse(Path(file_name).read_text())
    print(f'parsed {file_name}')
PY
```

Expected output:

```text
parsed app/templates/inventory/shared/requests/modal_request_detail.html
parsed app/templates/inventory/shared/approvals/modal_approval_detail.html
```

- [ ] **Step 2: Confirm no Alpine condition was changed**

Run:

```bash
git diff -- app/templates/inventory/shared/requests/modal_request_detail.html app/templates/inventory/shared/approvals/modal_approval_detail.html
```

Expected: the diff only changes `colgroup` widths, Tailwind classes, status badge markup, and inline SVG icons. It must not rename these expressions:

```text
getRequestStatusInfo().isShipping
getRequestStatusInfo().isCompleted
getStatusInfo().isPending
getStatusInfo().isShipping
viewingRequestTicket?.items
viewingApprovalTicket?.items
item.received_quantity
item.approved_quantity
```

- [ ] **Step 3: Run existing inventory modal JS check if available**

Run:

```bash
node tests/test_inventory_capture_modal.js
```

Expected: PASS or the same pre-existing result if this test is not related to these templates. If it fails, inspect whether the failure references modal table markup before continuing.

- [ ] **Step 4: Run GitNexus change detection**

Run the MCP tool:

```js
gitnexus_detect_changes({ scope: 'all', repo: 'binbinops' })
```

Expected: changed scope includes the two shared inventory modal templates and no unexpected backend/API execution-flow changes from this task.

---

### Task 4: Browser Visual Check

**Files:**
- Verify rendered app page that includes the request/approval detail modal.

- [ ] **Step 1: Start the app using the project’s normal local command**

If the app is not already running, use the repo’s existing start command from `.claude/commands/build.md` or the user’s usual dev command. Do not change app configuration.

Expected: local PMS app is reachable in a browser.

- [ ] **Step 2: Open an inventory page containing request/approval modals**

Open the relevant inventory manager or reception request page and navigate to a request/approval detail modal with item rows.

Expected visual checks:

```text
- # column is visually narrow and no longer dominates the table.
- Tên hàng hóa / Vật tư has noticeably more horizontal space.
- Long product names wrap without pushing numeric columns out of alignment.
- ĐVT and quantity columns remain compact and readable.
- Tình trạng badge has an SVG icon and clear color.
- Light mode colors are readable.
- Dark mode colors are readable if theme toggle/session is available.
```

- [ ] **Step 3: Check responsive behavior**

Use browser devtools or viewport resizing to inspect a narrow/mobile width.

Expected:

```text
- The modal remains scrollable instead of overflowing the page.
- The table remains horizontally usable inside the existing modal content area.
- Status badges do not cover or overlap quantity cells.
```

---

### Task 5: Final Diff Review

**Files:**
- Review: `app/templates/inventory/shared/requests/modal_request_detail.html`
- Review: `app/templates/inventory/shared/approvals/modal_approval_detail.html`
- Review: `docs/superpowers/plans/2026-05-24-inventory-modal-table-layout.md`

- [ ] **Step 1: Inspect git status**

Run:

```bash
git status --short
```

Expected: changed files include the two target templates and this plan file. Existing unrelated working-tree changes may already be present; do not stage or modify unrelated files.

- [ ] **Step 2: Inspect focused diff**

Run:

```bash
git diff -- app/templates/inventory/shared/requests/modal_request_detail.html app/templates/inventory/shared/approvals/modal_approval_detail.html
```

Expected: only table layout/class/status SVG markup changes.

- [ ] **Step 3: Report verification**

Report exactly which checks passed and which UI checks could not be run. Do not claim browser verification if the app could not be opened or authenticated.
