"""Explicit customer price comparisons; independent of model interpretation."""
from decimal import Decimal
import re
import unicodedata


def price_constraints(query):
 text=''.join(c for c in unicodedata.normalize('NFD',query.lower().replace('đ','d')) if unicodedata.category(c)!='Mn')
 operators={'>':'>','>=':'>=','≥':'>=','<':'<','<=':'<=','≤':'<=',
  'lon hon':'>','cao hon':'>','hon':'>','tren':'>','duoi':'<','nho hon':'<','thap hon':'<',
  'it nhat':'>=','toi thieu':'>=','lon hon hoac bang':'>=','cao hon hoac bang':'>=',
  'khong tren':'<=','khong duoi':'>=','khong it hon':'>=','khong thap hon':'>=',
  'toi da':'<=','khong qua':'<=','khong vuot qua':'<=','nho hon hoac bang':'<='}
 pattern=r'(?<!\w)('+ '|'.join(re.escape(x) for x in sorted(operators,key=len,reverse=True))+r')\s*(\d+(?:[.,]\d+)*)\s*(trieu|nghin|ngan|dong|vnd|k|tr|d|₫)?(?!\w)'
 results=[]
 for match in re.finditer(pattern,text):
  raw=match[2];parts=re.split(r'[.,]',raw)
  amount=Decimal(''.join(parts) if len(parts)>1 and all(len(x)==3 for x in parts[1:]) else raw.replace(',','.'))
  amount*=1000 if match[3] in {'k','nghin','ngan'} else 1000000 if match[3] in {'tr','trieu'} else 1
  results.append((operators[match[1]],amount))
 return results


def matches_price(price,constraints,budget=None):
 price=Decimal(str(price))
 if not constraints:return budget is None or price<=Decimal(str(budget))
 for operator,amount in constraints:
  if not {'>':price>amount,'>=':price>=amount,'<':price<amount,'<=':price<=amount}[operator]:return False
 return True
