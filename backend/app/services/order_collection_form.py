"""Recognize explicit form fields without model calls or implicit submission."""
import re
from app.rag.topics import fold_topic_text
from app.services.business_request import pending_contact_action


LABELS = {"ten nguoi nhan":"name","ho ten":"name","ten":"name",
    "so dien thoai":"phone","so lien he":"phone","sdt":"phone",
    "email":"email","dia chi nhan hang":"address","dia chi":"address",
    "thanh toan":"payment_method","hinh thuc thanh toan":"payment_method"}


def order_form_action(query, collected):
    from app.services.customer_collection_flow import _extract_value
    if not collected.get("offering_ref") or "?" in query:
        return None
    if fold_topic_text(query) in {'xac nhan','dong y','xac nhan tao don','xac nhan gui yeu cau'}:
        return {'action':'submit' if collected.get('phase')=='review' else 'collect',
            'action_evidence':query,'offering_ref':collected['offering_ref'],'fields':{}}
    definitions={d['key']:d for d in collected.get('field_definitions',[])}
    definitions['payment_method']={"type":"text"}
    fields={}
    for raw in query.strip().splitlines():
        raw=raw.strip()
        if not raw: continue
        label,sep,value=raw.partition(':')
        key=LABELS.get(fold_topic_text(re.sub(r"\([^)]*\)","",label))) if sep else None
        value=value.strip() if key else raw
        if key is None:
            if re.fullmatch(r"(?:cod|chuyển khoản|chuyen khoan|tiền mặt|tien mat|bank_transfer)",raw,re.I): key='payment_method'
            elif re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",raw): key='email'
            elif re.fullmatch(r"[+\d .()-]{9,20}",raw): key='phone'
            else:
                contact=pending_contact_action(raw,{**collected,'values':{**collected.get('values',{}),**{k:v['value'] for k,v in fields.items()}}})
                if contact:
                    fields.update(contact['fields']);continue
                if ('address' in definitions and len(raw)>=5 and re.search(r"\d",raw)
                    and re.search(r"[^\W\d_]",raw) and not re.search(r"\b(?:mua|gia|huy|dat|bao nhieu|xac nhan)\b",fold_topic_text(raw))): key='address'
        if key in definitions and not value:
            continue
        if key not in definitions or not value:
            return None
        if key=='payment_method':
            method=_extract_value('payment_method',value)
            if value=='bank_transfer': method='bank_transfer'
            if not method: return None
            value=method
        elif key in {'phone','email','address'}:
            if not _extract_value(key,value): return None
        fields[key]={'value':value,'evidence':raw}
    if not fields: return None
    return {'action':'collect','action_evidence':query,'offering_ref':collected['offering_ref'],'fields':fields}


def render_order_form(workflow):
    names={'name':'Tên người nhận','phone':'Số điện thoại','email':'Email','address':'Địa chỉ nhận hàng'}
    values=workflow.get('received') or {}
    lines=['Để lên đơn, bạn điền đầy đủ các mục dưới đây nhé. Nếu gửi thành vài tin, mình sẽ tự ghi nhận thay vì hỏi lại từng mục:']
    for key,label in names.items():
        if any(d['key']==key for d in workflow.get('field_definitions',[])):
            lines.append(f"{label}: {'đã ghi nhận' if key in values else ''}")
    methods=workflow.get('configured_payment_methods') or workflow.get('payment_methods') or {}
    labels={'cod':'COD','bank_transfer':'chuyển khoản','cash':'tiền mặt'}
    lines.append('Thanh toán ('+'/'.join(labels[k] for k in methods if k in labels)+'): '+('đã ghi nhận' if 'payment_method' in values else ''))
    return '\n'.join(lines)
