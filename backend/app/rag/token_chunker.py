"""Candidate token-safe chunks for offline evaluation; not enabled in ingestion."""
from app.rag.chunker import Chunk

def split_for_encoder(chunks, tokenizer, max_tokens, overlap_tokens=16):
    if max_tokens < 16:
        raise ValueError("Encoder token limit is too small")
    output=[]
    def size(value):
        return len(tokenizer(value,add_special_tokens=True,truncation=False)["input_ids"])
    for chunk in chunks:
        original_context=str(chunk.metadata.get("context") or "")
        context=original_context
        # Reserve most of the window for source text, not repeated headings.
        context_offsets=tokenizer(context,add_special_tokens=False,return_offsets_mapping=True)["offset_mapping"]
        if len(context_offsets)>max_tokens//4:
            context=context[:context_offsets[max_tokens//4-1][1]]
        prefix=context+"\n\n" if context else ""
        content=chunk.content
        offsets=tokenizer(content,add_special_tokens=False,return_offsets_mapping=True)["offset_mapping"]
        if not offsets:
            continue
        start=0
        while start<len(offsets):
            end=min(len(offsets),start+max(1,max_tokens-size(prefix)-4))
            while end>start+1 and size(prefix+content[offsets[start][0]:offsets[end-1][1]])>max_tokens:
                end-=1
            piece=content[offsets[start][0]:offsets[end-1][1]]
            if size(prefix+piece)>max_tokens:
                raise ValueError("A source token cannot fit within the encoder limit")
            metadata={**chunk.metadata,"context":context,"original_context":original_context,
                "source_chunk_index":chunk.index,"piece_start":offsets[start][0],"piece_end":offsets[end-1][1],
                "embedding_token_count":size(prefix+piece),"chunking_version":"token-safe-ab-v1"}
            metadata["char_count"]=len(piece)
            output.append(Chunk(content=piece,index=len(output),metadata=metadata))
            if end==len(offsets):break
            start=max(start+1,end-min(overlap_tokens,max(0,(end-start)//4)))
    for item in output:item.metadata["chunk_total"]=len(output)
    return output
