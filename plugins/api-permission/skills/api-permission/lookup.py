# Chạy trong Django shell của container crm-api:
#   MSYS_NO_PATHCONV=1 docker exec -i -e TARGET="<url hoặc ViewClass>" crm-api python manage.py shell < lookup.py
# MSYS_NO_PATHCONV=1: không có thì Git Bash đổi "/hubspot/..." thành "C:/Program Files/Git/hubspot/..."
import os
import re

from django.db import connection
from django.urls import URLPattern, URLResolver, get_resolver

from authentication.models import Permission

TARGET = os.environ["TARGET"].strip()
METHODS = ["get", "post", "put", "patch", "delete"]
KWARG_RE = re.compile(r"<(?:\w+:)?(\w+)>")


def walk(patterns, prefix=""):
    for p in patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from walk(p.url_patterns, route)
        elif isinstance(p, URLPattern) and hasattr(p.callback, "view_class"):
            # bản sao ".json/.api" do format_suffix_patterns sinh ra
            if "drf_format_suffix" in route or "(?P<format>" in route:
                continue
            yield route, p.callback.view_class


def normalize(path):
    # "/hubspot/student/detail/<int:pk>" hoặc "/hubspot/student/detail/pk" -> "hubspot student detail pk"
    return " ".join(KWARG_RE.sub(r"\1", path).strip("/").split("/"))


def kwargs_at_tail(route):
    segments = route.strip("/").split("/")
    kwarg_idx = [i for i, s in enumerate(segments) if KWARG_RE.fullmatch(s)]
    return kwarg_idx == list(range(len(segments) - len(kwarg_idx), len(segments)))


def matched_roles(api_pattern, method):
    # Cùng điều kiện join với RoleAccess.has_permission (src/app/permission.py), bỏ lọc theo role
    sql = """
    SELECT DISTINCT arp.role_slug, arp.permission_slug
    FROM authentication_rolepermission arp
    JOIN authentication_permission ap ON (
        ap.other_slug::jsonb @> '["cfg_public"]'::jsonb OR
        arp.permission_slug = ap.group_slug OR
        ap.other_slug::jsonb @> to_jsonb(arp.permission_slug)::jsonb
    ) AND ap.deleted = false
    WHERE arp.deleted = false AND ap.api_pattern = %s AND ap.method = %s
    ORDER BY arp.role_slug
    """
    with connection.cursor() as cur:
        cur.execute(sql, [api_pattern, method])
        return cur.fetchall()


routes = list(walk(get_resolver().url_patterns))
if "/" in TARGET:
    found = [(r, v) for r, v in routes if normalize(r) == normalize(TARGET)]
    if not found:
        from django.urls import Resolver404, resolve

        try:
            view_class = resolve(TARGET if TARGET.startswith("/") else "/" + TARGET).func.view_class
            found = [(r, v) for r, v in routes if v is view_class]
        except (Resolver404, AttributeError):
            pass
else:
    found = [(r, v) for r, v in routes if v.__name__ == TARGET]

if not found:
    print(f"NOT FOUND: {TARGET}")

for route, view_class in found:
    api_pattern = normalize(route)
    print("=" * 80)
    print(f"view:        {view_class.__module__}.{view_class.__name__}")
    print(f"route:       /{route}")
    print(f"api_pattern: {api_pattern}")
    print(f"permission_classes: {[c.__name__ for c in view_class.permission_classes]}")
    if not kwargs_at_tail(route):
        print("WARN: kwarg không nằm cuối path -> RoleAccess không bao giờ tính ra đúng api_pattern này")
    doc = (view_class.__doc__ or "").strip()
    if doc:
        print(f"class_doc:   {doc}")
    for m in METHODS:
        if not hasattr(view_class, m):
            continue
        method = m.upper()
        print(f"--- {method}")
        method_doc = (getattr(view_class, m).__doc__ or "").strip()
        if method_doc:
            print(f"  method_doc: {method_doc}")
        rows = Permission.objects.filter(api_pattern=api_pattern, method=method).values(
            "id", "permission_name", "group_name", "group_order", "order",
            "group_slug", "main_slug", "other_slug", "deleted",
        )
        if not rows:
            print("  DB permission: (chưa có)")
        for row in rows:
            print(f"  DB permission: {row}")
        roles = matched_roles(api_pattern, method)
        print(f"  roles được vào: {roles or '(không role nào)'}")
