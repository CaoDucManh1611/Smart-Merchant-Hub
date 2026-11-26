import json
from io import BytesIO
from unittest.mock import Mock,patch
import pytest
from PIL import Image
from app.services.auto_reply_service import _public_payment_qr

@pytest.mark.parametrize('origin,expected',[
 ('https://test-media.trycloudflare.com',True),
 ('https://test-media.trycloudflare.com.evil.test',False),
 ('http://test-media.trycloudflare.com',False),
 ('https://user@test-media.trycloudflare.com',False),
 ('https://test-media.trycloudflare.com/api',False),
])
def test_qr_uses_only_validated_runtime_media_origin(tmp_path,origin,expected):
 data=BytesIO();Image.new('RGB',(100,100),'white').save(data,format='PNG')
 (tmp_path/'payment-qr-origin.json').write_text(json.dumps({'origin':origin}))
 with patch('app.api.conversations.UPLOAD_DIR',tmp_path),patch('app.api.conversations.get_public_base_url',return_value='https://normal.test'),patch('app.services.shop_bank_transfer.shop_transfer_qr_png',return_value=data.getvalue()):
  url=_public_payment_qr(Mock(),8,'validated-url')
 assert url.startswith(origin+'/')==expected
 if expected:
  name=url.rsplit('/',1)[1]
  image=Image.open(tmp_path/'payment-qr'/name)
  assert image.format=='JPEG' and image.mode=='RGB' and image.size==(800,800)
 else:assert url.startswith('https://normal.test/api/conversations/media-uploads/')
