from app.rag.chunker import Chunk
from app.rag.token_chunker import split_for_encoder
import re
class WordTokenizer:
    def __call__(self,text,add_special_tokens=True,return_offsets_mapping=False,**kwargs):
        offsets=[m.span() for m in re.finditer(r"\S+",text)]
        return {"input_ids":list(range(len(offsets)+(2 if add_special_tokens else 0))),"offset_mapping":offsets}

def test_long_context_and_source_fit_and_preserve_source():
    content=" ".join("word"+str(i) for i in range(150))
    source=Chunk(content,0,{"context":" ".join(["heading"]*40)})
    pieces=split_for_encoder([source],WordTokenizer(),32)
    assert len(pieces)>1
    assert all(p.metadata["embedding_token_count"]<=32 for p in pieces)
    assert all(p.content==content[p.metadata["piece_start"]:p.metadata["piece_end"]] for p in pieces)
    coverage=set()
    for p in pieces:coverage.update(range(p.metadata["piece_start"],p.metadata["piece_end"]))
    assert all(i in coverage for i,c in enumerate(content) if not c.isspace())

def test_short_chunk_and_provenance_are_retained():
    pieces=split_for_encoder([Chunk("short source",3,{"context":"heading","source":"file.md"})],WordTokenizer(),32)
    assert len(pieces)==1 and pieces[0].content=="short source"
    assert pieces[0].metadata["source"]=="file.md"
    assert pieces[0].metadata["source_chunk_index"]==3
