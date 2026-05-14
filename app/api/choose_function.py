from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..core.security import require_checked_in_user
from ..core.templates import templates

router = APIRouter()


@router.get("/choose-function", response_class=HTMLResponse)
async def choose_function(request: Request, db: Session = Depends(get_db)):
    """
    Hiển thị trang chọn chức năng chính sau khi người dùng đã đăng nhập và điểm danh thành công.
    """
    if not require_checked_in_user(request):
        return RedirectResponse("/login", status_code=303)

    # Nếu có flag after_checkin thì xóa để tránh dùng lại
    if request.session.get("after_checkin") == "choose_function":
        request.session.pop("after_checkin", None)

    # Extract serializable data from session
    user_data = request.session.get("user")
    user_dict = None
    if user_data:
        user_dict = {
            "id": user_data.get("id"),
            "full_name": user_data.get("name"),
            "role": user_data.get("role"),
        }

    response = templates.TemplateResponse(request, "choose_function.html", {"request": request, "user": user_dict})
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
