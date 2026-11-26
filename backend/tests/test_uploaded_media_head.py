from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import conversations


def test_provider_can_probe_photo_before_downloading(tmp_path,monkeypatch):
 monkeypatch.setattr(conversations,'UPLOAD_DIR',tmp_path)
 (tmp_path/'qr.jpg').write_bytes(b'image-test')
 app=FastAPI();app.include_router(conversations.router,prefix='/api/conversations')
 client=TestClient(app)
 head=client.head('/api/conversations/media-uploads/qr.jpg')
 get=client.get('/api/conversations/media-uploads/qr.jpg')
 assert head.status_code==get.status_code==200
 assert head.content==b''
 assert head.headers['content-type']==get.headers['content-type']=='image/jpeg'
 assert head.headers['content-length']==get.headers['content-length']=='10'
 assert client.head('/api/conversations/media-uploads/missing.jpg').status_code==404
