# Chạy và kiểm chứng CP2

Chạy từ thư mục gốc. API dùng `.venv`, dashboard dùng `.venv-dashboard` riêng:

```powershell
uv venv --python .venv/Scripts/python.exe .venv-dashboard
uv pip install --python .venv-dashboard/Scripts/python.exe -r requirements-dashboard.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --env-file .env
# Terminal khác
.\.venv-dashboard\Scripts\python.exe scripts/dashboard.py --serve
```

Dashboard: http://127.0.0.1:8501, cập nhật 30 giây, cửa sổ 60 phút UTC.
Xuất biểu đồ thật từ log (không cần Browser):

```powershell
.\.venv-dashboard\Scripts\python.exe scripts/dashboard.py
```

Biểu đồ nằm ở `submission/evidence/11-dashboard-overview.png`. Sáu panel lấy
title/unit/threshold từ YAML. Latency và quality không có mẫu hiển thị gap;
traffic không có request là 0; tỉ lệ không có mẫu số là N/A. Error rate chia
`request_failed` cho `request_received`; retrieval success dùng mọi event có
boolean `tool_success`. Cost vẽ tổng theo phút và tích lũy trong cửa sổ; Tokens
vẽ input/output tích lũy. Ngưỡng cost dashboard 2.5 USD trong 60 phút khác
guardrail chi phí ngày của SLO. Không suy ra chi phí ngày từ cửa sổ 60 phút.

## Prompt lifecycle tự động

`scripts/cp2_workflow.py` dùng key từ `.env`, không in key. **Script thay đổi
prompt/labels thật trong project được cấu hình**: tạo baseline/candidate nếu
chưa tồn tại, chạy baseline → candidate → promote production → rollback
production, mỗi giai đoạn khởi động API mới và chờ exporter trước khi dừng.
Cuối cùng chạy 11 batch cách nhau một phút (110 request, khoảng 10 phút).
Script khôi phục `.env` label `production` và production về baseline khi kết thúc.
Không chạy khi port 8000 đang được sử dụng. Dừng API của bạn trước khi chạy:

```powershell
.\.venv\Scripts\python.exe scripts/cp2_workflow.py
```

Output lifecycle/correlation IDs: `submission/evidence/09-10-prompt-lifecycle.json`.
API output debug nằm ở `data/cp2-api.log`, được gitignore. Script không bật practice
incident; nếu đã practice, chuyển log ra ngoài repo trước khi chạy lại.
Sau workflow, khởi động API theo lệnh phía trên để tiếp tục sử dụng.

## Tracing và giới hạn bằng chứng

Root `lab-agent-run` có child `retrieval` (retriever) và `generation` (generation).
Không capture raw input/output ở cả ba observation; generation ghi model, token,
cost mô phỏng và liên kết managed prompt object. Trace metadata chứa correlation ID.
Tham khảo API chính thức: [prompt link](https://langfuse.com/docs/prompt-management/features/link-to-traces)
và [usage/cost](https://langfuse.com/docs/observability/features/token-and-cost-tracking).

`tracing_enabled: true` chỉ xác nhận SDK và key có mặt, không xác nhận Cloud đã
nhận trace. Kiểm tra trace IDs trên Cloud, parent observation và promptVersion.
Sau khi workload kết thúc, kiểm tra và xuất ảnh evidence:

```powershell
.\.venv\Scripts\python.exe scripts/verify_cp2_cloud.py
.\.venv-dashboard\Scripts\python.exe scripts/render_cp2_evidence.py
```

Verifier dùng API v2 vì endpoint `/api/public/traces` cũ trả 410 trong project này.
Script đối chiếu toàn bộ request trong manifest với log và trace, kiểm tra prompt
version/label theo từng bước và bỏ metadata chứa key khỏi file evidence.
Ảnh export từ dữ liệu API không được mô tả là screenshot Langfuse UI. Nếu bài chấm
yêu cầu UI, mở project và chụp trace list/waterfall/metadata/prompt versions.

Alerts là cấu hình và runbook; chưa triển khai scheduler/webhook Slack.
Tests chạy không nạp `.env` để không tạo trace test lẫn vào evidence.
