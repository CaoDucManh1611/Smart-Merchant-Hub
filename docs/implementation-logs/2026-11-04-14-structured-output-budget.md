# Mục 5: structured output và budget chung cho LLM

Ngày: 2026-11-04. Nhánh kiểm tra: `codex/rag-rfm-all-updates-20261104`.
Phạm vi worker: chỉ `backend/app/rag/llm_caller.py`, module mới `backend/app/rag/turn_budget.py`, `backend/tests/test_llm_turn_budget.py`, và log này.
Không sửa config, api_key_pool, graph, auto_reply, model/key; không commit/push/restart hoặc gọi provider live. Các thay đổi đồng thời ở file khác thuộc main/worker khác.

## Hợp đồng để main tích hợp

```python
from app.rag.turn_budget import turn_budget, remaining_seconds, current_budget, TurnBudgetExceeded
from app.rag.llm_caller import call_llm, call_structured, StructuredOutputError, StructuredOutputUnsupported

turn_budget(timeout_seconds=30, max_calls=4, max_attempts=6, max_provider_switches=1)
remaining_seconds(default: float) -> float
call_structured(messages, schema, schema_name="structured_output", model=None) -> dict

with turn_budget() as budget:
    plan = call_structured(messages, planner_schema, schema_name="turn_plan", model=call_llm)
    retrieval_timeout = remaining_seconds(8.0)
    trace = budget.snapshot()
```

- `turn_budget` là sync contextmanager dùng được bên trong async function. Yield `TurnBudget` có `snapshot()`, `remaining_seconds(default)`, `record_usage(provider, model, usage)`.
- Giữ nguyên signature/return các API cũ: `call_llm(messages) -> str`, vision, Gemini `include_usage`, dedicated turn/chunking và các async generator stream. Decorator dùng `functools.wraps`.
- `model=None` hoặc **identity của call_llm gốc**: gọi structured transport native theo provider/model cấu hình. `model=callable_khác`: gọi đúng `model(messages)`, parse + validate output độc lập provider. Main có thể truyền `graph.call_llm` đang monkeypatch bằng fake. Identity gốc được lưu riêng, không nhầm Mock sau monkeypatch module.
- Callable giả không có SDK transport nên tăng logical calls, không tăng physical attempts hoặc tạo token usage giả. Callable wrapper thực sự gọi lại llm_caller vẫn bị charge physical attempts, không đếm đôi logical call; wrapper đó là đường injection, không tự đổi một plain call thành native structured transport.
- `model=str` là override primary model do caller chỉ định trên provider đang cấu hình; không ghi settings, không thay fallback model/key.
- `schema`: JSON Schema dict (dùng `jsonschema` đã cài) hoặc lớp Pydantic v2 (validate strict, không cần jsonschema cho đường này). Dict schema thiếu dependency thì fail trước network; không tự cài package. JSON Schema dùng local refs; external refs bị chặn để validator không tải tài nguyên mạng.

## Budget và key/circuit

- Defaults đề xuất ban đầu: **30 giây / 4 logical calls / 6 physical attempts / 1 provider switch**, đúng hợp đồng main. Đây là guardrail đã test fake, chưa phải ngưỡng chất lượng/latency được benchmark production.
- Một public call được charge một lần qua các wrapper lồng nhau. Planner/composer/repair do main gọi riêng vẫn tốn từng logical call; không có repair loop ngầm trong call_structured.
- Physical attempt được reserve bên trong callback của key rotation, sau provider slot/key/circuit checks, trước thao tác SDK. Tất cả key rotations và model/provider fallback cùng dùng counters/deadline. Không reset theo key hoặc model. Provider switch chỉ tính khi dispatch attempt đổi provider, không tính model Gemini kế tiếp, circuit skip, hoặc route chưa dispatch. Gemini chunking vẫn tính là provider Gemini.
- Nested turn_budget có deadline min với parent và charge cả child/parent dưới lock chung; không nạp lại ngân sách. ContextVar tách root turn và truyền qua asyncio tasks / `asyncio.to_thread`. ThreadPoolExecutor tự tạo cần caller truyền copy_context; không khẳng định context tự đi qua process/thread tùy ý.
- Provider slot timeout là `min(10s, remaining)`; timeout SDK tính lại sau slot wait là `min(30s, remaining)`. OpenAI-compatible dùng giây; Google HttpOptions dùng milliseconds. Budgeted OpenAI/Groq tắt SDK retry; budgeted Gemini dùng `retry_options.attempts=1`. Structured Gemini cũng tắt SDK retry khi caller chưa wrap budget. Plain no-budget Gemini/OpenAI giữ call shape/retry cũ.
- `TurnBudgetExceeded(RuntimeError)` có `.reason`: `deadline`, `max_calls`, `max_attempts`, `max_provider_switches`. Lỗi local này không retry/fallback, không cooldown key hoặc ghi model/provider failure. Lỗi provider thực vẫn đi qua key cooldown và circuit logic cũ. Attempt bị budget chặn trước dispatch không tăng counters.
- Nonretryable request/schema/validation errors không chạy sang provider khác. Hết routes giữ exception provider cuối theo logic routing. `StructuredOutputError(ValueError)` báo schema/input/output không hợp lệ, JSON không phải object, nonfinite values, refusal/empty output. `StructuredOutputUnsupported` kế thừa lỗi trên khi không còn native schema route được hỗ trợ ở đây. SDK/provider exceptions vẫn có thể propagate.

## Native structured output và xác minh capability

- Groq: allowlist bảo thủ chỉ hai model đã đối chiếu tài liệu `openai/gpt-oss-20b` và `openai/gpt-oss-120b`. Request `response_format.type=json_schema`, `json_schema={name, strict: true, schema}`. Không đổi sang model khác để lấy capability. Groq model ngoài allowlist được bỏ qua sang các Gemini fallback đã cấu hình, hoặc raise Unsupported khi không có route; không hạ xuống prompt-only JSON.
- Schema caller phải phù hợp strict provider: ví dụ object đóng `additionalProperties: false`, khai báo đầy đủ required; field optional dùng nullable khi provider yêu cầu. Không tự sửa/mở rộng schema gốc. Schema provider không hỗ trợ sẽ fail theo response SDK, không khẳng định mọi JSON Schema keyword đều được provider enforce.
- Gemini primary/fallback: giữ system constraints và cùng schema bằng `GenerateContentConfig(response_mime_type="application/json", response_json_schema=schema)`. Không chỉ nhắc JSON trong prompt, không đánh rơi schema qua các fallback model.
- OpenAI provider: gửi native `json_schema` qua API chat của SDK; việc model cụ thể chấp nhận request còn phụ thuộc provider. Không chạy live hoặc tuyên bố mọi OpenAI model đều hỗ trợ.
- Server luôn validate lại: required/type/enum/nested constraints do JSON Schema hoặc Pydantic kiểm tra. Không strip code fences hoặc trích một phần JSON để cứu output. Output sai không tự sinh call sửa lỗi. Semantic/tool permissions/source/citation correctness vẫn do main kiểm tra.

Nguồn chính thức đã browse ngày 2026-11-04:

- [Groq Structured Outputs](https://console.groq.com/docs/structured-outputs): native JSON Schema, strict mode, hai GPT-OSS IDs và yêu cầu strict schema.
- [Google GenAI SDK README](https://github.com/googleapis/python-genai/blob/main/README.md): generate_content với response_mime_type + response_json_schema.
- [Google structured output guide](https://ai.google.dev/gemini-api/docs/structured-output): subset JSON Schema và yêu cầu validate phía application. Trang hiện redirect sang tài liệu AI Studio; transport generate_content được đối chiếu thêm trong SDK/source cài local.

Runtime local đã inspect: Python 3.12; `openai 3.3.0`, `google-genai 2.19.0`, `pydantic 2.13.4`, `jsonschema 4.26.0`, `pytest 9.0.2`. Inspect `HttpOptions`, `HttpRetryOptions.attempts` (bao gồm request đầu), `GenerateContentConfig.response_json_schema`, source `_api_client.py` chuyển timeout ms sang giây và retry stop_after_attempt. Requirements repo ghi `google-genai>=1.0,<2`; bản local **khác ràng buộc đó**. Chưa xác minh container/runtime deployment hoặc mọi bản 1.x; cần xác nhận runtime thực có các HttpOptions/schema fields trước bật live. Không sửa dependency/config theo phạm vi giao.

## Trace thực tế, không suy từ config

`budget.snapshot()` trả:

- `calls/max_calls`, `attempts/max_attempts`, `provider_switches/max_provider_switches`, `last_provider`.
- `deadline` và `started_at` trong attempt là monotonic timestamps của process; không phải thời gian UTC.
- `remaining_seconds`, `elapsed_seconds`, `attempt_records` là bản sao để caller serialize/persist.
- Mỗi attempt có provider/model thực sự dispatch, `latency_ms`, `outcome` pending/success/error, `error_type`, `status_code` khi SDK cho biết, `usage`.
- `usage=None` nếu provider không trả; khi có usage: `prompt_tokens`, `completion_tokens`, `total_tokens`, `thoughts_tokens`, từng trường chưa có giữ `None`. Zero chỉ xuất hiện nếu provider thực sự báo zero. Không suy tokens từ configured model hoặc biến unknown thành zero. Lỗi 429/timeout vẫn có record latency/error, usage thường None.
- Không chứa API key, messages, response body hay error text. Trace chưa được ghi DB/file tự động; main quyết định chỗ persist/summarize. Chưa có chi phí tiền, p50/p95 hoặc benchmark live; không cộng token unknown như thể đã biết tổng cost.

## Streaming và giới hạn deadline

- Stream cả ba provider cũng có logical/attempt/switch budget, SDK timeout clamp, check deadline giữa chunk, attempt latency/error, đóng SDK response khi dừng và capture usage nếu chunk thực trả. Không bật thêm request tùy chọn đòi usage, nên stream thường usage=None.
- Giữ quy tắc không replay/fallback sau text đầu tiên. Decorator reset ContextVar trước mỗi yield, tránh làm mất logical count của call do consumer gọi trong khi stream tạm dừng.
- SDK streaming hiện là sync iteration trong async generator: không hard-cancel được blocking network read bằng ContextVar. HTTPX timeout theo các pha I/O cũng không phải hard wall-clock cancellation toàn request. Budget chặn dispatch tiếp và loại late success/chunk sau khi control trở về; **không chứng minh request luôn kết thúc trong đúng 30 giây**. Muốn hard wall deadline cần async transport/cancellation ở lớp integration khác.
- Physical attempts là số lần callback được reserve trước SDK operation, không phải đo packet trên wire. Client construction/SDK-local rejection hoặc Gemini empty-history no-op có thể bị đếm bảo thủ; SDK internal retries đã tắt trong budget để không nhân request. Stream creation trước iteration không tốn call; iteration mới charge.

## Kiểm thử offline

Chạy từ `backend` (không conftest DB, không pytest cache/bytecode):

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -B -m pytest --noconftest -p no:cacheprovider -o addopts= tests/test_llm_turn_budget.py tests/test_llm_key_rotation.py tests/test_llm_provider_fallback.py tests/test_gemini_sdk.py tests/test_vision_llm.py tests/test_api_key_pool.py -q
```

Kết quả sau thay đổi: **75 passed**. Bao phủ defaults/reset/nesting/context isolation/to_thread, logical de-duplication, cap xuyên key+fallback, switch cap, deadline trong slot wait và sau late response, timeout SDK, actual model/usage/latency/error records, native schema payload Groq/Gemini fallback, injectable callable/identity/legacy call shape, invalid schema/output/no repair, circuit skip, streaming limit/close/usage/no partial replay. Fake clock không sleep. SDK fake; test mới chặn socket connect ngoại trừ wakeup socketpair nội bộ của Windows asyncio. Không gọi LLM/DB thật.

Lần đầu có 3 lỗi test harness vì guard socket chặn cả socketpair của Windows asyncio; đã thu hẹp ngoại lệ đúng `_fallback_socketpair`, sau đó toàn bộ test pass. `git diff --check` cho file worker sạch. Không chạy full backend suite vì phạm vi task và bootstrap DB của conftest không phù hợp kiểm thử offline này.
