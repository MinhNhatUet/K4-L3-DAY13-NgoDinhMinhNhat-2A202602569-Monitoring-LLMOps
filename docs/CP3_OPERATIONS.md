# CP3: điều tra theo Metrics → Logs → Traces

CP4 là checkpoint cuối, chưa thực hiện trong lượt công việc này. CP3 chính thức
cần `config/challenge.json` gốc của Lab Coach cho đúng lớp. Không tự tạo, sửa,
force-add, commit hoặc gửi file này ra ngoài. Hiện repo chưa có file đó.

API cần chạy với `.env` và kết nối được Langfuse; `/health` phải ok và tất cả
incident flag tắt. Khởi động từ thư mục gốc nếu API chưa chạy:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --env-file .env
```

## Practice đã thực hiện

```powershell
.\.venv\Scripts\python.exe scripts/investigate_incident.py --scenario tool_fail
```

Script đo baseline 10 request, inject bằng script lab, chạy 10 request sự cố với
concurrency 5, tự tắt scenario trong `finally`, chạy 10 request hậu kiểm. Sau đó
đợi exporter và đọc Cloud observations API v2. Thứ tự điều tra: tổng hợp metric
của từng pha → chọn log bất thường → tìm trace cùng correlation ID → so parent,
status và duration các span. Không xóa log lỗi. Phần count/percentile dùng chung
hàm tổng hợp với dashboard.

Evidence: `submission/evidence/cp3-practice-tool_fail.json`, ảnh 12/13/14 có tiền
tố `practice-`. Script từ chối ghi đè evidence đã tồn tại. Nếu Cloud tạm timeout,
chạy lại **chỉ bước đọc trace**, không inject thêm:

```powershell
.\.venv\Scripts\python.exe scripts/investigate_incident.py --scenario tool_fail --verify-only
.\.venv-dashboard\Scripts\python.exe scripts/render_incident_evidence.py submission/evidence/cp3-practice-tool_fail.json
```

## Khi nhận challenge chính thức

Lưu file nguyên bản vào `config/challenge.json`, kiểm tra đúng lớp theo thông báo
Lab Coach. Script sử dụng loader có sẵn, không sửa file, không export seed/query
gốc vào report. Chạy:

```powershell
.\.venv\Scripts\python.exe scripts/investigate_incident.py --challenge
.\.venv-dashboard\Scripts\python.exe scripts/render_incident_evidence.py submission/evidence/cp3-challenge.json
```

Script gọi đúng `inject_incident.py` và `load_test.py --challenge --concurrency 5`.
Cùng query/seed được dùng cho baseline, incident, hậu kiểm. Sau khi thu metric,
log, trace, cần viết root cause/fix/prevention dựa trên span thực tế trong mục 7
REPORT, không suy đoán từ tên scenario. Ảnh chính thức không có tiền tố practice.

Nếu Cloud chưa trả đủ observation, dùng `--challenge --verify-only` sau vài giây.
Ảnh render API luôn ghi rõ nguồn; chụp thêm Langfuse UI nếu rubric yêu cầu.
Practice không thay thế challenge ID và evidence chính thức.
