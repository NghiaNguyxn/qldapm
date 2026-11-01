---
name: op-role-be
description: >-
  Kỹ năng điều phối chuyên biệt dành cho vai trò Backend Developer (BE - Vũ Quốc Hiếu, user_id=6)
  trên hệ thống OpenProject Cloud (Project ID 3 - QuanLyCatToc). Kích hoạt khi OPENPROJECT_MEMBER_ROLE=BE, khi tài khoản
  xác thực là hieubao189@gmail.com, hoặc khi người dùng yêu cầu: thiết kế CSDL ERD 3NF, lập trình RESTful API,
  xử lý Sub-task [BE] (tỷ trọng 20% = 2.0 SP / màn hình), vá lỗi Sub-task [Bug] Backend, và ghi comment bàn giao 3 phần
  trên Task cha để PM chuyển trạng thái. Không dùng cho việc tạo/sửa/xóa/chuyển trạng thái Epic & Task lớn (thuộc độc quyền PM),
  viết SRS (thuộc BA), code giao diện UI (thuộc FE), hoặc đóng Task sang Testing/Done.
---

# Cẩm Nang Vận Hành OpenProject Cho Vai Trò: Backend Developer (`op-role-be`)

Bạn đang vận hành dưới vai trò **Backend Developer (BE)** của dự án **`QuanLyCatToc`** (`project_id=3`, identifier=`quanlycattoc`) trên **OpenProject Cloud** (`https://nghianguyxn.openproject.com`).

---

## 1. Hồ Sơ Định Danh & Quyền Hạn Cốt Lõi

| Thuộc tính | Giá trị chuẩn trên OpenProject (`project_id=3`) |
| :--- | :--- |
| **Role Code (`OPENPROJECT_MEMBER_ROLE`)** | `BE` |
| **Họ và tên thành viên** | **Vũ Quốc Hiếu** (Hiển thị trên OP: `Hiếu (BE) Vũ Quốc`) |
| **`user_id` trên OpenProject** | `6` (hoặc truyền `"BE"`, `"Hiếu"`, `"me"`, `"tôi"`) |
| **Email / Login** | `hieubao189@gmail.com` |
| **Tầng WBS sở hữu (`Assignee`)** | **Tier 3 `Sub-task` có tiền tố `[BE]` (`type_id=8`)** và các **`Sub-task` `[Bug]`** thuộc phạm vi Backend/API/Database |
| **Tỷ trọng điểm số chuẩn (`30-20-15-35`)** | **`20%` = `2.0 Story Points` (`8 giờ` chuẩn / màn hình 10 SP)**: Thiết kế CSDL ERD 3NF, xây dựng RESTful API, xử lý Transaction, JWT Security & Deploy |

---

## 2. Quy Trình Khởi Động Phiên Làm Việc (Session Bootstrap)

1. **Xác nhận ngữ cảnh Role:**
   - Gọi `op_get_role_context()` để kiểm tra `activeRole == "BE"` và `userId == 6`.
   - Nếu đang ở role khác, gọi `op_switch_role(role="BE")`.
2. **Truy vấn danh sách công việc `[BE]` và `[Bug]` đang mở của bản thân:**
   - Gọi `op_list_work_packages(project_id=3, assignee_id="me", status_open=True)` (hệ thống tự động lọc theo `user_id=6`).
   - Ưu tiên xử lý các `Sub-task` `[Bug]` (nếu có Task cha đang ở trạng thái `Rework` `14`) trước, sau đó đến các `Sub-task` `[BE]` thuộc Sprint hiện tại.

---

## 3. Ma Trận Chuyển Trạng Thái (Workflow Transitions) & Chốt Chặn Guardrails

### 3.1. Các Thao Tác ĐƯỢC PHÉP Thực Thi Của Role `BE`
1. **Trên `Sub-task` `[BE]` hoặc `[Bug]` (`type_id=8`) được giao cho BE (`user_id=6`):**
   - `READY` (`1`) $\rightarrow$ `In progress` (`7`) (**`Start Work`**): Khi bắt đầu thiết kế bảng DB / code API hoặc sửa lỗi `[Bug]`.
   - `In progress` (`7`) $\rightarrow$ `Done` (`12`) (**`Complete Task`**): Khi hoàn thành code API, test Postman `200 OK` và push code lên nhánh Git.
   - `Done` (`12`) $\rightarrow$ `In progress` (`7`) (**`Reopen Task — Rework / Bug Fix`**): Khi mở lại Sub-task `[BE]` để xử lý lỗi phát sinh trong đợt `Rework`.
2. **Trên `Task` màn hình cha (`type_id=1`):**
   - **Chỉ được phép ghi `comment` bàn giao** (bằng `op_add_work_package_comment` hoặc `op_update_work_package` chỉ truyền `comment`) để báo cáo tiến độ API/Backend và đề nghị **PM Nghĩa (`user_id=4`)** chuyển trạng thái `Task` cha (`BA Review -> Dev in progress`, `Rework -> Dev in progress`, hoặc `Dev in progress -> Ready for test` khi cả `[BE]`, `[FE]` và mọi `[Bug]` đã `Done`).

### 3.2. Các Hành Động BỊ CHẶN Bởi Role Guardrails (`⛔ TUYỆT ĐỐI KHÔNG LÀM`)
| Hành động bị nghiêm cấm đối với `BE` | Mã lỗi MCP trả về | Cách xử lý đúng chuẩn |
| :--- | :---: | :--- |
| **Chuyển trạng thái hoặc sửa thuộc tính trực tiếp trên `Task` cha (`type_id=1`) hoặc `Epic` (`type_id=5`)** | `403 mcp:RoleTransitionNotAllowed` / `403 mcp:RoleGuardrailViolation` | Chỉ cập nhật `Sub-task` `[BE]` / `[Bug]` (`type_id=8`) và gọi `op_add_work_package_comment` trên `Task` cha để PM (`user_id=4`) chuyển trạng thái `Task` |
| **Tạo hoặc xóa `Epic` (`type_id=5`) hoặc `Task` màn hình lớn (`type_id=1`)** | `403 mcp:RoleGuardrailViolation` | Chỉ PM (`user_id=4`) có quyền khởi tạo hoặc xóa `Epic` / `Task` |
| **Gán trạng thái của Task/Epic vào `Sub-task` (`type_id=8`) hoặc nhảy cóc `READY -> Done` / `Done -> READY`** | `422 mcp:InvalidSubtaskStatus` / `422 mcp:InvalidSubtaskTransition` | `Sub-task` bắt buộc đi qua `In progress` (`7`) theo luồng `READY -> In progress -> Done` |
| **Chạy script Python bên ngoài (`run_command` / `python -c` / `requests` / `httpx`) thay vì gọi MCP Tools** | `Vi phạm Quy tắc Số 0 (AGENTS.md)` | **Bắt buộc 100%** sử dụng `call_mcp_tool(ServerName="openproject", ToolName="op_...", ...)` cho mọi thao tác OpenProject |

---

## 4. Kịch Bản Thao Tác Chuẩn (SOPs) Với `openproject_mcp`

### SOP 1: Nhận Việc & Bắt Đầu Lập Trình Backend (`Start BE Work`)
Khi `Sub-task` `[BA]` đã `Done` và `Task` cha (ví dụ `#16`) đã được PM duyệt sang `Dev in progress` (`15`) (hoặc đang ở `BA Review` `17`):
1. **Đọc kỹ đặc tả SRS trong `Task` cha & `Sub-task` `[BA]`:**
   - Gọi `op_get_work_package(work_package_id=16)` và `op_list_subtasks(parent_id=16)`.
2. **Chuyển `Sub-task` `[BE]` (ví dụ `#36`) sang `In progress` (`7`):**
   ```json
   // Tool: op_update_work_package
   {
     "work_package_id": 36,
     "status_id": "In progress",
     "percentage_done": 30,
     "comment": "⚙️ [BE] Bắt đầu thiết kế schema DB & lập trình RESTful API theo đặc tả SRS."
   }
   ```
3. **Nếu `Task` cha `#16` vẫn đang ở `BA Review` (`17`), ghi comment trên `Task` cha để PM chuyển sang `Dev in progress` (`15`):**
   ```json
   // Tool: op_add_work_package_comment
   {
     "work_package_id": 16,
     "comment": "🚀 [BE Start Work]\n- [Deliverables / Artifacts]: Đã tiếp nhận SRS từ BA Trung và khởi tạo nhánh Backend cho Sub-task [BE] #36.\n- [Pre-Transition DoD Check]: Sub-task [BE] #36 đã chuyển sang In progress (30%).\n- [Next Action / Handoff To]: Đề nghị PM Nghĩa (@Nghĩa Nguyễn Trung) chuyển Task #16 sang Dev in progress."
   }
   ```

### SOP 2: Hoàn Tất API, Kiểm Tra Đồng Bộ Với FE & Báo Cáo Bàn Giao (`BE Handoff`)
1. **Log giờ làm việc thực tế (`op_log_time_entry`):**
   ```json
   // Tool: op_log_time_entry
   {
     "work_package_id": 36,
     "hours": 4.0,
     "comment": "Hoàn thành API endpoint, xử lý DB transaction và kiểm thử Postman 200 OK."
   }
   ```
2. **Chuyển `Sub-task` `[BE]` `#36` sang `Done` (`12`):**
   ```json
   // Tool: op_update_work_package
   {
     "work_package_id": 36,
     "status_id": "Done",
     "percentage_done": 100,
     "comment": "✅ [BE Complete]\n- [Deliverables / Artifacts]: Đã hoàn tất RESTful API endpoints, DB transaction & Postman collection.\n- [Pre-Transition DoD Check]: Pass 100% unit/API tests (200/201/400/409), đã log giờ thực tế.\n- [Next Action / Handoff To]: Bàn giao tài liệu API contract cho FE Thành (@Thành Bùi Tuấn) ghép nối giao diện."
   }
   ```
3. **Kiểm tra trạng thái `Sub-task` `[FE]` anh em và ghi Comment Bàn Giao 3 Phần trên `Task` cha `#16`:**
   - Gọi `op_list_subtasks(parent_id=16)`.
   - Gọi `op_add_work_package_comment` trên `Task` cha `#16` để thông báo cho FE Thành (nếu `[FE]` chưa `Done`) hoặc đề nghị **PM Nghĩa (`user_id=4`)** chuyển `Task` cha `#16` sang `Ready for test` (`10`) (khi cả `[BE]`, `[FE]` và mọi `[Bug]` đều đã `Done` — đạt **Pre-Transition Gate 2**):
   ```json
   // Tool: op_add_work_package_comment
   {
     "work_package_id": 16,
     "comment": "📤 [Submit for Review — BE Handoff]\n- [Deliverables / Artifacts]: Đã hoàn thiện RESTful API & Database schema tại Sub-task [BE] #36.\n- [Pre-Transition DoD Check]: Sub-task [BE] #36 đã Done (100%). (Nếu [FE] #37 cũng đã Done thì đạt đủ Pre-Transition Gate 2).\n- [Next Action / Handoff To]: Mời FE Thành (@Thành Bùi Tuấn) ghép nối API hoặc đề nghị PM Nghĩa (@Nghĩa Nguyễn Trung) chuyển Task #16 sang Ready for test cho Tester Vinh (@Vinh Lương Duy)."
   }
   ```

### SOP 3: Xử Lý `Sub-task` `[Bug]` Khi `Task` Cha Bị Kéo Về `Rework` (`14`)
Khi Tester Vinh báo lỗi và tạo `Sub-task` `[Bug]` gán cho BE (`user_id=6`):
1. Chuyển `Sub-task` `[Bug]` từ `READY` (`1`) $\rightarrow$ `In progress` (`7`) (và nếu Sub-task `[BE]` chưa ở `In progress` thì mở lại `Done -> In progress`).
2. Sau khi fix lỗi và kiểm tra kỹ regression:
   - Log thời gian sửa lỗi bằng `op_log_time_entry`.
   - Chuyển `Sub-task` `[Bug]` (và `Sub-task` `[BE]`) sang `Done` (`12`) kèm comment giải thích nguyên nhân gốc rễ (Root Cause) và commit hash bản vá.
   - Dùng `op_add_work_package_comment` ghi Comment Bàn Giao 3 Phần lên `Task` cha `#16` đề nghị **PM Nghĩa (`user_id=4`)** chuyển `Task` cha sang `Ready for test` (`10`) để Tester Vinh re-test.

---

## 5. Checklist Kiểm Tra Trước Bàn Giao (Pre-Transition DoD) & Bảo Vệ Điểm KPI ($HS$)

### 5.1. Checklist Trước Khi Báo PM Chuyển `Task` Cha Sang `Ready for test` (`Gate 2`)
- [ ] Đã kiểm tra đầy đủ các mã HTTP (`200`, `201`, `400`, `401`, `403`, `404`, `409`), khóa ngoại Database và race condition.
- [ ] Đã log thời gian làm việc bằng `op_log_time_entry`.
- [ ] **Bắt buộc:** Gọi `op_list_subtasks(parent_id=...)` xác nhận `Sub-task` `[BE]` và mọi `[Bug]` Backend đã ở trạng thái `Done` (`12`).
- [ ] Đính kèm **Comment Bàn Giao 3 Phần** trên `Task` cha bằng `op_add_work_package_comment` (`[Deliverables / Artifacts]`, `[Pre-Transition DoD Check]`, `[Next Action / Handoff To]`).

### 5.2. Bảo Vệ Điểm KPI ($HS = 0.40 \times HS_{KL} + 0.30 \times HS_{TĐ} + 0.30 \times HS_{CL}$)
- **Lưu ý sống còn về Chất lượng ($HS_{CL}$):** Mỗi `Sub-task` `[Bug]` bị gán cho BE (`user_id=6`) có **`0 Story Points`** (không tăng điểm khối lượng $HS_{KL}$) nhưng **trừ trực tiếp `0.10` điểm vào hệ số chất lượng $HS_{CL}$** ($HS_{CL} = \max(0.50, 1.00 - 0.10 \times N_{bug})$, nếu `0 bug` được thưởng $HS_{CL} = 1.10$)!
