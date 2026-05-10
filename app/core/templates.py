"""
Shared Jinja2Templates instance for the application.
The Jinja2 patch is in jinja2_patch.py which handles url_for.
"""
import os
from fastapi.templating import Jinja2Templates

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATES_DIR = os.path.join(APP_ROOT, "templates")

# Create templates instance - jinja2_patch.py adds url_for
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def clear_template_cache():
    """Clear Jinja2 template cache."""
    if hasattr(templates.env, 'cache'):
        try:
            templates.env.cache.clear()
        except Exception:
            pass
