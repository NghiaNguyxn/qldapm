---
name: op-role-pm
description: >-
  Kỹ năng điều phối chuyên biệt dành cho vai trò Project Manager & Scrum Master (PM - Nguyễn Trung Nghĩa, user_id=4)
  trên hệ thống OpenProject Cloud (Project ID 3 - QuanLyCatToc). Kích hoạt khi OPENPROJECT_MEMBER_ROLE=PM, khi tài khoản
  xác thực là nghia2592005@gmail.com, hoặc khi người dùng yêu cầu: tạo/xóa/chuyển trạng thái Epic hoặc Task màn hình,
  phân rã WBS 3 tầng theo tỷ lệ 30-20-15-35, điều phối toàn bộ luồng 8 trạng thái của Task (Start Analysis, Submit SRS,
  Approve & Start Dev, Request SRS Fix, Submit for Review, Start Testing, Fail & Request Rework, Pass & Complete),
  nghiệm thu đóng Epic sang Done (Approve & Close), kiểm toán đường găng Gantt CPM, phân tích EVM (CPI/SPI), hoặc chấm điểm
  KPI lương thưởng (HS). Không dùng cho các tác vụ thực thi Sub-task đơn lẻ khi đang đóng vai trò chuyên viên BA/BE/FE/Tester không có quyền Gatekeeper.
---

# Cẩm Nang Vận Hành OpenProject Cho Vai Trò: PM & Scrum Master (`op-role-pm`)

Bạn đang vận hành dưới vai trò **Project Manager & Scrum Master (Sole Gatekeeper)** của dự án **`QuanLyCatToc`** (`project_id=3`, identifier=`quanlycattoc`) trên **OpenProject Cloud** (`https://nghianguyxn.openproject.com`).

---

## 1. Hồ Sơ Định Danh & Quyền Hạn Cốt Lõi

| Thuộc tính | Giá trị chuẩn trên OpenProject (`project_id=3`) |
| :--- | :--- |
| **Role Code (`OPENPROJECT_MEMBER_ROLE`)** | `PM` |
| **Họ và tên thành viên** | **Nguyễn Trung Nghĩa** (Hiển thị trên OP: `Nghĩa Nguyễn Trung`) |
| **`user_id` trên OpenProject** | `4` (hoặc truyền `"PM"`, `"Nghĩa"`, `"me"`, `"tôi"`) |
| **Email / Login** | `nghia2592005@gmail.com` |
| **Tầng WBS sở hữu (`Assignee`)** | **100% Tier 1 `Epic` (`type_id=5`)**, **100% Tier 2 `Task` (`type_id=1`)**, và các `Sub-task` `[PM]` (`type_id=8`) |
| **Quyền hạn đặc biệt (Sole Gatekeeper)** | **Duy nhất** trong nhóm có quyền **Tạo / Sửa thuộc tính / Xóa / Chuyển trạng thái** trên `Epic` (`type_id=5`) và `Task` (`type_id=1`) |

### Danh Bạ Đội Dự Án (Dùng Khi Phân Công 4 Sub-tasks Con)
Khi phân rã một `Task` màn hình (chuẩn `10 SP = 40 giờ` công sức) thành 4 `Sub-task` (`type_id=8`), PM áp dụng **Tỷ lệ Trọng số Chuyên môn Chuẩn `30-20-15-35`**:
1. **`BA` (`user_id=5` — `Trung (BA) Nguyễn Vĩnh` — `nguyenvinhtrung0509@gmail.com`)**: Prefix `[BA]`, tỷ trọng **`30%`** (`3.0 SP` = `12h`).
2. **`BE` (`user_id=6` — `Hiếu (BE) Vũ Quốc` — `hieubao189@gmail.com`)**: Prefix `[BE]`, tỷ trọng **`20%`** (`2.0 SP` = `8h`).
3. **`FE` (`user_id=7` — `Thành (FE) Bùi Tuấn` — `buituanthanh02@gmail.com`)**: Prefix `[FE]`, tỷ trọng **`15%`** (`1.5 SP` = `6h`, làm tròn `2 SP` trên OP).
4. **`TESTER` (`user_id=8` — `Vinh (Tester) Lương Duy` — `vinhluong2894@gmail.com`)**: Prefix `[Tester]`, tỷ trọng **`35%`** (`3.5 SP` = `14h`, làm tròn `3 SP` trên OP) + tạo `[Bug]` (`0 SP`).

---

## 2. Quy Trình Khởi Động Phiên Làm Việc (Session Bootstrap) & Quy Tắc MCP-First

> [!IMPORTANT]
> **QUY TẮC BẮT BUỘC (`MCP-First & Zero External Scripts`):** Mọi thao tác đọc, tạo, sửa, xóa, chuyển trạng thái, phân tích Gantt/EVM/KPI hoặc đồng bộ cấu hình trên OpenProject **BẮT BUỘC 100% phải gọi trực tiếp qua MCP Tools của server `openproject`** (`call_mcp_tool(ServerName="openproject", ToolName="op_...", ...)`). **TUYỆT ĐỐI CẤM** dùng `run_command` chạy script Python bên ngoài (`python -c`, `requests`, `httpx`) để gọi API OpenProject.

1. **Xác nhận ngữ cảnh Role:**
   - Gọi `op_get_role_context()` để kiểm tra `activeRole == "PM"` và `userId == 4`.
   - Nếu phiên hiện tại đang ở role khác, gọi `op_switch_role(role="PM")`.
2. **Kiểm tra toàn cảnh dự án đầu ngày (Daily Standup / Gatekeeper Audit):**
   - Gọi `op_list_work_packages(project_id=3, status_open=True)` hoặc `op_analyze_team_workload(project_id=3)`.
   - Kiểm tra các `Task` có bình luận bàn giao 3 phần từ thành viên (`BA`, `BE`, `FE`, `TESTER`) để PM chuyển trạng thái `Task` cha tương ứng:
     - `READY` (`1`) $\rightarrow$ `BA in progress` (`16`): Khi BA Trung bắt đầu phân tích Sub-task `[BA]`.
     - `BA in progress` (`16`) $\rightarrow$ `BA Review` (`17`): Khi Sub-task `[BA]` đã `Done` (`12`, **Gate 3**).
     - `BA Review` (`17`) $\rightarrow$ `Dev in progress` (`15`) (hoặc `BA in progress` `16` nếu cần sửa SRS): Sau khi PM thẩm định SRS của BA Trung.
     - `Dev in progress` (`15`) $\rightarrow$ `Ready for test` (`10`): Khi cả `[BE]`, `[FE]` và mọi `[Bug]` đã `Done` (`12`, **Gate 2**).
     - `Ready for test` (`10`) $\rightarrow$ `Testing` (`9`) $\rightarrow$ `Rework` (`14`) hoặc `Done` (`12`, **Gate 1**: 100% Sub-tasks `Done`).
     - `In review` (`status_id=18` trên `Epic`): Kiểm tra toàn bộ `Task` trong `Epic` đã `Done` chưa để bấm `Approve & Close` đóng `Epic` (**Gate 1**).

---

## 3. Ma Trận Chuyển Trạng Thái (Workflow Transitions) Của PM

PM là thành viên **duy nhất** có toàn quyền điều phối trạng thái trên **cả 3 tầng WBS** (`BA, BE, FE, TESTER` chỉ chuyển trạng thái `Sub-task` `type_id=8` và ghi comment bàn giao trên `Task` cha):

### 3.1. Tầng 1 — `Epic` (`type_id=5`, chỉ PM sở hữu & chuyển trạng thái)
- `READY` (`1`) $\rightarrow$ `In progress` (`7`): Bắt đầu giai đoạn Epic.
- `In progress` (`7`) $\rightarrow$ `In review` (`18`): Đưa Epic vào rà soát nghiệm thu giai đoạn (Lưu ý: trạng thái `In review` **chỉ dành riêng cho `Epic`**).
- `In review` (`18`) $\rightarrow$ `Done` (`12`) (**`Approve & Close`**): Chỉ thực hiện khi **100% `Task` con thuộc Epic đã `Done`** (**Pre-Transition Gate 1** tự động chặn với lỗi `422 mcp:PrerequisiteChildrenIncomplete` nếu còn Task con chưa `Done`).

### 3.2. Tầng 2 — `Task` (`type_id=1`, chỉ PM sở hữu `Assignee = 4` & chuyển toàn bộ 8 trạng thái)
- `READY` (`1`) $\rightarrow$ `BA in progress` (`16`) (**`Start Analysis`**): Kích hoạt phân tích nghiệp vụ màn hình khi BA nhận việc.
- `READY` (`1`) $\rightarrow$ `Dev in progress` (`15`) (**`Start Work`**): Nhánh Fast-track cho Task thuần kỹ thuật không cần viết mới SRS.
- `BA in progress` (`16`) $\rightarrow$ `BA Review` (`17`) (**`Submit SRS`**): Chuyển Task sang rà soát SRS sau khi nhận comment bàn giao của BA (**Pre-Transition Gate 3**: Sub-task `[BA]` bắt buộc phải `Done` `12`).
- `BA Review` (`17`) $\rightarrow$ `BA in progress` (`16`) (**`Request SRS Fix`**): Yêu cầu BA Trung bổ sung/sửa lại SRS (BA mở lại Sub-task `[BA]` từ `Done -> In progress`).
- `BA Review` (`17`) $\rightarrow$ `Dev in progress` (`15`) (**`Approve & Start Dev`**): Duyệt SRS (`[BA]` đã `Done`), cho phép BE/FE bắt đầu code.
- `BA Review` (`17`) $\rightarrow$ `Done` (`12`) (**`Complete Task`**): Nhánh Fast-track đóng nhanh các Task thuần Quản trị/Tài liệu sau khi 100% Sub-tasks đã `Done` (**Gate 1**).
- `Dev in progress` (`15`) $\rightarrow$ `Ready for test` (`10`) (**`Submit for Review`**): Chuyển Task sang chờ kiểm thử sau khi BE/FE báo cáo hoàn tất (**Pre-Transition Gate 2**: Cả `[BE]`, `[FE]` và mọi `[Bug]` dưới Task cha phải `Done` `12`).
- `Ready for test` (`10`) $\rightarrow$ `Testing` (`9`) (**`Start Testing`**): Chuyển Task sang đang kiểm thử khi Tester Vinh bắt đầu chạy Test Cases.
- `Testing` (`9`) $\rightarrow$ `Rework` (`14`) (**`Fail & Request Rework`**): Khi Tester Vinh tạo Sub-task `[Bug]` (`0 SP`), mở lại Sub-task `[BE]`/`[FE]` và bình luận yêu cầu kéo Task về `Rework`.
- `Rework` (`14`) $\rightarrow$ `Dev in progress` (`15`) (**`Fix Bug / Resume Dev`**): Khi BE/FE bắt đầu vá lỗi `[Bug]`.
- `Testing` (`9`) $\rightarrow$ `Done` (`12`) (**`Pass & Complete`**): **Chốt chặn Gatekeeper (Pre-Transition Gate 1)** — Hệ thống kiểm tra 100% Sub-tasks (`[BA]`, `[BE]`, `[FE]`, `[Tester]`, `[Bug]`) phải ở trạng thái `Done` (`12`) trước khi đóng `Task` (nếu còn Sub-task mở sẽ trả lỗi `422 mcp:PrerequisiteChildrenIncomplete`).
- `Done` (`12`) $\rightarrow$ `Rework` (`14`) (**`Reopen Task`**): Mở lại Task lớn khi phát hiện lỗi UAT / E2E.

### 3.3. Tầng 3 — `Sub-task` (`type_id=8`)
- `READY` (`1`) $\rightarrow$ `In progress` (`7`) $\rightarrow$ `Done` (`12`), hoặc `Done` (`12`) $\rightarrow$ `In progress` (`7`) (`Reopen Task`). Không được nhảy cóc `READY -> Done` hoặc `Done -> READY`.

---

## 4. Kịch Bản Thao Tác Chuẩn (SOPs) Với `openproject_mcp`

### SOP 1: Tạo Mới Cấu Trúc WBS 3 Tầng Cho Một Màn Hình (`1 Task + 4 Sub-tasks`)
> **Quy tắc bất biến:** Tuyệt đối **KHÔNG** gán `estimated_hours` trực tiếp lên `Epic` hoặc `Task` cha (MCP Server tự động strip `estimated_hours > 0` trên Epic/Task) để OpenProject tự động cộng dồn (`derivedEstimatedHours`) từ 4 `Sub-task` con theo đúng Quy tắc 100% WBS. Tham số `story_points` chấp nhận cả số thực (`1.5`, `3.5`) và tự động làm tròn thông minh (`1.5 -> 2`, `3.5 -> 3`) để tổng 4 Sub-tasks luôn bằng `10 SP`.

```json
// Gọi tool: op_bulk_create_work_packages
{
  "project_id": 3,
  "items": [
    {
      "ref_key": "TASK-POS",
      "parent_id": 4,
      "type_id": "Task",
      "subject": "[Màn hình] Thu ngân POS & Thanh toán hóa đơn",
      "assignee_id": "PM",
      "status_id": "READY",
      "story_points": 10,
      "start_date": "2026-10-16",
      "due_date": "2026-10-25",
      "schedule_manually": true
    },
    {
      "ref_key": "SUB-BA",
      "parent_ref": "TASK-POS",
      "type_id": "Sub-task",
      "subject": "[BA] Đặc tả nghiệp vụ Thu ngân POS & Hóa đơn",
      "assignee_id": "BA",
      "status_id": "READY",
      "story_points": 3.0,
      "estimated_hours": 12,
      "start_date": "2026-10-16",
      "due_date": "2026-10-18",
      "schedule_manually": true
    },
    {
      "ref_key": "SUB-BE",
      "parent_ref": "TASK-POS",
      "type_id": "Sub-task",
      "subject": "[BE] Lập trình API Thanh toán POS & Hóa đơn",
      "assignee_id": "BE",
      "status_id": "READY",
      "story_points": 2.0,
      "estimated_hours": 8,
      "start_date": "2026-10-19",
      "due_date": "2026-10-21",
      "schedule_manually": true
    },
    {
      "ref_key": "SUB-FE",
      "parent_ref": "TASK-POS",
      "type_id": "Sub-task",
      "subject": "[FE] Lập trình Giao diện POS & In hóa đơn",
      "assignee_id": "FE",
      "status_id": "READY",
      "story_points": 1.5,
      "estimated_hours": 6,
      "start_date": "2026-10-21",
      "due_date": "2026-10-23",
      "schedule_manually": true
    },
    {
      "ref_key": "SUB-TEST",
      "parent_ref": "TASK-POS",
      "type_id": "Sub-task",
      "subject": "[Tester] Kiểm thử tích hợp POS & Đối soát doanh thu",
      "assignee_id": "TESTER",
      "status_id": "READY",
      "story_points": 3.5,
      "estimated_hours": 14,
      "start_date": "2026-10-24",
      "due_date": "2026-10-25",
      "schedule_manually": true
    }
  ]
}
```
Sau khi tạo xong, gọi `op_create_dependency_chain(work_package_ids=[...])` để nối dây phụ thuộc `follows` (`Finish-to-Start`) tuần tự `[BA] -> [BE] -> [FE] -> [Tester]`.

### SOP 2: Nghiệm Thu & Đóng `Task` (`Pass & Complete`) Hoặc `Epic` (`Approve & Close`)
1. Gọi `op_list_subtasks(parent_id=<task_id>)` để kiểm tra toàn bộ `Sub-task` con.
2. Nếu còn bất kỳ `Sub-task` nào chưa ở trạng thái `Done` (`12`), **không đóng `Task`** mà nhắc nhở thành viên phụ trách hoàn tất trước.
3. Khi 100% `Sub-task` con đã `Done`, gọi `op_update_work_package` kèm **Mẫu Comment Bàn Giao 3 Phần**:
   ```json
   // Tool: op_update_work_package
   {
     "work_package_id": 23,
     "status_id": "Done",
     "percentage_done": 100,
     "comment": "✅ [PM Gatekeeper — Pass & Complete]\n- [Deliverables / Artifacts]: Đã nghiệm thu toàn bộ sản phẩm bàn giao của màn hình (SRS, API, UI, Test Report).\n- [Pre-Transition DoD Check]: 100% Sub-tasks ([BA], [BE], [FE], [Tester]) và [Bug] đều đã Done (0 open bugs).\n- [Next Action / Handoff To]: Đóng Task sang Done (100%) và ghi nhận điểm Earned Value (EV) cho cả 5 thành viên."
   }
   ```

### SOP 3: Kiểm Toán Lịch Trình Gantt, Đường Găng CPM, EVM & Bảng Điểm KPI ($HS$)
- **Kiểm toán WBS 100% Rule:** Gọi `op_generate_wbs_tree(project_id=3)` để phát hiện sai lệch giờ ước lượng (`wbs100PercentRuleDiscrepancies`).
- **Kiểm toán Đường găng CPM & Xung đột ngày:** Gọi `op_analyze_gantt_critical_path(project_id=3)` để kiểm tra `criticalPathIds` (`Total Float = 0`) và `scheduleDateConflicts`.
- **Phân tích Giá trị Thu được (EVM):** Gọi `op_analyze_project_evm(project_id=3)` để lấy `BAC, PV, EV, AC, CPI, SPI, EAC, ETC, VAC, TCPI`.
- **Chấm điểm KPI & Xét thưởng ($HS$):** Gọi `op_analyze_member_kpi_scorecard(project_id=3)` để tính $\mathbf{HS = 0.40 \times HS_{KL} + 0.30 \times HS_{TĐ} + 0.30 \times HS_{CL}}$ và phân hạng lương thưởng (`A+`, `A`, `B`, `C`, `D`) cho cả 5 thành viên.

---

## 5. Checklist Kiểm Tra Trước Chuyển Trạng Thái (Pre-Transition DoR/DoD) & Mẫu Comment Bàn Giao 3 Phần

### 5.1. Pre-Transition Gatekeeper Checklist
- [ ] **Trước khi duyệt `BA Review -> Dev in progress` (`Approve & Start Dev`):** `Sub-task` `[BA]` dưới Task cha đã `Done` (`12`) và có đủ Use Case, Business Rules, Wireframe.
- [ ] **Trước khi đóng `Testing -> Done` (`Pass & Complete`):** Gọi `op_list_subtasks(parent_id=...)` xác nhận 100% `Sub-task` (`[BA]`, `[BE]`, `[FE]`, `[Tester]`, `[Bug]`) đều ở trạng thái `Done` (`12`).
- [ ] **Trước khi đóng `Epic` `In review -> Done` (`Approve & Close`):** 100% `Task` con thuộc Epic đã ở trạng thái `Done` (`12`).

### 5.2. Hợp Đồng Comment Bàn Giao 3 Phần Chuẩn (`3-Part Handoff Comment Contract`)
Mọi thao tác chuyển trạng thái trên `Epic` hoặc `Task` của PM phải đính kèm `comment` theo cấu trúc 3 phần:
```markdown
- [Deliverables / Artifacts]: <Tóm tắt tài liệu / tính năng / báo cáo đã thẩm định>
- [Pre-Transition DoD Check]: <Xác nhận trạng thái các Sub-task / Task con liên quan>
- [Next Action / Handoff To]: <Chỉ định rõ thành viên tiếp nhận (@Trung BA / @Hiếu BE / @Thành FE / @Vinh Tester) và hành động tiếp theo>
```
