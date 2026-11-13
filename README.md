# Day 06 · Data Ingestion Engineering

## Bài làm — Hoàng Lam Minh (2A202603566)

Corpus: 2 báo cáo World Bank *Taking Stock* về kinh tế Việt Nam (kỳ 12/2017 và 06/2018), giấy phép CC BY 3.0 IGO, 98 trang nội dung. Embedding local `paraphrase-multilingual-MiniLM-L12-v2` (384 chiều), vector store Chroma (cosine). Báo cáo: [report/individual/2A202603566_HoangLamMinh.md](report/individual/2A202603566_HoangLamMinh.md).

**Ghi nguồn dữ liệu (CC BY 3.0 IGO):** World Bank. 2017. *Taking Stock, December 2017* (https://hdl.handle.net/10986/29032) và World Bank. 2018. *Taking Stock, June 2018* (https://hdl.handle.net/10986/29959). World Bank, Washington, DC. License: CC BY 3.0 IGO. PDF gốc được phân phối lại nguyên vẹn trong `data/raw/`. **Thay đổi:** text trích xuất trong `results/` (trace, bảng chấm) đã được chuẩn hóa (Unicode, bỏ header, số trang, nhãn biểu đồ) và cắt thành thẻ. Đây là sản phẩm của học viên, không phải bản chính thức của World Bank, và World Bank không xác nhận nội dung này.

### Setup (Windows PowerShell; macOS/Linux thay lệnh activate)

Cần Python 3.11–3.13. Không cần Docker hay API key. Lần đầu cần mạng để tải thư viện (torch khoảng 200MB) và model (khoảng 470MB).

```bash
cd starter
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt fonttools
# hoặc cài đúng phiên bản của lần chạy đã báo cáo:
# python -m pip install -r requirements-lock.txt
```

PDF đã có sẵn trong `data/raw/`. Nếu thiếu, tải lại theo `original_url` trong [data/manifest.json](data/manifest.json) và kiểm tra `sha256`.

### Chạy (từ thư mục `starter/`)

```bash
python -m src.run ingest            # đọc, chuẩn hóa, chunk A/B, embed, lưu Chroma (chạy lại không nhân đôi)
python -m src.run verify            # kiểm chứng evidence của benchmark có trên trang gold
python -m src.run evaluate          # top-3 cho A/B/C, ghi trace + metrics + experiment_log
python -m src.run audit             # tạo bảng chấm tay (không ghi đè bảng đã có nhãn)
python -m src.run summarize-audit   # tổng hợp nhãn chấm tay
python scripts/reingest_change_test.py   # kiểm tra xử lý tài liệu thay đổi (kho tạm)
```

Có thể ghi đè `EMBEDDING_MODEL` và `CHROMA_PATH` trong `starter/.env`. Nếu model lỗi, pipeline dừng và báo lỗi, không chuyển sang vector giả.

### Cấu trúc bài nộp

| Đường dẫn | Nội dung |
|---|---|
| `starter/src/` | Code pipeline (ingestion, chunking, embeddings, store, evaluation, run) |
| `data/manifest.json`, `data/page_inventory.csv`, `data/raw/` | Nguồn, giấy phép, quy tắc tính trang, số ký tự từng trang, PDF gốc |
| `benchmark/questions.json` | 20 câu (15 dev / 5 test), gold page và evidence, filter |
| `artifacts/experiment_log.csv` | Cấu hình, giả thuyết và Hit@1/Hit@3 của A/B/C |
| `results/` | ingest_report, metrics, traces top-3, per_question, audit_* (nhãn chấm tay), reingest_test |

---

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.
