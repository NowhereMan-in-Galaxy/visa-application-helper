"""按试用模式的虚构资料，给 README 动图的虚构签证表生成填写计划（见 docs/demo/README.md）。

    uv run python docs/demo/make_plan.py

读 visa-form.scan.json（在页面上运行 src/form_engine/scan.js 得到），写 visa-form.plan.json。
用的就是插件背后的 plan()，只是把计划存成文件，方便页面一格一格填、录成动图。
"""

import json
from pathlib import Path

from api.demo import DEMO_PROFILE, DEMO_TRIP
from core.models import PersonalProfile
from core.trip import TripInfo
from form_engine.match import default_dictionary, expand_scan, plan, profile_leaves
from form_engine.sites import site_date_format

HERE = Path(__file__).parent
fields = expand_scan((HERE / "visa-form.scan.json").read_text(encoding="utf-8"))
trip = TripInfo.model_validate({**DEMO_TRIP, "arrival_date": "2026-11-02", "departure_date": "2026-11-09"})
allow = [p for p, leaf in profile_leaves().items() if leaf.sensitive]  # 资料是虚构的，敏感字段也填
result = plan(fields, PersonalProfile.model_validate(DEMO_PROFILE), default_dictionary(), allow,
              site_date_format(fields), trip=trip)
(HERE / "visa-form.plan.json").write_text(json.dumps(result["ops"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"{len(result['ops'])} 格要填；没有资料的：{[m['label'] for m in result['missing']]}")
