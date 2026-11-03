# Industry profile Q&A seed

> Synthetic seed extracted from the 15 supplied DOCX files. Review and approve before using customer-facing. This document is suitable for a controlled RAG pilot; the JSONL case file remains the evaluation source of truth.

## industry_01 Lam dep va cham soc ca nhan

### Phạm vi ngành
Hồ sơ ngành hàng bán lẻ mỹ phẩm và sản phẩm chăm sóc cá nhân, gồm chăm sóc da, tóc, trang điểm và cơ thể. Tư vấn phải phân biệt kiến thức ngành với thông tin xác thực của từng SKU; không chẩn đoán bệnh da, không hứa hiệu quả điều trị và không tự kết luận độ an toàn/dị ứng.

### Thuật ngữ và FAQ
- **Cleanser** (Sữa rửa mặt): Sản phẩm làm sạch da, giúp loại bỏ dầu, bụi, makeup và bã nhờn. Aliases: face wash, cleanser gel, srm.
- **Toner** (Nước hoa hồng): Dòng hỗ trợ làm cân bằng độ pH, bổ sung độ ẩm và chuẩn bị da cho bước dưỡng tiếp theo. Aliases: nước cân bằng, toner dưỡng.
- **Serum** (Tinh chất): Sản phẩm tập trung theo mục tiêu như dưỡng ẩm, trị mụn, làm sáng hoặc cấp nước. Aliases: essence, serum dưỡng.
- **Moisturizer** (Kem dưỡng): Sản phẩm cung cấp độ ẩm, khóa nước và hỗ trợ hàng rào da. Aliases: cream, lotion, kem dưỡng ẩm.
- **Sunscreen** (Kem chống nắng): Sản phẩm bảo vệ da khỏi tia UV, cần dùng đều đặn để hỗ trợ chống lão hóa và chống sạm. Aliases: spf, kcn.
- **Retinol** (Retinol): Hoạt chất phổ biến trong chăm sóc da nhằm hỗ trợ tái tạo và cải thiện bề mặt da. Aliases: retinoid.
- **Niacinamide** (Niacinamide): Vitamin B3 used in skincare to support oil balance, barrier and brightening support. Aliases: vitamin B3, B3.
- **AHA** (AHA): Loại acid giúp hỗ trợ bong da và cải thiện bề mặt da, thường phù hợp với da dầu hoặc thô sần. Aliases: acid alpha hydroxy.
- **BHA** (BHA): Hoạt chất thâm nhập lỗ chân lông để hỗ trợ làm sạch và kiểm soát mụn. Aliases: salicylic acid, acid salicylic.
- **PHA** (PHA): Mặt acid nhẹ hơn, thường phù hợp cho da nhạy cảm cần tẩy tế bào chết dịu hơn. Aliases: poly hydroxy acid.
- **Hyaluronic Acid** (Axit Hyaluronic): Thành phần giữ ẩm mạnh, giúp da mềm mại và đầy bóng. Aliases: HA, hyaluronic.
- **Vitamin C** (Vitamin C): Hoạt chất hỗ trợ làm sáng và bảo vệ da khỏi stress môi trường. Aliases: ascorbic acid, VC.
- **Ceramide** (Ceramide): Thành phần hỗ trợ hàng rào da, giữ ẩm và giảm kích ứng. Aliases: ceramide complex.
- **Double Cleansing** (Rửa mặt 2 bước): Quy trình làm sạch da bằng tẩy trang hoặc dầu + sữa rửa mặt để loại bỏ makeup và bụi bẩn hiệu quả. Aliases: double cleanse.
- **Exfoliation** (Tẩy tế bào chết): Quy trình hoặc sản phẩm hỗ trợ loại bỏ tế bào chết, thường cần dùng đúng tần suất để tránh kích ứng. Aliases: exfoliant, peeling.
- **TDC** (Tẩy da chết): Tẩy da chết Aliases: —.
- **B5** (Panthenol): Panthenol Aliases: —.
- **sp** (sản phẩm): sản phẩm Aliases: —.
- **mk** (makeup / trang điểm): makeup / trang điểm Aliases: —.
- **ko/k** (không / không biết): không / không biết Aliases: —.
- **ib** (inbox / nhắn tin): inbox / nhắn tin Aliases: —.
- **rep** (representative / nhân viên hỗ trợ): representative / nhân viên hỗ trợ Aliases: —.

#### beauty_qa_01
**Câu hỏi:** Serum niacinamide có tác dụng gì?
**Cách hỏi khác:** Niacinamide là gì? | Tinh chất niacinamide dùng để làm gì?
**Intent:** product_benefits
**Câu trả lời gợi ý:** Niacinamide là hoạt chất phổ biến trong chăm sóc da, thường hỗ trợ cân bằng dầu, giữ ẩm và hỗ trợ làm sáng bề mặt da. Với mỗi sản phẩm, công dụng cụ thể vẫn cần dựa vào thành phần và hướng dẫn sử dụng trên sản phẩm đó.
**Nguồn cần truy xuất:** knowledge_base
**Điều kiện chuyển người:** If user asks about medical diagnosis or severe skin conditions, hand off to human support.

#### beauty_qa_02
**Câu hỏi:** Sữa rửa mặt phù hợp với da dầu là gì?
**Cách hỏi khác:** Da dầu nên dùng sữa rửa mặt nào? | SRM nào tốt cho da dầu?
**Intent:** skin_type_advice
**Câu trả lời gợi ý:** Da dầu thường phù hợp với sữa rửa mặt có khả năng làm sạch nhẹ, giảm nhờn và không gây căng, thường ưu tiên công thức không gây khô quá mức. Nếu bạn có mụn hoặc lỗ chân lông to, cần thêm thông tin về tình trạng da để gợi ý đúng hơn.
**Nguồn cần truy xuất:** knowledge_base, product_catalog
**Điều kiện chuyển người:** If acne is severe or inflamed, ask for a human or qualified support path.

#### beauty_qa_03
**Câu hỏi:** Dưỡng ẩm cho da khô nên chọn sản phẩm nào?
**Cách hỏi khác:** Mình da khô, có nên dùng kem dưỡng không? | Da khô nên mua gì?
**Intent:** skin_type_advice
**Câu trả lời gợi ý:** Da khô thường cần các sản phẩm có khả năng cấp ẩm và khóa ẩm, như kem dưỡng hoặc serum có thành phần dưỡng ẩm như hyaluronic acid, ceramide hoặc glycerin. Tôi cần biết thêm bạn thích dạng gel, lotion hay cream để gợi ý phù hợp hơn.
**Nguồn cần truy xuất:** knowledge_base, product_catalog
**Điều kiện chuyển người:** If the user reports peeling, itching, or rash, route to a human or medical support.

#### beauty_qa_04
**Câu hỏi:** Có bao nhiêu loại da cần biết khi chọn sản phẩm?
**Cách hỏi khác:** Loại da nào? | Mình thuộc loại da nào?
**Intent:** skin_type_advice
**Câu trả lời gợi ý:** Thông thường có các nhóm da dầu, khô, hỗn hợp, nhạy cảm và da thiếu nước. Không phải ai cũng chỉ thuộc một loại cố định, nên khi tư vấn nên hỏi thêm về trạng thái da hiện tại và cách da phản ứng với sản phẩm.
**Nguồn cần truy xuất:** knowledge_base
**Điều kiện chuyển người:** If the user needs a clinical skin diagnosis, transfer to professional support.

#### beauty_qa_05
**Câu hỏi:** Mặt mình nhạy cảm thì nên tránh thành phần nào?
**Cách hỏi khác:** Da nhạy cảm nên tránh thành phần gì? | Da nhạy cảm nên dùng gì?
**Intent:** skin_condition_advice
**Câu trả lời gợi ý:** Da nhạy cảm thường cần tránh hoặc hạn chế các thành phần gây kích ứng theo từng người, như fragrance mạnh, alcohol khô da hoặc các hoạt chất mạnh nếu bạn biết mình dễ kích ứng. Nếu bạn đang có đỏ, ngứa, rát rõ, nên kiểm tra thêm tình trạng da và ưu tiên hỗ trợ chuyên gia hoặc nhân viên chăm sóc khách hàng.
**Nguồn cần truy xuất:** knowledge_base
**Điều kiện chuyển người:** Severe itching, persistent redness, swelling, or rash require urgent professional help.

#### beauty_qa_06
**Câu hỏi:** Da tôi có mụn, nên dùng sản phẩm nào cho routine?
**Cách hỏi khác:** Routine cho da mụn là gì? | Mình mụn nên bắt đầu từ đâu?
**Intent:** routine_advice
**Câu trả lời gợi ý:** Với da mụn, routine thường gồm làm sạch nhẹ, dùng sản phẩm hỗ trợ kiểm soát dầu hoặc giúp làm sạch lỗ chân lông, và dưỡng ẩm đủ. Tuy nhiên, thứ tự và lựa chọn sản phẩm cần dựa vào mức độ mụn, loại da và cách da phản ứng với từng hoạt chất.
**Nguồn cần truy xuất:** knowledge_base, product_catalog
**Điều kiện chuyển người:** Cystic acne or severe irritation should be escalated to a medical professional.

#### beauty_qa_07
**Câu hỏi:** Da khô có nên dùng toner không?
**Cách hỏi khác:** Toner có cần cho da khô không? | Da khô dùng toner có tốt không?
**Intent:** skin_type_advice
**Câu trả lời gợi ý:** Da khô có thể dùng toner nếu toner đó là dạng cấp ẩm, dịu nhẹ và không chứa cồn quá mạnh. Tần suất và công thức nên phù hợp với cảm giác da của bạn; nếu da dễ khô, rát hoặc kích ứng, nên chọn toner dịu và không quá mạnh.
**Nguồn cần truy xuất:** knowledge_base
**Điều kiện chuyển người:** If stinging or active rash, hand off to human support immediately.

#### beauty_qa_08
**Câu hỏi:** Da hỗn hợp nên dùng kem dưỡng như thế nào?
**Cách hỏi khác:** Da hỗn hợp cần kem nào? | Dùng kem dưỡng cho da hỗn hợp như thế nào?
**Intent:** skin_type_advice
**Câu trả lời gợi ý:** Da hỗn hợp thường cần loại kem dưỡng nhẹ, không quá nặng ở vùng chữ T nhưng vẫn đủ ẩm ở hai má. Nếu da bạn có dầu ở vùng chữ T và khô ở má, bạn có thể chia theo khu vực hoặc chọn lớp dưỡng cân bằng, không quá dầu nhưng không thiếu ẩm.
**Nguồn cần truy xuất:** knowledge_base
**Điều kiện chuyển người:** If the user is experiencing irritated skin or harsh peeling, transfer.

#### beauty_qa_09
**Câu hỏi:** Mụn đầu đen nên dùng sản phẩm nào?
**Cách hỏi khác:** Mụn đầu đen nên dùng gì? | Có sản phẩm nào giúp mụn đầu đen không?
**Intent:** skin_condition_advice
**Câu trả lời gợi ý:** Mụn đầu đen thường gắn với lỗ chân lông bít tắc, và các sản phẩm hỗ trợ làm sạch sâu hoặc tẩy tế bào chết đúng cách có thể phù hợp. Tuy nhiên, lựa chọn vẫn cần dựa trên loại da và độ nhạy của da, vì dùng hoạt chất mạnh quá mức dễ kích ứng.
**Nguồn cần truy xuất:** knowledge_base
**Điều kiện chuyển người:** If the issue spreads or becomes painful, escalate.

#### beauty_qa_10
**Câu hỏi:** Tôi bị dầu nhờn, có nên dùng AHA không?
**Cách hỏi khác:** AHA có thích hợp cho da dầu không? | Da dầu dùng AHA có tốt không?
**Intent:** ingredient_advice
**Câu trả lời gợi ý:** AHA là một nhóm hoạt chất giúp hỗ trợ làm mịn bề mặt da và cải thiện tẩy tế bào chết, nên có thể phù hợp cho da dầu hoặc da thô sần nếu dùng đúng cách. Nhưng nếu da bạn dễ kích ứng hoặc đang có các vết đỏ/khô, cần giới hạn dần và tránh lạm dụng.
**Nguồn cần truy xuất:** knowledge_base
**Điều kiện chuyển người:** If the user has active burns, redness, or severe irritation, route to professional support.

#### beauty_qa_11
**Câu hỏi:** Serum Vitamin C dùng buổi sáng hay tối?
**Cách hỏi khác:** Vitamin C nên dùng sáng hay tối? | Mình nên thoa vitamin C lúc nào?
**Intent:** routine_advice
**Câu trả lời gợi ý:** Nhiều người thường dùng vitamin C vào buổi sáng vì hỗ trợ tạo cảm giác sáng và bảo vệ da trong ngày, nhưng tùy từng công thức và cơ địa mỗi người. Nếu bạn có da nhạy cảm, hãy bắt đầu chậm và theo hướng dẫn của nhà sản xuất.
**Nguồn cần truy xuất:** knowledge_base, product_usage_instructions
**Điều kiện chuyển người:** If irritation occurs, stop use and ask for human review.

#### beauty_qa_12
**Câu hỏi:** Kem chống nắng nên thoa mấy lần một ngày?
**Cách hỏi khác:** Mỗi ngày dùng kem chống nắng bao nhiêu lần? | Kem chống nắng cần thoa mấy lần?
**Intent:** routine_advice
**Câu trả lời gợi ý:** Về nguyên tắc, kem chống nắng nên được thoa đều đặn theo hướng dẫn trên sản phẩm, và thường cần được sử dụng lại trong trường hợp tiếp xúc lâu với ánh nắng hoặc sau khi đổ mồ hôi, làm sạch hoặc lau khô. Khuyến nghị chung là dùng thường xuyên hàng ngày, không dựa vào cảm giác của da.
**Nguồn cần truy xuất:** knowledge_base
**Điều kiện chuyển người:** If the user has severe sun reaction or condition, direct to expert support.

#### beauty_qa_13
**Câu hỏi:** Cách dùng toner đúng là gì?
**Cách hỏi khác:** Toner dùng như thế nào? | Có cần dùng toner không?
**Intent:** routine_advice
**Câu trả lời gợi ý:** Toner thường được dùng sau bước làm sạch và trước serum hoặc kem dưỡng. Nhiều người dùng bằng cách thấm lên bông hoặc tay, tùy vào công thức và mức độ da. Quan trọng là chọn toner phù hợp với loại da và không làm da khô quá mức hoặc kích ứng.
**Nguồn cần truy xuất:** knowledge_base, product_usage_instructions
**Điều kiện chuyển người:** Itchy or burning skin after toner usage should be escalated.

#### beauty_qa_14
**Câu hỏi:** Rửa mặt bằng sữa rửa mặt 2 lần/ngày có cần thiết không?
**Cách hỏi khác:** Có cần rửa mặt 2 lần không? | Rửa mặt ngày 2 lần là đủ không?
**Intent:** routine_advice
**Câu trả lời gợi ý:** Đối với nhiều người, rửa mặt 2 lần mỗi ngày là cách làm sạch cân bằng, tùy vào mức độ dầu, môi trường và cảm giác da. Nếu da quá khô hoặc dễ kích ứng, cần điều chỉnh tần suất và chọn sữa rửa mặt dịu hơn. Mỗi da có phản ứng riêng nên nên kiểm tra cảm giác sau khi dùng đến 1-2 tuần.
**Nguồn cần truy xuất:** knowledge_base
**Điều kiện chuyển người:** Persistent dryness or redness indicates human review.

#### beauty_qa_15
**Câu hỏi:** Sau khi dùng retinol, cần tránh kết hợp gì?
**Cách hỏi khác:** Retinol nên tránh dùng với gì? | Kết hợp retinol và AHA có được không?
**Intent:** product_combination
**Câu trả lời gợi ý:** Retinol là hoạt chất mạnh hơn nên nếu bạn mới bắt đầu, nên dùng chậm và theo hướng dẫn của từng sản phẩm. Nếu da còn nhạy cảm, nên tránh kết hợp quá nhiều hoạt chất mạnh cùng lúc như AHA, BHA hoặc các sản phẩm exfoliating quá mạnh trong một thời gian ngắn.
**Nguồn cần truy xuất:** knowledge_base, product_usage_instructions
**Điều kiện chuyển người:** When skin becomes raw, painful, or has severe irritation, transfer.

#### beauty_qa_16
**Câu hỏi:** Mình muốn so sánh 2 serum niacinamide, nên xem yếu tố nào?
**Cách hỏi khác:** Làm sao so sánh serum niacinamide? | Niacinamide serum nào tốt hơn?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Nên xem nồng độ, thành phần đi kèm, kiểu da phù hợp, mức độ dịu hay mạnh, cùng với công thức dưỡng ẩm và cách sử dụng. Nếu bạn có da nhạy cảm, cần ưu tiên công thức dịu hơn và thử chậm.
**Nguồn cần truy xuất:** product_catalog, knowledge_base
**Điều kiện chuyển người:** If the user wants a medical comparison or face diagnosis, route to a human.

#### beauty_qa_17
**Câu hỏi:** Serum nào phù hợp cho da nhạy cảm hơn?
**Cách hỏi khác:** Da nhạy cảm nên chọn serum nào? | Serum cho da nhạy cảm là gì?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Da nhạy cảm thường phù hợp với serum có thành phần dịu, ít hương, ít hoạt chất mạnh và thân thiện với hàng rào da. Tôi cần biết bạn ưu tiên cấp ẩm, làm dịu hay hỗ trợ barrier trước khi gợi ý chính xác.
**Nguồn cần truy xuất:** product_catalog, knowledge_base
**Điều kiện chuyển người:** Any open dermatitis or severe reaction should be escalated.

#### beauty_qa_18
**Câu hỏi:** Sữa rửa mặt nào tốt cho da mụn?
**Cách hỏi khác:** Sữa rửa mặt cho mụn nên chọn loại nào? | Da mụn mua sữa rửa mặt thế nào?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Sữa rửa mặt cho da mụn thường là dạng làm sạch nhẹ nhưng đủ hiệu quả để giảm bã nhờn và bụi bẩn. Nên ưu tiên công thức dịu, không làm da khô quá mức, và nếu có thành phần hỗ trợ kiểm soát dầu, cần kiểm tra độ nhạy của da.
**Nguồn cần truy xuất:** product_catalog, knowledge_base
**Điều kiện chuyển người:** If acne is inflamed or painful, route to supported human care.

#### beauty_qa_19
**Câu hỏi:** Kem dưỡng nào phù hợp với da hỗn hợp?
**Cách hỏi khác:** Da hỗn hợp nên dùng kem dưỡng nào? | Mình da hỗn hợp thì mua kem dưỡng gì?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Da hỗn hợp thường hợp với kem dưỡng có kết cấu vừa đủ ẩm, không quá nặng nhưng vẫn đủ cấp nước và giữ ẩm ở vùng khô. Nếu bạn có vùng chữ T nhờn và má khô, có thể cân nhắc kiểu lotion hoặc gel-cream theo khu vực.
**Nguồn cần truy xuất:** product_catalog
**Điều kiện chuyển người:** If skin is irritated or inflamed, involve human support.

#### beauty_qa_20
**Câu hỏi:** Mình đang cân nhắc mua kem dưỡng vs serum, lựa chọn dựa vào gì?
**Cách hỏi khác:** Nên chọn serum hay kem dưỡng? | Serum và kem dưỡng khác nhau thế nào?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Kem dưỡng thường tập trung dưỡng ẩm và khóa ẩm, trong khi serum thường tập trung vào hoạt chất và mục tiêu cụ thể. Nếu mục tiêu chính là cấp ẩm, kem dưỡng là nền tảng; nếu muốn bổ sung mục tiêu như làm sáng, dịu da hay hỗ trợ thô sần, serum thường là lựa chọn bổ trợ trong routine.
**Nguồn cần truy xuất:** knowledge_base
**Điều kiện chuyển người:** If user has medical conditions, refer to a human support path.

#### beauty_qa_21
**Câu hỏi:** Shop có sản phẩm nào phù hợp với da dầu không?
**Cách hỏi khác:** Sản phẩm cho da dầu của shop là gì? | Mình da dầu, shop có gì cho da dầu không?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tôi cần kiểm tra catalog hiện có của shop để xem các sản phẩm phù hợp với da dầu đang còn hàng, với các tiêu chí như loại sản phẩm, thành phần và khối lượng. Nếu chưa có dữ liệu live, tôi sẽ nói rõ rằng cần xác minh tồn kho và sản phẩm phù hợp trong catalog.
**Nguồn cần truy xuất:** product_catalog
**Điều kiện chuyển người:** If product catalog is unavailable or out of date, hand off to staff.

#### beauty_qa_22
**Câu hỏi:** Sản phẩm này còn hàng không?
**Cách hỏi khác:** Còn hàng không? | Sản phẩm X còn tồn kho không?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tôi cần kiểm tra trạng thái tồn kho của sản phẩm cụ thể trong catalog hoặc hệ thống CRM. Nếu chưa có thông tin trạng thái live, tôi sẽ không tự đưa ra con số hoặc khẳng định hàng còn trước khi xác nhận.
**Nguồn cần truy xuất:** product_catalog
**Điều kiện chuyển người:** If no live stock is available, transfer to staff.

#### beauty_qa_23
**Câu hỏi:** Giá của sản phẩm X là bao nhiêu?
**Cách hỏi khác:** Sản phẩm này bao nhiêu tiền? | Giá của sản phẩm X là mấy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá sản phẩm cần được kiểm tra trong Product Catalog hoặc hệ thống CRM. Tôi không dùng tài liệu RAG để suy ra giá khi chưa có dữ liệu live hoặc thông tin được shop xác nhận.
**Nguồn cần truy xuất:** product_catalog
**Điều kiện chuyển người:** If no exact price record exists, route to staff support.

#### beauty_qa_24
**Câu hỏi:** Có khuyến mãi nào cho combo dưỡng da không?
**Cách hỏi khác:** Combo này đang giảm không? | Shop có ưu đãi cho skincare combo không?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Khuyến mãi cần được xác minh từ chính sách ưu đãi của shop. Nếu chưa có thông tin xác nhận hoặc nếu combo không có dữ liệu cấu hình, tôi sẽ thông báo rằng cần kiểm tra với nhân viên hoặc chính sách hiện hành.
**Nguồn cần truy xuất:** shop_policy, promotion_data
**Điều kiện chuyển người:** When the promotion is not documented or requires approval, hand off.

#### beauty_qa_25
**Câu hỏi:** Mình muốn đặt 2 sản phẩm, có thể ship trước ngày mai không?
**Cách hỏi khác:** Có giao nhanh được không? | Ship trước ngày mai được không?
**Intent:** delivery_time
**Câu trả lời gợi ý:** Thời gian giao hàng và khả năng giao nhanh phụ thuộc vào chính sách vận chuyển, khu vực nhận hàng và trạng thái đơn. Nếu shop chưa có thông tin xác nhận cho trường hợp này, tôi sẽ nói rõ cần kiểm tra và có thể chuyển cho nhân viên.
**Nguồn cần truy xuất:** shop_policy, delivery_data
**Điều kiện chuyển người:** If not documented, route to staff.

#### beauty_qa_26
**Câu hỏi:** Hàng đã mở nắp có được đổi trả không?
**Cách hỏi khác:** Đã mở hộp có đổi trả được không? | Mở nắp rồi thì đổi hàng được không?
**Intent:** return_policy
**Câu trả lời gợi ý:** Việc đổi trả sau khi sản phẩm đã được mở nắp phụ thuộc vào chính sách shop và điều kiện cụ thể của từng sản phẩm. Tôi không tự áp dụng quy tắc chung cho mọi mỹ phẩm nếu shop chưa cấu hình rõ. Nếu không có thông tin xác nhận, tôi sẽ hướng dẫn bạn liên hệ nhân viên hỗ trợ.
**Nguồn cần truy xuất:** shop_policy
**Điều kiện chuyển người:** If the shop policy is missing or ambiguous, hand off to staff.

#### beauty_qa_27
**Câu hỏi:** Có thể đổi trả nếu sản phẩm bị hư trong lúc vận chuyển không?
**Cách hỏi khác:** Hàng bị hỏng khi giao có đổi được không? | Vận chuyển hỏng thì được đổi trả không?
**Intent:** return_policy
**Câu trả lời gợi ý:** Nếu sản phẩm bị hỏng hoặc sai trong quá trình vận chuyển, thường cần kiểm tra hình ảnh và tình trạng hộp, sản phẩm và thông tin đơn hàng. Quy định cụ thể vẫn thuộc shop policy, nên tôi cần xác minh chính sách hoặc chuyển cho nhân viên nếu chưa có dữ liệu.
**Nguồn cần truy xuất:** shop_policy
**Điều kiện chuyển người:** Any damaged inbound goods or disputed damage should be handed off.

#### beauty_qa_28
**Câu hỏi:** Phí ship cho đơn dưới 500k là bao nhiêu?
**Cách hỏi khác:** Đơn dưới 500k ship bao nhiêu? | Phí vận chuyển cho đơn nhỏ?
**Intent:** shipping_fee
**Câu trả lời gợi ý:** Phí ship phụ thuộc vào khu vực, phương thức giao hàng và chính sách shop hiện hành. Tôi không thể tự mặc định con số nếu shop chưa xác nhận. Bạn có thể cho tôi địa chỉ nhận hàng hoặc tôi sẽ chuyển cho nhân viên để xác minh chi tiết.
**Nguồn cần truy xuất:** shop_policy
**Điều kiện chuyển người:** If the shop lacks a documented shipping tier, hand off.

#### beauty_qa_29
**Câu hỏi:** Thời gian giao hàng là bao lâu?
**Cách hỏi khác:** Giao hàng mất mấy ngày? | Đơn dự kiến đến khi nào?
**Intent:** delivery_time
**Câu trả lời gợi ý:** Thời gian giao hàng cần dựa trên chính sách vận chuyển và địa chỉ nhận hàng của shop. Tôi không nên suy đoán một khoảng thời gian nếu chưa có xác minh từ shop hoặc đơn hàng cụ thể.
**Nguồn cần truy xuất:** shop_policy, order_record
**Điều kiện chuyển người:** If delivery data is missing, hand off to a person.

#### beauty_qa_30
**Câu hỏi:** Mình muốn thanh toán bằng ngân hàng hoặc COD thì được không?
**Cách hỏi khác:** Shop hỗ trợ COD không? | Có thanh toán chuyển khoản không?
**Intent:** payment_method
**Câu trả lời gợi ý:** Phương thức thanh toán phải được xác định theo cấu hình của shop. Nếu shop đã hỗ trợ COD hoặc chuyển khoản, tôi sẽ chỉ nói dựa trên chính sách hiện hành. Nếu chưa có dữ liệu xác nhận, tôi sẽ hỏi bạn chờ hoặc chuyển nhân viên hỗ trợ.
**Nguồn cần truy xuất:** shop_policy
**Điều kiện chuyển người:** When policy is unclear or missing, transfer to staff.

#### beauty_qa_31
**Câu hỏi:** Hàng đến bị rách seal thì xử lý thế nào?
**Cách hỏi khác:** Seal bị rách thì làm sao? | Hàng bị rách niêm phong khi giao?
**Intent:** complaint
**Câu trả lời gợi ý:** Nếu seal hoặc bao bì bị rách, bạn nên chụp hình và thông báo ngay cho shop để xác minh. Tùy vào chính sách của shop và tình trạng sản phẩm, chúng tôi có thể hướng dẫn đổi trả hoặc hỗ trợ nhân viên kiểm tra.
**Nguồn cần truy xuất:** shop_policy, complaint_workflow
**Điều kiện chuyển người:** If case requires approval or is severe, direct to staff.

#### beauty_qa_32
**Câu hỏi:** Tôi mua sản phẩm nhưng cảm giác dị ứng, cần hỗ trợ gì?
**Cách hỏi khác:** Sản phẩm khiến mình dị ứng, làm sao? | Mặt đỏ và ngứa sau khi dùng sản phẩm?
**Intent:** complaint
**Câu trả lời gợi ý:** Nếu bạn có dấu hiệu dị ứng như ngứa, đỏ, sưng hoặc khó chịu, nên dừng sử dụng sản phẩm và tìm hỗ trợ y tế hoặc chuyên gia phù hợp. Bot không được chẩn đoán bệnh lý; nếu cần, tôi có thể hướng dẫn bạn gửi thông tin chi tiết cho nhân viên hỗ trợ để xử lý đơn hàng hoặc phản hồi hàng hóa.
**Nguồn cần truy xuất:** knowledge_base, shop_policy
**Điều kiện chuyển người:** Severe allergic reaction or medical concern must be escalated immediately.

#### beauty_qa_33
**Câu hỏi:** Tôi có khiếu nại về dịch vụ, muốn được hỗ trợ nhân viên?
**Cách hỏi khác:** Mình muốn khiếu nại và nói chuyện nhân viên | Tôi cần hỗ trợ từ người thật
**Intent:** human_handoff
**Câu trả lời gợi ý:** Tôi có thể ghi nhận thông tin khiếu nại của bạn và chuyển cho nhân viên hỗ trợ. Hãy cho tôi mã đơn hàng, tên sản phẩm hoặc vấn đề bạn gặp nếu có, để đội ngũ hỗ trợ xử lý nhanh hơn.
**Nguồn cần truy xuất:** complaint_workflow, customer_record
**Điều kiện chuyển người:** Always escalate when the complaint requires staff judgment or payment policy review.

#### beauty_qa_34
**Câu hỏi:** Sản phẩm này có chính sách bảo hành không?
**Cách hỏi khác:** Dòng này có bảo hành không? | Mỹ phẩm có bảo hành không?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Không phải mọi sản phẩm làm đẹp đều có chính sách bảo hành. Điều này phụ thuộc vào từng sản phẩm và quy định của shop. Nếu bộ phận hỗ trợ chưa xác nhận, tôi sẽ không tự khẳng định có hoặc không có bảo hành.
**Nguồn cần truy xuất:** shop_policy
**Điều kiện chuyển người:** If the product category or policy is unclear, refer to staff.

#### beauty_qa_35
**Câu hỏi:** Tôi muốn nhân viên tư vấn trực tiếp, làm sao?
**Cách hỏi khác:** Cho mình nhân viên hỗ trợ trực tiếp | Mình cần tư vấn thật
**Intent:** human_handoff
**Câu trả lời gợi ý:** Bạn có thể yêu cầu nhân viên hỗ trợ bằng cách cung cấp nội dung cần tư vấn hoặc mã đơn hàng. Tôi sẽ chuyển thông tin đó cho bộ phận hỗ trợ để được xử lý nhanh nhất, đặc biệt nếu vấn đề cần đánh giá chính sách hoặc hỗ trợ tùy trường hợp.
**Nguồn cần truy xuất:** support_queue
**Điều kiện chuyển người:** Always transfer when a live conversation is needed.

## industry_02 Thời trang & phụ kiện

### Phạm vi ngành
Ngành bán lẻ quần áo, giày dép, túi, trang sức và phụ kiện thời trang. Khả năng tư vấn phụ thuộc mạnh vào biến thể (size, màu, form), chất liệu, cách bảo quản và mùa vụ. Không suy đoán vừa vặn từ chiều cao/cân nặng nếu không có bảng size của sản phẩm.

### Thuật ngữ và FAQ
- **size chart** (bảng size): Bảng đối chiếu size và số đo được công bố cho đúng mẫu; không thay thế việc thử. Aliases: size guide.
- **fit** (form dáng): Cách trang phục ôm/rộng theo thiết kế, không bảo đảm phù hợp mọi vóc dáng. Aliases: silhouette.
- **oversized** (dáng rộng): Dáng rộng chủ ý; cần đọc bảng số đo thay vì tự tăng size. Aliases: loose fit.
- **inseam** (đường dài ống trong): Số đo quần hữu ích khi chọn chiều dài. Aliases: inner leg length.
- **upper** (thân giày): Phần bao phủ phía trên của giày. Aliases: shoe upper.
- **outsole** (đế ngoài): Phần đế tiếp xúc mặt đất. Aliases: outsole.
- **lining** (lớp lót): Lớp vật liệu bên trong sản phẩm. Aliases: inner lining.
- **hardware** (phụ kiện kim loại): Khóa, khoen hoặc chi tiết kim loại trên phụ kiện. Aliases: metal trims.
- **colorway** (phối màu): Tên/mã một phối màu được quản lý như biến thể. Aliases: color variant.
- **genuine leather** (da thật): Chỉ dùng khi nguồn sản phẩm xác nhận chính xác vật liệu. Aliases: leather.

#### industry_02_qa_01
**Câu hỏi:** size chart là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** bảng size nghĩa là gì? | Cho mình hỏi về size chart | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Bảng đối chiếu size và số đo được công bố cho đúng mẫu; không thay thế việc thử. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_02_qa_02
**Câu hỏi:** fit là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** form dáng nghĩa là gì? | Cho mình hỏi về fit | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Cách trang phục ôm/rộng theo thiết kế, không bảo đảm phù hợp mọi vóc dáng. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_02_qa_03
**Câu hỏi:** oversized là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** dáng rộng nghĩa là gì? | Cho mình hỏi về oversized | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Dáng rộng chủ ý; cần đọc bảng số đo thay vì tự tăng size. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_02_qa_04
**Câu hỏi:** inseam là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** đường dài ống trong nghĩa là gì? | Cho mình hỏi về inseam | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Số đo quần hữu ích khi chọn chiều dài. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_02_qa_05
**Câu hỏi:** upper là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** thân giày nghĩa là gì? | Cho mình hỏi về upper | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Phần bao phủ phía trên của giày. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_02_qa_06
**Câu hỏi:** outsole là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** đế ngoài nghĩa là gì? | Cho mình hỏi về outsole | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Phần đế tiếp xúc mặt đất. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_02_qa_07
**Câu hỏi:** lining là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** lớp lót nghĩa là gì? | Cho mình hỏi về lining | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Lớp vật liệu bên trong sản phẩm. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_02_qa_08
**Câu hỏi:** hardware là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** phụ kiện kim loại nghĩa là gì? | Cho mình hỏi về hardware | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Khóa, khoen hoặc chi tiết kim loại trên phụ kiện. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_02_qa_09
**Câu hỏi:** colorway khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh colorway giúp mình | phối màu có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Tên/mã một phối màu được quản lý như biến thể. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_02_qa_10
**Câu hỏi:** genuine leather khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh genuine leather giúp mình | da thật có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Chỉ dùng khi nguồn sản phẩm xác nhận chính xác vật liệu. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_02_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Quần áo, trước hết cần biết dáng người/tùy chọn vừa vặn do khách tự nêu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_02_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Giày dép, trước hết cần biết size và hệ đo. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_02_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Túi, trang sức và phụ kiện, trước hết cần biết màu/undertone nếu có. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_02_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Quần áo, trước hết cần biết chất liệu và dị ứng do khách chủ động nêu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_02_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Giày dép, trước hết cần biết dịp sử dụng. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_02_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Túi, trang sức và phụ kiện, trước hết cần biết ngân sách do khách cung cấp. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_02_qa_17
**Câu hỏi:** Bảng size nên đọc thế nào?
**Cách hỏi khác:** Bảng size nên đọc thế nào thế nào? | Bảng size nên đọc thế nào?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Giải thích cách đối chiếu số đo với bảng size đúng mẫu; nếu ở giữa hai size thì hỏi tư vấn viên dựa trên số đo thực tế và độ ôm mong muốn, không tự cam kết vừa.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_02_qa_18
**Câu hỏi:** Áo này chất liệu gì?
**Cách hỏi khác:** Áo này chất liệu gì thế nào? | Áo này chất liệu gì?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Tra đúng biến thể/mã hàng trong Product Catalog hoặc nhãn đã xác minh. Nếu không có tỷ lệ sợi hay thành phần, nói chưa xác nhận và không đoán theo ảnh.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_02_qa_19
**Câu hỏi:** Màu trên ảnh có giống ngoài đời không?
**Cách hỏi khác:** Màu trên ảnh có giống ngoài đời không thế nào? | Màu trên ảnh có giống ngoài đời không?
**Intent:** product_information
**Câu trả lời gợi ý:** Ảnh có thể khác do ánh sáng/màn hình. Chỉ mô tả tên/mã màu từ catalog; nếu khách cần chính xác, gửi ảnh thật đã được shop duyệt hoặc nhờ nhân viên.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_02_qa_20
**Câu hỏi:** Giày có đổi size được không?
**Cách hỏi khác:** Giày có đổi size được không thế nào? | Giày có đổi size được không?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Điều kiện đổi size lấy từ Shop Policy và trạng thái đơn; không hứa nhận đổi nếu policy chưa được cấu hình.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_02_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_02_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_02_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_02_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_02_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_02_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_02_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_02_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_02_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_02_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_03 Điện tử & điện gia dụng

### Phạm vi ngành
Bán thiết bị điện tử, thiết bị gia dụng, phụ kiện và thiết bị kết nối. Tư vấn phải phân biệt model/SKU, thông số định mức, khả năng tương thích, phụ kiện đi kèm, nguồn điện, an toàn sử dụng và điều kiện bảo hành chính thức.

### Thuật ngữ và FAQ
- **model** (mã model): Định danh chính xác để tra cấu hình và phụ kiện. Aliases: model number.
- **rated power** (công suất định mức): Thông số trên nhãn; không dùng như lời hứa về chi phí điện. Aliases: wattage.
- **voltage** (điện áp): Điều kiện nguồn điện phải phù hợp nhãn máy. Aliases: input voltage.
- **compatibility** (tương thích): Chỉ xác nhận các model/hệ thống nằm trong danh sách nguồn. Aliases: supported devices.
- **firmware** (phần mềm điều khiển): Phiên bản phần mềm thiết bị; cập nhật theo chỉ dẫn hãng. Aliases: firmware.
- **port** (cổng kết nối): Hình dạng/chuẩn cổng; không suy ra tính năng chỉ từ hình dạng. Aliases: connector.
- **capacity** (dung tích/công suất chứa): Giá trị và đơn vị theo model. Aliases: capacity.
- **IP rating** (cấp bảo vệ vỏ): Chỉ giải thích khi chứng nhận/mã được xác minh. Aliases: ingress protection.
- **accessory** (phụ kiện đi kèm): Danh sách đóng hộp chính xác. Aliases: in-box item.
- **warranty** (bảo hành): Không thay Shop Policy hoặc điều kiện nhà sản xuất. Aliases: manufacturer warranty.

#### industry_03_qa_01
**Câu hỏi:** model là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** mã model nghĩa là gì? | Cho mình hỏi về model | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Định danh chính xác để tra cấu hình và phụ kiện. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_03_qa_02
**Câu hỏi:** rated power là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** công suất định mức nghĩa là gì? | Cho mình hỏi về rated power | W là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Thông số trên nhãn; không dùng như lời hứa về chi phí điện. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_03_qa_03
**Câu hỏi:** voltage là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** điện áp nghĩa là gì? | Cho mình hỏi về voltage | V là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Điều kiện nguồn điện phải phù hợp nhãn máy. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_03_qa_04
**Câu hỏi:** compatibility là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** tương thích nghĩa là gì? | Cho mình hỏi về compatibility | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ xác nhận các model/hệ thống nằm trong danh sách nguồn. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_03_qa_05
**Câu hỏi:** firmware là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** phần mềm điều khiển nghĩa là gì? | Cho mình hỏi về firmware | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Phiên bản phần mềm thiết bị; cập nhật theo chỉ dẫn hãng. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_03_qa_06
**Câu hỏi:** port là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** cổng kết nối nghĩa là gì? | Cho mình hỏi về port | USB-C/HDMI… là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Hình dạng/chuẩn cổng; không suy ra tính năng chỉ từ hình dạng. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_03_qa_07
**Câu hỏi:** capacity là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** dung tích/công suất chứa nghĩa là gì? | Cho mình hỏi về capacity | L/GB… là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Giá trị và đơn vị theo model. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_03_qa_08
**Câu hỏi:** IP rating là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** cấp bảo vệ vỏ nghĩa là gì? | Cho mình hỏi về IP rating | mã hãng công bố là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ giải thích khi chứng nhận/mã được xác minh. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_03_qa_09
**Câu hỏi:** accessory khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh accessory giúp mình | phụ kiện đi kèm có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Danh sách đóng hộp chính xác. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_03_qa_10
**Câu hỏi:** warranty khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh warranty giúp mình | bảo hành có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Không thay Shop Policy hoặc điều kiện nhà sản xuất. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_03_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thiết bị điện tử, trước hết cần biết nhu cầu sử dụng. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_03_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Điện gia dụng, trước hết cần biết model thiết bị cần tương thích. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_03_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thiết bị mạng/âm thanh, trước hết cần biết không gian và điều kiện lắp đặt. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_03_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thiết bị điện tử, trước hết cần biết ngân sách. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_03_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Điện gia dụng, trước hết cần biết mức độ cần hỗ trợ cài đặt. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_03_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thiết bị mạng/âm thanh, trước hết cần biết thông số nguồn điện hiện có. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_03_qa_17
**Câu hỏi:** Thiết bị này có dùng được với model của tôi không?
**Cách hỏi khác:** Thiết bị này có dùng được với model của tôi không thế nào? | Thiết bị này có dùng được với model của mình không?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Cần đối chiếu model đầy đủ của hai thiết bị với danh sách tương thích hoặc thông số do hãng công bố. Gửi model trên nhãn máy giúp kiểm tra; không thể kết luận chỉ từ tên thương mại.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_03_qa_18
**Câu hỏi:** Máy có những phụ kiện nào trong hộp?
**Cách hỏi khác:** Máy có những phụ kiện nào trong hộp thế nào? | Máy có những phụ kiện nào trong hộp?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Đọc danh sách đóng hộp của đúng SKU/phiên bản. Nếu thông tin chưa có, báo cần kiểm tra; không mặc định dây, pin hay adapter đi kèm.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_03_qa_19
**Câu hỏi:** Công suất thiết bị là bao nhiêu?
**Cách hỏi khác:** Công suất thiết bị là bao nhiêu thế nào? | Công suất thiết bị là bao nhiêu?
**Intent:** product_information
**Câu trả lời gợi ý:** Tra thông số định mức của đúng model. Không dùng công suất để tự tính chi phí điện nếu thiếu thời gian sử dụng, biểu giá và điều kiện vận hành.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_03_qa_20
**Câu hỏi:** Thiết bị nóng/mùi khét thì làm gì?
**Cách hỏi khác:** Thiết bị nóng/mùi khét thì làm gì thế nào? | Thiết bị nóng/mùi khét thì làm gì?
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ngừng sử dụng; nếu an toàn, ngắt nguồn và tránh chạm vào phần nóng/ướt. Không tự tháo thiết bị. Liên hệ hỗ trợ kỹ thuật; nếu có cháy/khói nguy hiểm, gọi dịch vụ khẩn cấp tại địa phương.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_03_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_03_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_03_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_03_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_03_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_03_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_03_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_03_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_03_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_03_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_04 Nhà cửa & đời sống

### Phạm vi ngành
Ngành hàng nội thất, đồ bếp, trang trí, lưu trữ và tiện ích gia đình. Các thông tin quyết định mua thường là kích thước thực, vật liệu, tải trọng, cách lắp, tương thích không gian, vệ sinh và vận chuyển cồng kềnh.

### Thuật ngữ và FAQ
- **footprint** (diện tích chiếm chỗ): Khoảng không gian cần dành cho món đồ. Aliases: floor footprint.
- **load capacity** (tải trọng tối đa công bố): Chỉ dùng mức do nhà sản xuất xác nhận. Aliases: weight limit.
- **flat-pack** (hàng đóng gói phẳng): Hàng cần lắp ráp sau khi nhận. Aliases: knock-down furniture.
- **finish** (lớp hoàn thiện): Bề mặt được xử lý; không tự suy ra khả năng chống nước. Aliases: surface finish.
- **food-contact** (tiếp xúc thực phẩm): Cần căn cứ hồ sơ/nhãn; không khẳng định an toàn nếu thiếu. Aliases: food contact.
- **mounting** (cách cố định/lắp): Cần tuân thủ hướng dẫn và vật liệu tường/bề mặt. Aliases: installation.
- **modular** (cấu hình mô-đun): Các phần ghép nối theo cấu hình tương thích. Aliases: modular.
- **capacity** (dung tích): Dung tích theo thông tin sản phẩm. Aliases: volume.
- **care label** (nhãn hướng dẫn bảo quản): Hướng dẫn vệ sinh do nhà cung cấp đưa ra. Aliases: care instructions.
- **assembly** (lắp ráp): Quy trình/điều kiện lắp ráp. Aliases: assembly.

#### industry_04_qa_01
**Câu hỏi:** footprint là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** diện tích chiếm chỗ nghĩa là gì? | Cho mình hỏi về footprint | cm là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Khoảng không gian cần dành cho món đồ. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_04_qa_02
**Câu hỏi:** load capacity là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** tải trọng tối đa công bố nghĩa là gì? | Cho mình hỏi về load capacity | kg là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ dùng mức do nhà sản xuất xác nhận. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_04_qa_03
**Câu hỏi:** flat-pack là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** hàng đóng gói phẳng nghĩa là gì? | Cho mình hỏi về flat-pack | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Hàng cần lắp ráp sau khi nhận. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_04_qa_04
**Câu hỏi:** finish là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** lớp hoàn thiện nghĩa là gì? | Cho mình hỏi về finish | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Bề mặt được xử lý; không tự suy ra khả năng chống nước. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_04_qa_05
**Câu hỏi:** food-contact là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** tiếp xúc thực phẩm nghĩa là gì? | Cho mình hỏi về food-contact | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Cần căn cứ hồ sơ/nhãn; không khẳng định an toàn nếu thiếu. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_04_qa_06
**Câu hỏi:** mounting là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** cách cố định/lắp nghĩa là gì? | Cho mình hỏi về mounting | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Cần tuân thủ hướng dẫn và vật liệu tường/bề mặt. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_04_qa_07
**Câu hỏi:** modular là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** cấu hình mô-đun nghĩa là gì? | Cho mình hỏi về modular | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Các phần ghép nối theo cấu hình tương thích. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_04_qa_08
**Câu hỏi:** capacity là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** dung tích nghĩa là gì? | Cho mình hỏi về capacity | L/ml là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Dung tích theo thông tin sản phẩm. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_04_qa_09
**Câu hỏi:** care label khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh care label giúp mình | nhãn hướng dẫn bảo quản có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Hướng dẫn vệ sinh do nhà cung cấp đưa ra. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_04_qa_10
**Câu hỏi:** assembly khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh assembly giúp mình | lắp ráp có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Quy trình/điều kiện lắp ráp. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_04_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Nội thất, trước hết cần biết kích thước không gian. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_04_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Đồ bếp và dụng cụ, trước hết cần biết kích thước món đồ hiện có. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_04_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Trang trí và lưu trữ, trước hết cần biết vật liệu bề mặt lắp đặt. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_04_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Nội thất, trước hết cần biết phong cách/màu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_04_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Đồ bếp và dụng cụ, trước hết cần biết nhu cầu vệ sinh. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_04_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Trang trí và lưu trữ, trước hết cần biết giới hạn vận chuyển/lắp ráp. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_04_qa_17
**Câu hỏi:** Món đồ này kích thước bao nhiêu?
**Cách hỏi khác:** Món đồ này kích thước bao nhiêu thế nào? | Món đồ này kích thước bao nhiêu?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Tra kích thước của đúng mẫu và biến thể; đối chiếu rộng, sâu, cao với không gian thực tế, kể cả lối vào/thang máy nếu giao đồ lớn. Không suy ra kích thước từ ảnh.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_04_qa_18
**Câu hỏi:** Kệ chịu được bao nhiêu kg?
**Cách hỏi khác:** Kệ chịu được bao nhiêu kg thế nào? | Kệ chịu được bao nhiêu kg?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Chỉ trả lời tải trọng nếu tài liệu nhà sản xuất công bố cho đúng cấu hình và cách lắp. Nếu không có, nói chưa xác minh; không tự thử tải.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_04_qa_19
**Câu hỏi:** Đồ này có dùng được với bếp từ/lò vi sóng không?
**Cách hỏi khác:** Đồ này có dùng được với bếp từ/lò vi sóng không thế nào? | Đồ này có dùng được với bếp từ/lò vi sóng không?
**Intent:** product_information
**Câu trả lời gợi ý:** Đối chiếu danh sách nguồn nhiệt hoặc biểu tượng trên nhãn của đúng sản phẩm. Nếu dữ liệu thiếu, không thử sử dụng vì có thể gây hư hỏng hoặc nguy hiểm.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_04_qa_20
**Câu hỏi:** Shop có lắp đặt và giao lên tầng không?
**Cách hỏi khác:** Shop có lắp đặt và giao lên tầng không thế nào? | Shop có lắp đặt và giao lên tầng không?
**Intent:** human_handoff
**Câu trả lời gợi ý:** Thông tin này phải tra Shop Policy theo địa chỉ, loại hàng và đơn cụ thể. Không hứa dịch vụ/phí nếu shop chưa cấu hình.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_04_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_04_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_04_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_04_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_04_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_04_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_04_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_04_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_04_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_04_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_05 Bách hóa – Thực phẩm

### Phạm vi ngành
Bán thực phẩm đóng gói, đồ uống, hàng tiêu dùng và sản phẩm tươi/đông lạnh tùy phạm vi shop. Tư vấn phụ thuộc nhãn, thành phần, dị nguyên, khối lượng, điều kiện bảo quản, lô/date và vùng giao. Không thay thế tư vấn y tế hay thông tin nhãn.

### Thuật ngữ và FAQ
- **allergen** (dị nguyên): Chỉ báo dị nguyên từ nhãn/hồ sơ; không suy luận an toàn từ danh sách rút gọn. Aliases: food allergen.
- **cross-contact** (nguy cơ nhiễm chéo): Cảnh báo theo cơ sở/nhãn; không diễn giải là bảo đảm không có. Aliases: may contain.
- **net weight** (khối lượng tịnh): Lượng thực phẩm theo nhãn. Aliases: net content.
- **best before** (sử dụng tốt nhất trước): Không đồng nhất với hướng dẫn HSD; dùng nội dung nhãn. Aliases: best before.
- **batch/lot** (mã lô): Định danh lô cần cho truy xuất/thu hồi. Aliases: batch number.
- **cold chain** (chuỗi lạnh): Yêu cầu nhiệt độ trong lưu trữ/vận chuyển. Aliases: temperature-controlled supply.
- **thawing** (rã đông): Làm theo hướng dẫn an toàn thực phẩm. Aliases: defrosting.
- **serving size** (khẩu phần): Cơ sở hiểu bảng dinh dưỡng; không phải lượng khuyến nghị y tế. Aliases: serving size.
- **traceability** (truy xuất nguồn gốc): Tra cứu theo hồ sơ lô/nhà cung cấp. Aliases: traceability.
- **use-by date** (hạn sử dụng): Thông tin có thể khác theo từng lô. Aliases: expiry date.

#### industry_05_qa_01
**Câu hỏi:** allergen là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** dị nguyên nghĩa là gì? | Cho mình hỏi về allergen | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ báo dị nguyên từ nhãn/hồ sơ; không suy luận an toàn từ danh sách rút gọn. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_05_qa_02
**Câu hỏi:** cross-contact là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** nguy cơ nhiễm chéo nghĩa là gì? | Cho mình hỏi về cross-contact | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Cảnh báo theo cơ sở/nhãn; không diễn giải là bảo đảm không có. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_05_qa_03
**Câu hỏi:** net weight là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** khối lượng tịnh nghĩa là gì? | Cho mình hỏi về net weight | g/ml là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Lượng thực phẩm theo nhãn. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_05_qa_04
**Câu hỏi:** best before là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** sử dụng tốt nhất trước nghĩa là gì? | Cho mình hỏi về best before | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Không đồng nhất với hướng dẫn HSD; dùng nội dung nhãn. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_05_qa_05
**Câu hỏi:** batch/lot là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** mã lô nghĩa là gì? | Cho mình hỏi về batch/lot | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Định danh lô cần cho truy xuất/thu hồi. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_05_qa_06
**Câu hỏi:** cold chain là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** chuỗi lạnh nghĩa là gì? | Cho mình hỏi về cold chain | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Yêu cầu nhiệt độ trong lưu trữ/vận chuyển. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_05_qa_07
**Câu hỏi:** thawing là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** rã đông nghĩa là gì? | Cho mình hỏi về thawing | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Làm theo hướng dẫn an toàn thực phẩm. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_05_qa_08
**Câu hỏi:** serving size là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** khẩu phần nghĩa là gì? | Cho mình hỏi về serving size | g/ml là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Cơ sở hiểu bảng dinh dưỡng; không phải lượng khuyến nghị y tế. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_05_qa_09
**Câu hỏi:** traceability khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh traceability giúp mình | truy xuất nguồn gốc có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Tra cứu theo hồ sơ lô/nhà cung cấp. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_05_qa_10
**Câu hỏi:** use-by date khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh use-by date giúp mình | hạn sử dụng có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Thông tin có thể khác theo từng lô. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_05_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thực phẩm đóng gói/đồ uống, trước hết cần biết dị ứng/dị nguyên do khách chủ động nêu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_05_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Hàng tươi/đông lạnh, trước hết cần biết chế độ ăn do khách tự nêu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_05_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Hàng tiêu dùng gia đình, trước hết cần biết khu vực giao. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_05_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thực phẩm đóng gói/đồ uống, trước hết cần biết thời điểm nhận hàng. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_05_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Hàng tươi/đông lạnh, trước hết cần biết yêu cầu bảo quản. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_05_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Hàng tiêu dùng gia đình, trước hết cần biết số lượng/đơn vị. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_05_qa_17
**Câu hỏi:** Sản phẩm có chứa dị nguyên X không?
**Cách hỏi khác:** Sản phẩm có chứa dị nguyên X không thế nào? | Sản phẩm có chứa dị nguyên X không?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Đọc đúng nhãn và cảnh báo nhiễm chéo của đúng sản phẩm/lô. Nếu thông tin chưa xác minh, không bảo đảm an toàn; đề nghị khách chờ nhân viên kiểm tra hoặc chọn sản phẩm có hồ sơ rõ.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_05_qa_18
**Câu hỏi:** Hạn sử dụng của lô đang bán là khi nào?
**Cách hỏi khác:** Hạn sử dụng của lô đang bán là khi nào thế nào? | Hạn sử dụng của lô đang bán là khi nào?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Hạn dùng có thể phụ thuộc lô. Tra lô hàng đang được giữ trong catalog/inventory; không lấy ngày trong tài liệu cũ. Nếu batch data không có, cần xác nhận trước khi trả lời.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_05_qa_19
**Câu hỏi:** Sản phẩm cần bảo quản thế nào sau khi mở?
**Cách hỏi khác:** Sản phẩm cần bảo quản thế nào sau khi mở thế nào? | Sản phẩm cần bảo quản thế nào sau khi mở?
**Intent:** product_information
**Câu trả lời gợi ý:** Theo hướng dẫn trên nhãn/tài liệu sản phẩm. Không tự đặt nhiệt độ hay số ngày sau mở; nếu nhãn không nêu, nói rõ cần nhà cung cấp/shop xác minh.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_05_qa_20
**Câu hỏi:** Shop có giao thực phẩm đông lạnh đến địa chỉ tôi không?
**Cách hỏi khác:** Shop có giao thực phẩm đông lạnh đến địa chỉ tôi không thế nào? | Shop có giao thực phẩm đông lạnh đến địa chỉ mình không?
**Intent:** human_handoff
**Câu trả lời gợi ý:** Kiểm tra vùng phục vụ và phương thức vận chuyển hiện hành theo địa chỉ. Không hứa giao/giữ nhiệt nếu shop chưa cấu hình quy trình tương ứng.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_05_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_05_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_05_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_05_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_05_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_05_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_05_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_05_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_05_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_05_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_06 Mẹ & bé

### Phạm vi ngành
Ngành hàng sản phẩm cho thai kỳ, chăm sóc mẹ, trẻ sơ sinh và trẻ em: quần áo, đồ dùng, vệ sinh, ăn uống và thiết bị. Phải kiểm tra độ tuổi/giai đoạn, hướng dẫn nhà sản xuất, cảnh báo, kích cỡ và điều kiện vệ sinh; tuyệt đối tránh khuyến nghị y tế hoặc an toàn cho trẻ khi không có nguồn.

### Thuật ngữ và FAQ
- **age grade** (độ tuổi phù hợp): Dùng đúng chỉ định nhà sản xuất; không suy ra chỉ từ ảnh. Aliases: age recommendation.
- **supervision** (cần người lớn giám sát): Cảnh báo an toàn theo hướng dẫn sản phẩm. Aliases: adult supervision.
- **choking hazard** (nguy cơ hóc nghẹn): Tuân thủ cảnh báo chi tiết và không thay bằng lời đảm bảo. Aliases: small-parts warning.
- **sleep safety** (an toàn giấc ngủ): Chỉ cung cấp thông tin từ nguồn y tế/chính thức được shop duyệt. Aliases: safe sleep.
- **size chart** (bảng cỡ): Bảng của hãng; độ tuổi không bảo đảm vừa. Aliases: sizing guide.
- **sterilization** (tiệt trùng): Thực hiện theo hướng dẫn thiết bị/sản phẩm. Aliases: sterilizing.
- **feeding stage** (giai đoạn ăn): Theo nhãn và hướng dẫn chuyên môn phù hợp. Aliases: feeding stage.
- **batch code** (mã lô): Dùng khi tra hạn, nguồn gốc hoặc thông báo thu hồi. Aliases: lot number.
- **skin sensitivity** (nhạy cảm da): Không chẩn đoán dị ứng; kiểm tra thành phần/hướng dẫn. Aliases: skin sensitivity.
- **parental consent** (sự đồng ý của người giám hộ): Đặc biệt với thông tin và tương tác của trẻ. Aliases: guardian consent.

#### industry_06_qa_01
**Câu hỏi:** age grade là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** độ tuổi phù hợp nghĩa là gì? | Cho mình hỏi về age grade | tháng/năm là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Dùng đúng chỉ định nhà sản xuất; không suy ra chỉ từ ảnh. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_06_qa_02
**Câu hỏi:** supervision là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** cần người lớn giám sát nghĩa là gì? | Cho mình hỏi về supervision | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Cảnh báo an toàn theo hướng dẫn sản phẩm. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_06_qa_03
**Câu hỏi:** choking hazard là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** nguy cơ hóc nghẹn nghĩa là gì? | Cho mình hỏi về choking hazard | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Tuân thủ cảnh báo chi tiết và không thay bằng lời đảm bảo. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_06_qa_04
**Câu hỏi:** sleep safety là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** an toàn giấc ngủ nghĩa là gì? | Cho mình hỏi về sleep safety | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ cung cấp thông tin từ nguồn y tế/chính thức được shop duyệt. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_06_qa_05
**Câu hỏi:** size chart là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** bảng cỡ nghĩa là gì? | Cho mình hỏi về size chart | cm/kg là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Bảng của hãng; độ tuổi không bảo đảm vừa. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_06_qa_06
**Câu hỏi:** sterilization là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** tiệt trùng nghĩa là gì? | Cho mình hỏi về sterilization | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Thực hiện theo hướng dẫn thiết bị/sản phẩm. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_06_qa_07
**Câu hỏi:** feeding stage là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** giai đoạn ăn nghĩa là gì? | Cho mình hỏi về feeding stage | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Theo nhãn và hướng dẫn chuyên môn phù hợp. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_06_qa_08
**Câu hỏi:** batch code là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** mã lô nghĩa là gì? | Cho mình hỏi về batch code | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Dùng khi tra hạn, nguồn gốc hoặc thông báo thu hồi. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_06_qa_09
**Câu hỏi:** skin sensitivity khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh skin sensitivity giúp mình | nhạy cảm da có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Không chẩn đoán dị ứng; kiểm tra thành phần/hướng dẫn. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_06_qa_10
**Câu hỏi:** parental consent khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh parental consent giúp mình | sự đồng ý của người giám hộ có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Đặc biệt với thông tin và tương tác của trẻ. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_06_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Đồ dùng và thiết bị trẻ em, trước hết cần biết độ tuổi/giai đoạn do khách cung cấp. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_06_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Quần áo/tã và đồ dệt, trước hết cần biết cân nặng/kích cỡ chỉ khi cần đối chiếu bảng hãng. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_06_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Chăm sóc và dinh dưỡng, trước hết cần biết mục đích sử dụng. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_06_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Đồ dùng và thiết bị trẻ em, trước hết cần biết khả năng lắp đặt. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_06_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Quần áo/tã và đồ dệt, trước hết cần biết dị ứng/nhạy cảm do khách nêu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_06_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Chăm sóc và dinh dưỡng, trước hết cần biết địa chỉ giao. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_06_qa_17
**Câu hỏi:** Sản phẩm dùng cho bé mấy tháng tuổi?
**Cách hỏi khác:** Sản phẩm dùng cho bé mấy tháng tuổi thế nào? | Sản phẩm dùng cho bé mấy tháng tuổi?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Tra đúng chỉ định tuổi của nhà sản xuất trên nhãn/hướng dẫn và SKU. Không suy ra độ tuổi phù hợp từ tên sản phẩm; nếu thiếu, chuyển nhân viên kiểm tra.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_06_qa_18
**Câu hỏi:** Size quần áo/tã nào phù hợp?
**Cách hỏi khác:** Size quần áo/tã nào phù hợp thế nào? | Size quần áo/tã nào phù hợp?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Đối chiếu bảng size chính thức và số đo/cân nặng khách cung cấp nếu bảng yêu cầu. Độ tuổi chỉ là tham khảo của hãng; không cam kết vừa.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_06_qa_19
**Câu hỏi:** Sản phẩm có an toàn tuyệt đối cho trẻ không?
**Cách hỏi khác:** Sản phẩm có an toàn tuyệt đối cho trẻ không thế nào? | Sản phẩm có an toàn tuyệt đối cho trẻ không?
**Intent:** product_information
**Câu trả lời gợi ý:** Không thể bảo đảm an toàn tuyệt đối. Chỉ cung cấp vật liệu, cảnh báo và cách dùng đã xác minh; cần đọc nhãn và tuân thủ giám sát/hướng dẫn.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_06_qa_20
**Câu hỏi:** Bé có dấu hiệu khó thở sau khi dùng sản phẩm thì sao?
**Cách hỏi khác:** Bé có dấu hiệu khó thở sau khi dùng sản phẩm thì sao thế nào? | Bé có dấu hiệu khó thở sau khi dùng sản phẩm thì sao?
**Intent:** human_handoff
**Câu trả lời gợi ý:** Đây có thể là tình huống khẩn cấp. Ngừng tiếp xúc nếu an toàn và tìm trợ giúp y tế khẩn cấp ngay; chatbot không chẩn đoán. Nhân viên shop có thể hỗ trợ hồ sơ đơn sau khi trẻ được chăm sóc.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_06_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_06_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_06_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_06_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_06_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_06_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_06_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_06_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_06_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_06_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_07 Phụ kiện điện thoại & máy tính

### Phạm vi ngành
Ngành phụ kiện thiết bị gồm cáp, sạc, ốp, thiết bị nhập liệu, lưu trữ và kết nối. Tương thích là khóa tư vấn: đối chiếu model thiết bị, chuẩn/cổng, công suất và chức năng được hỗ trợ; hình dáng cổng giống nhau không đồng nghĩa tính năng giống nhau.

### Thuật ngữ và FAQ
- **USB-C** (cổng USB Type-C): Kiểu đầu nối; không mặc định hỗ trợ mọi tốc độ/chế độ. Aliases: USB Type-C.
- **PD** (sạc Power Delivery): Chuẩn cần hỗ trợ cả bộ sạc, cáp và thiết bị. Aliases: USB Power Delivery.
- **QC** (sạc nhanh Quick Charge): Chỉ xác nhận phiên bản tương thích theo nguồn. Aliases: Quick Charge.
- **MagSafe** (phụ kiện/chuẩn từ tính): Tên chuẩn/nhãn hệ sinh thái; không suy rộng sang phụ kiện tương tự. Aliases: MagSafe.
- **OTG** (kết nối thiết bị ngoại vi): Phụ thuộc hỗ trợ của thiết bị/cáp/ứng dụng. Aliases: USB On-The-Go.
- **MFi** (chứng nhận phụ kiện): Không khẳng định chứng nhận nếu thiếu hồ sơ. Aliases: Made for iPhone/iPad.
- **DPI** (độ nhạy chuột): Thông số cấu hình/nhãn, không nhất thiết đo chất lượng. Aliases: dots per inch.
- **layout** (bố cục bàn phím): Bố trí phím và ngôn ngữ. Aliases: keyboard layout.
- **form factor** (kiểu kích thước): Dạng vật lý của linh kiện/phụ kiện. Aliases: form factor.
- **data rate** (tốc độ truyền dữ liệu): Tốc độ chuẩn không đảm bảo tốc độ thực tế trên mọi thiết bị. Aliases: transfer rate.

#### industry_07_qa_01
**Câu hỏi:** USB-C là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** cổng USB Type-C nghĩa là gì? | Cho mình hỏi về USB-C | USB-C là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Kiểu đầu nối; không mặc định hỗ trợ mọi tốc độ/chế độ. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_07_qa_02
**Câu hỏi:** PD là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** sạc Power Delivery nghĩa là gì? | Cho mình hỏi về PD | PD là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chuẩn cần hỗ trợ cả bộ sạc, cáp và thiết bị. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_07_qa_03
**Câu hỏi:** QC là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** sạc nhanh Quick Charge nghĩa là gì? | Cho mình hỏi về QC | QC là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ xác nhận phiên bản tương thích theo nguồn. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_07_qa_04
**Câu hỏi:** MagSafe là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** phụ kiện/chuẩn từ tính nghĩa là gì? | Cho mình hỏi về MagSafe | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Tên chuẩn/nhãn hệ sinh thái; không suy rộng sang phụ kiện tương tự. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_07_qa_05
**Câu hỏi:** OTG là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** kết nối thiết bị ngoại vi nghĩa là gì? | Cho mình hỏi về OTG | OTG là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Phụ thuộc hỗ trợ của thiết bị/cáp/ứng dụng. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_07_qa_06
**Câu hỏi:** MFi là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** chứng nhận phụ kiện nghĩa là gì? | Cho mình hỏi về MFi | MFi là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Không khẳng định chứng nhận nếu thiếu hồ sơ. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_07_qa_07
**Câu hỏi:** DPI là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** độ nhạy chuột nghĩa là gì? | Cho mình hỏi về DPI | DPI là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Thông số cấu hình/nhãn, không nhất thiết đo chất lượng. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_07_qa_08
**Câu hỏi:** layout là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** bố cục bàn phím nghĩa là gì? | Cho mình hỏi về layout | ANSI/ISO… là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Bố trí phím và ngôn ngữ. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_07_qa_09
**Câu hỏi:** form factor khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh form factor giúp mình | kiểu kích thước có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Dạng vật lý của linh kiện/phụ kiện. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_07_qa_10
**Câu hỏi:** data rate khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh data rate giúp mình | tốc độ truyền dữ liệu có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Tốc độ chuẩn không đảm bảo tốc độ thực tế trên mọi thiết bị. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_07_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Cáp, sạc và nguồn, trước hết cần biết hãng và model thiết bị. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_07_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Ốp, kính và phụ kiện ngoại hình, trước hết cần biết cổng/chuẩn hiện có. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_07_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Lưu trữ, nhập liệu và kết nối, trước hết cần biết nhu cầu sạc, dữ liệu hay hình ảnh. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_07_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Cáp, sạc và nguồn, trước hết cần biết chiều dài cáp. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_07_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Ốp, kính và phụ kiện ngoại hình, trước hết cần biết bố cục bàn phím. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_07_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Lưu trữ, nhập liệu và kết nối, trước hết cần biết màu/kiểu dáng. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_07_qa_17
**Câu hỏi:** Ốp này vừa điện thoại model nào?
**Cách hỏi khác:** Ốp này vừa điện thoại model nào thế nào? | Ốp này vừa điện thoại model nào?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ xác nhận model liệt kê cho đúng SKU; tên dòng có thể có nhiều kích thước/cụm camera. Hỏi mã model trong Cài đặt hoặc trên hộp nếu khách chưa chắc.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_07_qa_18
**Câu hỏi:** Cáp này có sạc nhanh không?
**Cách hỏi khác:** Cáp này có sạc nhanh không thế nào? | Cáp này có sạc nhanh không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Đối chiếu chuẩn và công suất của cáp, adapter và thiết bị; cả ba phía cần tương thích. Không khẳng định sạc nhanh chỉ vì đầu cắm là USB-C.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_07_qa_19
**Câu hỏi:** Hub này xuất được màn hình 4K không?
**Cách hỏi khác:** Hub này xuất được màn hình 4K không thế nào? | Hub này xuất được màn hình 4K không?
**Intent:** product_information
**Câu trả lời gợi ý:** Cần kiểm tra thông số hub, cổng thiết bị chủ, cáp/màn hình và tần số hỗ trợ. Nếu thiếu một phần, nêu điều kiện cần xác minh thay vì bảo đảm.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_07_qa_20
**Câu hỏi:** Pin dự phòng bị phồng thì còn dùng được không?
**Cách hỏi khác:** Pin dự phòng bị phồng thì còn dùng được không thế nào? | Pin dự phòng bị phồng thì còn dùng được không?
**Intent:** compatibility_check
**Câu trả lời gợi ý:** Không tiếp tục sạc hoặc sử dụng pin phồng. Tránh đè/chọc thủng và làm theo hướng dẫn xử lý an toàn/điểm thu hồi phù hợp; liên hệ nhân viên để hỗ trợ bảo hành nếu có.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_07_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_07_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_07_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_07_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_07_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_07_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_07_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_07_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_07_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_07_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_08 Thể thao & dã ngoại

### Phạm vi ngành
Sản phẩm vận động, tập luyện và hoạt động ngoài trời. Khả năng phù hợp dựa vào môn/hoạt động, môi trường, size, tải trọng, tiêu chuẩn thiết bị và hướng dẫn bảo trì; không thay thế huấn luyện chuyên môn hoặc khuyến nghị y tế.

### Thuật ngữ và FAQ
- **drop** (độ chênh): Chênh cao gót-mũi theo thông số giày. Aliases: heel-to-toe drop.
- **grip** (độ bám): Mô tả/đặc tính đế; không bảo đảm chống trượt mọi điều kiện. Aliases: traction.
- **load rating** (tải trọng công bố): Giới hạn sản phẩm theo hãng và cách lắp. Aliases: weight capacity.
- **waterproof rating** (mức chống nước công bố): Không đồng nhất với chống nước trong mọi thời gian/độ sâu. Aliases: waterproof rating.
- **R-value** (chỉ số cách nhiệt): Chỉ giải thích khi sản phẩm có thông số. Aliases: thermal resistance.
- **taper** (độ thuôn): Hình dạng lều/túi ngủ hoặc dụng cụ theo thiết kế. Aliases: taper.
- **carabiner** (móc khóa leo núi): Thiết bị chịu lực phải kiểm tra chứng nhận và tải trọng. Aliases: carabiner.
- **hydration bladder** (túi nước): Dung tích theo thông số nhà sản xuất. Aliases: hydration reservoir.
- **layering** (mặc nhiều lớp): Nguyên tắc trang phục; điều chỉnh theo điều kiện thực tế. Aliases: layering system.
- **maintenance** (bảo trì): Theo hướng dẫn, đặc biệt thiết bị bảo hộ/chịu lực. Aliases: gear care.

#### industry_08_qa_01
**Câu hỏi:** drop là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** độ chênh nghĩa là gì? | Cho mình hỏi về drop | mm là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chênh cao gót-mũi theo thông số giày. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_08_qa_02
**Câu hỏi:** grip là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** độ bám nghĩa là gì? | Cho mình hỏi về grip | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Mô tả/đặc tính đế; không bảo đảm chống trượt mọi điều kiện. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_08_qa_03
**Câu hỏi:** load rating là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** tải trọng công bố nghĩa là gì? | Cho mình hỏi về load rating | kg là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Giới hạn sản phẩm theo hãng và cách lắp. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_08_qa_04
**Câu hỏi:** waterproof rating là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** mức chống nước công bố nghĩa là gì? | Cho mình hỏi về waterproof rating | mã/đơn vị hãng là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Không đồng nhất với chống nước trong mọi thời gian/độ sâu. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_08_qa_05
**Câu hỏi:** R-value là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** chỉ số cách nhiệt nghĩa là gì? | Cho mình hỏi về R-value | R-value là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ giải thích khi sản phẩm có thông số. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_08_qa_06
**Câu hỏi:** taper là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** độ thuôn nghĩa là gì? | Cho mình hỏi về taper | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Hình dạng lều/túi ngủ hoặc dụng cụ theo thiết kế. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_08_qa_07
**Câu hỏi:** carabiner là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** móc khóa leo núi nghĩa là gì? | Cho mình hỏi về carabiner | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Thiết bị chịu lực phải kiểm tra chứng nhận và tải trọng. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_08_qa_08
**Câu hỏi:** hydration bladder là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** túi nước nghĩa là gì? | Cho mình hỏi về hydration bladder | L là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Dung tích theo thông số nhà sản xuất. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_08_qa_09
**Câu hỏi:** layering khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh layering giúp mình | mặc nhiều lớp có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Nguyên tắc trang phục; điều chỉnh theo điều kiện thực tế. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_08_qa_10
**Câu hỏi:** maintenance khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh maintenance giúp mình | bảo trì có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Theo hướng dẫn, đặc biệt thiết bị bảo hộ/chịu lực. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_08_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Trang phục và giày thể thao, trước hết cần biết môn/hoạt động. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_08_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dụng cụ tập luyện, trước hết cần biết mức độ kinh nghiệm do khách tự nêu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_08_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Cắm trại và dã ngoại, trước hết cần biết địa hình/thời tiết. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_08_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Trang phục và giày thể thao, trước hết cần biết size/cỡ. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_08_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dụng cụ tập luyện, trước hết cần biết khối lượng cần mang. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_08_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Cắm trại và dã ngoại, trước hết cần biết nhóm đi cùng. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_08_qa_17
**Câu hỏi:** Giày này phù hợp chạy địa hình không?
**Cách hỏi khác:** Giày này phù hợp chạy địa hình không thế nào? | Giày này phù hợp chạy địa hình không?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Đối chiếu mô tả hãng về địa hình, đế, form và hoạt động. Hỏi cung đường/điều kiện dự kiến nếu thông tin ảnh hưởng lựa chọn; không bảo đảm chống trượt.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_08_qa_18
**Câu hỏi:** Lều chịu mưa được đến mức nào?
**Cách hỏi khác:** Lều chịu mưa được đến mức nào thế nào? | Lều chịu mưa được đến mức nào?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Chỉ nêu thông số chống nước/cấu trúc nếu catalog hoặc tài liệu hãng ghi rõ. Điều kiện dựng, tuổi vật liệu và thời tiết có thể ảnh hưởng; không hứa chống mọi cơn mưa.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_08_qa_19
**Câu hỏi:** Dây/móc này chịu được bao nhiêu tải?
**Cách hỏi khác:** Dây/móc này chịu được bao nhiêu tải thế nào? | Dây/móc này chịu được bao nhiêu tải?
**Intent:** product_information
**Câu trả lời gợi ý:** Thiết bị chịu lực chỉ trả lời theo rating được xác minh của đúng model và điều kiện sử dụng. Nếu thiếu chứng nhận, không khuyến nghị dùng cho leo trèo/đỡ người.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_08_qa_20
**Câu hỏi:** Thiết bị bảo hộ có phù hợp cho tôi không?
**Cách hỏi khác:** Thiết bị bảo hộ có phù hợp cho tôi không thế nào? | Thiết bị bảo hộ có phù hợp cho mình không?
**Intent:** compatibility_check
**Câu trả lời gợi ý:** Cần xác định hoạt động, kích cỡ và tiêu chuẩn của thiết bị; hướng dẫn hãng hoặc nhân viên chuyên môn xác nhận. Không thay thế huấn luyện an toàn.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_08_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_08_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_08_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_08_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_08_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_08_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_08_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_08_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_08_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_08_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_09 Sách & văn phòng phẩm

### Phạm vi ngành
Bán sách in/số và vật phẩm học tập, làm việc, sáng tạo. Cần phân biệt ấn bản, ngôn ngữ, ISBN, tình trạng sách, định dạng, khổ giấy, loại ngòi/mực và tương thích vật tư; không mô tả sai nội dung hay tình trạng bản quyền.

### Thuật ngữ và FAQ
- **ISBN** (mã số sách quốc tế): Định danh một ấn bản; không dùng chung cho mọi bản. Aliases: International Standard Book Number.
- **edition** (ấn bản): Phiên bản xuất bản, có thể khác nội dung/trình bày. Aliases: edition.
- **paperback** (bìa mềm): Dạng đóng sách; thông tin theo sản phẩm. Aliases: softcover.
- **hardcover** (bìa cứng): Dạng bìa; không mặc định có áo bìa. Aliases: hardback.
- **grammage** (định lượng giấy): Khối lượng giấy trên diện tích, theo thông số. Aliases: paper weight.
- **nib** (ngòi bút): Kích cỡ/kiểu ngòi theo mẫu. Aliases: pen nib.
- **refill** (ruột thay thế): Chỉ tương thích với dòng được xác nhận. Aliases: replacement refill.
- **ISBN-13** (mã 13 chữ số): Mã nhận diện ấn bản sách. Aliases: ISBN-13.
- **format** (định dạng): Định dạng được bán, khác quyền sử dụng. Aliases: book format.
- **condition grade** (mức tình trạng): Mô tả tình trạng thực tế, không dùng một quy tắc chung. Aliases: condition.

#### industry_09_qa_01
**Câu hỏi:** ISBN là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** mã số sách quốc tế nghĩa là gì? | Cho mình hỏi về ISBN | ISBN là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Định danh một ấn bản; không dùng chung cho mọi bản. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_09_qa_02
**Câu hỏi:** edition là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** ấn bản nghĩa là gì? | Cho mình hỏi về edition | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Phiên bản xuất bản, có thể khác nội dung/trình bày. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_09_qa_03
**Câu hỏi:** paperback là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** bìa mềm nghĩa là gì? | Cho mình hỏi về paperback | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Dạng đóng sách; thông tin theo sản phẩm. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_09_qa_04
**Câu hỏi:** hardcover là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** bìa cứng nghĩa là gì? | Cho mình hỏi về hardcover | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Dạng bìa; không mặc định có áo bìa. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_09_qa_05
**Câu hỏi:** grammage là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** định lượng giấy nghĩa là gì? | Cho mình hỏi về grammage | gsm là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Khối lượng giấy trên diện tích, theo thông số. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_09_qa_06
**Câu hỏi:** nib là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** ngòi bút nghĩa là gì? | Cho mình hỏi về nib | mm là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Kích cỡ/kiểu ngòi theo mẫu. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_09_qa_07
**Câu hỏi:** refill là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** ruột thay thế nghĩa là gì? | Cho mình hỏi về refill | mã hàng là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ tương thích với dòng được xác nhận. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_09_qa_08
**Câu hỏi:** ISBN-13 là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** mã 13 chữ số nghĩa là gì? | Cho mình hỏi về ISBN-13 | 13 chữ số là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Mã nhận diện ấn bản sách. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_09_qa_09
**Câu hỏi:** format khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh format giúp mình | định dạng có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Định dạng được bán, khác quyền sử dụng. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_09_qa_10
**Câu hỏi:** condition grade khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh condition grade giúp mình | mức tình trạng có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Mô tả tình trạng thực tế, không dùng một quy tắc chung. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_09_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Sách, trước hết cần biết chủ đề/môn học. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_09_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Văn phòng phẩm, trước hết cần biết ngôn ngữ và cấp độ đọc do khách nêu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_09_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dụng cụ học tập/sáng tạo, trước hết cần biết định dạng sách. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_09_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Sách, trước hết cần biết khổ giấy/loại thiết bị. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_09_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Văn phòng phẩm, trước hết cần biết ngân sách. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_09_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dụng cụ học tập/sáng tạo, trước hết cần biết nhu cầu quà tặng. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_09_qa_17
**Câu hỏi:** Có đúng ấn bản/ISBN này không?
**Cách hỏi khác:** Có đúng ấn bản/ISBN này không thế nào? | Có đúng ấn bản/ISBN này không?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Đối chiếu ISBN, nhà xuất bản, lần xuất bản và định dạng trong catalog. Nếu khách có ảnh bìa nhưng không có mã, hỏi tên tác giả/ấn bản để tránh chọn nhầm.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_09_qa_18
**Câu hỏi:** Sách có bao nhiêu trang và ngôn ngữ gì?
**Cách hỏi khác:** Sách có bao nhiêu trang và ngôn ngữ gì thế nào? | Sách có bao nhiêu trang và ngôn ngữ gì?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Tra thông tin của đúng ấn bản trong catalog hoặc metadata nhà xuất bản. Không suy ra từ tên sách vì các bản dịch/ấn bản có thể khác.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_09_qa_19
**Câu hỏi:** Ruột bút này dùng được với bút nào?
**Cách hỏi khác:** Ruột bút này dùng được với bút nào thế nào? | Ruột bút này dùng được với bút nào?
**Intent:** product_information
**Câu trả lời gợi ý:** So mã ruột, kích thước và danh sách model tương thích theo nhà sản xuất. Không khẳng định vừa chỉ dựa vào hình dáng.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_09_qa_20
**Câu hỏi:** Sách bị rách khi nhận thì xử lý sao?
**Cách hỏi khác:** Sách bị rách khi nhận thì xử lý sao thế nào? | Sách bị rách khi nhận thì xử lý sao?
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận mã đơn, ảnh tình trạng và bao bì; quy trình đổi/hoàn theo Shop Policy. Không hứa đổi trước khi kiểm tra điều kiện.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_09_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_09_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_09_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_09_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_09_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_09_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_09_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_09_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_09_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_09_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_10 Thú cưng

### Phạm vi ngành
Ngành sản phẩm và dịch vụ chăm sóc thú cưng gồm thức ăn, vệ sinh, phụ kiện và thiết bị. Khuyến nghị phụ thuộc loài, giống/tuổi/kích thước, hướng dẫn nhãn và nhu cầu đã được chủ nuôi nêu; không chẩn đoán hoặc kê điều trị thú y.

### Thuật ngữ và FAQ
- **life stage** (giai đoạn sống): Phân loại trên nhãn thức ăn/phụ kiện. Aliases: life stage.
- **feeding guide** (hướng dẫn cho ăn): Không thay thế đánh giá dinh dưỡng của bác sĩ thú y. Aliases: feeding instructions.
- **complete feed** (thức ăn hoàn chỉnh): Chỉ dùng nếu nhà sản xuất/nhãn ghi rõ. Aliases: complete pet food.
- **species-specific** (dành riêng cho loài): Không tự mở rộng dùng chéo giữa loài. Aliases: species-specific.
- **harness** (đai yếm): Đối chiếu vòng ngực/cổ với bảng hãng. Aliases: pet harness.
- **enrichment** (làm giàu môi trường): Đồ chơi/hoạt động kích thích hành vi; có giám sát phù hợp. Aliases: enrichment.
- **topical** (dùng ngoài da): Tuân thủ nhãn, tránh liếm/tiếp xúc ngoài hướng dẫn. Aliases: topical.
- **litter** (cát vệ sinh): Vật liệu/quy cách theo sản phẩm. Aliases: cat litter.
- **microchip** (vi mạch định danh): Thiết bị định danh; việc cấy cần chuyên môn phù hợp. Aliases: microchip.
- **veterinary diet** (chế độ ăn thú y): Cần chỉ định/hướng dẫn của bác sĩ thú y. Aliases: therapeutic diet.

#### industry_10_qa_01
**Câu hỏi:** life stage là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** giai đoạn sống nghĩa là gì? | Cho mình hỏi về life stage | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Phân loại trên nhãn thức ăn/phụ kiện. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_10_qa_02
**Câu hỏi:** feeding guide là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** hướng dẫn cho ăn nghĩa là gì? | Cho mình hỏi về feeding guide | g/ngày theo nhãn là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Không thay thế đánh giá dinh dưỡng của bác sĩ thú y. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_10_qa_03
**Câu hỏi:** complete feed là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** thức ăn hoàn chỉnh nghĩa là gì? | Cho mình hỏi về complete feed | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ dùng nếu nhà sản xuất/nhãn ghi rõ. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_10_qa_04
**Câu hỏi:** species-specific là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** dành riêng cho loài nghĩa là gì? | Cho mình hỏi về species-specific | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Không tự mở rộng dùng chéo giữa loài. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_10_qa_05
**Câu hỏi:** harness là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** đai yếm nghĩa là gì? | Cho mình hỏi về harness | cm là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Đối chiếu vòng ngực/cổ với bảng hãng. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_10_qa_06
**Câu hỏi:** enrichment là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** làm giàu môi trường nghĩa là gì? | Cho mình hỏi về enrichment | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Đồ chơi/hoạt động kích thích hành vi; có giám sát phù hợp. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_10_qa_07
**Câu hỏi:** topical là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** dùng ngoài da nghĩa là gì? | Cho mình hỏi về topical | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Tuân thủ nhãn, tránh liếm/tiếp xúc ngoài hướng dẫn. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_10_qa_08
**Câu hỏi:** litter là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** cát vệ sinh nghĩa là gì? | Cho mình hỏi về litter | kg/L là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Vật liệu/quy cách theo sản phẩm. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_10_qa_09
**Câu hỏi:** microchip khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh microchip giúp mình | vi mạch định danh có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Thiết bị định danh; việc cấy cần chuyên môn phù hợp. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_10_qa_10
**Câu hỏi:** veterinary diet khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh veterinary diet giúp mình | chế độ ăn thú y có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Cần chỉ định/hướng dẫn của bác sĩ thú y. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_10_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thức ăn và dinh dưỡng, trước hết cần biết loài thú cưng. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_10_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Phụ kiện và vận chuyển, trước hết cần biết tuổi/cân nặng/kích thước do chủ cung cấp. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_10_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Vệ sinh và chăm sóc, trước hết cần biết mục tiêu sử dụng. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_10_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thức ăn và dinh dưỡng, trước hết cần biết dị ứng/nhạy cảm đã được chẩn đoán do chủ nêu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_10_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Phụ kiện và vận chuyển, trước hết cần biết vật nuôi trong nhà/ngoài trời. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_10_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Vệ sinh và chăm sóc, trước hết cần biết mã đơn. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_10_qa_17
**Câu hỏi:** Thức ăn này dành cho loài/độ tuổi nào?
**Cách hỏi khác:** Thức ăn này dành cho loài/độ tuổi nào thế nào? | Thức ăn này dành cho loài/độ tuổi nào?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Đọc đúng loài và giai đoạn trên nhãn. Nếu chủ nuôi hỏi cho trường hợp bệnh lý, thai kỳ hoặc chế độ thú y, không tự kết luận; nên hỏi bác sĩ thú y.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_10_qa_18
**Câu hỏi:** Khẩu phần mỗi ngày là bao nhiêu?
**Cách hỏi khác:** Khẩu phần mỗi ngày là bao nhiêu thế nào? | Khẩu phần mỗi ngày là bao nhiêu?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Chỉ trích hướng dẫn khẩu phần trên nhãn của đúng sản phẩm và nêu đơn vị/điều kiện cân nặng nếu có. Không tự tính liều hoặc thay đổi khẩu phần theo bệnh.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_10_qa_19
**Câu hỏi:** Đai yếm cỡ nào vừa thú cưng?
**Cách hỏi khác:** Đai yếm cỡ nào vừa thú cưng thế nào? | Đai yếm cỡ nào vừa thú cưng?
**Intent:** product_information
**Câu trả lời gợi ý:** Đo theo hướng dẫn và đối chiếu bảng size chính thức, lưu ý khoảng điều chỉnh. Không chọn chỉ theo giống vì kích thước từng cá thể khác nhau.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_10_qa_20
**Câu hỏi:** Thú cưng vừa ăn nhầm hóa chất và nôn thì làm gì?
**Cách hỏi khác:** Thú cưng vừa ăn nhầm hóa chất và nôn thì làm gì thế nào? | Thú cưng vừa ăn nhầm hóa chất và nôn thì làm gì?
**Intent:** human_handoff
**Câu trả lời gợi ý:** Liên hệ bác sĩ thú y/cơ sở cấp cứu thú y ngay, cung cấp bao bì/tên chất và lượng/thời gian nếu biết. Không tự gây nôn hay cho dùng thuốc nếu chưa được chuyên gia hướng dẫn.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_10_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_10_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_10_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_10_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_10_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_10_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_10_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_10_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_10_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_10_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_11 Phụ tùng ô tô – xe máy

### Phạm vi ngành
Bán phụ tùng thay thế, vật tư bảo dưỡng và phụ kiện phương tiện. Độ tương thích phải dựa trên hãng, dòng xe, đời xe, phiên bản, mã OEM/cross-reference và cấu hình thực tế; không tư vấn lắp đặt an toàn bằng suy đoán.

### Thuật ngữ và FAQ
- **OEM** (mã phụ tùng hãng): Mã định danh linh kiện gốc. Aliases: Original Equipment Manufacturer number.
- **VIN** (số khung nhận dạng xe): Dùng tra cấu hình chính xác; hạn chế thu thập và bảo vệ dữ liệu. Aliases: Vehicle Identification Number.
- **fitment** (khả năng lắp tương thích): Phải theo fitment list cho phiên bản xe. Aliases: vehicle fitment.
- **cross-reference** (mã thay thế đối chiếu): Chỉ dùng khi nguồn catalog xác nhận tương đương. Aliases: cross reference.
- **viscosity** (độ nhớt): Chọn theo sổ tay xe và tiêu chuẩn yêu cầu. Aliases: viscosity grade.
- **brake pad** (má phanh): Bộ phận an toàn; cần lắp/kiểm tra đúng kỹ thuật. Aliases: brake pad.
- **left/right-hand** (bên trái/phải): Quy ước theo hướng nhìn được tài liệu định nghĩa. Aliases: LH/RH.
- **front/rear** (trước/sau): Vị trí lắp trên xe. Aliases: front/rear.
- **aftermarket** (phụ tùng ngoài hãng): Không tự khẳng định chất lượng/tương đương OEM. Aliases: aftermarket part.
- **torque spec** (mô-men siết): Chỉ dùng giá trị từ manual kỹ thuật đúng xe. Aliases: torque specification.

#### industry_11_qa_01
**Câu hỏi:** OEM là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** mã phụ tùng hãng nghĩa là gì? | Cho mình hỏi về OEM | OEM là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Mã định danh linh kiện gốc. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_11_qa_02
**Câu hỏi:** VIN là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** số khung nhận dạng xe nghĩa là gì? | Cho mình hỏi về VIN | VIN là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Dùng tra cấu hình chính xác; hạn chế thu thập và bảo vệ dữ liệu. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_11_qa_03
**Câu hỏi:** fitment là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** khả năng lắp tương thích nghĩa là gì? | Cho mình hỏi về fitment | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Phải theo fitment list cho phiên bản xe. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_11_qa_04
**Câu hỏi:** cross-reference là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** mã thay thế đối chiếu nghĩa là gì? | Cho mình hỏi về cross-reference | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ dùng khi nguồn catalog xác nhận tương đương. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_11_qa_05
**Câu hỏi:** viscosity là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** độ nhớt nghĩa là gì? | Cho mình hỏi về viscosity | SAE… là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chọn theo sổ tay xe và tiêu chuẩn yêu cầu. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_11_qa_06
**Câu hỏi:** brake pad là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** má phanh nghĩa là gì? | Cho mình hỏi về brake pad | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Bộ phận an toàn; cần lắp/kiểm tra đúng kỹ thuật. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_11_qa_07
**Câu hỏi:** left/right-hand là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** bên trái/phải nghĩa là gì? | Cho mình hỏi về left/right-hand | LH/RH là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Quy ước theo hướng nhìn được tài liệu định nghĩa. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_11_qa_08
**Câu hỏi:** front/rear là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** trước/sau nghĩa là gì? | Cho mình hỏi về front/rear | F/R là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Vị trí lắp trên xe. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_11_qa_09
**Câu hỏi:** aftermarket khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh aftermarket giúp mình | phụ tùng ngoài hãng có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Không tự khẳng định chất lượng/tương đương OEM. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_11_qa_10
**Câu hỏi:** torque spec khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh torque spec giúp mình | mô-men siết có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Chỉ dùng giá trị từ manual kỹ thuật đúng xe. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_11_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Phụ tùng thay thế, trước hết cần biết hãng/dòng/năm sản xuất/phiên bản. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_11_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dầu nhớt và vật tư bảo dưỡng, trước hết cần biết mã VIN hoặc mã phụ tùng do khách chủ động cung cấp. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_11_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Phụ kiện điện/ngoại thất, trước hết cần biết động cơ/hộp số. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_11_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Phụ tùng thay thế, trước hết cần biết bên lắp trái/phải. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_11_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dầu nhớt và vật tư bảo dưỡng, trước hết cần biết mục đích sửa chữa. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_11_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Phụ kiện điện/ngoại thất, trước hết cần biết khu vực lắp đặt. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_11_qa_17
**Câu hỏi:** Phụ tùng này có đúng xe của tôi không?
**Cách hỏi khác:** Phụ tùng này có đúng xe của tôi không thế nào? | Phụ tùng này có đúng xe của mình không?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Cần hãng, dòng, năm, phiên bản/động cơ hoặc mã OEM. Đối chiếu catalog fitment chính thức; nếu nhiều cấu hình, yêu cầu kỹ thuật viên xác nhận trước khi đặt.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_11_qa_18
**Câu hỏi:** Mã phụ tùng OEM ở đâu?
**Cách hỏi khác:** Mã phụ tùng OEM ở đâu thế nào? | Mã phụ tùng OEM ở đâu?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Có thể tra trên hóa đơn, nhãn phụ tùng cũ hoặc catalog hãng; vị trí tùy bộ phận. Không tháo bộ phận nguy hiểm để tìm mã; có thể cung cấp VIN cho nhân viên theo quy trình bảo mật.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_11_qa_19
**Câu hỏi:** Xe này cần dùng loại dầu nào?
**Cách hỏi khác:** Xe này cần dùng loại dầu nào thế nào? | Xe này cần dùng loại dầu nào?
**Intent:** product_information
**Câu trả lời gợi ý:** Tra sổ tay đúng xe và tiêu chuẩn/độ nhớt nhà sản xuất yêu cầu, rồi đối chiếu nhãn sản phẩm. Không chọn chỉ theo dung tích động cơ hoặc thương hiệu.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_11_qa_20
**Câu hỏi:** Tôi tự thay má phanh được không?
**Cách hỏi khác:** Tôi tự thay má phanh được không thế nào? | Mình tự thay má phanh được không?
**Intent:** human_handoff
**Câu trả lời gợi ý:** Má phanh là bộ phận an toàn và cần dụng cụ, quy trình, thông số siết và kiểm tra phù hợp. Nên giao kỹ thuật viên đủ chuyên môn; chatbot không hướng dẫn thao tác thay khi không thể xác nhận điều kiện.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_11_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_11_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_11_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_11_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_11_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_11_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_11_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_11_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_11_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_11_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_12 Sức khỏe & thực phẩm chức năng

### Phạm vi ngành
Ngành hàng sức khỏe và sản phẩm bổ sung có rủi ro cao về tuyên bố công dụng, chống chỉ định, tương tác và quảng cáo. Profile chỉ hỗ trợ đọc nhãn/nguồn được duyệt và quy trình bán hàng; không chẩn đoán, điều trị, kê liều hoặc hứa hiệu quả.

### Thuật ngữ và FAQ
- **dietary supplement** (thực phẩm bổ sung): Không đồng nghĩa thuốc hoặc được phép điều trị bệnh. Aliases: food supplement.
- **serving** (khẩu phần): Lượng dùng trên nhãn; không phải tư vấn liều cá nhân. Aliases: serving size.
- **active ingredient** (thành phần hoạt tính): Chỉ ghi hàm lượng và tác dụng được phép công bố. Aliases: active ingredient.
- **contraindication** (chống chỉ định/cảnh báo): Nguồn nhãn/chuyên môn; chuyển chuyên gia khi cá nhân hóa. Aliases: contraindication.
- **interaction** (tương tác): Không dự đoán từ kiến thức chung; yêu cầu nhân viên y tế. Aliases: interaction.
- **batch/lot** (mã lô): Truy xuất từng đơn vị/lô. Aliases: batch number.
- **registration number** (số hồ sơ/đăng ký): Xác minh trên giấy tờ có thẩm quyền. Aliases: registration ID.
- **adverse event** (biến cố bất lợi): Quy trình tiếp nhận/chuyển chuyên môn. Aliases: adverse event.
- **intended use** (mục đích sử dụng): Phạm vi do nhà sản xuất/hồ sơ xác lập. Aliases: intended purpose.
- **claim substantiation** (căn cứ tuyên bố): Tuyên bố marketing phải có hồ sơ hợp lệ và được duyệt. Aliases: claim evidence.

#### industry_12_qa_01
**Câu hỏi:** dietary supplement là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** thực phẩm bổ sung nghĩa là gì? | Cho mình hỏi về dietary supplement | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Không đồng nghĩa thuốc hoặc được phép điều trị bệnh. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_12_qa_02
**Câu hỏi:** serving là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** khẩu phần nghĩa là gì? | Cho mình hỏi về serving | theo nhãn là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Lượng dùng trên nhãn; không phải tư vấn liều cá nhân. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_12_qa_03
**Câu hỏi:** active ingredient là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** thành phần hoạt tính nghĩa là gì? | Cho mình hỏi về active ingredient | mg/µg… là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ ghi hàm lượng và tác dụng được phép công bố. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_12_qa_04
**Câu hỏi:** contraindication là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** chống chỉ định/cảnh báo nghĩa là gì? | Cho mình hỏi về contraindication | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Nguồn nhãn/chuyên môn; chuyển chuyên gia khi cá nhân hóa. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_12_qa_05
**Câu hỏi:** interaction là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** tương tác nghĩa là gì? | Cho mình hỏi về interaction | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Không dự đoán từ kiến thức chung; yêu cầu nhân viên y tế. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_12_qa_06
**Câu hỏi:** batch/lot là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** mã lô nghĩa là gì? | Cho mình hỏi về batch/lot | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Truy xuất từng đơn vị/lô. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_12_qa_07
**Câu hỏi:** registration number là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** số hồ sơ/đăng ký nghĩa là gì? | Cho mình hỏi về registration number | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Xác minh trên giấy tờ có thẩm quyền. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_12_qa_08
**Câu hỏi:** adverse event là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** biến cố bất lợi nghĩa là gì? | Cho mình hỏi về adverse event | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Quy trình tiếp nhận/chuyển chuyên môn. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_12_qa_09
**Câu hỏi:** intended use khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh intended use giúp mình | mục đích sử dụng có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Phạm vi do nhà sản xuất/hồ sơ xác lập. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_12_qa_10
**Câu hỏi:** claim substantiation khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh claim substantiation giúp mình | căn cứ tuyên bố có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Tuyên bố marketing phải có hồ sơ hợp lệ và được duyệt. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_12_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thực phẩm bổ sung, trước hết cần biết câu hỏi về nhãn/thành phần. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_12_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thiết bị chăm sóc sức khỏe, trước hết cần biết nhu cầu sản phẩm phi chẩn đoán. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_12_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Chăm sóc cá nhân liên quan sức khỏe, trước hết cần biết tuổi/nhóm sử dụng chỉ khi nhãn yêu cầu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_12_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thực phẩm bổ sung, trước hết cần biết dị ứng/tình trạng sức khỏe do khách tự nêu (không lưu ngoài quy trình cần thiết). Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_12_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Thiết bị chăm sóc sức khỏe, trước hết cần biết đang dùng thuốc cần chuyển chuyên gia. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_12_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Chăm sóc cá nhân liên quan sức khỏe, trước hết cần biết mã lô. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_12_qa_17
**Câu hỏi:** Sản phẩm này có chữa bệnh X không?
**Cách hỏi khác:** Sản phẩm này có chữa bệnh X không thế nào? | Sản phẩm này có chữa bệnh X không?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Không thể kết luận hoặc hứa điều trị. Chỉ cung cấp nội dung công dụng đã được phê duyệt trên nhãn/hồ sơ hợp lệ; vui lòng hỏi chuyên gia y tế về chẩn đoán và điều trị.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_12_qa_18
**Câu hỏi:** Tôi đang dùng thuốc, uống sản phẩm này được không?
**Cách hỏi khác:** Tôi đang dùng thuốc, uống sản phẩm này được không thế nào? | Mình đang dùng thuốc, uống sản phẩm này được không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Tương tác phụ thuộc thuốc, liều và tình trạng sức khỏe; chatbot không thể xác nhận an toàn. Hãy hỏi bác sĩ/dược sĩ và cung cấp nhãn thành phần nếu cần.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_12_qa_19
**Câu hỏi:** Mỗi ngày nên dùng bao nhiêu?
**Cách hỏi khác:** Mỗi ngày nên dùng bao nhiêu thế nào? | Mỗi ngày nên dùng bao nhiêu?
**Intent:** product_information
**Câu trả lời gợi ý:** Chỉ trích đúng hướng dẫn sử dụng trên nhãn, không điều chỉnh liều cá nhân. Nếu khách hỏi liều khác nhãn, có bệnh nền, mang thai hoặc đang dùng thuốc, chuyển chuyên gia.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_12_qa_20
**Câu hỏi:** Tôi thấy khó thở sau khi dùng sản phẩm
**Cách hỏi khác:** Tôi thấy khó thở sau khi dùng sản phẩm | Mình thấy khó thở sau khi dùng sản phẩm
**Intent:** human_handoff
**Câu trả lời gợi ý:** Khó thở có thể là tình huống cấp cứu. Ngừng sử dụng nếu an toàn và gọi dịch vụ cấp cứu/y tế ngay; không chờ chatbot hoặc nhân viên bán hàng đánh giá.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_12_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_12_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_12_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_12_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_12_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_12_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_12_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_12_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_12_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_12_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_13 Spa & thẩm mỹ

### Phạm vi ngành
Ngành dịch vụ chăm sóc sắc đẹp gồm liệu trình, chăm sóc thư giãn và dịch vụ thẩm mỹ trong phạm vi được cấp phép. Cần phân biệt thông tin dịch vụ, điều kiện thực hiện, tư vấn chuyên môn, đặt lịch, nhân sự, giá và chính sách do từng cơ sở cấu hình.

### Thuật ngữ và FAQ
- **consultation** (buổi tư vấn): Không đồng nghĩa chẩn đoán hay cam kết có thể thực hiện. Aliases: consult.
- **contraindication** (điều kiện cần sàng lọc): Cần hỏi theo quy trình cơ sở/chuyên môn. Aliases: contraindication.
- **aftercare** (chăm sóc sau dịch vụ): Chỉ đưa hướng dẫn được cơ sở duyệt. Aliases: post-care.
- **patch test** (thử phản ứng tại vùng nhỏ): Chỉ nêu nếu quy trình dịch vụ chính thức quy định. Aliases: patch test.
- **treatment plan** (kế hoạch liệu trình): Do người đủ chuyên môn xác định; không ép mua gói. Aliases: service plan.
- **booking slot** (khung lịch hẹn): Trạng thái phải lấy từ lịch CRM trực tiếp. Aliases: appointment slot.
- **no-show** (không đến hẹn): Áp dụng theo quy định cơ sở đã cấu hình. Aliases: no-show.
- **deposit** (tiền đặt cọc): Chỉ báo mức/điều kiện từ CRM/Shop Policy. Aliases: booking deposit.
- **licensed service** (dịch vụ có phạm vi cấp phép): Không quảng bá dịch vụ ngoài phạm vi được xác nhận. Aliases: licensed scope.
- **handoff** (chuyển nhân viên): Dùng khi cần đánh giá chuyên môn/ngoại lệ. Aliases: human handoff.

#### industry_13_qa_01
**Câu hỏi:** consultation là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** buổi tư vấn nghĩa là gì? | Cho mình hỏi về consultation | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Không đồng nghĩa chẩn đoán hay cam kết có thể thực hiện. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_13_qa_02
**Câu hỏi:** contraindication là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** điều kiện cần sàng lọc nghĩa là gì? | Cho mình hỏi về contraindication | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Cần hỏi theo quy trình cơ sở/chuyên môn. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_13_qa_03
**Câu hỏi:** aftercare là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** chăm sóc sau dịch vụ nghĩa là gì? | Cho mình hỏi về aftercare | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ đưa hướng dẫn được cơ sở duyệt. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_13_qa_04
**Câu hỏi:** patch test là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** thử phản ứng tại vùng nhỏ nghĩa là gì? | Cho mình hỏi về patch test | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ nêu nếu quy trình dịch vụ chính thức quy định. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_13_qa_05
**Câu hỏi:** treatment plan là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** kế hoạch liệu trình nghĩa là gì? | Cho mình hỏi về treatment plan | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Do người đủ chuyên môn xác định; không ép mua gói. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_13_qa_06
**Câu hỏi:** booking slot là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** khung lịch hẹn nghĩa là gì? | Cho mình hỏi về booking slot | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Trạng thái phải lấy từ lịch CRM trực tiếp. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_13_qa_07
**Câu hỏi:** no-show là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** không đến hẹn nghĩa là gì? | Cho mình hỏi về no-show | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Áp dụng theo quy định cơ sở đã cấu hình. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_13_qa_08
**Câu hỏi:** deposit là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** tiền đặt cọc nghĩa là gì? | Cho mình hỏi về deposit | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ báo mức/điều kiện từ CRM/Shop Policy. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_13_qa_09
**Câu hỏi:** licensed service khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh licensed service giúp mình | dịch vụ có phạm vi cấp phép có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Không quảng bá dịch vụ ngoài phạm vi được xác nhận. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_13_qa_10
**Câu hỏi:** handoff khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh handoff giúp mình | chuyển nhân viên có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Dùng khi cần đánh giá chuyên môn/ngoại lệ. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_13_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dịch vụ/liệu trình, trước hết cần biết dịch vụ khách quan tâm. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_13_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Gói/khuyến mãi dịch vụ, trước hết cần biết cơ sở/khu vực. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_13_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Lịch hẹn, trước hết cần biết thời gian mong muốn. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_13_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dịch vụ/liệu trình, trước hết cần biết điều kiện cần sàng lọc qua nhân viên chuyên môn. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_13_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Gói/khuyến mãi dịch vụ, trước hết cần biết nhân sự nếu khách yêu cầu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_13_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Lịch hẹn, trước hết cần biết mã lịch hẹn. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_13_qa_17
**Câu hỏi:** Dịch vụ này có phù hợp với tôi không?
**Cách hỏi khác:** Dịch vụ này có phù hợp với tôi không thế nào? | Dịch vụ này có phù hợp với mình không?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Có thể cung cấp phạm vi và điều kiện đã được cơ sở duyệt; phù hợp cá nhân cần được nhân viên đủ chuyên môn sàng lọc. Không chẩn đoán qua chat hoặc bảo đảm kết quả.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_13_qa_18
**Câu hỏi:** Giá liệu trình/gói hiện tại là bao nhiêu?
**Cách hỏi khác:** Giá liệu trình/gói hiện tại là bao nhiêu thế nào? | Giá liệu trình/gói hiện tại là bao nhiêu?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Tra bảng giá/khuyến mãi CRM đang hiệu lực, điều kiện áp dụng và cơ sở thực hiện. Không dùng giá trong tài liệu kiến thức làm giá hiện hành.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_13_qa_19
**Câu hỏi:** Tôi muốn đặt lịch chiều mai
**Cách hỏi khác:** Tôi muốn đặt lịch chiều mai | Mình muốn đặt lịch chiều mai
**Intent:** product_information
**Câu trả lời gợi ý:** Kiểm tra lịch CRM theo dịch vụ, cơ sở và nhân sự; tạo yêu cầu trước. Chỉ xác nhận lịch khi hệ thống chuyển trạng thái confirmed.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_13_qa_20
**Câu hỏi:** Sau dịch vụ tôi sưng đau nhiều thì sao?
**Cách hỏi khác:** Sau dịch vụ tôi sưng đau nhiều thì sao thế nào? | Sau dịch vụ mình sưng đau nhiều thì sao?
**Intent:** human_handoff
**Câu trả lời gợi ý:** Không chẩn đoán qua chatbot. Hướng dẫn liên hệ ngay cơ sở/người thực hiện để được đánh giá; nếu triệu chứng nghiêm trọng hoặc cấp tính, tìm hỗ trợ y tế khẩn cấp.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_13_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_13_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_13_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_13_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_13_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_13_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_13_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_13_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_13_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_13_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_14 Phòng khám & nha khoa

### Phạm vi ngành
Ngành cung cấp dịch vụ khám/chăm sóc sức khỏe. Profile dùng cho thông tin hành chính, lịch hẹn và hướng dẫn quy trình đã duyệt; mọi chẩn đoán, phân loại cấp cứu, chỉ định xét nghiệm/điều trị và tư vấn cá nhân phải do nhân viên y tế có thẩm quyền thực hiện.

### Thuật ngữ và FAQ
- **triage** (phân loại mức độ ưu tiên): Do nhân viên y tế/đường dây được phê duyệt thực hiện. Aliases: clinical triage.
- **appointment** (lịch hẹn khám): Xác nhận qua lịch CRM, không từ tin nhắn dự kiến. Aliases: appointment.
- **referral** (chuyển tuyến): Quyết định chuyên môn. Aliases: referral.
- **informed consent** (đồng ý sau khi được giải thích): Quy trình của cơ sở, không thay bằng chatbot. Aliases: informed consent.
- **medical record** (hồ sơ bệnh án): Dữ liệu nhạy cảm, truy cập theo quyền và mục đích. Aliases: medical record.
- **copay** (khoản cùng chi trả): Chỉ thông tin theo quyền lợi và xác nhận của cơ sở/bảo hiểm. Aliases: co-payment.
- **follow-up** (tái khám/theo dõi): Theo chỉ định của nhân viên y tế. Aliases: follow-up.
- **specialty** (chuyên khoa): Danh mục chuyên khoa được cơ sở công bố. Aliases: medical specialty.
- **dental cleaning** (làm sạch răng chuyên môn): Mô tả dịch vụ không thay chẩn đoán. Aliases: professional cleaning.
- **emergency** (cấp cứu): Hướng dẫn liên hệ dịch vụ khẩn cấp phù hợp. Aliases: emergency care.

#### industry_14_qa_01
**Câu hỏi:** triage là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** phân loại mức độ ưu tiên nghĩa là gì? | Cho mình hỏi về triage | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Do nhân viên y tế/đường dây được phê duyệt thực hiện. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_14_qa_02
**Câu hỏi:** appointment là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** lịch hẹn khám nghĩa là gì? | Cho mình hỏi về appointment | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Xác nhận qua lịch CRM, không từ tin nhắn dự kiến. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_14_qa_03
**Câu hỏi:** referral là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** chuyển tuyến nghĩa là gì? | Cho mình hỏi về referral | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Quyết định chuyên môn. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_14_qa_04
**Câu hỏi:** informed consent là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** đồng ý sau khi được giải thích nghĩa là gì? | Cho mình hỏi về informed consent | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Quy trình của cơ sở, không thay bằng chatbot. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_14_qa_05
**Câu hỏi:** medical record là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** hồ sơ bệnh án nghĩa là gì? | Cho mình hỏi về medical record | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Dữ liệu nhạy cảm, truy cập theo quyền và mục đích. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_14_qa_06
**Câu hỏi:** copay là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** khoản cùng chi trả nghĩa là gì? | Cho mình hỏi về copay | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ thông tin theo quyền lợi và xác nhận của cơ sở/bảo hiểm. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_14_qa_07
**Câu hỏi:** follow-up là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** tái khám/theo dõi nghĩa là gì? | Cho mình hỏi về follow-up | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Theo chỉ định của nhân viên y tế. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_14_qa_08
**Câu hỏi:** specialty là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** chuyên khoa nghĩa là gì? | Cho mình hỏi về specialty | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Danh mục chuyên khoa được cơ sở công bố. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_14_qa_09
**Câu hỏi:** dental cleaning khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh dental cleaning giúp mình | làm sạch răng chuyên môn có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Mô tả dịch vụ không thay chẩn đoán. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_14_qa_10
**Câu hỏi:** emergency khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh emergency giúp mình | cấp cứu có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Hướng dẫn liên hệ dịch vụ khẩn cấp phù hợp. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_14_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dịch vụ khám và thủ thuật, trước hết cần biết chuyên khoa/dịch vụ khách tìm. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_14_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dịch vụ nha khoa, trước hết cần biết cơ sở và khung giờ. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_14_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Lịch khám và hồ sơ hành chính, trước hết cần biết nhu cầu hỗ trợ hành chính. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_14_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dịch vụ khám và thủ thuật, trước hết cần biết thông tin liên hệ tối thiểu. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_14_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Dịch vụ nha khoa, trước hết cần biết mã lịch hẹn. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_14_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Lịch khám và hồ sơ hành chính, trước hết cần biết không thu triệu chứng chi tiết ngoài luồng an toàn. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_14_qa_17
**Câu hỏi:** Phòng khám có chuyên khoa X không?
**Cách hỏi khác:** Phòng khám có chuyên khoa X không thế nào? | Phòng khám có chuyên khoa X không?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Tra danh mục chuyên khoa/cơ sở đã xác minh và tình trạng hoạt động hiện tại. Nếu chưa có dữ liệu, chuyển nhân viên; không suy ra từ tên cơ sở.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_14_qa_18
**Câu hỏi:** Phí khám là bao nhiêu?
**Cách hỏi khác:** Phí khám là bao nhiêu thế nào? | Phí khám là bao nhiêu?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Tra bảng phí đã duyệt, cơ sở, loại khám và các điều kiện được công bố. Chi phí thủ thuật/xét nghiệm có thể cần bác sĩ đánh giá; không báo tổng phí khi chưa xác nhận.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_14_qa_19
**Câu hỏi:** Tôi có triệu chứng X, có phải bệnh gì không?
**Cách hỏi khác:** Tôi có triệu chứng X, có phải bệnh gì không thế nào? | Mình có triệu chứng X, có phải bệnh gì không?
**Intent:** product_information
**Câu trả lời gợi ý:** Chatbot không chẩn đoán. Tôi có thể hỗ trợ đặt lịch/chuyển nhân viên y tế. Nếu triệu chứng nghiêm trọng, đột ngột hoặc đe dọa tính mạng, gọi cấp cứu/đến cơ sở cấp cứu ngay.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_14_qa_20
**Câu hỏi:** Lịch khám của tôi đã xác nhận chưa?
**Cách hỏi khác:** Lịch khám của tôi đã xác nhận chưa thế nào? | Lịch khám của mình đã xác nhận chưa?
**Intent:** appointment_booking
**Câu trả lời gợi ý:** Tra trạng thái trong CRM sau khi xác minh thông tin cần thiết. Chỉ thông báo confirmed khi hệ thống ghi nhận; nếu chưa, hướng dẫn nhân viên xác nhận.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_14_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_14_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_14_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_14_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_14_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_14_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_14_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_14_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_14_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_14_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

## industry_15 Giáo dục & đào tạo

### Phạm vi ngành
Ngành khóa học, chương trình đào tạo, gia sư và tài liệu học. Tư vấn cần chính xác mục tiêu, trình độ đầu vào, lịch học, hình thức, chuẩn đầu ra được phê duyệt, điều kiện hoàn/học bù và bảo vệ dữ liệu học viên, đặc biệt trẻ em.

### Thuật ngữ và FAQ
- **prerequisite** (điều kiện đầu vào): Nền tảng cần có theo đề cương. Aliases: prerequisite.
- **learning outcome** (chuẩn/mục tiêu đầu ra): Mục tiêu đào tạo; không đảm bảo kết quả cá nhân. Aliases: learning outcome.
- **cohort** (khóa/lớp tuyển sinh): Nhóm học viên theo kỳ/lịch cụ thể. Aliases: cohort.
- **synchronous** (học đồng bộ): Học theo lịch trực tiếp. Aliases: live learning.
- **asynchronous** (học không đồng bộ): Học theo nội dung tự học được cấp. Aliases: self-paced.
- **syllabus** (đề cương học phần): Nội dung, đánh giá và tài liệu khóa. Aliases: course outline.
- **credit** (tín chỉ): Chỉ dùng theo đơn vị đào tạo được công nhận. Aliases: credit.
- **make-up class** (buổi học bù): Áp dụng theo chính sách trung tâm. Aliases: make-up class.
- **certificate** (chứng chỉ): Nêu rõ đơn vị cấp và điều kiện xác minh. Aliases: certificate.
- **assessment** (đánh giá kết quả học): Hình thức đánh giá theo chương trình. Aliases: assessment.

#### industry_15_qa_01
**Câu hỏi:** prerequisite là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** điều kiện đầu vào nghĩa là gì? | Cho mình hỏi về prerequisite | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Nền tảng cần có theo đề cương. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_15_qa_02
**Câu hỏi:** learning outcome là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** chuẩn/mục tiêu đầu ra nghĩa là gì? | Cho mình hỏi về learning outcome | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Mục tiêu đào tạo; không đảm bảo kết quả cá nhân. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_15_qa_03
**Câu hỏi:** cohort là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** khóa/lớp tuyển sinh nghĩa là gì? | Cho mình hỏi về cohort | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Nhóm học viên theo kỳ/lịch cụ thể. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_15_qa_04
**Câu hỏi:** synchronous là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** học đồng bộ nghĩa là gì? | Cho mình hỏi về synchronous | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Học theo lịch trực tiếp. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_15_qa_05
**Câu hỏi:** asynchronous là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** học không đồng bộ nghĩa là gì? | Cho mình hỏi về asynchronous | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Học theo nội dung tự học được cấp. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_15_qa_06
**Câu hỏi:** syllabus là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** đề cương học phần nghĩa là gì? | Cho mình hỏi về syllabus | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Nội dung, đánh giá và tài liệu khóa. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_15_qa_07
**Câu hỏi:** credit là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** tín chỉ nghĩa là gì? | Cho mình hỏi về credit | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Chỉ dùng theo đơn vị đào tạo được công nhận. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_15_qa_08
**Câu hỏi:** make-up class là gì và thường dùng trong trường hợp nào?
**Cách hỏi khác:** buổi học bù nghĩa là gì? | Cho mình hỏi về make-up class | — là gì?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Áp dụng theo chính sách trung tâm. Thông tin này giải thích thuật ngữ; mức phù hợp với một sản phẩm cụ thể cần đối chiếu nhãn, hướng dẫn hoặc thông số của đúng mã hàng.
**Nguồn cần truy xuất:** approved_knowledge_base, verified_product_documentation
**Điều kiện chuyển người:** 

#### industry_15_qa_09
**Câu hỏi:** certificate khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh certificate giúp mình | chứng chỉ có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Nêu rõ đơn vị cấp và điều kiện xác minh. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_15_qa_10
**Câu hỏi:** assessment khác gì với lựa chọn tương tự?
**Cách hỏi khác:** So sánh assessment giúp mình | đánh giá kết quả học có điểm gì cần chú ý?
**Intent:** product_comparison
**Câu trả lời gợi ý:** Chỉ so sánh các thuộc tính đã xác minh của từng lựa chọn như công năng, thông số, điều kiện sử dụng và giới hạn. Hình thức đánh giá theo chương trình. Cần tên/mã của các lựa chọn để đối chiếu chính xác.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_15_qa_11
**Câu hỏi:** Tôi nên chọn sản phẩm nào cho nhu cầu của mình?
**Cách hỏi khác:** Mình nên chọn sp nào cho nhu cầu của mình? | Tôi nên chọn sản phẩm loại nào cho nhu cầu của mình?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Khóa học/chương trình, trước hết cần biết mục tiêu học tập. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_15_qa_12
**Câu hỏi:** Có loại nào phù hợp cho người mới bắt đầu không?
**Cách hỏi khác:** Có loại nào phù hợp cho người mới bắt đầu không? | Có loại loại nào phù hợp cho người mới bắt đầu không?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Lớp học và lịch, trước hết cần biết trình độ hiện tại do người học tự đánh giá. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_15_qa_13
**Câu hỏi:** Tôi cần lưu ý gì trước khi chọn?
**Cách hỏi khác:** Mình cần lưu ý gì trước khi chọn? | Tôi cần lưu ý gì trước khi chọn?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Học phí và ghi danh, trước hết cần biết lịch và múi giờ. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_15_qa_14
**Câu hỏi:** Cần đo/kiểm tra thông tin nào trước khi mua?
**Cách hỏi khác:** Cần đo/kiểm tra thông tin nào trước khi mua? | Cần đo/kiểm tra thông tin loại nào trước khi mua?
**Intent:** pre_purchase_advice
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Khóa học/chương trình, trước hết cần biết hình thức học. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_15_qa_15
**Câu hỏi:** Loại nào phù hợp với điều kiện sử dụng của tôi?
**Cách hỏi khác:** Loại nào phù hợp với điều kiện sử dụng của tôi? | Loại loại nào phù hợp với điều kiện sử dụng của tôi?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Lớp học và lịch, trước hết cần biết độ tuổi/người giám hộ nếu cần. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_15_qa_16
**Câu hỏi:** Có thể dùng sản phẩm này cho mục đích khác không?
**Cách hỏi khác:** Có thể dùng sp này cho mục đích khác không? | Có thể dùng sản phẩm này cho mục đích khác không?
**Intent:** product_information
**Câu trả lời gợi ý:** Để gợi ý trong nhóm Học phí và ghi danh, trước hết cần biết yêu cầu hỗ trợ tiếp cận. Tôi sẽ lọc Product Catalog theo thuộc tính đã khai báo và chỉ đưa ra lựa chọn có dữ liệu phù hợp; nếu thông tin quan trọng còn thiếu, tôi sẽ hỏi lại thay vì đoán.
**Nguồn cần truy xuất:** Product Catalog, approved_knowledge_base
**Điều kiện chuyển người:** 

#### industry_15_qa_17
**Câu hỏi:** Khóa học này phù hợp trình độ nào?
**Cách hỏi khác:** Khóa học này phù hợp trình độ nào thế nào? | Khóa học này phù hợp trình độ nào?
**Intent:** industry_knowledge
**Câu trả lời gợi ý:** Đối chiếu yêu cầu đầu vào, nội dung và mục tiêu trong đề cương hiện hành. Nếu trình độ chưa rõ, đề xuất quy trình xếp lớp/tư vấn; không hứa đạt chuẩn đầu ra.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_15_qa_18
**Câu hỏi:** Lịch học và hình thức học ra sao?
**Cách hỏi khác:** Lịch học và hình thức học ra sao thế nào? | Lịch học và hình thức học ra sao?
**Intent:** product_recommendation
**Câu trả lời gợi ý:** Tra lịch cụ thể theo cohort, địa điểm/múi giờ và trạng thái tuyển sinh trong CRM. Chỉ nêu khung đã xác nhận.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_15_qa_19
**Câu hỏi:** Học xong có chắc chắn đạt chứng chỉ/việc làm không?
**Cách hỏi khác:** Học xong có chắc chắn đạt chứng chỉ/việc làm không thế nào? | Học xong có chắc chắn đạt chứng chỉ/việc làm không?
**Intent:** product_information
**Câu trả lời gợi ý:** Không thể cam kết kết quả cá nhân. Nêu điều kiện chứng chỉ/đơn vị cấp hoặc hỗ trợ nghề nghiệp đã được công bố; đề nghị đọc đề cương và điều khoản khóa.
**Nguồn cần truy xuất:** approved_knowledge_base, Product Catalog
**Điều kiện chuyển người:** 

#### industry_15_qa_20
**Câu hỏi:** Tôi muốn xin hoàn học phí/chuyển lớp
**Cách hỏi khác:** Tôi muốn xin hoàn học phí/chuyển lớp | Mình muốn xin hoàn học phí/chuyển lớp
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy, trạng thái ghi danh/thanh toán và điều kiện khóa cụ thể. Nếu policy chưa có hoặc trường hợp ngoại lệ, chuyển nhân viên; không tự hứa hoàn.
**Nguồn cần truy xuất:** Shop Policy
**Điều kiện chuyển người:** 

#### industry_15_qa_21
**Câu hỏi:** Sản phẩm này giá bao nhiêu?
**Cách hỏi khác:** sp này giá bao nhiêu? | Sản phẩm này giá bao nhiêu vậy?
**Intent:** product_price
**Câu trả lời gợi ý:** Giá hiện tại phải được lấy từ Product Catalog/CRM đúng SKU và biến thể. Nếu không có giá live hoặc có nhiều biến thể chưa rõ, nói cần xác minh; không lấy con số từ tài liệu kiến thức.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_15_qa_22
**Câu hỏi:** Mẫu/phiên bản này còn hàng không?
**Cách hỏi khác:** Mẫu/phiên bản này còn hàng không? | Mẫu/phiên bản này còn hàng không vậy?
**Intent:** product_availability
**Câu trả lời gợi ý:** Tồn kho cần truy vấn trạng thái live theo SKU/biến thể. Không khẳng định còn hàng từ tài liệu RAG hoặc ảnh chụp cũ.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_15_qa_23
**Câu hỏi:** Có ưu đãi nào đang áp dụng không?
**Cách hỏi khác:** Có ưu đãi nào đang áp dụng không? | Có ưu đãi nào đang áp dụng không vậy?
**Intent:** promotion_inquiry
**Câu trả lời gợi ý:** Tra chương trình khuyến mãi hiện hành, thời hạn, điều kiện và mặt hàng áp dụng từ CRM/Shop Policy; không tự tính ưu đãi.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_15_qa_24
**Câu hỏi:** Đơn của tôi đang ở trạng thái nào?
**Cách hỏi khác:** Đơn của tôi đang ở trạng thái nào? | Đơn của tôi đang ở trạng thái nào vậy?
**Intent:** order_status
**Câu trả lời gợi ý:** Tra đơn của chính khách trong CRM sau bước xác minh cần thiết. Không tìm đơn của người khác hoặc suy đoán trạng thái.
**Nguồn cần truy xuất:** Product Catalog/CRM
**Điều kiện chuyển người:** 

#### industry_15_qa_25
**Câu hỏi:** Tôi có thể thanh toán bằng cách nào?
**Cách hỏi khác:** Mình có thể thanh toán bằng cách nào? | Tôi có thể thanh toán bằng cách nào vậy?
**Intent:** payment_method
**Câu trả lời gợi ý:** Chỉ nêu hình thức thanh toán đang bật trong cấu hình shop và phù hợp đơn hàng; nếu chưa rõ, chuyển nhân viên.
**Nguồn cần truy xuất:** Promotion Data/Shop Policy
**Điều kiện chuyển người:** 

#### industry_15_qa_26
**Câu hỏi:** Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào?
**Cách hỏi khác:** Mình muốn đổi hoặc trả sp thì làm thế nào? | Tôi muốn đổi hoặc trả sản phẩm thì làm thế nào giúp mình với?
**Intent:** return_refund_policy
**Câu trả lời gợi ý:** Tra Shop Policy hiện hành, trạng thái đơn và loại hàng. Nếu shop chưa cấu hình điều kiện, thời hạn hay trường hợp ngoại lệ, thông báo chưa xác nhận và chuyển nhân viên.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_15_qa_27
**Câu hỏi:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao?
**Cách hỏi khác:** Nếu nhận hàng bị hỏng thì shop xử lý ra sao? | Nếu nhận hàng bị hỏng thì shop xử lý ra sao giúp mình với?
**Intent:** complaint
**Câu trả lời gợi ý:** Ghi nhận mã đơn và ảnh tình trạng phù hợp; kiểm tra quy trình hàng hỏng của Shop Policy. Không hứa đổi/hoàn trước khi xác minh.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_15_qa_28
**Câu hỏi:** Phí giao hàng và thời gian giao là bao lâu?
**Cách hỏi khác:** Phí giao hàng và thời gian giao là bao lâu? | Phí giao hàng và thời gian giao là bao lâu giúp mình với?
**Intent:** shipping_delivery
**Câu trả lời gợi ý:** Phụ thuộc địa chỉ, loại hàng và cấu hình vận chuyển của shop. Tra dữ liệu cụ thể; không đưa ra phí/ngày giao mặc định.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_15_qa_29
**Câu hỏi:** Sản phẩm/dịch vụ có bảo hành không?
**Cách hỏi khác:** Sản phẩm/dịch vụ có bảo hành không? | Sản phẩm/dịch vụ có bảo hành không giúp mình với?
**Intent:** warranty_policy
**Câu trả lời gợi ý:** Chỉ áp dụng khi hồ sơ sản phẩm hoặc Shop Policy quy định rõ. Không mặc định toàn ngành có bảo hành.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 

#### industry_15_qa_30
**Câu hỏi:** Tôi muốn nói chuyện với nhân viên
**Cách hỏi khác:** Mình muốn nói chuyện với nhân viên | Tôi muốn nói chuyện với nhân viên
**Intent:** human_handoff
**Câu trả lời gợi ý:** Ghi nhận yêu cầu, ngữ cảnh tối thiểu và chuyển vào support queue. Không bắt khách lặp lại thông tin đã có.
**Nguồn cần truy xuất:** Shop Policy, CRM, support workflow
**Điều kiện chuyển người:** 
