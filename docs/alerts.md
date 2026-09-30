# Alerts và runbook

Các rule trong `config/alert_rules.yaml` là contract lab, chưa có scheduler hoặc
Slack webhook gửi thông báo tự động. Đánh giá mỗi 30 giây trên cửa sổ trượt 5 phút;
điều kiện phải giữ liên tục đủ `duration`, reset khi hết vi phạm. Dưới 10 mẫu là
insufficient data, không coi là hệ thống khỏe. Timestamp dùng UTC. Không đưa PII
hoặc key vào alert. Kênh dự kiến: `#k4-l3b-alerts`.

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `HighLatencyP95`; severity: `warning`; duration: `5m`.
- Kênh: Slack `#k4-l3b-alerts`; owner: `student-2A202602569`.
- SLI/SLO: request thành công trong 3000ms, mục tiêu 99.5% / 28 ngày.
- Điều kiện: ít nhất 10 `response_sent` trong 5 phút và P95 `latency_ms > 3000`.
- Ảnh hưởng: người dùng chờ lâu, tiêu hao budget dù HTTP vẫn 200.

1. **Metrics:** xem Latency (P50/P95/P99, TTFT), xác định mốc UTC bắt đầu tăng;
   đối chiếu Traffic để phân biệt tải tăng với regression.
2. **Logs:** lọc `response_sent` cùng khoảng UTC và `latency_ms > 3000`, lấy
   `correlation_id`, model, feature; không sao chép nội dung người dùng.
3. **Traces:** tìm correlation ID trên Langfuse; mở `lab-agent-run`, so sánh thời
   gian `retrieval` và `generation`, kiểm tra prompt name/label/version.

Mitigation: nếu evidence cho thấy prompt candidate gây regression, dời `production`
về baseline rồi restart API để xóa cache. Nếu retrieval chậm, khôi phục dependency
hoặc cấu hình trước đó, giảm tải. Chỉ tắt `rag_slow` nếu xác nhận practice đang bật.
Hậu kiểm: P95 <= 3000ms trong 5 phút có đủ mẫu; lưu request/trace ID sau xử lý.

## Alert 2

- Tên: `HighRequestErrorRate`; severity: `critical`; duration: `3m`.
- Kênh: Slack `#k4-l3b-alerts`; owner: `student-2A202602569`.
- SLI/SLO: thành công và nhanh; lỗi là bad event, chỉ tính một lần mỗi request.
- Điều kiện: ít nhất 10 `request_received` trong 5 phút và
  `100 * count(request_failed) / count(request_received) > 2` cùng cửa sổ.
- Ảnh hưởng: request không có câu trả lời, error budget giảm nhanh.

1. **Metrics:** xem Errors và Traffic, xác nhận mẫu số, error types và mốc UTC
   lỗi tăng; phân biệt không có traffic với 0% lỗi.
2. **Logs:** chọn `request_failed`, nhóm `error_type`, lấy correlation ID của
   request đại diện cùng `request_received` tương ứng.
3. **Traces:** tìm ID đó, xem observation ERROR và span dừng sớm; đối chiếu
   retrieval/generation, prompt version với request thành công gần nhất.

Mitigation: khôi phục dependency/cấu hình bị lỗi theo evidence; rollback prompt
chỉ khi liên quan tới version mới. Nếu xác nhận practice `tool_fail` đang bật,
tắt scenario. Tránh retry không giới hạn làm tăng tải. Hậu kiểm: error rate <= 2%
trong 5 phút có đủ mẫu và request mới trả 200; lưu trace/log sau xử lý.

## Alert 3

- Tên: `LowRetrievalSuccess`; severity: `warning`; duration: `5m`.
- Kênh: Slack `#k4-l3b-alerts`; owner: `student-2A202602569`.
- SLI: retrieval success >= 90%; thành công kỹ thuật không chứng minh context phù hợp.
- Điều kiện: ít nhất 10 event có boolean `tool_success` trong 5 phút và
  `true / (true + false) * 100 < 90`. Dùng cả `response_sent` và `request_failed`,
  bỏ event thiếu/null `tool_success`.
- Ảnh hưởng: RAG không truy xuất được context hoặc request thất bại.

1. **Metrics:** xem retrieval success trong Errors, đối chiếu Quality và error
   rate; xác định khoảng UTC và số mẫu bị ảnh hưởng.
2. **Logs:** lấy event `tool_success == false` cùng khoảng UTC, chọn correlation
   ID và kiểm tra `tool_name`, `error_type`.
3. **Traces:** mở span `retrieval` cùng ID, xem duration/status; kiểm tra generation
   có được gọi không, so với trace thành công trong cùng project.

Mitigation: khôi phục kết nối/index vector store hoặc cấu hình retrieval đã biết
tốt; chỉ tắt scenario khi xác nhận practice gây lỗi. Đánh dấu câu trả lời fallback,
không coi quality proxy là đánh giá con người. Hậu kiểm: retrieval success >= 90%
trong 5 phút có đủ mẫu, error rate ổn định, quality >= 0.75.
