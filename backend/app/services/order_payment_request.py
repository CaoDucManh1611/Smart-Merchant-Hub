"""Shared charge breakdown and prepayment state; no industry-specific formulas."""
from decimal import Decimal
from app.schemas.business_profile import ChargeLine


def payment_request(order):
    value=(order.metadata_ or {}).get('payment_request')
    return value if isinstance(value,dict) else None


def publish_payment_request(order,lines,label='Khoản thu theo đơn'):
    if order.status!='draft' or Decimal(order.paid_amount or 0)>0:
        raise ValueError('Chỉ sửa bảng kê của đơn nháp chưa nhận tiền.')
    validated=[ChargeLine.model_validate(line) for line in lines]
    amount=sum((line.amount for line in validated),Decimal(0))
    if amount>Decimal('9999999999'): raise ValueError('Khoản thu vượt giới hạn.')
    order.total_amount=amount
    metadata=dict(order.metadata_ or {})
    metadata.update(payment_flow='prepay_then_confirm',payment_request={'label':label,'amount':str(amount),
        'lines':[{'label':line.label,'amount':str(line.amount)} for line in validated]})
    metadata.pop('customer_payment_reported_at',None)
    order.metadata_=metadata


def prepare_payment_request(order,offering,policy,method):
    order.metadata_={**(order.metadata_ or {}),'payment_flow':'prepay_then_confirm','payment_method':method,
        'offering_name':offering['name'],'base_order_amount':str(order.total_amount)}
    if policy.mode=='order_total':
        base=Decimal(order.total_amount or 0)
        lines=([{'label':policy.label,'amount':base}] if base>0 else [])+[line.model_dump() for line in policy.fixed_charges]
        try:
            publish_payment_request(order,lines,policy.label)
        except ValueError:
            # Fractional VND or oversized totals require an explicit corrected bill.
            order.metadata_={**order.metadata_,"payment_amount_requires_review":True}


def confirmation_payment_error(order):
    if (order.metadata_ or {}).get('payment_flow')!='prepay_then_confirm': return None
    request=payment_request(order)
    if request is None: return 'Cần lập bảng kê khoản thu trước; chưa thể xác nhận đơn.'
    if (order.metadata_ or {}).get('payment_method')=='cod': return None
    net=Decimal(order.paid_amount or 0)-Decimal(order.refunded_amount or 0)
    if net<Decimal(request['amount']): return 'Cần đối soát và ghi nhận đủ khoản thu trước khi xác nhận đơn.'
    return None


def payment_state(order):
    request=payment_request(order)
    if request is None: return 'awaiting_amount'
    net=Decimal(order.paid_amount or 0)-Decimal(order.refunded_amount or 0)
    if net>=Decimal(request['amount']): return 'awaiting_confirmation' if order.status=='draft' else 'paid'
    if (order.metadata_ or {}).get('customer_payment_reported_at'): return 'awaiting_reconciliation'
    if (order.metadata_ or {}).get('payment_method')=='cod': return 'pay_on_delivery'
    return 'awaiting_payment'


def payment_instructions(db,order):
    from app.services.auto_reply_service import _format_vnd
    from app.services.shop_bank_transfer import order_transfer_instructions
    request=payment_request(order)
    if request is None:
        return f'Yêu cầu {order.order_number} đã được tạo. Cần bổ sung bảng kê các khoản phải thu trước khi gửi QR; đây là kiểm tra số tiền, chưa phải xác nhận đơn.'
    lines=[f"- {item['label']}: {_format_vnd(item['amount'])} đồng" for item in request['lines']]
    total=Decimal(request['amount'])
    prefix=f"Đơn {order.order_number} — bảng kê khoản thu:\n"+'\n'.join(lines)+f"\nTổng khoản thu: {_format_vnd(total)} đồng.\n"
    remaining=total-(Decimal(order.paid_amount or 0)-Decimal(order.refunded_amount or 0))
    if remaining<=0: return prefix+('Không phát sinh khoản thu. ' if total==0 else 'Đã đối soát đủ khoản thu. ')+('Đơn đang chờ nhân viên xác nhận.' if order.status=='draft' else 'Đơn đã được ghi nhận thanh toán đủ.')
    method=(order.metadata_ or {}).get('payment_method')
    if method=='cod': return prefix+'Bạn chọn thanh toán khi nhận hàng (COD); nhân viên sẽ kiểm tra và xác nhận đơn theo hình thức trả sau.'
    if method=='cash': return prefix+'Bạn chọn tiền mặt. Vui lòng thanh toán qua kênh thu tiền mặt của shop; sau khi nhân viên ghi nhận đã nhận tiền, đơn chuyển sang chờ xác nhận. Chưa ghi nhận đã thanh toán.'
    return prefix+order_transfer_instructions(db,business_id=order.business_id,order_number=order.order_number,amount=int(remaining))+'\nSau đối soát, nhân viên xác nhận đơn; việc gửi QR chưa phải xác nhận đặt thành công.'
