"""
Gop 1 file "new permissions" (output cua diff_against_csv.py) vao file CSV
permission goc, GIU NGUYEN thu tu + noi dung moi dong da co trong file goc,
va chen cac dong moi vao vi tri hop ly:

- Neu app cua dong moi da co DUY NHAT 1 group_name trong file goc (xac dinh
  qua doi chieu (method, api_pattern) voi file scan) -> dong moi duoc gan
  lai group_name/group_order = dung group do, chen ngay sau dong CUOI CUNG
  cua group do trong file goc, 'order' noi tiep sau order lon nhat da co
  trong group.
- Neu app do khong co trong file goc, hoac co NHIEU group_name khac nhau
  (khong the chon 1 cach chac chan) -> giu group_name co hoc (tu
  diff_against_csv.py), gop thanh 1 khoi moi o CUOI file, cac group nay
  duoc danh group_order noi tiep sau group_order lon nhat toan file.

Output dung DUNG khung cot cua file goc (khong mang theo cac cot phu
service/url_name/view_class/source_file cua file --new).

Vi du:
    python merge_into_existing_csv.py \
        --existing my_permissions.csv \
        --scan sa_scan_all.csv \
        --new sa_new_permissions.csv \
        --out origin_and_new_permissions.csv
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


def to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--existing", required=True)
    ap.add_argument("--scan", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.existing, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        existing_rows = list(reader)

    with open(args.scan, newline="", encoding="utf-8-sig") as f:
        scan_rows = list(csv.DictReader(f))
    scan_app_by_key = {(r["method"], r["api_pattern"]): r["feature"] for r in scan_rows}

    import sys
    for i, row in enumerate(existing_rows, start=2):
        m = (row.get("method") or "").strip()
        if m not in VALID_METHODS:
            print(f"[WARN] dong {i} trong --existing co method khong hop le ({m!r}, "
                  f"permission_name={row.get('permission_name')!r}) - nghi bi lech cot. "
                  f"Dong nay van duoc GIU NGUYEN trong file ket qua (khong tu sua du lieu goc) "
                  f"nhung se KHONG duoc dung de xac dinh group cho dong moi.", file=sys.stderr)

    # app (thu muc src) -> {group_name: count}, chi tinh cac dong trong file goc
    # khop duoc voi 1 route thuc trong scan (va co method hop le)
    app_groups = {}
    for row in existing_rows:
        if (row.get("method") or "").strip() not in VALID_METHODS:
            continue
        key = (row["method"], normalize_api_pattern(row["api_pattern"]))
        app = scan_app_by_key.get(key)
        if not app:
            continue
        gn = row.get("group_name", "").strip()
        if not gn:
            continue
        app_groups.setdefault(app, {}).setdefault(gn, 0)
        app_groups[app][gn] += 1

    canonical_group_for_app = {
        app: next(iter(names)) for app, names in app_groups.items() if len(names) == 1
    }

    # vi tri dong CUOI CUNG trong file goc cho tung group_name, va order lon nhat trong group do
    last_index_for_group = {}
    max_order_for_group = {}
    max_group_order_overall = 0
    for idx, row in enumerate(existing_rows):
        gn = row.get("group_name", "").strip()
        if gn:
            last_index_for_group[gn] = idx
            max_order_for_group[gn] = max(max_order_for_group.get(gn, 0), to_int(row.get("order")))
        max_group_order_overall = max(max_group_order_overall, to_int(row.get("group_order")))

    with open(args.new, newline="", encoding="utf-8-sig") as f:
        new_rows = list(csv.DictReader(f))

    # goi tung dong moi vao 1 group da xac dinh o tren, hoac giu group co hoc
    # (moi cua diff_against_csv.py) neu khong hop nhat duoc
    inserts_after = {}  # index trong existing_rows -> list[row moi] (theo dung khung cot goc)
    new_group_blocks = {}  # group_name moi (chua tung co trong file goc) -> list[row moi]

    for nrow in new_rows:
        # nrow["api_pattern"] o dang co dau '/' (output cua diff_against_csv.py ban
        # da sua) - normalize ve dang scan noi bo (space-joined) truoc khi tra scan_app_by_key
        key = (nrow["method"], normalize_api_pattern(nrow["api_pattern"]))
        app = scan_app_by_key.get(key)
        canonical = canonical_group_for_app.get(app) if app else None

        out_row = {fn: nrow.get(fn, "") for fn in fieldnames}

        # uu tien group xac dinh duy nhat qua app (canonical); neu khong co,
        # van thu khop truc tiep theo dung chuoi group_name co hoc (truong
        # hop 1 app trai dai tren nhieu group nhung group_name co hoc vo
        # tinh trung voi 1 group da co san, vd app "tuition"/"hubspot")
        target_group = canonical if (canonical and canonical in last_index_for_group) else None
        if not target_group:
            gn_mechanical = nrow.get("group_name", "").strip()
            if gn_mechanical in last_index_for_group:
                target_group = gn_mechanical

        if target_group:
            out_row["group_name"] = target_group
            out_row["feature"] = target_group
            # giu group_order dung nhu cac dong da co cua group do
            sample_idx = last_index_for_group[target_group]
            out_row["group_order"] = existing_rows[sample_idx].get("group_order", "")
            max_order_for_group[target_group] = max_order_for_group.get(target_group, 0) + 1
            out_row["order"] = max_order_for_group[target_group]
            inserts_after.setdefault(last_index_for_group[target_group], []).append(out_row)
        else:
            gn = nrow.get("group_name", "").strip() or "Unclassified"
            new_group_blocks.setdefault(gn, []).append(out_row)

    # gan group_order moi cho cac group hoan toan moi, noi tiep sau group_order lon nhat file goc
    for i, gn in enumerate(sorted(new_group_blocks.keys())):
        go = max_group_order_overall + i + 1
        for j, row in enumerate(new_group_blocks[gn], start=1):
            row["group_order"] = go
            row["order"] = j

    # ráp file cuoi cung: giu nguyen thu tu file goc, chen dong moi ngay sau
    # dong cuoi cung cua group tuong ung; cac group hoan toan moi xep o cuoi
    combined = []
    for idx, row in enumerate(existing_rows):
        combined.append(row)
        for extra in inserts_after.get(idx, []):
            combined.append(extra)

    for gn in sorted(new_group_blocks.keys()):
        combined.extend(new_group_blocks[gn])

    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(combined)

    merged_count = sum(len(v) for v in inserts_after.values())
    appended_count = sum(len(v) for v in new_group_blocks.values())
    print(f"Dong goc: {len(existing_rows)}")
    print(f"Dong moi duoc gop vao group da co san (giu dung group_name/group_order goc): {merged_count}")
    print(f"Dong moi thuoc group hoan toan moi, xep cuoi file: {appended_count}")
    print(f"  -> cac group moi: {sorted(new_group_blocks.keys())}")
    print(f"Tong dong file ket qua: {len(combined)}  (ghi ra: {args.out})")


if __name__ == "__main__":
    main()
