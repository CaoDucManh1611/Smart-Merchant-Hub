"""
RAG (Retrieval-Augmented Generation) module.

Components:
- loader: Đọc nội dung từ nhiều định dạng file
- chunker: Chia text thành chunks nhỏ
- embedder: Chuyển text thành vector embedding
- retriever: Tìm kiếm chunks liên quan từ vector DB
- prompt_builder: Xây dựng prompt cho LLM
- llm_caller: Gọi LLM API (Groq / Gemini / OpenAI)
"""
