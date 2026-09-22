---
name: generate-permissions
description: Quét source code của MỘT repo Django backend bất kỳ (mỗi lần chạy phục vụ đúng 1 repo) để tự sinh danh sách endpoint (method, api_pattern), rồi AI điền các field nghiệp vụ (permission_name, group_slug, description...) thành 1 file CSV để review và import bằng cơ chế import CSV/Excel sẵn có của hệ thống đó. Dùng khi có endpoint mới cần gán quyền, hoặc cần rà soát lại danh sách permission mà không muốn gõ tay từng dòng.
---

# Generate Permissions

Skill này thay việc gõ tay CSV/Excel permission bằng cách quét source code
1 repo Django, tính `method`/`api_pattern` chính xác, và dùng AI để draft
các field nghiệp vụ. Không tự ghi vào DB — output cuối là 1 file CSV để
người dùng review rồi tự import.

## Nguyên tắc

- **1 lần chạy = 1 repo = 1 file CSV.** Cần quét nhiều backend → chạy nhiều
  lần, mỗi lần 1 repo root khác nhau, giữ file output riêng cho từng repo.
  **Không bao giờ** trộn `group_slug`/`main_slug` giữa 2 hệ thống khác nhau
  trong cùng 1 file, trừ khi bạn chắc chắn 2 hệ thống đó chia sẻ cùng 1 bảng
  Permission thật.
- Script chỉ đọc source code (regex tĩnh), **không** import Django, không
  cần venv/DB của repo đó — chạy được với Python 3 stock, không cần cài gì.

## Bước 1 — Xác định 2 tham số trước khi chạy (không đoán, phải tự đọc code)

| Câu hỏi | Cách xác định |
|---|---|
| Repo này có class nào "gate" endpoint theo role không? | `grep -rn "permission_classes" <repo>` rồi đọc code — có class nào implement `BasePermission.has_permission()` để chặn theo role không. Có → dùng `--gate-class <TenClass>`. Không chắc → chạy **không** có `--gate-class` trước (liệt kê hết) để xem tổng quan rồi hỏi người dùng. |
| Nếu có gate class, nó tính chuỗi so khớp lúc runtime như thế nào? | Đọc thẳng hàm `has_permission()` của gate class đó. Nếu nó thay N segment cuối của path bằng tên kwarg (theo vị trí) rồi join bằng space → dùng `--api-pattern-style tail-kwargs`. **Mọi trường hợp khác** (hoặc không chắc, hoặc không có gate class) → dùng `inline-kwargs` (mặc định) — chỉ mang tính mô tả, không đảm bảo khớp runtime của repo đó. |

⚠️ `api_pattern` **không** phổ quát hoá được. Thuật toán `tail-kwargs` chỉ
đúng khi gate class của repo đó thực sự làm đúng việc "thay N segment cuối
theo vị trí" — đây là hành vi cụ thể của 1 implementation, không phải quy
ước Django. Nếu repo lạ dùng cơ chế khác (regex route, DRF router basename,
hash, so khớp theo `url_name`...), phải tự tính `api_pattern` bằng tay dựa
vào cột `route` (route gốc còn nguyên `<int:pk>`) mà script luôn xuất kèm.

## Bước 2 — Chạy script

```bash
python "<skill_dir>/scripts/scan_django_permissions.py" "<repo_root>" \
    [--gate-class TenClass] [--api-pattern-style tail-kwargs] \
    --service <ten-service> --out scan.csv
```

`<skill_dir>` là thư mục chứa `SKILL.md` này. Có thể lặp `--gate-class`
nhiều lần nếu repo có nhiều class gate khác nhau đều cần tính là "có
permission". Cờ khác:
- `--project-package DIR`: chỉ định thẳng thư mục chứa `settings.py`+`urls.py`
  nếu script báo tìm thấy nhiều/không tìm thấy ứng viên.
- `--methods get,post,put,patch,delete`: mặc định đủ 5, ít khi cần đổi.
- `--include-unrouted`: báo thêm các file `urls.py` tồn tại nhưng không được
  `include()` từ root (route chết, không ai gọi tới).

Đọc kỹ toàn bộ `[WARN]`/`[INFO]` ở stderr trước khi đi tiếp:

| Cảnh báo | Ý nghĩa | Hành động |
|---|---|---|
| `khong tim thay dinh nghia class 'X'` | Không tìm được view class X ở đâu trong repo | Kiểm tra tay — có thể import động/alias lạ mà script chưa xử lý |
| `view class 'X' mo ho (N noi dinh nghia)` | Có nhiều class cùng tên X trong repo, không chắc cái nào đúng | Xem `route`/`url_name` để tự xác định, hoặc bỏ qua dòng đó |
| `khong resolve duoc include('mod.urls')` | Không tìm thấy module cho 1 `include()` | Có thể là app third-party không nằm trong repo (bỏ qua được) hoặc script chưa tìm đúng chỗ |
| `bo qua route (kwarg khong nam cuoi path...)` | Chỉ xảy ra với `tail-kwargs` — route có tham số ở giữa path, không thể có `api_pattern` tĩnh khớp runtime | Đây là hạn chế của chính cơ chế gate đó, không phải bug script — bỏ qua route này |
| `route ket thuc bang '/' co kwarg` | `tail-kwargs` có thể tính sai với route có trailing slash | Kiểm tra tay giá trị `api_pattern` sinh ra cho route này |

## Bước 3 — Map sang khung cột import

Đưa output sang khung cột mà hệ thống đích dùng để import (ví dụ nhiều hệ
thống Django dùng chung shape: `feature, permission_name, description,
group_name, group_order, order, permission_desc, group_slug, main_slug,
other_slug, method, api_pattern` — nhưng **đây là ví dụ, không phải chuẩn
chung**, phải tự kiểm tra khung cột thật của hệ thống đích trước). Giữ thêm
các cột phụ mà script xuất ra (`service, url_name, view_class, route,
source_file, class_doc, method_doc`) để có context khi draft và để người
review truy ngược đúng file nguồn.

## Bước 4 — Loại permission đã tồn tại (tự động bằng `diff_against_csv.py`)

Nếu người dùng đã có sẵn 1 file CSV permission đang dùng (khung cột kiểu
`feature, permission_name, ..., group_slug, main_slug, other_slug, method,
api_pattern`), dùng script thứ hai để tự động đối chiếu và chỉ xuất ra các
dòng CÒN THIẾU — không cần API/UI của hệ thống đích:

```bash
python "<skill_dir>/scripts/diff_against_csv.py" \
    --scan scan.csv \
    --existing <file_csv_dang_dung>.csv \
    --exclude-prefix /prefix-cua-repo-khac/ \
    --app-display ten_app_viet_tat=TenHienThi \
    --out <duong_dan_trong_project_dich>/new_permissions.csv
```

- `--exclude-prefix` (lặp lại được): dùng khi file CSV hiện có gộp chung
  permission của NHIỀU repo/service (vd file tổng của cả platform) — loại
  các dòng thuộc repo khác trước khi so khớp, tránh báo nhầm "thiếu".
- `--app-display app_dir=Ten`: override tên hiển thị cho 1 app cụ thể (vd
  viết hoa `HRM` thay vì `Hrm` mặc định). Không cần khai hết — app nào
  không khai thì mặc định `.capitalize()`.
- **Quét để tìm endpoint MỚI (đối chiếu với 1 catalog nghiệp vụ) nên chạy
  `scan_django_permissions.py` ở Bước 2 KHÔNG kèm `--gate-class`** (lấy hết
  mọi route bất kể code đã enforce hay chưa) — khác với việc quét để kiểm
  tra "code đang thực sự enforce route nào" (lúc đó mới cần `--gate-class`).
  Catalog nghiệp vụ thường đi trước code: nhiều dòng trong file CSV đã có
  có thể ứng với endpoint chưa hề bị gate trong code (hoặc gate bởi 1 class
  khác như `SupperRoleAccess`), nếu lọc theo `--gate-class` sẽ báo "thiếu"
  sai cho toàn bộ các dòng đó.

Nếu hệ thống đích có API/UI riêng để xem danh sách permission hiện có (vd
`GET /authentication/permissions`), có thể dùng thay cho `--existing` khi
không có sẵn file CSV.

## Bước 5 — AI draft các field nghiệp vụ

**Mặc định phải điền đầy đủ mọi field mô tả/metadata, không để trống, không
dùng `TODO`** (trừ ngoại lệ về cột gán quyền — xem cuối bước này). Đây là
hành vi mặc định của `diff_against_csv.py`:
- `group_name`/`feature` = tên app (tên thư mục repo chứa `urls.py`, đúng
  cột `feature` mà `scan_django_permissions.py` xuất ra) — **không tự bịa
  tên nghiệp vụ** (vd không tự đặt "Card"/"Integration" nếu app thật là
  `hubspot`/`process`). Người dùng review xong có thể đổi tên nhóm tay nếu
  muốn gộp/tách theo màn hình, nhưng giá trị mặc định luôn bám theo app.
- `description`: ưu tiên `method_doc`/`class_doc` nếu có. Không có →
  sinh cơ học từ `url_name`/`method` (vd `GET` + url_name không có sẵn động
  từ → `"Get " + tên rút ra từ url_name`). Loại description này **không
  phải business copy đã xác minh** — báo rõ số dòng bị fallback kiểu này
  cho người dùng để họ soát lại.
- `group_slug`/`main_slug`: sinh tự động dạng `{app}_{url_name hoặc
  api_pattern đã chuẩn hoá}`, duy nhất trong file (thêm hậu tố method nếu
  trùng). Đây là slug **placeholder có thể đổi tên** trước khi import, mục
  đích là không để trống chứ không cam kết khớp quy ước đặt tên cũ của hệ
  thống đích (quy ước cũ thường không nhất quán giữa các app, không nên
  đoán mò).
- `api_pattern` của dòng mới: dựng từ cột `route` (giữ nguyên cú pháp
  Django `<type:name>`, không phải từ `api_pattern`/`route` đã flatten của
  `scan.csv`), dạng `/segment/{ten_kwarg_that}/segment` — segment tĩnh giữ
  nguyên, segment là kwarg thật được bọc `{...}`, **trừ kwarg tên đúng là
  `id` phải để trần không ngoặc** (xem `api_pattern_bracketed()` — tránh
  bug hard-code `{id}` → `{pk}` của `format_api_pattern` phía hệ thống
  đích, sai với kwarg thật nếu nó không phải `pk`). Chuẩn `{}` này **chỉ
  được đảm bảo khớp runtime khi import qua đường Excel (`.xlsx`)** của hệ
  thống đích — xem cảnh báo ở Bước 6.
- `other_slug`: mặc định = chính `group_slug`/`main_slug` của dòng đó (tự
  tham chiếu) — an toàn vì không tạo phụ thuộc chéo sang permission khác,
  tránh cấp thừa quyền. Không tự suy luận "permission cha" trừ khi người
  dùng xác nhận.
- `order`/`group_order`: sinh số thứ tự tăng dần trong từng group, nối tiếp
  sau giá trị lớn nhất đã có trong file `--existing` — chỉ ảnh hưởng thứ tự
  hiển thị UI, không ảnh hưởng enforcement, nên điền số mặc định là an
  toàn.
- `permission_desc`: dùng để ghi vết nguồn (`view_class` + `source_file`)
  khi không có nội dung nghiệp vụ nào khác đáng tin để điền — vẫn hữu ích
  cho người review truy ngược, không bịa nội dung nghiệp vụ.
- **Ngoại lệ duy nhất — cột gán quyền cho role (`supper_admin`, `admin`,
  `teacher`, ...): LUÔN để trống, không tự đoán.** Tự điền cột này tương
  đương tự quyết định "ai được cấp quyền gì" trên hệ thống thật — một sai
  số ở đây cấp nhầm quyền cho người dùng thật. Gán role luôn là bước thủ
  công, ngoài phạm vi skill.
- Nếu route thuộc cùng nhóm chức năng/màn hình với 1 permission đã có sẵn
  trong `--existing` (không phải route mới), ưu tiên gợi ý người dùng tái
  dùng `group_slug` sẵn có thay vì tạo slug mới — nhưng đây là gợi ý thủ
  công khi review, script không tự làm việc này.

## Bước 5b — (tuỳ chọn) Gộp thẳng vào file gốc bằng `merge_into_existing_csv.py`

Nếu người dùng muốn 1 file duy nhất "gốc + dòng mới" thay vì 2 file tách
rời, dùng tiếp:

```bash
python "<skill_dir>/scripts/merge_into_existing_csv.py" \
    --existing <file_csv_dang_dung>.csv \
    --scan scan.csv \
    --new new_permissions.csv \
    --out origin_and_new.csv
```

Quy tắc chèn — **giữ nguyên 100% nội dung và thứ tự các dòng gốc**, chỉ
chèn thêm:
- Nếu app của dòng mới đã xác định được đúng 1 `group_name` sẵn có trong
  file gốc (đối chiếu qua `--scan`), HOẶC `group_name` cơ học của dòng mới
  trùng thẳng với 1 `group_name` đã có trong file gốc → chèn dòng mới ngay
  sau dòng CUỐI CÙNG của group đó, giữ đúng `group_order` đã có, `order`
  nối tiếp số lớn nhất trong group.
- Nếu app đó chưa từng có permission nào trong file gốc, hoặc trải dài
  không rõ ràng trên nhiều `group_name` khác nhau → xếp thành khối mới ở
  **cuối file**, mỗi app 1 `group_order` riêng nối tiếp sau `group_order`
  lớn nhất file gốc.

Vài app tên gần giống nhưng không trùng tuyệt đối với nhãn nghiệp vụ cũ
(vd thư mục `report_card` nhưng nhãn cũ là `ReportCard` không có gạch dưới)
sẽ không tự khớp được — dùng `--app-display` ở Bước 4 để chỉnh cho khớp
trước khi merge, rồi chạy lại cả 2 bước.

## Bước 6 — Xuất CSV vào project, Bước 7 — Nhắc import

**Ghi file CSV output vào trong thư mục project (repo đích hoặc thư mục
người dùng chỉ định), không để lại trong thư mục tạm/scratchpad** — để có
thể commit, review lại, và tái sử dụng cho lần chạy sau. Nếu người dùng
chưa chỉ định chỗ lưu, gợi ý một thư mục hợp lý trong repo (vd
`docs/permission/`) và xác nhận trước khi ghi.

Tóm tắt cho người dùng: tổng số dòng, số dòng có `description` sinh cơ học
(cần soát lại), số cảnh báo ở Bước 2. Sau khi người dùng review xong, nhắc
họ tự import bằng cơ chế sẵn có của hệ thống đích (endpoint/UI import CSV
hoặc Excel) — skill này không tự ghi DB.

⚠️ **Nếu `api_pattern` ở dạng có `/` hoặc `{}` (quy ước của Bước 5), phải
xác nhận đường import THẬT SỰ convert đúng định dạng đó trước khi đưa cho
người dùng** — đừng mặc định "có chữ CSV/Excel trong tên endpoint là an
toàn". Nhiều hệ thống có 2 đường import khác nhau cho CÙNG 1 bảng permission
với 2 cách xử lý `api_pattern` khác hẳn nhau (đã gặp thực tế ở `service-api`
— xem phụ lục): 1 đường tự strip `/`/`{}` đúng, đường còn lại lưu verbatim
(chỉ trim khoảng trắng) → cùng 1 file, import nhầm đường sẽ khiến TOÀN BỘ
permission trong file không bao giờ khớp lúc runtime mà không có lỗi rõ
ràng nào báo ra. Đọc thẳng code xử lý import (không suy đoán từ tên
endpoint) để xác nhận, và nếu nghi ngờ, xuất thêm bản `.xlsx` song song với
`.csv` (dùng `openpyxl`, đã có sẵn trong hầu hết môi trường Python) để người
dùng chọn đúng đường an toàn.

## Giới hạn đã biết

- Chỉ nhận diện endpoint dạng `SomeClass.as_view()`; không thấy
  function-based view, DRF `ViewSet`/`router.register(...)`, hay
  `as_view()` gọi qua biến trung gian.
- **Không** theo dõi kế thừa: nếu 1 view lấy `permission_classes` từ class
  cha (không tự khai báo lại), `--gate-class` sẽ bỏ sót view đó.
- `api_pattern` không phổ quát — xem Bước 1. `tail-kwargs` giả định route
  không kết thúc bằng `/` khi có kwarg; nếu có, kết quả có thể sai (script
  sẽ cảnh báo).
- Phân tích tĩnh bằng regex, không chạy Django — urlpatterns dựng động
  (vd thêm route bằng vòng lặp/biến điều kiện phức tạp) có thể không được
  nhận diện đầy đủ.
- Không tự diff với DB thật của hệ thống đích.
- `diff_against_csv.py` so khớp bằng chuỗi `(method, api_pattern)` sau khi
  tự chuẩn hoá `api_pattern` của file `--existing` (tách `/`, rút tên kwarg
  trong `<...>`). Nếu file `--existing` dùng quy ước khác (vd tên kwarg
  trong CSV không trùng tên kwarg thật trong `urls.py`), kết quả so khớp sẽ
  sai lệch — kiểm tra vài dòng mẫu đã biết là "đã có" trước khi tin tưởng
  toàn bộ danh sách "thiếu".
- Route bị scanner bỏ qua (`bo qua route (kwarg khong nam cuoi path...)`
  với `tail-kwargs`) sẽ **hoàn toàn vắng mặt** khỏi cả `scan.csv` lẫn danh
  sách "thiếu" — không phải "đã có", chỉ là tool không thấy được. Nếu 1
  permission trong file `--existing` trỏ tới đúng loại route này (kwarg
  giữa path), đừng tự bịa `api_pattern` thay nó: với `RoleAccess` của
  `service-api`, thuật toán runtime tự nó cũng giả định kwarg luôn nằm ở
  **cuối** path (xem `has_permission()` trong `src/app/permission.py`) nên
  route kwarg-giữa-path vốn dĩ **không có cách nào khớp đúng lúc runtime**
  — đây là giới hạn thật của hệ thống đích, không phải chỉ của scanner. Báo
  cho người dùng biết route nào rơi vào nhóm này thay vì đoán.
- 3 lỗi đã gặp và đã sửa trong `diff_against_csv.py`/`merge_into_existing_csv.py`
  (đáng nhớ vì dễ tái diễn):
  1. **Slug tự sinh bị lặp prefix app** (vd `bus_bus_history`) khi
     `url_name` đã tự có sẵn tên app ở đầu (vd `url_name="bus-history"` của
     app `bus`) — phải kiểm tra `rest_slug.startswith(app_slug)` trước khi
     nối, xem `build_slug()`.
  2. **`api_pattern` ghi ra file phải luôn ở dạng `/x/y/z`** (có `/`, khớp
     quy ước file CSV nghiệp vụ), **không phải** dạng space-joined nội bộ
     mà `scan_django_permissions.py` dùng để so khớp (`tail-kwargs`/
     `inline-kwargs`) — 2 dạng phục vụ 2 mục đích khác nhau, đừng ghi thẳng
     dạng scan ra file cuối. Khi 1 script khác (vd `merge_into_existing_csv.py`)
     cần tra cứu lại theo key của `scan.csv`, phải normalize `/` → space
     trước khi tra, không tra thẳng.
  3. **Luôn validate `method` của mỗi dòng trong file `--existing`** thuộc
     đúng 5 giá trị hợp lệ trước khi tin — 1 dòng thiếu/thừa vài ô trống ở
     giữa (copy-paste từ Excel) làm `method`/`api_pattern` thật bị dồn sang
     cột khác và biến thành rỗng, khiến diff tưởng nhầm route đó "chưa có"
     và tạo dòng trùng. Dòng lỗi kiểu này phải **cảnh báo rõ + loại khỏi
     tập so khớp**, không tự ý sửa nội dung gốc của người dùng.
  4. **Muốn đánh dấu rõ segment nào là tham số động** (vd bọc `{pk}` thay vì
     để trần `pk`) — phải dựng lại từ cột `route` gốc (còn cú pháp Django
     `<type:name>`), **không** suy đoán từ chuỗi đã flatten (không phân
     biệt được literal path segment với 1 kwarg tình cờ trùng tên, vd
     `/card/detail/id/<int:card_id>` có "id" là segment TĨNH, kwarg thật là
     `card_id`). Và phải đọc code import THẬT của hệ thống đích trước khi
     chọn có bọc `{}` hay không, xem đoạn "Nếu `api_pattern` ở dạng có `/`
     hoặc `{}`" ở Bước 6 — `service-api` còn có thêm 1 bug hard-code
     `{id}` → `{pk}` phía import, nên riêng kwarg tên đúng là `id` phải để
     trần (xem `api_pattern_bracketed()` trong `diff_against_csv.py`).

## Phụ lục — 2 repo đã biết (ví dụ minh hoạ, không phải default)

Mẫu lệnh chung cho bất kỳ repo Django nào (thay 2 đường dẫn dưới đây bằng
repo thật của bạn):
```bash
python scan_django_permissions.py <path-to-your-django-repo> --service <your-service-name> --out scan.csv
```

**`service-api`** (Django, container `crm-api`): có class gate thật là
`RoleAccess` (`src/app/permission.py`), thay N segment cuối theo vị trí →
dùng `tail-kwargs`:
```bash
python scan_django_permissions.py C:\VSS\service-api --gate-class RoleAccess --api-pattern-style tail-kwargs --service service-api --out sa.csv
```
Đối chiếu permission đã tồn tại qua `GET /authentication/permissions`.
Khi import, **BẮT BUỘC dùng endpoint Excel** (`POST
/authentication/permissions/upload` → `PermissionsUploadView` → Celery task
`task_import_permission` → `ImportPermissions.format_api_pattern`,
`src/helpers/permission.py:361-364`) — hàm này tự `strip("/")`, convert
`/` → space, và tự strip `{`/`}` quanh mỗi segment (nên `api_pattern` dạng
`/x/{y}/z` hay `/x/y/z` đều ra kết quả giống nhau qua đường này). **Không
dùng đường CSV** (`POST /authentication/permissions` →
`PermissionsListView.post` → `PermissionCSVTools.norm`,
`src/helpers/permissions_csv.py:24-25`) — hàm đó **chỉ trim khoảng
trắng**, lưu `api_pattern` gần như verbatim, không convert `/`/`{}` gì cả
→ bất kỳ `api_pattern` nào viết dạng `/x/y/z` (đúng quy ước file CSV
nghiệp vụ của repo này) đi qua đường CSV sẽ **không bao giờ khớp**
`result_path` mà `RoleAccess` tính lúc runtime (space-joined, không `/`,
không `{}`) — toàn bộ permission trong file sẽ âm thầm không enforce được,
không có lỗi nào báo ra. Đây là lý do nghiêm trọng hơn bug upsert theo
`main_slug` bỏ qua `method` đã biết trước đó (vẫn đúng, nhưng không phải
lý do duy nhất nữa).

⚠️ `RoleAccess` chỉ thực sự được khai `permission_classes = (...,
RoleAccess)` trên khoảng chục view trong toàn repo (`tuition`, `report`,
`payment`, cộng vài view dùng biến thể `SupperRoleAccess` trong
`authentication`/`hubspot`) — tuyệt đại đa số view còn lại chỉ dùng
`CustomIsAuthenticate` (đăng nhập là đủ, không phân biệt role) hoặc các
class API-key khác. Vì vậy khi cần **đối chiếu với 1 catalog permission
nghiệp vụ** (file CSV liệt kê permission cho nhiều feature, kể cả những
route code chưa gate) — quét Bước 2 **không** kèm `--gate-class`, rồi dùng
`diff_against_csv.py` ở Bước 4; chỉ dùng `--gate-class RoleAccess` khi mục
đích là kiểm tra "code đang thực sự enforce route nào" (sẽ ra rất ít dòng).
Output của lần chạy gần nhất cho repo này được lưu tại
`docs/permission/rbac-csv/` trong chính repo `service-api` (không phải
scratchpad) — chạy lại 2 lệnh scan + diff ở trên để cập nhật.

**`user-management`** (Django, container `crm-user`): **không có** class
gate nào theo role (bảng `Permission` chỉ là dữ liệu quản lý cho FE, không
enforce) → không dùng `--gate-class`, dùng `inline-kwargs` (mặc định):
```bash
python scan_django_permissions.py C:\VSS\user-management --service user-management --out um.csv
```
Đối chiếu permission đã tồn tại qua `GET /user/permissions/table`. Import
qua `POST /user/permissions` (CSV) hoặc `/user/permissions/upload` (Excel).
