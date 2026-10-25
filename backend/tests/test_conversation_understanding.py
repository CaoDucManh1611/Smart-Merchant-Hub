import json
from unittest.mock import patch
from app.services.conversation_understanding import interpret_collection_turn


def interpret(text, response):
    with patch('app.services.conversation_understanding.call_llm', return_value=json.dumps(response)):
        return interpret_collection_turn(text,required_fields=['name','phone','move_in'],current_field='name',collected_fields={})


def test_multiple_fields_require_explicit_customer_evidence():
    result=interpret('Tên Cao Đức Mạnh, Sdt 0901234567, Ngày 26/11/2026', {
        'intent':'provide_information','fields':{
            'name':{'value':'Cao Đức Mạnh','evidence':'Cao Đức Mạnh'},
            'phone':{'value':'0901234567','evidence':'0901234567'},
            'move_in':{'value':'26/11/2026','evidence':'Ngày 26/11/2026'},
            'price':{'value':'1','evidence':'1'}}})
    assert set(result['fields'])=={'name','phone','move_in'}


def test_fabricated_contact_and_unknown_intent_are_rejected():
    result=interpret('ok', {'intent':'provide_information','fields':{
        'phone':{'value':'0901234567','evidence':'ok'},
        'name':{'value':'Invented','evidence':'not in message'}}})
    assert result['fields']=={}
    assert interpret('ok',{'intent':'create_order','fields':{}}) is None


def test_provider_error_has_safe_fallback():
    with patch('app.services.conversation_understanding.call_llm', side_effect=TimeoutError):
        assert interpret_collection_turn('ok',required_fields=['name'],current_field='name',collected_fields={}) is None
