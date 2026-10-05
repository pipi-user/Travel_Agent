"""清掉 embedding 缓存（缓存里存了全零向量，必须清掉才能重试）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.travel_agent.cache import _conn

c = _conn()
n = c.execute("DELETE FROM cache WHERE key LIKE 'embed|%'").rowcount
c.commit()
c.close()

print(f"✅ 清掉了 {n} 条 embed 缓存")