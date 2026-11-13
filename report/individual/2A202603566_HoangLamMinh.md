# Báo cáo cá nhân — Day 6

Hoàng Lam Minh · 2A202603566 · L3A
Ngày chạy: 13/11/2026 · Chi phí: 0 USD (model chạy trên máy, không gọi API)

Mọi số liệu trong báo cáo được lấy từ các file kết quả mà pipeline sinh ra trong thư mục [results/](../../results/). Em có dùng AI hỗ trợ trong bài, chi tiết ở mục cuối.

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  Em chọn hai báo cáo *Taking Stock: An Update on Vietnam's Recent Economic Developments* của World Bank, kỳ tháng 12/2017 (chuyên đề chi tiêu công) và kỳ tháng 6/2018 (chuyên đề chi phí thương mại). Cả hai là PDF tiếng Anh, giấy phép CC BY 3.0 IGO theo trường `dc.rights` trên Open Knowledge Repository (handle 10986/29032 và 10986/29959). Em tải ngày 13/11/2026 và lưu mã SHA-256 của từng file trong [data/manifest.json](../../data/manifest.json).

  Hai file có tổng 124 trang (62 + 62). Em tính 98 trang nội dung: 51 trang của kỳ 2017 (tr.10–60) và 47 trang của kỳ 2018 (tr.9–12, 14–33, 36–58). Các trang bị loại gồm bìa, trang trống, trang tên sách, lời cảm ơn, danh mục viết tắt, mục lục và danh mục hình/bảng, trang chia phần chỉ có tiêu đề, và tài liệu tham khảo. Số ký tự từng trang sau chuẩn hóa nằm trong [data/page_inventory.csv](../../data/page_inventory.csv); tổng nội dung khoảng 260.873 ký tự.

- **Chuẩn hóa, lỗi và giới hạn:**
  Em đọc PDF bằng `pypdf 6.21.4` (có cài thêm `fonttools`), chuẩn hóa Unicode NFKC, đổi dấu nháy cong, gạch nối và bullet về ASCII, gộp khoảng trắng nhưng vẫn giữ xuống dòng. Bước làm sạch bỏ 97 dòng header lặp lại, 655 dòng chỉ có số trang và 583 dòng chỉ gồm số/ký hiệu (phần lớn là nhãn trục biểu đồ). Khi nối dòng, từ bị ngắt bằng gạch nối được ghép lại.

  Theo log [results/ingest_report.json](../../results/ingest_report.json), có 3 trang không trích được chữ (2017 tr.2, 2018 tr.2 và tr.34, đều nằm trong nhóm trang bị loại) và không có lỗi đọc. PDF là file số nên không cần OCR. Vẫn còn vài vấn đề em chưa xử lý được: chữ trong biểu đồ có lẫn chữ cái (ví dụ "Taxes Fee, charges…") vẫn lọt vào thẻ; trang nhiều cột đôi khi bị đọc sai thứ tự (thẻ pos02 của B kết thúc bằng một mảnh câu ở cột khác); một số tiêu đề bị sai hoa/thường ngay từ PDF ("gDP", "FDi").

- **Embedding model, vector store, metric, lệnh chạy và chi phí:**
  Model là `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` chạy local (revision `e8f8c211…`), 384 chiều, `max_seq_length` 128 token, vector chuẩn hóa L2. Query và document được mã hóa giống nhau, không thêm prefix. Phiên bản thư viện: `sentence-transformers 5.7.0`, `transformers 5.22.2`, `torch 2.15.0+cpu`.

  Máy em không có Docker nên em dùng Chroma 1.5.9 thay cho pgvector (GUIDE cho phép). Dữ liệu lưu bằng `PersistentClient` tại `starter/chroma_db`, gồm hai collection `day6_index_A` và `day6_index_B`, metric cosine, tìm kiếm HNSW (gần đúng), filter `where` nằm ngay trong truy vấn. Lệnh chạy là `python -m src.run ingest | verify | evaluate | audit | summarize-audit` (hướng dẫn trong [README](../../README.md)). Chi phí 0 USD. Lần ingest đầu mất 85,9 giây để tải model; tạo embedding và lưu mất 45,1 giây với A và 33,7 giây với B, chạy trên CPU.

- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**
  Mỗi thẻ có `document_id`, `source` (đường dẫn PDF), `page` (trang PDF), `char_start`/`char_end` (vị trí trong text đã chuẩn hóa của trang) và `content_hash`. Ngoài ra có hai trường dùng để lọc: `edition` (`"2017-12"` hoặc `"2018-06"`, lấy từ bìa) kèm `year`, và `section` (`overview`, `part1_recent_developments`, `part2_special_focus`, gán theo khoảng trang trong mục lục), kèm `section_title` và `language`.

  Em chọn `edition` vì hai kỳ báo cáo viết về cùng một nền kinh tế nên nhiều chỉ số xuất hiện ở cả hai với giá trị khác nhau. Ví dụ thâm hụt ngân sách 2017 là "khoảng 4%" trong kỳ 2017 nhưng là 4,5% trong kỳ 2018. Nếu người dùng nói rõ mình đang đọc kỳ nào thì lọc theo `edition` loại được số liệu sai kỳ. Bộ ba `source` + `page` + `char_start`/`char_end` giúp mở đúng trang PDF và tìm đúng đoạn; cả 45 bản ghi top-3 của tập test đều có text nằm thật trên trang được ghi.

  Metadata vẫn có hạn chế. Thứ nhất, `section` có trong mọi thẻ nhưng không câu hỏi nào dùng nó để lọc, nên em chưa có bằng chứng là nó hữu ích. Thứ hai, `section` gán theo khoảng trang nên khá thô: trang có cả phần cuối mục trước và tiêu đề mục sau chỉ nhận một giá trị. Thứ ba, thẻ không vượt qua ranh giới trang, nên đoạn văn nằm vắt hai trang bị tách thành hai thẻ. Cuối cùng, `edition` chỉ giúp được khi người dùng cho biết kỳ báo cáo; câu nào không nêu kỳ thì C chạy không lọc và cũng bị lẫn kỳ như B.

## Cấu hình và benchmark

- **A / B / C:**
  - A: cắt cố định 500 ký tự, chồng lấn 50 ký tự, cắt trong phạm vi từng trang, không lọc. Được 618 thẻ.
  - B: cắt theo đoạn văn. Ranh giới đoạn dựa vào số thứ tự đoạn ("1.22.", "12."), chú thích hình/bảng, và dòng ngắn kết thúc bằng dấu câu. Tiêu đề được ghép với đoạn ngay sau; đoạn dài hơn 600 ký tự được tách theo câu; các đoạn ngắn được gộp lại cho tới 600 ký tự. Không lọc. Được 606 thẻ.
  - C: dùng lại đúng thẻ và vector của B (cùng collection `day6_index_B`), chỉ thêm filter `where` khi câu hỏi có `filter`. B và C chỉ khác nhau ở bước lọc.

  A và B khác nhau ở cách cắt. Em chọn mức 600 ký tự cho B để kích thước thẻ gần với A và phần lớn thẻ không vượt giới hạn 128 token của model. Dù vậy vẫn còn 62 thẻ B và 39 thẻ A dài hơn 128 token. Phân bố độ dài (lấy từ [results/ingest_report.json](../../results/ingest_report.json), token đếm bằng tokenizer của model):

  | Index | Số thẻ | Ký tự: min / trung vị / TB / p90 / max | Tổng ký tự | Token: trung vị / TB / p90 / max | Tổng token | Thẻ > 128 token |
  |---|---|---|---|---|---|---|
  | A | 618 | 51 / 500 / 464 / 500 / 500 | 286.873 | 108 / 104 / 123 / 168 | 64.367 | 39 |
  | B (= C) | 606 | 40 / 464 / 430 / 576 / 600 | 260.365 | 100 / 96 / 129 / 207 | 58.115 | 62 |

  Tổng ký tự của A lớn hơn tổng nội dung vì có phần chồng lấn 50 ký tự giữa các cửa sổ. Tổng của B gần bằng tổng nội dung.

- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  Bộ câu hỏi có 20 câu, chia 15 dev / 5 test ([benchmark/questions.json](../../benchmark/questions.json)). Em chốt bộ câu và cách chia trước khi chạy truy xuất lần đầu. Có 6 câu hỏi trực tiếp, 5 câu diễn đạt lại, 5 câu có điều kiện/ngoại lệ và 4 câu kiểm tra filter: q14, q15 ở dev, q19, q20 ở test. Filter được coi là thông tin người dùng đưa vào trước khi tìm (ví dụ "tôi đang đọc kỳ 06/2018"), không lấy từ đáp án.

  Để kiểm chứng evidence, lệnh `verify` so từng `evidence_quote` với text đã chuẩn hóa của trang gold: tìm thấy 26/26 đoạn ([results/benchmark_verification.json](../../results/benchmark_verification.json)). Câu nào có bằng chứng ở nhiều trang (q01–q04, q09) thì em ghi đủ các trang. Vì câu filter cần cả hai kỳ, em chia theo câu chứ không chia theo tài liệu; do đó vẫn có câu dev và câu test thuộc cùng một chương (ví dụ phần tài khóa), đây là nguy cơ rò rỉ.

- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:**
  Chọn cách có Evidence Hit@3 trên dev cao nhất; nếu bằng nhau thì xét Hit@1 trên dev; nếu vẫn bằng thì chọn cách ít thẻ hơn hoặc nạp nhanh hơn. Tiêu chí này được viết sẵn trong code (`SELECTION_RULE`, file `starter/src/run.py`) trước lần chạy `evaluate` đầu tiên. Có một điểm cần nói rõ: repo không có commit nào trước lần chạy đó, nên lịch sử git không chứng minh được thứ tự thời gian.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 7/15 | 12/15 | 618 | embed + lưu 45,1 s; 20 truy vấn 0,13 s | 0 USD |
| A | test | 2/5 | 3/5 | 618 | | 0 USD |
| B | dev | 6/15 | 9/15 | 606 | embed + lưu 33,7 s; 20 truy vấn 0,07 s | 0 USD |
| B | test | 3/5 | 4/5 | 606 | | 0 USD |
| C | dev | 6/15 | 9/15 | 606 (= B) | dùng index B; 20 truy vấn 0,11 s | 0 USD |
| C | test | 4/5 | 4/5 | 606 (= B) | | 0 USD |

Embedding 20 câu hỏi mất 0,90 giây. Về thời gian ingest: A được embed trước B trong cùng lần chạy nên con số 45,1 giây có thể gồm cả phần khởi động model; A cũng nhiều token hơn (64.367 so với 58.115). Mỗi số chỉ đo một lần trên CPU, nên em chỉ xem đây là thứ tự độ lớn chứ không so sánh chính xác.

Em chạy ingest lại hai lần trên cùng dữ liệu: không thẻ nào phải embed lại, không có thẻ thừa, số thẻ trong kho giữ nguyên 618/606. Em cũng thử trường hợp tài liệu thay đổi trên một kho tạm ([results/reingest_test.json](../../results/reingest_test.json)): sửa một trang thì chỉ 1 thẻ được embed lại; bỏ một trang thì 8 thẻ cũ bị xóa; kho còn đúng 20 thẻ của phiên bản mới.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1,0 (10) | 15/15 | test 0/2 (dev 1/2) | 2 / 1 / 2 → 1,0 |
| B | 1,7 (10) | 15/15 | test 0/2 (dev 0/2) | 1 / 1 / 3 → 1,4 |
| C | 1,7 (10), dùng thẻ của B | 15/15 | test 2/2 (dev 2/2) | 1 / 0 / 4 → 1,6 |

A và B không dùng filter. Cột "filter tuân thủ" của hai cách này chỉ cho biết top-3 có tình cờ nằm trong đúng kỳ hay không.

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**
- Trace đầy đủ top-3 (câu hỏi, ID và text thẻ, score, metadata, nhãn hit) ở [results/traces/](../../results/traces/); bảng theo từng câu ở [results/per_question.csv](../../results/per_question.csv); bảng chỉ số ở [results/metrics.md](../../results/metrics.md).
- Coherence ([audit_coherence.csv](../../results/audit_coherence.csv)): 10 vị trí được chọn theo quy tắc cố định trước khi chấm. Sắp 98 trang nội dung theo (`document_id`, `page`), lấy mỗi trang thứ 10, tại ký tự giữa trang; chấm thẻ của A và thẻ của B chứa vị trí đó.
- Metadata ([audit_metadata.csv](../../results/audit_metadata.csv)): 5 câu test × top-3 × 3 cách = 45 bản ghi (32 thẻ khác nhau). Script kiểm tra đủ trường, text có nằm trên trang được ghi không, và `section` có khớp mục lục không. Sau đó từng thẻ được đối chiếu với đoạn text của trang tại vị trí `char_start`–`char_end`, có ghi chú riêng trong cột `notes`. Kết quả 45/45 đúng. Có vài điểm đáng chú ý: một thẻ chỉ là chú thích biểu đồ (A p41 c06); hai thẻ bắt đầu giữa câu vì đoạn văn vắt từ trang trước sang (kỳ 2018 p17); các thẻ kỳ 2017 trong top-3 của A và B ở q19, q20 có metadata đúng nhưng nằm ngoài phạm vi filter.
- Grounding ([audit_grounding.csv](../../results/audit_grounding.csv)): 5 câu test × 3 cách, chấm 0/1/2 kèm lý do.
- Bảng tổng hợp: [results/audit_summary.md](../../results/audit_summary.md).

## Phân tích và kết luận

- **So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:**

  *A–B (đổi cách cắt).* Trên dev, A tìm được bằng chứng nhiều hơn (Hit@3 12/15 so với 9/15); B chỉ thắng A ở một câu test (q16). Ban đầu em nghĩ B thua vì thẻ dài bị model cắt bớt khi vượt 128 token. Kiểm tra lại thì không phải: ở cả hai cách, câu nào cũng có ít nhất một thẻ chứa trọn bằng chứng, và bằng chứng luôn nằm trong 128 token đầu của thẻ đó. Lý do thật nằm ở xếp hạng. Khi B tách một đoạn dài thành thẻ chứa câu chủ đề và thẻ chứa con số, câu hỏi thường khớp nghĩa với thẻ câu chủ đề hơn. Ví dụ q08: thẻ B p054:c05 (mở đầu đoạn 2.40 về trợ cấp tiền mặt) đứng hạng 1, còn câu trả lời "An exception is contributory public pensions…" nằm ở thẻ c06 và chỉ đứng hạng 6. Cửa sổ chồng lấn của A thì hay gói được cả câu chủ đề lẫn con số trong cùng một thẻ.

  Đổi lại, thẻ của B dễ đọc hơn hẳn (coherence 1,7 so với 1,0). Cả 10 thẻ A trong mẫu đều bị cắt giữa câu hoặc giữa từ ở đầu hoặc cuối, ví dụ "ion.", "Taking a", hay "rising by just 1.7" mất đơn vị. Điều này cũng thể hiện ở grounding trên test: B 1,4, A 1,0.

  *B–C (chỉ thêm filter).* Trên 4 câu có filter, top-3 của C luôn nằm đúng kỳ (4/4), còn B không lần nào (0/4). Rõ nhất là q19 (thâm hụt 2017, người dùng đọc kỳ 2018-06): B xếp hạng 1 một thẻ kỳ 2017 ghi "around 4 percent", con số đúng 4,5% chỉ ở hạng 3, nên grounding chỉ được 1. C loại các thẻ kỳ 2017 và đưa đoạn 4,5% lên hạng 1, nên Hit@1 đúng và grounding được 2. Nhờ vậy Hit@1 trên test của C là 4/5, của B là 3/5. Filter không giải quyết được mọi câu: ở q15 (dev), bằng chứng của B và C vẫn nằm ngoài top-3 (với C ở hạng 39).

  *Ví dụ sai 1: q20* (test, filter 2018-06, gold `ts-2018-06` tr.31: "real GDP now projected to expand by 6.8 percent in 2018"). Cả ba cách đều sai. Top-3 của C đều thuộc đúng kỳ nhưng là các đoạn có "6.8 percent in 2017" (tăng trưởng thực tế năm 2017, tr.9 và tr.16) và số liệu 6,3% của khu vực EAP. Thẻ đúng đứng hạng 6 ở C, 14 ở B, 28 ở A. Con số trùng nhau nhưng nghĩa khác nhau, và embedding không phân biệt được "dự báo 2018" với "đã đạt năm 2017".

  *Ví dụ sai 2: q16* (test, gold `ts-2017-12` tr.17: "rose to 53.3 in September from 51.8 in August"). A sai hẳn (thẻ đúng ở ngoài hạng 60), trong khi B và C đều có thẻ đúng ở hạng 1. Cửa sổ 500 ký tự của A trộn câu về PMI với đoạn sản lượng công nghiệp phía trước, còn B có một thẻ chỉ nói về PMI nên khớp rõ với câu hỏi.

  Ngoài ra, q01 (dự trữ ngoại hối tháng 9/2017) và q10 (mục tiêu tín dụng 2018) sai ở cả ba cách; thẻ đúng nằm ở hạng 6–7.

- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**
  Theo tiêu chí đã chốt, em chọn A vì có Evidence Hit@3 trên dev cao nhất (12/15). Kết quả test lại không ủng hộ lựa chọn này: A chỉ 3/5, còn B và C 4/5. Tuy vậy test chỉ có 5 câu và hai bên chỉ chênh một câu, nên em không đủ cơ sở để nói cách nào tốt hơn. Em giữ nguyên lựa chọn A, không đổi tiêu chí sau khi đã xem test.

  Đánh đổi giữa các cách khá rõ. A tìm bằng chứng tốt hơn trên dev nhưng thẻ khó đọc, và không xử lý được câu hỏi phụ thuộc kỳ báo cáo. B và C cho thẻ dễ đọc, grounding tốt hơn, và C trả lời đúng các câu phụ thuộc kỳ. Trong phạm vi corpus này, nếu người dùng thường cho biết họ đang đọc kỳ nào thì nên dùng filter (4/4 so với 0/4). Bước tiếp theo hợp lý là thử A kết hợp filter; em chưa chạy cấu hình đó nên không đưa số liệu.

- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  Corpus chỉ có 2 tài liệu tiếng Anh cùng loại, chữ trong biểu đồ còn gây nhiễu, và thẻ không vượt qua ranh giới trang. Về nhãn: chỉ có một lượt chấm, chưa có người chấm thứ hai để đối chiếu (cách chấm ghi ở mục cuối). Hit dựa trên so khớp chuỗi chính xác nên có thể bỏ sót bằng chứng được diễn đạt khác. Test chỉ có 5 câu (2 câu có filter), mỗi câu tương đương 20 điểm phần trăm; dev cũng chỉ 15 câu. Thời gian đo một lần trên CPU và lần đầu có tính cả thời gian tải model. Câu hỏi đều bằng tiếng Anh; em chưa thử hỏi bằng tiếng Việt dù model hỗ trợ đa ngữ.

- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  Em sẽ thử A + filter, và một biến thể của B ghép tiêu đề mục hoặc câu chủ đề vào mọi thẻ con của cùng một đoạn. Với các câu có số liệu hoặc năm như q20, em muốn thử hybrid với BM25 và chọn tham số trên dev. Em cũng cần lọc chữ biểu đồ và xử lý trang nhiều cột tốt hơn, thêm câu hỏi tiếng Việt, tăng test lên ít nhất 15 câu, và nhờ thêm một người chấm để đo độ đồng thuận.

## Sử dụng AI và cách kiểm tra

Em dùng Claude (Claude Code) để hỗ trợ chọn tài liệu, viết code pipeline, soạn nháp bộ câu hỏi, chấm nháp coherence và grounding, và đối chiếu metadata. Em duyệt bộ câu hỏi và tiêu chí chọn chiến lược trước khi chạy truy xuất.

Các bước kiểm tra: evidence được script đối chiếu với trang gold (26/26). Metadata được script kiểm tra rồi AI đối chiếu từng thẻ với text trang PDF và mục lục, kèm ghi chú từng dòng; em chấp nhận kết quả này mà không tự kiểm tra lại từng dòng. 35 nhãn coherence và grounding do AI chấm nháp, mỗi nhãn có lý do; em đã đọc lại và giữ nguyên toàn bộ. Cột `labeller` trong các file audit ghi đúng như vậy. Vì em duyệt trên bản nháp có sẵn chứ không tự chấm từ đầu, điểm có thể bị bản nháp ảnh hưởng.
