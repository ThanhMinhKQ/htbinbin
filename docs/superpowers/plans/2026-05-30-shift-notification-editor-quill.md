# Trình soạn thông báo ca (Quill 2.0) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay lõi soạn thảo thông báo ca từ `document.execCommand` (deprecated) sang Quill 2.0, bổ sung font-family + cỡ chữ, giữ nguyên ảnh/file/link/kéo-thả, và đảm bảo định dạng hiển thị đúng ở popup.

**Architecture:** Quill 2.0 load qua CDN (pin 2.0.3), cấu hình xuất inline CSS thay vì class `ql-*` để khớp sanitizer popup. Đồng bộ Alpine ↔ Quill qua sự kiện `text-change`. Sửa allowlist style ở cả 2 file sanitizer (`attendance_notifications.html` + `includes/shift_notifications.html`).

**Tech Stack:** Quill 2.0.3 (CDN jsdelivr), Alpine.js, Jinja2, TailwindCSS, vanilla JS.

**Lưu ý kiểm thử:** Dự án không có JS test runner. Verification mỗi task = `node --check` cho cú pháp JS tách được + kiểm tra thủ công trên trình duyệt (mô tả rõ bước bấm). Không dùng pytest cho phần này.

---

### Task 1: Nạp Quill 2.0 qua CDN

**Files:**
- Modify: `app/templates/base.html` (thêm CSS Quill cạnh flatpickr ~dòng 25, JS Quill cạnh flatpickr ~dòng 1459)

- [ ] **Step 1: Thêm CSS Quill**

Sau dòng `<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">`, thêm:

```html
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.snow.css">
```

- [ ] **Step 2: Thêm JS Quill**

Cạnh dòng `<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>`, thêm trước nó:

```html
    <script src="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.js"></script>
```

- [ ] **Step 3: Verify nạp được**

Mở trang bất kỳ (đã đăng nhập) → DevTools Console gõ `Quill` → Expected: in ra `ƒ Quill(...)`, không `undefined`. Network tab: 2 request quill@2.0.3 trả 200.

- [ ] **Step 4: Commit**

```bash
git add app/templates/base.html
git commit -m "feat(editor): load Quill 2.0.3 from CDN"
```

---

### Task 2: Cấu hình Quill xuất inline-style + bộ font/size (module JS riêng)

**Files:**
- Create: `app/static/js/shift_notification_editor.js`
- Modify: `app/templates/base.html` (thêm `<script src>` sau Quill, trước Alpine)

Tách logic khởi tạo Quill ra file JS riêng để giữ template gọn và `node --check` được.

- [ ] **Step 1: Tạo file với đăng ký attributor inline-style**

`app/static/js/shift_notification_editor.js`:

```javascript
// Cấu hình Quill 2.0 cho trình soạn thông báo ca.
// Xuất inline CSS (style="...") thay vì class ql-* để khớp sanitizer popup.
(function () {
  'use strict';
  if (typeof Quill === 'undefined') {
    console.warn('[ShiftEditor] Quill chưa nạp — sẽ fallback textarea.');
    return;
  }

  // 5 font hiển thị tiếng Việt tốt. Key = giá trị lưu trong style.
  var FONTS = ['Inter', 'Arial', 'Times New Roman', 'Roboto', 'Be Vietnam Pro'];
  // 4 cỡ chữ px cụ thể.
  var SIZES = ['12px', '15px', '20px', '28px'];

  // Đăng ký font ở chế độ inline-style (Style attributor) thay vì class.
  var FontStyle = Quill.import('attributors/style/font');
  FontStyle.whitelist = FONTS;
  Quill.register(FontStyle, true);

  var SizeStyle = Quill.import('attributors/style/size');
  SizeStyle.whitelist = SIZES;
  Quill.register(SizeStyle, true);

  // Align cũng dùng inline-style để sanitizer (vốn giữ text-align) nhận ra.
  var AlignStyle = Quill.import('attributors/style/align');
  Quill.register(AlignStyle, true);

  // Color/background của Quill mặc định đã là inline-style — không cần đổi.

  window.ShiftEditorConfig = {
    fonts: FONTS,
    sizes: SIZES,
    toolbar: [
      [{ font: FONTS }, { size: SIZES }],
      [{ header: [1, 2, 3, false] }],
      ['bold', 'italic', 'underline', 'strike'],
      [{ color: [] }, { background: [] }],
      [{ list: 'ordered' }, { list: 'bullet' }],
      [{ align: [] }],
      ['link', 'image'],
      ['clean'],
    ],
  };
})();
```

- [ ] **Step 2: Verify cú pháp**

Run: `node --check app/static/js/shift_notification_editor.js`
Expected: không lỗi (exit 0).

- [ ] **Step 3: Nạp file trong base.html**

Sau `<script src="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.js"></script>`, thêm:

```html
    <script src="/static/js/shift_notification_editor.js?v=1"></script>
```

- [ ] **Step 4: Verify**

Reload trang → Console gõ `window.ShiftEditorConfig.fonts` → Expected: mảng 5 font. `Quill.import('attributors/style/font').whitelist` → 5 font.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/shift_notification_editor.js app/templates/base.html
git commit -m "feat(editor): register Quill inline-style fonts and sizes"
```

---

### Task 3: Thay markup vùng soạn — toolbar Quill + container

**Files:**
- Modify: `app/templates/attendance_notifications.html:944-1059` (toàn bộ `.sn-editor-toolbar` + `x-ref="editor"`)

- [ ] **Step 1: Thay toàn bộ block toolbar + editor area**

Thay khối từ `<div class="sn-editor-toolbar ...">` (dòng 944) đến hết `</div>` của `x-ref="editor"` (dòng 1059) bằng:

```html
                <!-- Toolbar do Quill tự render vào #sn-quill-toolbar -->
                <div id="sn-quill-toolbar"></div>
                <div x-ref="editor" class="sn-editor-area sn-rich-content"></div>
                <!-- Fallback nếu Quill không nạp được -->
                <textarea x-ref="editorFallback" x-model="form.body"
                          class="sn-editor-area sn-rich-content hidden"
                          placeholder="Soạn nội dung thông báo..."></textarea>
```

Giữ nguyên 2 input file ẩn (`imageFileInput`, `docFileInput`) ở trên.

- [ ] **Step 2: Verify cú pháp template render**

Run: `python3 -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('attendance_notifications.html')"`
Expected: không lỗi parse.

- [ ] **Step 3: Commit**

```bash
git add app/templates/attendance_notifications.html
git commit -m "feat(editor): replace execCommand toolbar markup with Quill container"
```

---

### Task 4: Khởi tạo Quill trong Alpine + đồng bộ text-change

**Files:**
- Modify: `app/templates/attendance_notifications.html` — vùng `<script>` Alpine: `refreshEditor`/`syncEditor`/`deferSyncEditor`/`saveSelection`/`restoreSelection`/`editorCommand`/`editorBlock` (~dòng 1309-1366, 1519-1521)

- [ ] **Step 1: Thêm state + hàm khởi tạo Quill**

Trong object Alpine, thêm property `quill: null` và hàm:

```javascript
    initQuill() {
      const el = this.$refs.editor;
      if (!el) return;
      if (typeof Quill === 'undefined' || !window.ShiftEditorConfig) {
        // Fallback: hiện textarea, ẩn vùng Quill
        if (this.$refs.editorFallback) this.$refs.editorFallback.classList.remove('hidden');
        el.classList.add('hidden');
        return;
      }
      if (this.quill) return; // đã init
      this.quill = new Quill(el, {
        theme: 'snow',
        placeholder: 'Soạn nội dung thông báo, có thể định dạng, chèn link, ảnh hoặc file...',
        modules: {
          toolbar: {
            container: '#sn-quill-toolbar',
            handlers: {
              image: () => this.$refs.imageFileInput.click(),
            },
          },
        },
      });
      // Toolbar config phải set trước khi new Quill qua container rỗng → dùng cách dưới:
      this.quill.on('text-change', () => {
        this.form.body = this.sanitizeRichHtml(this.quill.root.innerHTML);
      });
    },
```

LƯU Ý: vì `#sn-quill-toolbar` rỗng, Quill cần nhận mảng toolbar. Sửa Step như sau — truyền thẳng mảng thay vì container rỗng:

```javascript
          toolbar: {
            container: window.ShiftEditorConfig.toolbar,
            handlers: {
              image: () => this.$refs.imageFileInput.click(),
            },
          },
```

Và bỏ `<div id="sn-quill-toolbar"></div>` (Task 3) — Quill tự tạo toolbar phía trên editor. Cập nhật Task 3 markup: chỉ giữ `x-ref="editor"` + fallback textarea.

- [ ] **Step 2: Thay refreshEditor để nạp nội dung vào Quill**

Thay hàm `refreshEditor` (dòng ~1309):

```javascript
    refreshEditor() {
      setTimeout(() => {
        this.initQuill();
        const html = this.richBody(this.form.body || '');
        if (this.quill) {
          this.quill.clipboard.dangerouslyPasteHTML(html);
        } else if (this.$refs.editorFallback) {
          this.$refs.editorFallback.value = this.form.body || '';
        }
      }, 0);
    },
```

- [ ] **Step 3: Xóa các hàm execCommand cũ**

Xóa hẳn: `syncEditor`, `deferSyncEditor`, `savedRange`, `saveSelection`, `restoreSelection`, `editorCommand`, `editorBlock`. Các hàm này không còn ai gọi sau khi bỏ markup cũ (Task 3).

- [ ] **Step 4: Verify không còn tham chiếu mồ côi**

Run: `grep -n "syncEditor\|deferSyncEditor\|saveSelection\|restoreSelection\|editorCommand\|editorBlock\|savedRange" app/templates/attendance_notifications.html`
Expected: không còn dòng nào (trừ định nghĩa đã xóa). Nếu còn chỗ gọi → xử lý tiếp.

- [ ] **Step 5: Browser test**

Mở modal thêm thông báo → gõ chữ, đổi font, đổi cỡ chữ, đậm/nghiêng, màu chữ, danh sách, căn lề. Expected: toolbar hoạt động, không lỗi Console.

- [ ] **Step 6: Commit**

```bash
git add app/templates/attendance_notifications.html
git commit -m "feat(editor): init Quill in Alpine, sync via text-change, drop execCommand"
```

---

### Task 5: Nối upload ảnh/file, chèn URL/link, kéo-thả, dán vào Quill

**Files:**
- Modify: `app/templates/attendance_notifications.html` — `uploadAndInsert` (~1429-1528), `insertLink`/`insertImage`/`insertAttachment` (~1531-1559), `handleDrop`/`handlePaste`

- [ ] **Step 1: Sửa uploadAndInsert chèn qua Quill API**

Thay đoạn chèn (dùng `editorCommand('insertHTML', ...)` và `tempEl.outerHTML`) bằng chèn qua Quill. Sau khi upload thành công, lấy vị trí con trỏ và chèn:

```javascript
      // Thay this.editorCommand('insertHTML', tempHtml) — chèn placeholder:
      const range = this.quill ? (this.quill.getSelection(true) || { index: this.quill.getLength() }) : null;
      // ... sau khi fetch thành công:
      if (this.quill && range) {
        if (isImage) {
          this.quill.insertEmbed(range.index, 'image', data.url, 'user');
          this.quill.setSelection(range.index + 1);
        } else {
          // File đính kèm: chèn link tải
          this.quill.insertText(range.index, data.filename, 'link', data.url, 'user');
          this.quill.setSelection(range.index + data.filename.length);
        }
        this.form.body = this.sanitizeRichHtml(this.quill.root.innerHTML);
      }
```

Bỏ phần tạo `tempId`/spinner HTML chèn vào contenteditable cũ (Quill quản lý DOM riêng, chèn trực tiếp sau khi có URL). Giữ validation size/type và toast lỗi.

- [ ] **Step 2: Sửa insertImage (URL) và insertLink**

```javascript
    insertImage() {
      const url = this.safeUrl(prompt('Nhập URL hình ảnh'), true);
      if (!url || !this.quill) return;
      const range = this.quill.getSelection(true) || { index: this.quill.getLength() };
      this.quill.insertEmbed(range.index, 'image', url, 'user');
      this.form.body = this.sanitizeRichHtml(this.quill.root.innerHTML);
    },
    insertLink() {
      const url = this.safeUrl(prompt('Nhập URL liên kết'));
      if (!url || !this.quill) return;
      const label = prompt('Tên hiển thị', url) || url;
      const range = this.quill.getSelection(true) || { index: this.quill.getLength() };
      this.quill.insertText(range.index, label, 'link', url, 'user');
      this.form.body = this.sanitizeRichHtml(this.quill.root.innerHTML);
    },
```

`insertAttachment` giữ logic prompt nhưng chèn qua `insertText(..., 'link', url)` như trên.

- [ ] **Step 3: Kéo-thả & dán**

Quill xử lý paste/drop nội bộ. Cho ảnh từ máy: giữ `handleDrop`/`handlePaste` nhưng đổi đích chèn sang `uploadAndInsert` (đã sửa ở Step 1, dùng Quill). Bỏ `@dragover/@drop/@paste` cũ trên div (div giờ là Quill) — gắn listener trong `initQuill` qua `this.quill.root.addEventListener`.

```javascript
      // trong initQuill, sau khi tạo this.quill:
      this.quill.root.addEventListener('drop', (e) => this.handleDrop(e), true);
      this.quill.root.addEventListener('paste', (e) => this.handlePaste(e), true);
```

- [ ] **Step 4: Browser test**

Upload ảnh từ máy, chèn ảnh URL, chèn link, đính kèm file, kéo-thả ảnh, dán ảnh từ clipboard. Expected: tất cả chèn đúng vào editor, lưu được.

- [ ] **Step 5: Commit**

```bash
git add app/templates/attendance_notifications.html
git commit -m "feat(editor): wire uploads, links, drag-drop, paste into Quill"
```

---

### Task 6: Nới allowlist style cho sanitizer ở CẢ HAI file

**Files:**
- Modify: `app/templates/attendance_notifications.html` — `sanitizeRichHtml` (~1555+, nhánh xử lý style cho P/DIV/SPAN/H1-3/BLOCKQUOTE ~1598-1607)
- Modify: `app/templates/includes/shift_notifications.html` — `sanitizeRichHtml` (~599-606)

- [ ] **Step 1: Thêm font-size + font-family vào parser style (file attendance)**

Trong nhánh xử lý style, sau dòng match `bg`, thêm match có whitelist:

```javascript
          const fontSize = originalStyle.match(/font-size\s*:\s*(12px|15px|20px|28px)/i);
          const fontFamily = originalStyle.match(/font-family\s*:\s*([^;]+)/i);
          if (fontSize) styles.push(`font-size: ${fontSize[1]}`);
          if (fontFamily) {
            const allowedFonts = ['inter','arial','times new roman','roboto','be vietnam pro'];
            const fam = fontFamily[1].trim().replace(/["']/g, '').toLowerCase();
            if (allowedFonts.some(f => fam.includes(f))) styles.push(`font-family: ${fontFamily[1].trim()}`);
          }
```

Đảm bảo nhánh này áp cho cả tag SPAN (Quill bọc font/size trong span).

- [ ] **Step 2: Copy y hệt logic sang file popup**

Mở `includes/shift_notifications.html`, thêm CHÍNH XÁC cùng đoạn match font-size/font-family vào nhánh style tương ứng (dòng ~599-606). Hai bản phải khớp tuyệt đối.

- [ ] **Step 3: Verify whitelist chặn giá trị lạ**

Console (sau khi mở trang có hàm — hoặc test thủ công): tạo thông báo, sửa HTML thô không khả thi qua UI → test logic bằng cách dán đoạn có `font-family: 'Comic Sans'` → Expected: bị loại, không xuất hiện trong output.

- [ ] **Step 4: Browser test xuyên suốt**

Soạn thông báo có font Roboto + cỡ 20px + màu → Lưu → Mở popup hiển thị (`shift_notifications.html`) → Expected: font/cỡ/màu hiển thị ĐÚNG, không bị strip.

- [ ] **Step 5: Commit**

```bash
git add app/templates/attendance_notifications.html app/templates/includes/shift_notifications.html
git commit -m "feat(editor): allow font-size/font-family in sanitizer (both files)"
```

---

### Task 7: CSS toolbar Quill khớp tông + dark mode + font preview

**Files:**
- Modify: `app/templates/attendance_notifications.html` — khối `<style>` (gần `.sn-editor-select` ~174, `.sn-editor-shell` ~192)

- [ ] **Step 1: Thêm CSS override Quill snow**

Trong `<style>`, thêm: bo góc khớp `.sn-editor-shell`, viền theo `--`, dark mode cho `.ql-toolbar`/`.ql-container`, và nhãn font hiển thị tên thật trong dropdown:

```css
    .sn-editor-shell .ql-toolbar { border: 0; border-bottom: 1px solid rgb(226 232 240); }
    .sn-editor-shell .ql-container { border: 0; font-family: inherit; }
    .dark .sn-editor-shell .ql-toolbar { border-color: rgb(71 85 105); }
    .dark .sn-editor-shell .ql-toolbar .ql-stroke { stroke: rgb(203 213 225); }
    .dark .sn-editor-shell .ql-toolbar .ql-fill { fill: rgb(203 213 225); }
    .dark .sn-editor-shell .ql-toolbar .ql-picker { color: rgb(203 213 225); }
    /* Nhãn font trong dropdown */
    .ql-snow .ql-picker.ql-font .ql-picker-label[data-value="Inter"]::before,
    .ql-snow .ql-picker.ql-font .ql-picker-item[data-value="Inter"]::before { content: 'Inter'; }
    /* lặp cho Arial, Times New Roman, Roboto, Be Vietnam Pro */
```

(Liệt kê đầy đủ 5 font + 4 size label trong khi viết.)

- [ ] **Step 2: Browser test dark + light + mobile**

Toggle dark mode, thu nhỏ về mobile width. Expected: toolbar đọc được ở cả 2 theme, không tràn, không vỡ layout.

- [ ] **Step 3: Commit**

```bash
git add app/templates/attendance_notifications.html
git commit -m "style(editor): match Quill toolbar to theme + dark mode"
```

---

### Task 8: Dọn CSS chết + kiểm thử hồi quy toàn luồng

**Files:**
- Modify: `app/templates/attendance_notifications.html` — xóa `.sn-editor-select`, `.sn-editor-btn`, `.sn-upload-spinner` nếu không còn dùng

- [ ] **Step 1: Tìm CSS/markup chết**

Run: `grep -n "sn-editor-select\|sn-editor-btn\|sn-upload-spinner\|sn-editor-toolbar" app/templates/attendance_notifications.html`
Expected: chỉ còn định nghĩa CSS (không còn nơi dùng) → xóa các rule CSS đó.

- [ ] **Step 2: Kiểm thử hồi quy đầy đủ**

Checklist browser:
- Tạo mới: font + cỡ + định dạng + ảnh + link → Lưu → Mở sửa → đúng nguyên trạng.
- Hiển thị popup: font/cỡ/màu/căn lề đúng.
- Thông báo CŨ (HTML không Quill): mở sửa + hiển thị không vỡ.
- Dark mode + mobile.
- Tắt mạng tới CDN Quill (DevTools block) → reload → fallback textarea hoạt động.

- [ ] **Step 3: Commit**

```bash
git add app/templates/attendance_notifications.html
git commit -m "chore(editor): remove dead execCommand CSS"
```

---

## Self-Review Notes

- **Spec coverage:** Quill+CDN (T1), inline-style+font/size (T2), toolbar/markup (T3-4), upload/link/drag/paste (T5), sanitize cả 2 file (T6), dark mode/CSS (T7), dọn dẹp+regression+fallback (T8). Tương thích dữ liệu cũ: T4 Step 2 (`dangerouslyPasteHTML`). ✓
- **Mâu thuẫn đã sửa:** Task 3 ban đầu tạo `#sn-quill-toolbar` rỗng nhưng Task 4 truyền mảng toolbar trực tiếp → đã ghi chú bỏ div đó, Quill tự render toolbar. Khi thực thi, markup Task 3 chỉ giữ `x-ref="editor"` + fallback textarea.
- **Verification:** không pytest (frontend trong template) — dùng `node --check`, jinja parse check, và browser checklist.
