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
