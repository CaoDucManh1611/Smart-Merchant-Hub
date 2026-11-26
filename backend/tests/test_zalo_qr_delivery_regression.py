from unittest.mock import Mock, patch
import pytest
from app.services.auto_reply_service import _send_channel_reply

QR='https://img.vietqr.io/image/970422-123456-compact2.png?amount=59000&addInfo=CHAT9&accountName=TEST'
TEXT='Thông tin chuyển khoản CHAT-9\nSố tiền: 59.000 đồng\nMã QR: '+QR
PUBLIC='https://shop.ngrok-free.dev/api/conversations/media-uploads/qr.jpg'
REJECTION=RuntimeError('The photo URL is invalid. Please check your image link, make sure it uses HTTPS and that the image size is valid.')

def call():
 return _send_channel_reply(db=Mock(),conversation_id=28,channel='zalo',recipient_id='test-only',text=TEXT,business_id=8)

def test_rejected_public_photo_retries_validated_direct_qr():
 with patch('app.services.auto_reply_service._public_payment_qr',return_value=PUBLIC),patch('app.services.auto_reply_service.send_zalo_media',side_effect=[REJECTION,{'ok':True,'message_id':'photo-1'}]) as photo,patch('app.services.auto_reply_service.send_zalo_message') as text:
  result=call()
 assert [c.kwargs['media_url'] for c in photo.call_args_list]==[PUBLIC,QR]
 assert result['media_type']=='image' and result['media_url']==QR
 text.assert_not_called()

def test_rejected_both_photos_still_delivers_payment_text_with_link():
 with patch('app.services.auto_reply_service._public_payment_qr',return_value=PUBLIC),patch('app.services.auto_reply_service.send_zalo_media',side_effect=REJECTION),patch('app.services.auto_reply_service.send_zalo_message',return_value={'ok':True,'message_id':'text-1'}) as send:
  result=call()
 assert QR in send.call_args.kwargs['text'] and '59.000' in send.call_args.kwargs['text']
 assert 'media_type' not in result
 assert QR in result['caption']
 assert result['qr_delivery']=='link_only'

@pytest.mark.parametrize('error',[TimeoutError('unconfirmed'),RuntimeError('Token invalid')])
def test_uncertain_or_unrelated_failure_is_not_resent(error):
 with patch('app.services.auto_reply_service._public_payment_qr',return_value=PUBLIC),patch('app.services.auto_reply_service.send_zalo_media',side_effect=error) as photo,patch('app.services.auto_reply_service.send_zalo_message') as text:
  with pytest.raises(type(error)):
   call()
 photo.assert_called_once()
 text.assert_not_called()
