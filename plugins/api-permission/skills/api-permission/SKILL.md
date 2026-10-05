---
name: api-permission
description: Tra permission của 1 hoặc vài API trong service-api theo URL hoặc tên view class — view nào xử lý, có bị RoleAccess chặn không, DB đã có row permission chưa, role nào đang vào được — rồi đưa ra row CSV permission hợp lý để import. Dùng khi hỏi "API này cần permission gì", "sao API này bị 403", hoặc cần row permission cho endpoint mới.
argument-hint: <url | ViewClass> [...]
---

# API Permission

Input (`$ARGUMENTS`): một hoặc nhiều target, cách nhau bởi dấu cách. Mỗi target là:
- URL thật: `/hubspot/student/detail/126`
- URL ghi theo tên kwarg (giống file CSV): `/hubspot/student/detail/pk`
- Tên view class: `SyncStudentDebts`

Skill **không ghi DB**. Chỉ được sửa code (thêm `RoleAccess`) khi user đồng ý.

## Bước 1 — Tra cứu

Với mỗi target, chạy script (cần container `crm-api` đang chạy):

```bash
MSYS_NO_PATHCONV=1 docker exec -i -e TARGET="<target>" crm-api python manage.py shell < "<skill_dir>/lookup.py"
```

`MSYS_NO_PATHCONV=1` là bắt buộc trong Git Bash, vì thiếu nó thì URL bị đổi thành đường dẫn Windows.

Với mỗi route khớp target, script in ra:
- view, route, `api_pattern` (giá trị mà `RoleAccess` sẽ tính lúc runtime), `permission_classes`
- với từng method view có cài: row `authentication_permission` trong DB và danh sách role đang vào được (cùng điều kiện join với `RoleAccess.has_permission`)
- `WARN` khi kwarg không nằm cuối path. `RoleAccess` thay N segment cuối bằng tên kwarg, nên route kiểu đó không bao giờ khớp. Báo cho user, không tự bịa `api_pattern`.

Nếu kết quả là `NOT FOUND`, grep `urls.py` hoặc tên class để tìm tay.

## Bước 2 — Đọc view

Mở code view (`<app>/views.py`) để biết API làm gì: đọc hay ghi, phạm vi dữ liệu, có xuất dữ liệu cá nhân không. Thông tin này dùng để viết `description` và chọn role.

## Bước 3 — Trả lời

### 3a. Tình trạng hiện tại
Trình bày ngắn cho từng method: có bị gate không, DB có row chưa, role nào đang vào được, và kết luận vì sao bị 403 hoặc không bị.

- View **không có** `RoleAccess` trong `permission_classes`: row permission không có tác dụng enforce (chỉ cần đăng nhập là gọi được). Nói rõ điều này và hỏi user có muốn thêm `RoleAccess` không. **Lưu ý**: thêm `RoleAccess` khi chưa role nào được gán thì mọi user sẽ bị 403.
- Có `RoleAccess` nhưng `roles được vào` rỗng: mọi user bị 403, kể cả `supper_admin`, vì `RoleAccess` không có bypass.

### 3b. Row CSV
Header của file permission nghiệp vụ (giữ đúng thứ tự cột):

```
feature,permission_name,description,group_name,group_order,order,permission_desc,group_slug,main_slug,other_slug,method,api_pattern,supper_admin,admin,head_of_school,principal,academic,academic_manager,operation,operation_manager,it,it_manager,teacher,nanny,nurse,fnb,fnb_manager,accountant_view,accountant,chief_accountant,purchasing,contact_center,contact_center_manager,admission,admission_manager,marketing,crm_admin,finance_director,application_pipeline_manager,medicine,leave_request,user_actor
```

Đếm lại đủ 42 cột trước khi đưa row cho user.

Quy tắc điền, lấy từ cách importer và `RoleAccess` thực sự chạy:

| Cột | Cách điền | Vì sao |
|---|---|---|
| `main_slug` | **Bắt buộc**, duy nhất cho mỗi row. Nếu DB đã có row thì dùng lại `main_slug` của row đó. | Importer upsert theo `main_slug` và bỏ qua `method` (`authentication/views.py`, `PermissionsListView.post`). Row thiếu `main_slug` hoặc `permission_name` bị **bỏ qua im lặng**. Hai method trên cùng path phải có `main_slug` khác nhau. |
| `group_slug` | Quyền riêng: đặt bằng `main_slug`. Quyền con: để trống. | Ô role đánh `1` sẽ tạo `rolepermission.permission_slug = main_slug`, còn `RoleAccess` so slug đó với `group_slug` hoặc `other_slug`. |
| `other_slug` | Quyền con: slug của quyền cha (vd `s_application_pipeline_read`). Quyền riêng: để trống. | Role nào có slug cha thì vào được API này. |
| `api_pattern` | Dạng `/` với tên kwarg để trần, vd `/hubspot/student/detail/pk` | Giống quy ước của file CSV nghiệp vụ. |
| `feature`, `group_name`, `group_order`, `order` | Lấy theo row cùng nhóm đã có trong DB hoặc trong file CSV user đưa. | Chỉ ảnh hưởng hiển thị trên UI. |
| `description` | Mô tả từ việc đã đọc code ở Bước 2. | |
| Cột role | Chỉ điền cho quyền riêng: **copy từ một permission tham chiếu cụ thể** (vd "View student list", "Manage Tuition") và **nói rõ đã copy từ row nào**. Quyền con để trống hết. | Gán role là cấp quyền thật cho người dùng, nên user phải thấy căn cứ để sửa. Không tự nghĩ ra danh sách role. |

Nên đưa 2 phương án khi cả hai đều hợp lý:
- **Quyền riêng**: dùng cho API ghi, API chạy hàng loạt, hoặc API export dữ liệu cá nhân.
- **Quyền con** theo `other_slug`: ai có quyền cha là dùng được.

Nêu rõ phương án nào được khuyến nghị và vì sao.

### 3c. Nhắc cách import
- Import bằng **Excel** (`POST /authentication/permissions/upload`): `ImportPermissions.format_api_pattern` (`helpers/permission.py`) tự đổi `/x/y/z` thành `x y z`, nên dùng được `api_pattern` dạng `/`.
- Import bằng **CSV** (`POST /authentication/permissions`): `api_pattern` được lưu **nguyên văn**. Khi đó phải ghi dạng dấu cách (`hubspot student detail pk`), nếu không sẽ không bao giờ khớp và vẫn bị 403.

Sau khi user import, chạy lại Bước 1 để xác nhận `roles được vào` đã đúng.
