# AGENTS.md — Bộ Điều Phối Vai Trò & Kỹ Năng OpenProject (`QuanLyCatToc` - Project ID `3`)

Tệp cấu hình trung tâm này định hướng cho AI Agent khi làm việc với hệ thống **OpenProject Cloud** (`https://nghianguyxn.openproject.com`, Project ID `3`, identifier `quanlycattoc`, tên dự án `QuanLyCatToc`) thông qua **`openproject_mcp`**.

Mọi thao tác của Agent trên OpenProject **BẮT BUỘC** phải tuân thủ đúng **Quy tắc MCP-First (Cấm dùng script ngoài)**, **Vai trò thành viên đang kích hoạt (`OPENPROJECT_MEMBER_ROLE`)**, nạp đúng `SKILL.md` tương ứng của vai trò đó, và tuân thủ nghiêm ngặt quy chế **WBS 3 Tầng (Epic $\rightarrow$ Task $\rightarrow$ Sub-task)** cùng **Tỷ lệ Trọng số Chuyên môn `30-20-15-35`**.

---

## 0. Quy Tắc Bất Biến Số 0: Bắt Buộc Dùng 100% MCP Tools — Cấm Tuyệt Đối Script Ngoài (`MCP-First & Zero External Scripts`)

- **✅ BẮT BUỘC (`MANDATORY`):** Mọi thao tác đọc, tra cứu, tạo, sửa, xóa, chuyển trạng thái, chấm công, phân tích Gantt/EVM/KPI hoặc đồng bộ cấu hình trên OpenProject **BẮT BUỘC 100% phải gọi trực tiếp qua MCP Tools của server `openproject`** (`call_mcp_tool(ServerName="openproject", ToolName="op_...", Arguments={...})`).
- **⛔ CẤM TUYỆT ĐỐI (`HARD BAN`):**
  - **KHÔNG BAO GIỜ** dùng `run_command` chạy script Python bên ngoài (`python -c`, `requests`, `httpx`, hoặc khởi tạo `OpenProjectClient` từ terminal) hay tạo file `.py` tạm trong `scratch/` để gọi REST API OpenProject.
  - Khi cần kiểm tra nhiều danh mục cùng lúc (ví dụ: `types`, `priorities`, `statuses`, `roles`, `users`, `work_packages`), hãy phát đồng thời nhiều lệnh `call_mcp_tool` (`op_list_types`, `op_list_priorities`, `op_list_statuses`, `op_list_roles`, `op_list_users`, `op_list_work_packages`...) trong cùng một lượt phản hồi.

---

## 1. Quy Trình Nhận Diện Vai Trò & Điều Phối Tới Skill (Role Dispatcher)

Ngay khi người dùng yêu cầu thao tác với OpenProject (hoặc ở đầu phiên làm việc), Agent thực hiện theo thứ tự ưu tiên sau:

1. **Bước 1 — Xác định Role hiện tại bằng MCP Tool `op_get_role_context`:**
   - Gọi `op_get_role_context()` (hoặc `op_get_role_context(include_skill_markdown=True)`).
   - Hệ thống `openproject_mcp` tự động xác định Role theo 3 lớp:
     1. **Runtime Override:** Nếu người dùng vừa yêu cầu đổi vai trò trong phiên chat (ví dụ *"Mình là Hiếu BE"*, *"Chuyển sang role Tester"*), gọi ngay `op_switch_role(role="BE")` (hoặc `"PM"`, `"BA"`, `"FE"`, `"TESTER"`).
     2. **Biến môi trường `OPENPROJECT_MEMBER_ROLE`** trong [`openproject_mcp/.env`](file:///D:/PTIT/QLDAPM/openproject_mcp/.env) hoặc [`mcp_qldapm/.env`](file:///D:/PTIT/QLDAPM/mcp_qldapm/.env) (`PM`, `BA`, `BE`, `FE`, `TESTER`, hoặc `AUTO`).
     3. **Tự động nhận diện (`AUTO`):** Khi `OPENPROJECT_MEMBER_ROLE=AUTO`, MCP Server tự động đối chiếu thông tin tài khoản từ `GET /api/v3/users/me` (theo `OPENPROJECT_API_KEY` cá nhân) để suy ra đúng Role của thành viên.
2. **Bước 2 — Đọc và tuân thủ `SKILL.md` của Role tương ứng:**

| Mã Role (`OPENPROJECT_MEMBER_ROLE`) | Thành viên phụ trách | `user_id` | Email / Login | Tiền tố & Tỷ trọng chuẩn (`30-20-15-35`) | Đường dẫn Skill điều phối (`SKILL.md`) |
| :---: | :--- | :---: | :--- | :--- | :--- |
| **`PM`** | **Nguyễn Trung Nghĩa** (`Nghĩa Nguyễn Trung`) | `4` | `nghia2592005@gmail.com` | `[PM]` — **Gatekeeper & Owner 100% `Epic` / `Task`** | [`.agents/skills/op-role-pm/SKILL.md`](file:///D:/PTIT/QLDAPM/.agents/skills/op-role-pm/SKILL.md) |
| **`BA`** | **Nguyễn Vĩnh Trung** (`Trung (BA) Nguyễn Vĩnh`) | `5` | `nguyenvinhtrung0509@gmail.com` | `[BA]` — **`30%`** (`3.0 SP` = `12h` / màn hình) | [`.agents/skills/op-role-ba/SKILL.md`](file:///D:/PTIT/QLDAPM/.agents/skills/op-role-ba/SKILL.md) |
| **`BE`** | **Vũ Quốc Hiếu** (`Hiếu (BE) Vũ Quốc`) | `6` | `hieubao189@gmail.com` | `[BE]` — **`20%`** (`2.0 SP` = `8h` / màn hình) | [`.agents/skills/op-role-be/SKILL.md`](file:///D:/PTIT/QLDAPM/.agents/skills/op-role-be/SKILL.md) |
| **`FE`** | **Bùi Tuấn Thành** (`Thành (FE) Bùi Tuấn`) | `7` | `buituanthanh02@gmail.com` | `[FE]` — **`15%`** (`1.5 SP` = `6h` / màn hình) | [`.agents/skills/op-role-fe/SKILL.md`](file:///D:/PTIT/QLDAPM/.agents/skills/op-role-fe/SKILL.md) |
| **`TESTER`** | **Lương Duy Vinh** (`Vinh (Tester) Lương Duy`) | `8` | `vinhluong2894@gmail.com` | `[Tester]` — **`35%`** (`3.5 SP` = `14h` / màn hình) + `[Bug]` (`0 SP`) | [`.agents/skills/op-role-tester/SKILL.md`](file:///D:/PTIT/QLDAPM/.agents/skills/op-role-tester/SKILL.md) |

---

## 2. Cơ Chế Định Tuyến Thông Minh (`Smart Assignee Resolution`)

Trong tất cả các công cụ `op_list_work_packages`, `op_create_work_package`, `op_update_work_package`, `op_bulk_create_work_packages`, `op_bulk_update_work_packages`, và `op_validate_work_package_form`, tham số `assignee_id` (cũng như `responsible_id`, `author_id`) hỗ trợ truyền trực tiếp:
- **`"me"` / `"tôi"`** (hoặc bật `only_my_tasks=True` trong `op_list_work_packages`): Tự động dịch sang `user_id` của Role đang active (`PM -> 4`, `BA -> 5`, `BE -> 6`, `FE -> 7`, `TESTER -> 8`).
- **Mã Role:** `"PM"`, `"BA"`, `"BE"`, `"FE"`, `"TESTER"`, `"QA"`.
- **Tên thành viên:** `"Nghĩa"`, `"Trung"`, `"Hiếu"`, `"Thành"`, `"Vinh"`.
- **Số nguyên `user_id`:** `4`, `5`, `6`, `7`, `8`.

---

## 3. Kiến Trúc WBS 3 Tầng, 10 Trạng Thái & Chốt Chặn Phân Quyền (`Role Guardrails`)

### 3.1. Ba Tầng Công Việc (3-Tier Hierarchy)
1. **Tầng 1 — `Epic` (`type_id=5`):** Đại diện cho 4 giai đoạn lớn của dự án. Chỉ sử dụng 4 trạng thái:
   - `READY` (`1`) $\rightarrow$ `In progress` (`7`) $\rightarrow$ `In review` (`18`, **dành riêng cho Epic**) $\rightarrow$ `Done` (`12`).
   - **Owner & Người chuyển trạng thái duy nhất:** `PM` (`user_id=4`). Không nhập `estimated_hours` trực tiếp lên Epic.
2. **Tầng 2 — `Task` (`type_id=1`):** Mỗi Task là 1 màn hình chức năng (`[Màn hình] ...`, chuẩn `10 SP`) hoặc hạng mục quản trị/kiến trúc, nằm dưới 1 `Epic`. Sử dụng 8 trạng thái:
   - `READY` (`1`) $\rightarrow$ `BA in progress` (`16`) $\rightarrow$ `BA Review` (`17`) $\rightarrow$ `Dev in progress` (`15`) $\rightarrow$ `Ready for test` (`10`) $\rightarrow$ `Testing` (`9`) $\rightarrow$ `Rework` (`14`) $\rightarrow$ `Done` (`12`).
   - **Owner & Người chuyển trạng thái duy nhất:** `PM` (`user_id=4`). Không nhập `estimated_hours` trực tiếp lên Task. Các thành viên (`BA`, `BE`, `FE`, `TESTER`) khi hoàn thành `Sub-task` sẽ ghi **Comment bàn giao 3 phần** (`op_add_work_package_comment`) lên `Task` cha để `PM` chuyển trạng thái `Task`.
3. **Tầng 3 — `Sub-task` (`type_id=8`):** Mỗi `Task` màn hình chia thành 4 `Sub-task` chuẩn (`[BA]`, `[BE]`, `[FE]`, `[Tester]`) và các `[Bug]` phát sinh (`0 SP`). Chỉ sử dụng 3 trạng thái tinh gọn:
   - `READY` (`1`) $\rightarrow$ `In progress` (`7`) $\rightarrow$ `Done` (`12`) (và `Done` $\rightarrow$ `In progress` khi mở lại Sub-task để sửa SRS / Rework / QA hậu kiểm).

### 3.2. Bảng Phân Quyền Chuyển Trạng Thái, Chốt Chặn Pre-Transition Gates & Handoff Contract Theo Role
Hệ thống [`openproject_mcp/domains/work_packages.py`](file:///D:/PTIT/QLDAPM/openproject_mcp/domains/work_packages.py) tự động kiểm tra và chặn ngay các thao tác vượt thẩm quyền của từng Role (kèm `recoveryHint` tự phục hồi):

| Hạng mục kiểm soát | `PM` (`user_id=4`) | `BA` (`user_id=5`) | `BE` (`user_id=6`) | `FE` (`user_id=7`) | `TESTER` (`user_id=8`) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Tạo / Xóa `Epic` (`5`) & `Task` (`1`)** | ✅ Toàn quyền | ⛔ Chặn (`403`) | ⛔ Chặn (`403`) | ⛔ Chặn (`403`) | ⛔ Chặn (`403`) |
| **Sửa thuộc tính `Epic` (`5`) / `Task` (`1`)** | ✅ Toàn quyền | ⛔ Chặn (`403` — Chỉ được phép ghi `comment` bàn giao trên `Task` cha) | ⛔ Chặn (`403` — Chỉ được phép ghi `comment` bàn giao trên `Task` cha) | ⛔ Chặn (`403` — Chỉ được phép ghi `comment` bàn giao trên `Task` cha) | ⛔ Chặn (`403` — Chỉ được phép ghi `comment` bàn giao trên `Task` cha) |
| **Tạo `Sub-task` (`8`) dưới `Task` cha** | ✅ Toàn quyền | ✅ `[BA]` | ✅ `[BE]` | ✅ `[FE]` | ✅ `[Tester]` & `[Bug]` (`0 SP`, gán `BE`/`FE`) |
| **Chuyển trạng thái `Epic` (`type_id=5`)** | ✅ Toàn bộ luồng Epic (Gate 1: 100% Task con `Done`) | ⛔ Chặn (`403`) | ⛔ Chặn (`403`) | ⛔ Chặn (`403`) | ⛔ Chặn (`403`) |
| **Chuyển trạng thái `Task` (`type_id=1`)** | ✅ Toàn bộ luồng 8 trạng thái Task (kèm 3 Pre-Transition Child Gates) | ⛔ Chặn (`403` — Chỉ bình luận bàn giao trên `Task` cha để `PM` chuyển trạng thái) | ⛔ Chặn (`403` — Chỉ bình luận bàn giao trên `Task` cha để `PM` chuyển trạng thái) | ⛔ Chặn (`403` — Chỉ bình luận bàn giao trên `Task` cha để `PM` chuyển trạng thái) | ⛔ Chặn (`403` — Chỉ bình luận bàn giao trên `Task` cha để `PM` chuyển trạng thái) |
| **Đóng `Epic` / `Task` sang `Done` (`12`)** | ✅ Duy nhất (`Approve & Close` / `Pass & Complete`, Gate 1: 100% con `Done`) | ⛔ Chặn (`403`) | ⛔ Chặn (`403`) | ⛔ Chặn (`403`) | ⛔ Chặn (`403`) |
| **Chuyển trạng thái `Sub-task` (`8`)** | ✅ `READY -> In progress -> Done` & `Done -> In progress` | ✅ `READY -> In progress -> Done` & `Done -> In progress` (khi `Request SRS Fix`) | ✅ `READY -> In progress -> Done` & `Done -> In progress` (khi `Rework`) | ✅ `READY -> In progress -> Done` & `Done -> In progress` (khi `Rework`) | ✅ `READY -> In progress -> Done` + `Reopen Task` chéo (`Done -> In progress`) |

---

## 4. Hướng Dẫn Cấu Hình Cho Thành Viên Trong Team

Mỗi thành viên chỉ cần mở file [`openproject_mcp/.env`](file:///D:/PTIT/QLDAPM/openproject_mcp/.env) trên máy cá nhân và đặt:
```ini
OPENPROJECT_URL=https://nghianguyxn.openproject.com
OPENPROJECT_API_KEY=<mã_api_key_cá_nhân_của_bạn>
OPENPROJECT_PROJECT_ID=3
# Điền mã vai trò của bạn: PM, BA, BE, FE, TESTER (hoặc để AUTO để tự nhận diện theo API Key)
OPENPROJECT_MEMBER_ROLE=AUTO
```
Hoặc trong bất kỳ phiên chat nào với AI Agent, bạn có thể ra lệnh trực tiếp:
- *"Kiểm tra role hiện tại của mình trên OpenProject"* $\rightarrow$ Agent gọi `op_get_role_context`.
- *"Chuyển sang role FE (Thành) và liệt kê các task đang mở của mình"* $\rightarrow$ Agent gọi `op_switch_role(role="FE")`, đọc [`.agents/skills/op-role-fe/SKILL.md`](file:///D:/PTIT/QLDAPM/.agents/skills/op-role-fe/SKILL.md), và gọi `op_list_work_packages(project_id=3, assignee_id="me", status_open=True)`.
