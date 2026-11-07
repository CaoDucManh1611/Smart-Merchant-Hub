# Performance và reliability

Đo 11 request GET /health tuần tự qua urllib trên host. Median 573.24 ms; max 1533.99 ms. Raw sample trong live-readonly.json. Có thể chịu ảnh hưởng client/proxy và cold-start; chưa tách server timing. Không áp ngưỡng PASS khi chưa có SLA.

Không có authenticated business API baseline, throughput, browser LCP/INP, DB slow-query profile, leak hoặc load test. Các mục này NOT RUN. Không thay health timing bằng tốc độ chatbot. Timeout/circuit-breaker/retry được kiểm bằng unit/fixture trong backend suite; môi trường mất DB và recovery trên production không được thử.

Ngưỡng gợi ý để chủ sở hữu xem xét là tỷ lệ lỗi 0 trong smoke; latency p95 phải chọn theo loại nghiệp vụ và hạ tầng staging trước khi áp gate. Không coi đây là SLA đã được duyệt.
