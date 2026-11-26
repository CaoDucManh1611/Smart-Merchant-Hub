"""Parse explicit appointment fragments within one pending request."""
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

DATE = re.compile(r"(?<!\d)(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{4})(?!\d)")
TIME = re.compile(r"(?<!\d)(\d{1,2})(?::(\d{2})|\s*(?:h|giờ|gio)\s*(\d{2})?)(?:\s*(sáng|sang|chiều|chieu|tối|toi|trưa|trua|am|pm))?(?!\w)", re.I)
PHONE = re.compile(r"(?<![\w/])(?:\+84|0)\d{8,10}(?![\w/])")


def explicit_calendar(text):
    from app.rag.topics import fold_topic_text
    dates, times = [], []
    invalid = False
    for match in DATE.finditer(text):
        token = match.group()
        try:
            dates.append(datetime.strptime(token, '%Y-%m-%d' if token[4:5] == '-' else '%d/%m/%Y' if '/' in token else '%d-%m-%Y').date())
        except ValueError:
            invalid = True
    for match in TIME.finditer(text):
        hour = int(match[1]); minute = int(match[2] or match[3] or 0)
        qualifier = fold_topic_text(match[4] or '')
        if qualifier in {'chieu', 'toi', 'pm'} and hour < 12:
            hour += 12
        elif qualifier in {'sang', 'am'} and hour == 12:
            hour = 0
        elif qualifier in {'trua'} and hour < 11:
            hour += 12
        try:
            if not (match[2] or match[3] or qualifier):
                raise ValueError('ambiguous hour')
            times.append(time(hour, minute))
        except ValueError:
            invalid = True
    ambiguous = invalid or len(set(dates)) > 1 or len(set(times)) > 1
    return dates, times, ambiguous


def service_contact_fragment(query, existing, timezone_name='Asia/Ho_Chi_Minh'):
    from app.rag.topics import fold_topic_text
    from app.services.business_request import _valid_customer_name, is_business_request_cancellation
    from app.services.customer_collection_flow import _extract_value
    if (not str(existing.get('offering_ref') or '').startswith('service:')
            or '?' in query or is_business_request_cancellation(query)):
        return None
    definitions = existing.get('field_definitions') or []
    calendar_keys = [d['key'] for d in definitions if d.get('type') == 'datetime']
    if not calendar_keys:
        return None
    dates, times, ambiguous = explicit_calendar(query)
    phones = list(PHONE.finditer(query))
    fields = {}
    parts = {k: existing[k] for k in ('pending_calendar_date', 'pending_calendar_date_evidence',
              'pending_calendar_time', 'pending_calendar_time_evidence') if k in existing}
    previous = next((existing.get('values', {}).get(k) for k in calendar_keys
                     if existing.get('values', {}).get(k)), None)
    if previous:
        when = datetime.fromisoformat(previous).astimezone(ZoneInfo(timezone_name))
        parts.setdefault('pending_calendar_date', when.date().isoformat())
        parts.setdefault('pending_calendar_time', when.time().isoformat())
    if dates and not ambiguous:
        parts.update(pending_calendar_date=dates[0].isoformat(), pending_calendar_date_evidence=next(DATE.finditer(query)).group())
    if times and not ambiguous:
        parts.update(pending_calendar_time=times[0].isoformat(), pending_calendar_time_evidence=next(TIME.finditer(query)).group())
    if (dates or times) and not ambiguous and parts.get('pending_calendar_date') and parts.get('pending_calendar_time'):
        value = datetime.combine(datetime.fromisoformat(parts['pending_calendar_date']).date(),
                                 time.fromisoformat(parts['pending_calendar_time']), ZoneInfo(timezone_name)).isoformat()
        proof = query + ' ' + str(parts.get('pending_calendar_date_evidence', '')) + ' ' + str(parts.get('pending_calendar_time_evidence', ''))
        fields.update({key: {'value': value, 'evidence': proof.strip()} for key in calendar_keys})
    if phones:
        fields['phone'] = {'value': phones[0].group(), 'evidence': query if len(phones) > 1 else phones[0].group()}
    remainder = PHONE.sub(' ', TIME.sub(' ', DATE.sub(' ', query))).strip(' ,;\n\t')
    remainder = re.sub(r"(?:số điện thoại|số liên hệ|sđt|phone|sdt)\s*[:=]?\s*$", '', remainder, flags=re.I).strip(' ,;\n\t')
    name = _extract_value('name', remainder)
    if (name and re.fullmatch(r"[^\W\d_]+(?:[ \t]+[^\W\d_]+){1,7}", name)
            and _valid_customer_name(name)
            and not re.search(r'\b(?:muon|can|dat|mua|huy|xac nhan|chuyen khoan|tien mat|ngay|luc|gio)\b', fold_topic_text(name))):
        fields['name'] = {'value': name, 'evidence': remainder}
    if not fields and not dates and not times and not ambiguous:
        return None
    return {'action': 'collect', 'action_evidence': query, 'offering_ref': existing['offering_ref'],
            'fields': fields, 'calendar_parts': parts, 'calendar_invalid': ambiguous}
