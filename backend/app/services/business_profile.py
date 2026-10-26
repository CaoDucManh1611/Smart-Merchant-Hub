import json
from app.models.business_setting import BusinessSetting
from app.schemas.business_profile import BusinessProfile

KEY="chatbot.business_profile"


def get_business_profile(db,business_id):
    row=db.query(BusinessSetting).filter(BusinessSetting.business_id==business_id,BusinessSetting.key==KEY).first()
    return BusinessProfile.model_validate_json(row.value) if row else BusinessProfile()


def save_business_profile(db,business_id,profile):
    profile=BusinessProfile.model_validate(profile)
    row=db.query(BusinessSetting).filter(BusinessSetting.business_id==business_id,BusinessSetting.key==KEY).first()
    if row is None:
        row=BusinessSetting(business_id=business_id,key=KEY)
        db.add(row)
    row.value=json.dumps(profile.model_dump(mode="json"),ensure_ascii=False)
    db.flush()
    return profile
