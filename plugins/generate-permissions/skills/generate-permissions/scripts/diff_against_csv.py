"""
Doi chieu output cua scan_django_permissions.py voi 1 file CSV permission da co,
tim cac endpoint (method, api_pattern) CHUA co dong nao trong CSV, va xuat 1 file
CSV nhap moi cho cac dong con thieu do.

group_name cua dong moi = ten app (thu muc chua urls.py trong repo, cot "feature"
cua scan.csv) - khong tu bia ten nghiep vu. Neu can ten hien thi khac ten thu muc
(vd viet hoa dung chuan "HRM" thay vi "Hrm"), dung --app-display.

`api_pattern` cua dong moi duoc dung tu cot "route" (con nguyen cu phap Django
<type:name>), boc {ten_kwarg} cho segment la tham so dong that (tru kwarg ten
"id" phai de tran - xem api_pattern_bracketed()). Chuan nay chi dam bao khop
runtime khi import qua duong Excel (.xlsx) cua he thong dich - xem canh bao
trong SKILL.md / README truoc khi import qua duong CSV thuan.

Khong ghi de gia tri group_name/group_slug/... da co san trong CSV dau vao - script
nay CHI xuat cac dong con thieu, khong dung de sua dong da ton tai.

Vi du:
    python diff_against_csv.py \
        --scan sa_scan_all.csv \
        --existing my_permissions.csv \
        --exclude-prefix /user/ \
        --app-display hrm=HRM --app-display cms=Cms --app-display app=App \
        --out new_permissions.csv
"""
import argparse
import csv
import re

TAG_RE = re.compile(r"<(?:\w+:)?(\w+)>")
BRACE_RE = re.compile(r"\{(\w+)\}")


def normalize_api_pattern(raw):
    segs = [s for s in raw.strip("/").split("/") if s != ""]
    out = []
    for s in segs:
        m = TAG_RE.fullmatch(s) or BRACE_RE.fullmatch(s)
        out.append(m.group(1) if m else s)
    return " ".join(out)


def title_from_url_name(url_name, api_pattern):
    base = url_name or api_pattern
    base = re.sub(r"[-_]+", " ", base)
    return base.strip().title()


VERB_WORDS = (
    "get", "list", "view", "create", "add", "update", "edit", "delete", "remove",
    "resend", "sync", "upload", "send", "change", "assign", "approve", "reject",
    "confirm", "verify", "merge", "clone", "activate", "block", "notify", "push",
    "import", "export", "track", "search", "find", "cancel", "close", "recall",
    "healthz", "readyz",
)
METHOD_VERB = {"GET": "Get", "POST": "Create", "PUT": "Update", "PATCH": "Update", "DELETE": "Delete"}


def mechanical_description(method, permission_name):
    first_word = permission_name.split(" ", 1)[0].lower() if permission_name else ""
    if first_word in VERB_WORDS:
        return permission_name
    verb = METHOD_VERB.get(method, method.title())
    return f"{verb} {permission_name}".strip()


def slugify(text):
    text = re.sub(r"[-\s]+", "_", text.strip().lower())
    text = re.sub(r"[^a-z0-9_]", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def build_slug(app, url_name_or_pattern):
    app_slug = slugify(app)
    rest_slug = slugify(url_name_or_pattern)
    # nhieu url_name da tu co san ten app o dau (vd app "bus", url_name
    # "bus-history") - khong noi them app prefix nua neu vay, tranh lap doi
    # kieu "bus_bus_history"
    if rest_slug == app_slug or rest_slug.startswith(app_slug + "_"):
        return rest_slug
    return f"{app_slug}_{rest_slug}"


VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def api_pattern_bracketed(route):
    """Dung cot 'route' goc (con nguyen cu phap Django <type:name>) de dung
    api_pattern dang '/segment/{ten_kwarg}/segment'. Segment tinh giu nguyen;
    segment la kwarg that duoc boc {ten} - TRU kwarg ten dung la 'id', phai
    de tran vi ImportPermissions.format_api_pattern (service-api) hard-code
    doi '{id}' -> '{pk}' truoc khi strip ngoac, sai neu kwarg that khong
    phai pk (da xac nhan co route dung dung ten 'id')."""
    segs = [s for s in route.strip("/").split("/") if s != ""]
    out = []
    for s in segs:
        m = TAG_RE.fullmatch(s)
        if not m:
            out.append(s)
            continue
        name = m.group(1)
        out.append(name if name == "id" else f"{{{name}}}")
    return "/" + "/".join(out)


ROLE_COLUMNS_DEFAULT = [
    "supper_admin", "admin", "head_of_school", "principal", "academic", "academic_manager",
    "operation", "operation_manager", "it", "it_manager", "teacher", "nanny", "nurse", "fnb",
    "fnb_manager", "accountant_view", "accountant", "chief_accountant", "purchasing",
    "contact_center", "contact_center_manager", "admission", "admission_manager", "marketing",
    "crm_admin", "finance_director", "application_pipeline_manager", "medicine", "leave_request",
    "user_actor",
]


def load_existing_keys(path, exclude_prefixes):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    keys = set()
    for i, row in enumerate(rows, start=2):
        method = (row.get("method") or "").strip()
        pat = (row.get("api_pattern") or "").strip()
        if method not in VALID_METHODS:
            print(f"[WARN] dong {i} trong --existing co method khong hop le ({method!r}, "
                  f"permission_name={row.get('permission_name')!r}) - nghi bi lech cot (thieu/thua "
                  f"o mot cot truoc do). BO QUA dong nay khi so khop, khong tinh la 'da co'.",
                  file=__import__("sys").stderr)
            continue
        if any(pat.startswith(p) for p in exclude_prefixes):
            continue
        keys.add((method, normalize_api_pattern(pat)))
    role_columns = [c for c in (rows[0].keys() if rows else []) if c not in (
        "feature", "permission_name", "description", "group_name", "group_order", "order",
        "permission_desc", "group_slug", "main_slug", "other_slug", "method", "api_pattern",
    )]
    return keys, (role_columns or ROLE_COLUMNS_DEFAULT)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", required=True, help="output cua scan_django_permissions.py")
    ap.add_argument("--existing", required=True, help="file CSV permission dang dung (khung cot business)")
    ap.add_argument("--out", required=True, help="duong dan file CSV moi se ghi (nen nam trong project, khong phai scratchpad)")
    ap.add_argument("--exclude-prefix", action="append", default=[],
                     help="bo qua dong trong --existing co api_pattern bat dau bang prefix nay "
                          "(dung khi file existing gom ca permission cua repo khac). Co the lap lai.")
    ap.add_argument("--app-display", action="append", default=[],
                     help="map ten thu muc app -> ten hien thi cho group_name, dang app=Ten. Co the lap lai.")
    args = ap.parse_args()

    app_display = {}
    for kv in args.app_display:
        k, _, v = kv.partition("=")
        app_display[k] = v or k.capitalize()

    existing_keys, role_columns = load_existing_keys(args.existing, args.exclude_prefix)

    with open(args.scan, newline="", encoding="utf-8-sig") as f:
        scan_rows = list(csv.DictReader(f))

    header = [
        "feature", "permission_name", "description", "group_name", "group_order", "order",
        "permission_desc", "group_slug", "main_slug", "other_slug", "method", "api_pattern",
        "service", "url_name", "view_class", "source_file",
    ] + role_columns

    out_rows = []
    matched = 0
    mechanical_desc_count = 0
    slug_seen = {}

    # gan group_order moi cho tung group_name moi, noi tiep sau group_order lon nhat da co
    existing_max_group_order = 0
    with open(args.existing, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                existing_max_group_order = max(existing_max_group_order, int(r.get("group_order") or 0))
            except ValueError:
                pass
    group_order_map = {}

    def group_order_for(group_name):
        if group_name not in group_order_map:
            group_order_map[group_name] = existing_max_group_order + len(group_order_map) + 1
        return group_order_map[group_name]

    group_row_counter = {}

    for row in scan_rows:
        key = (row["method"], row["api_pattern"])
        if key in existing_keys:
            matched += 1
            continue

        app = row["feature"]
        group_name = app_display.get(app, app.capitalize())

        doc = (row.get("method_doc") or "").strip() or (row.get("class_doc") or "").strip()
        permission_name = title_from_url_name(row["url_name"], row["api_pattern"])
        if doc:
            description = doc
        else:
            description = mechanical_description(row["method"], permission_name)
            mechanical_desc_count += 1

        base_slug = build_slug(app, row["url_name"] or row["api_pattern"])
        slug = base_slug
        if slug in slug_seen:
            slug = f"{base_slug}_{row['method'].lower()}"
        slug_seen[slug] = True

        view_class = row.get("view_class", "")
        source_file = row.get("source_file", "")

        group_row_counter[group_name] = group_row_counter.get(group_name, 0) + 1

        out_rows.append({
            "feature": group_name,
            "permission_name": permission_name,
            "description": description,
            "group_name": group_name,
            "group_order": group_order_for(group_name),
            "order": group_row_counter[group_name],
            "permission_desc": f"Nguon: {view_class} ({source_file})".strip(),
            "group_slug": slug,
            "main_slug": slug,
            "other_slug": slug,
            "method": row["method"],
            "api_pattern": api_pattern_bracketed(row["route"]),
            "service": row.get("service", ""),
            "url_name": row.get("url_name", ""),
            "view_class": view_class,
            "source_file": source_file,
            **{rc: "" for rc in role_columns},
        })

    out_rows.sort(key=lambda r: (r["group_name"], r["api_pattern"], r["method"]))

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Da khop voi CSV hien co: {matched}")
    print(f"Dong moi can review: {len(out_rows)}  (ghi ra: {args.out})")
    print(f"Description sinh co hoc tu url_name (khong co docstring nguon): {mechanical_desc_count}")
    print("LUU Y: cac cot role (supper_admin, admin, ...) va group_slug/main_slug/other_slug")
    print("       la GIA TRI TU SINH/de trong cho nguoi duyet, KHONG tu gan quyen that.")


if __name__ == "__main__":
    main()
