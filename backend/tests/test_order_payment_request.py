from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from test_business_request import setup,run,details
from app.models.sales import Order
from app.models.industry_modules import Appointment
from app.schemas.business_profile import BusinessProfile,PaymentPolicy
from app.schemas.payment import PaymentCreate,PaymentRequestUpdate
from app.services.business_profile import save_business_profile
from app.services.order_payment_request import publish_payment_request,payment_instructions,payment_state
from app.services.order_service import record_order_payment,transition_sales_order,SalesOrderOperationError,PaymentOperationError
from app.services.shop_bank_transfer import BankTransferSettingsUpdate,save_shop_bank_transfer


def configured(db,kind='goods',method='bank_transfer',manual=False):
    profile=BusinessProfile(payment_methods=[method])
    profile.payment_policies[kind]=PaymentPolicy(mode='manual' if manual else 'order_total',label='Kỳ đầu' if kind=='rental' else 'Giá cơ sở',fixed_charges=[{'label':'Khoản bổ sung theo cấu hình','amount':50000}])
    save_business_profile(db,1,profile);db.commit()
    save_shop_bank_transfer(db,1,BankTransferSettingsUpdate(enabled=True,bank_bin='970403',account_number='1234567890',account_name='TEST ONLY'));db.commit()


def submitted(data,kind='goods',method='bank_transfer'):
    entity={'goods':data[2],'rental':data[3],'service':data[4]}[kind]
    ref=f"{'service' if kind=='service' else 'product'}:{entity.id}"
    text,values=details(kind)
    if method=='cod':
        text=text.replace('chuyển khoản','COD');values['payment_method']={'value':'cod','evidence':'COD'}
    run(data,'collect',ref,text,values)
    result=run(data,'submit',ref,'Xác nhận gửi yêu cầu')
    return result,data[0].query(Order).one()


def paid(db,order,amount=None,key='receipt'):
    return record_order_payment(db,order_id=order.id,amount=Decimal(amount or order.total_amount),method='bank_transfer',status='paid',reference='TEST',idempotency_key=key,actor_id=None,business_id=1)


@pytest.mark.parametrize('kind,expected',[('goods',450000),('rental',150000),('service',200000)])
def test_bill_and_qr_before_staff_confirmation_then_reconciled_gate(setup,kind,expected):
    db=setup[0];configured(db,kind)
    result,order=submitted(setup,kind)
    assert order.status=='draft' and order.paid_amount==0
    assert order.total_amount==expected and result['payment_state']=='awaiting_payment'
    assert f'amount={expected}' in result['payment_instructions']
    with pytest.raises(SalesOrderOperationError,match='đối soát'):
        transition_sales_order(db,order_id=order.id,to_status='confirmed',actor_id=None,business_id=1)
    paid(db,order,10000,'partial')
    with pytest.raises(SalesOrderOperationError):
        transition_sales_order(db,order_id=order.id,to_status='confirmed',actor_id=None,business_id=1)
    paid(db,order,expected-10000,'remainder')
    assert order.status=='draft' and payment_state(order)=='awaiting_confirmation'
    transition_sales_order(db,order_id=order.id,to_status='confirmed',actor_id=None,business_id=1)
    assert order.status=='confirmed'
    if kind=='service':assert db.query(Appointment).one().status=='confirmed'


def test_manual_bill_never_invents_deposit_and_staff_can_publish(setup):
    db=setup[0];configured(db,'rental',manual=True)
    result,order=submitted(setup,'rental')
    assert result['payment_state']=='awaiting_amount' and 'vietqr' not in result['payment_instructions']
    with pytest.raises(PaymentOperationError):paid(db,order)
    publish_payment_request(order,[{'label':'Kỳ đầu','amount':100000},{'label':'Cọc do chủ quy định','amount':300000}])
    assert order.total_amount==400000 and 'amount=400000' in payment_instructions(db,order)
    paid(db,order)
    with pytest.raises(ValueError):publish_payment_request(order,[{'label':'Sửa sau thu','amount':1}])


def test_reported_transfer_not_paid_and_retries_do_not_double_collect(setup):
    db,conversation,*_=setup;configured(db)
    _,order=submitted(setup)
    from app.services.customer_order_service import customer_context_reply
    answer=customer_context_reply(db,1,conversation.id,'Tôi đã chuyển khoản rồi')
    assert 'đối soát' in answer and order.paid_amount==0 and order.status=='draft'
    assert payment_state(order)=='awaiting_reconciliation'
    paid(db,order);db.commit()
    _,_,created=paid(db,order)
    assert not created and order.paid_amount==450000


def test_cod_is_explicit_pay_later_exception(setup):
    db=setup[0];configured(db,method='cod')
    result,order=submitted(setup,method='cod')
    assert 'COD' in result['payment_instructions']
    transition_sales_order(db,order_id=order.id,to_status='confirmed',actor_id=None,business_id=1)
    assert order.paid_amount==0 and order.status=='confirmed'


def test_policy_change_demands_fresh_customer_review(setup):
    db=setup[0];configured(db)
    text,values=details('goods');ref=f'product:{setup[2].id}'
    run(setup,'collect',ref,text,values)
    profile=BusinessProfile();profile.payment_policies['goods'].fixed_charges=[]
    save_business_profile(db,1,profile);db.commit()
    assert run(setup,'submit',ref,'Xác nhận gửi')['state']=='review'
    assert db.query(Order).count()==0


@pytest.mark.parametrize('amount',[0,-1,'1.5','10000000000','NaN'])
def test_invalid_money_rejected(amount):
    with pytest.raises(ValidationError):PaymentRequestUpdate(lines=[{'label':'Phí','amount':amount}])


def test_payment_request_api_scoped_and_metadata_cannot_drop_gate(setup):
    db=setup[0];configured(db,'rental',manual=True);_,order=submitted(setup,'rental')
    from app.api.sales import update_payment_request,update_order
    from app.schemas.sales import OrderUpdate
    body=PaymentRequestUpdate(lines=[{'label':'Khoản rõ ràng','amount':100000}])
    with pytest.raises(HTTPException) as error:update_payment_request(order.id,body,db,SimpleNamespace(business_id=2),None)
    assert error.value.status_code==404
    update_payment_request(order.id,body,db,SimpleNamespace(business_id=1),None)
    update_order(order.id,OrderUpdate(metadata={'note':'Giữ bảo vệ'}),db,SimpleNamespace(business_id=1),None)
    assert order.metadata_['payment_flow']=='prepay_then_confirm'
    with pytest.raises(HTTPException):update_order(order.id,OrderUpdate(metadata={'payment_flow':'bypass'}),db,SimpleNamespace(business_id=1),None)


def test_native_service_payment_and_confirmation_api(setup):
    db=setup[0];configured(db,'service');_,order=submitted(setup,'service');appointment=db.query(Appointment).one()
    from app.api.appointments import appointment_payment,update_appointment,AppointmentUpdate
    tenant=SimpleNamespace(business_id=1)
    with pytest.raises(HTTPException) as error:
        update_appointment(appointment.id,AppointmentUpdate(status='confirmed'),db,db,tenant,db)
    assert error.value.status_code==409
    db.rollback()
    # Submit transaction was committed; failed confirmation must roll back.
    db.refresh(appointment);assert appointment.status=='pending'
    appointment_payment(appointment.id,PaymentCreate(amount=200000,method='bank_transfer',idempotency_key='service-paid'),db,tenant,None)
    with patch('app.api.appointments.emit_workflow_event'):
        update_appointment(appointment.id,AppointmentUpdate(status='confirmed'),db,db,tenant,db)
    assert order.status=='confirmed' and appointment.status=='confirmed'


def test_cancel_native_service_disables_payment_request(setup):
    db=setup[0];configured(db,'service');_,order=submitted(setup,'service');appointment=db.query(Appointment).one()
    from app.api.appointments import update_appointment,AppointmentUpdate
    with patch('app.api.appointments.emit_workflow_event'):
        update_appointment(appointment.id,AppointmentUpdate(status='cancelled'),db,db,SimpleNamespace(business_id=1),db)
    assert order.status=='cancelled'
    with pytest.raises(PaymentOperationError):paid(db,order)


def test_existing_order_keeps_original_confirmation_contract(setup):
    db,conversation,goods,*_=setup
    order=Order(business_id=1,customer_id=conversation.customer_id,conversation_id=conversation.id,order_number='LEGACY',status='draft',total_amount=100000)
    db.add(order);db.flush()
    transition_sales_order(db,order_id=order.id,to_status='confirmed',actor_id=None,business_id=1)
    assert order.status=='confirmed' and order.paid_amount==0
    paid(db,order)
    assert order.paid_amount==100000


def test_cod_still_requires_known_bill_and_zero_bill_does_not_claim_receipt(setup):
    db=setup[0];configured(db,'rental',method='cod',manual=True);_,order=submitted(setup,'rental',method='cod')
    with pytest.raises(SalesOrderOperationError):transition_sales_order(db,order_id=order.id,to_status='confirmed',actor_id=None,business_id=1)
    publish_payment_request(order,[])
    assert 'Không phát sinh khoản thu' in payment_instructions(db,order)
    assert 'Đã đối soát đủ' not in payment_instructions(db,order)
