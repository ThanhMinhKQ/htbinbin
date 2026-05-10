"""
Early loading module to patch Jinja2 for Python 3.14 compatibility.
Fixes cache issues and provides backward-compatible TemplateResponse.
"""
import os

_jinja2_patched = False
_app_ref = None


def patch_jinja2():
    """
    Patch Jinja2 and Starlette to fix Python 3.14 compatibility issues.
    """
    global _jinja2_patched
    if _jinja2_patched:
        return

    try:
        from jinja2 import Environment
        from fastapi.templating import Jinja2Templates
        from starlette.templating import Jinja2Templates as StarletteJinja2Templates

        # ── Patch 1: Environment._load_template to bypass cache ──
        _original_load_template = Environment._load_template

        def _patched_load_template(self, name, globals=None):
            """Load template without cache to avoid Python 3.14 issues."""
            if self.loader is None:
                raise TypeError("no loader for this environment specified")
            
            if not isinstance(name, str):
                raise TypeError(f"Template name must be string, got {type(name).__name__}: {name!r}")

            # Load directly without cache
            template = self.loader.load(self, name, self.make_globals(globals))
            if globals:
                template.globals.update(globals)
            return template

        Environment._load_template = _patched_load_template

        # ── Patch 2: TemplateResponse backward compatibility ──
        _original_template_response = Jinja2Templates.TemplateResponse

        def _patched_template_response(self, *args, **kwargs):
            """
            Backward-compatible TemplateResponse that accepts both old and new API.
            
            Old: TemplateResponse("name.html", {"request": request, ...})
            New: TemplateResponse(request, "name.html", {...})
            """
            # Check if this is OLD API: (template_name, context_dict, ...)
            if (len(args) >= 2 
                and isinstance(args[0], str) 
                and isinstance(args[1], dict)):
                # OLD API detected: (name, context)
                name = args[0]
                context = args[1]
                extra_args = args[2:] if len(args) > 2 else ()
                
                # Extract request from context (old API puts request in context)
                request = context.get("request")
                if request is None:
                    raise ValueError(
                        f"Old-style TemplateResponse requires 'request' in context dict. "
                        f"Context keys: {list(context.keys())}"
                    )
                
                # Call with NEW API format
                return _original_template_response(
                    self,
                    request,      # NEW: request first
                    name,         # NEW: name second
                    context=context,
                    *extra_args,
                    **kwargs
                )
            
            # NEW API or different format: pass through
            return _original_template_response(self, *args, **kwargs)

        Jinja2Templates.TemplateResponse = _patched_template_response

        # Also patch Starlette's Jinja2Templates if different
        if StarletteJinja2Templates is not Jinja2Templates:
            StarletteJinja2Templates.TemplateResponse = _patched_template_response

        # ── Patch 3: Add url_for to Jinja2Templates ──
        _original_init = Jinja2Templates.__init__

        def _patched_init(self, *args, **kwargs):
            _original_init(self, *args, **kwargs)
            self.env.globals['url_for'] = _dynamic_url_for

        Jinja2Templates.__init__ = _patched_init

        _jinja2_patched = True
        print("[PATCH] Jinja2/TemplateResponse patched for Python 3.14 + backward compatibility")

    except ImportError as e:
        print(f"[WARN] Could not patch Jinja2: {e}")


def _dynamic_url_for(name: str, **kwargs):
    """Dynamic url_for that resolves app at call time."""
    app = _app_ref
    if app is None:
        return f"/{name}"
    try:
        return app.url_path_for(name, **kwargs)
    except Exception:
        return f"/{name}"


def configure_url_for(app):
    """Configure url_for for all templates. Call after app is created."""
    global _app_ref
    _app_ref = app


# Apply patch immediately
patch_jinja2()
