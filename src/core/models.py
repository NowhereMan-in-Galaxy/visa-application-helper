"""对应 specs/001-visa-material-hub/spec.md 的 Key Entities。

有效期（validity）和更新提醒（recommended update）都用整数天数表示，不用"几个月"这种日历单位——
天数加减法没有歧义（每个月天数不一样，"3 个月后"这种说法本身就模糊），FR-003a 已经把这两个字段
明确成两个独立维度，这里用统一的天数单位实现，避免引入不必要的日历计算复杂度。
"""

from __future__ import annotations

import types
from datetime import date
from enum import Enum
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MaterialCategory(str, Enum):
    """spec.md FR-001 锁定的四大类（结构化个人信息不算在内，走 PersonalProfile，见 FR-011）。"""

    PASSPORT_SCAN = "passport_scan"
    FINANCIAL_SNAPSHOT = "financial_snapshot"
    EMPLOYMENT_DOC = "employment_doc"
    ID_PHOTO = "id_photo"
    # specs/002：攻略里很多材料（保险、行程单、机酒预订单……）不属于上面四类，
    # 在攻略页面上传时归到这里。（旧的材料维护页已删除。）
    OTHER = "other"


class MaterialStatus(str, Enum):
    """spec.md 锁定的四种状态（对应 docs/SPEC-mvp.md 第 4/5 条）。"""

    NEEDS_MATERIAL = "待补"
    COMPLETE = "已备齐"
    EXPIRING_SOON = "即将过期"
    EXPIRED = "已过期"


class VisaApplication(BaseModel):
    """一次具体的签证申请（spec.md Key Entities）。"""

    id: str
    country: str
    visa_type: str
    deadline: date  # DDL：整次申请统一的提交截止日期（FR-004、FR-006）


class MaterialRecord(BaseModel):
    """一条材料记录，对应 docs/SPEC-mvp.md 第 4 条锁定字段的扩展版本（spec.md FR-001）。"""

    id: str
    category: MaterialCategory
    type: str  # 人类可读的材料类型名称，例如"银行流水"

    # 所属 VisaApplication 的 id；留空表示这条材料属于个人材料库，不挂靠任何具体申请
    # （例如证件类——护照、身份证、户口本——是长期积累的个人资产，不是为某一次申请单独
    # 准备的，参考 PersonalProfile 已经确立的"申请人级别、不挂 belongs_to"模式）。
    # financial_snapshot / employment_doc 这两类目前实践上仍然会填具体申请 id，
    # 但字段本身不强制——要不要让它们也支持"不挂靠"，留给以后再评估。
    belongs_to: str | None = None

    # obtained_date 为空表示"这条材料还没拿到手，只是先占个位置"，对应状态"待补"。
    obtained_date: date | None = None

    # 有效期规则：材料从 obtained_date 起多少天内视为有效；留空表示这类材料没有过期概念
    # （例如证件照通常不强制过期，只是建议更新）。
    validity_days: int | None = None

    # 建议更新频率：与 validity_days 是两个独立维度（FR-003a），例如财务快照即使没过期，
    # 也可能因为太久没同步新的一份而需要提醒。这里有两种互斥的表达方式（FR-014），一条记录
    # 只能用其中一种：
    #   - recommended_update_interval_days：滚动周期，"每隔 N 天"（例如证件照每 180 天）
    #   - recommended_update_day_of_month：日历周期，"每月固定第几天"（例如发薪日是 15 号，
    #     工资流水按这个提醒比"上次更新后 N 天"更准，因为每个月天数不一样，滚动周期会慢慢偏移）
    # 两个都留空表示这类材料不需要主动提醒更新。
    recommended_update_interval_days: int | None = None
    recommended_update_day_of_month: int | None = None

    # 相对于"材料根目录"（见 src/config.py）的相对路径，不存文件内容本身。
    file_ref: str | None = None

    sublabel: str | None = None

    # 属于共享词表（community/material_types.yaml）里的哪个标准类型，见 specs/002 数据结构 §4。
    # 留空时匹配代码用 `type` 字段去词表里推断，所以老记录不用补这个字段也能被匹配上。
    material_type: str | None = None

    # 只属于某一件办事的一次性材料（值为那件办事的 Track id）；None = 长期资料，可以跨事项复用。
    # 本次专用的材料只会匹配给它所属的那件办事，「我的资料」里默认也不显示。见 specs/002。
    for_track: str | None = None


class TravelHistoryEntry(BaseModel):
    """PersonalProfile.travel_history 里的一条出行记录（spec.md Key Entities）。

    country 可以留空：从出入境记录能推出"这段时间出境了"，但推不出具体去了哪个国家时
    （比如只有出发口岸、没有目的地信息），应该让用户自己补，而不是猜一个可能错的国家。
    """

    country: str | None = None
    entry_date: date
    exit_date: date | None = None  # 还在境外、尚未返回时留空
    purpose: str | None = None


# ======================================================================================
# PersonalProfile（基本信息）：可以反复复用、但不是文件形式的个人资料。
# 字段设计、分组、DS-160 映射提示和迁移规则见 specs/003-personal-profile/spec.md。
#
# 每个字段都用 _f() 声明：title = 界面上的中文标签；json_schema_extra 里放
#   ds160     —— 对应 DS-160 哪一页 / 哪一问（给将来的填表 Agent 做映射；不确定就是 None）
#   sensitive —— 是否敏感（证件号、出生日期等），给调用方决定要不要在对话里复述
#   widget    —— 界面控件提示（textarea），可省略
#   options   —— 下拉选项的中文标签
# 这样"标签 / 映射 / 敏感"只写在这一处：网页表单（GET /api/personal-profile/fields）和
# MCP 工具 get_personal_profile 都从 describe_personal_profile() 生成，不会各写一份再对不上。
#
# extra="forbid"：拼错的字段名（例如 pasport_number）直接报错，而不是被悄悄丢掉——
# 这份文件每次保存都是整份重写，如果忽略未知字段，下一次保存就会把用户手写的内容删掉。
# ======================================================================================

PROFILE_SCHEMA_VERSION = 2


def _f(label: str, ds160: str | None = None, *, sensitive: bool = False, widget: str | None = None,
       options: dict[str, str] | None = None, default: Any = None):
    extra: dict[str, Any] = {"ds160": ds160, "sensitive": sensitive}
    if widget:
        extra["widget"] = widget
    if options:
        extra["options"] = options
    if isinstance(default, list):
        return Field(default_factory=list, title=label, json_schema_extra=extra)
    if isinstance(default, type) and issubclass(default, BaseModel):
        return Field(default_factory=default, title=label, json_schema_extra=extra)
    return Field(default=default, title=label, json_schema_extra=extra)


class _ProfilePart(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- 下拉选项（值用稳定的英文，界面显示中文） ----------

SEX_OPTIONS = {"male": "男", "female": "女"}
MARITAL_OPTIONS = {
    "single": "未婚", "married": "已婚", "common_law": "事实婚姻", "civil_union": "民事结合",
    "divorced": "离异", "widowed": "丧偶", "separated": "分居", "other": "其他",
}
PASSPORT_TYPE_OPTIONS = {"regular": "普通护照", "official": "公务护照", "diplomatic": "外交护照", "other": "其他"}
OCCUPATION_OPTIONS = {
    "agriculture": "农业", "artist_performer": "艺术/表演", "business": "商业", "communications": "通信",
    "computer_science": "计算机科学", "culinary_food_services": "餐饮服务", "education": "教育",
    "engineering": "工程", "government": "政府", "homemaker": "家庭主妇/主夫", "legal_profession": "法律",
    "medical_health": "医疗/健康", "military": "军事", "natural_science": "自然科学",
    "not_employed": "待业", "physical_sciences": "物理科学", "religious_vocation": "宗教职业",
    "research": "研究", "retired": "退休", "social_science": "社会科学", "student": "学生", "other": "其他",
}
SPOUSE_ADDRESS_OPTIONS = {
    "same_as_home": "与我的家庭住址相同", "same_as_mailing": "与我的邮寄地址相同",
    "same_as_us_contact": "与我的美国联系人地址相同", "other": "其他（下面填写）",
}
US_RELATIVE_OPTIONS = {"spouse": "配偶", "fiance": "未婚夫/妻", "child": "子女", "sibling": "兄弟姐妹"}
US_STATUS_OPTIONS = {
    "us_citizen": "美国公民", "lpr": "美国永久居民（绿卡）", "nonimmigrant": "非移民（访问/留学/工作等）",
    "other": "其他/不清楚",
}

Sex = Literal["male", "female"]
MaritalStatus = Literal["single", "married", "common_law", "civil_union", "divorced", "widowed", "separated", "other"]
PassportType = Literal["regular", "official", "diplomatic", "other"]
Occupation = Literal[
    "agriculture", "artist_performer", "business", "communications", "computer_science",
    "culinary_food_services", "education", "engineering", "government", "homemaker", "legal_profession",
    "medical_health", "military", "natural_science", "not_employed", "physical_sciences",
    "religious_vocation", "research", "retired", "social_science", "student", "other",
]
SpouseAddressType = Literal["same_as_home", "same_as_mailing", "same_as_us_contact", "other"]
UsRelativeType = Literal["spouse", "fiance", "child", "sibling"]
UsStatus = Literal["us_citizen", "lpr", "nonimmigrant", "other"]


# ---------- 复用的小结构 ----------


class Address(_ProfilePart):
    street: str | None = _f("街道地址（门牌、楼栋、单元、房号）")
    city: str | None = _f("城市")
    province: str | None = _f("省 / 州")
    postal_code: str | None = _f("邮编")
    country: str | None = _f("国家 / 地区")


class PersonName(_ProfilePart):
    surname: str | None = _f("姓（拼音）")
    given_names: str | None = _f("名（拼音）")


class OtherNationality(_ProfilePart):
    country: str | None = _f("国籍国家")
    passport_number: str | None = _f("该国护照号（没有就留空）", sensitive=True)


# ---------- 分组 1：基本身份 ----------


class IdentityInfo(_ProfilePart):
    surname: str | None = _f("姓（拼音，同护照）", "Personal 1 · Surnames")
    given_names: str | None = _f("名（拼音，同护照）", "Personal 1 · Given Names")
    native_full_name: str | None = _f("中文姓名", "Personal 1 · Full Name in Native Alphabet")
    other_names: list[PersonName] = _f("曾用名", "Personal 1 · Have you ever used other names?", default=[])
    telecode_surname: str | None = _f("姓的电码", "Personal 1 · Telecode that represents your name")
    telecode_given_names: str | None = _f("名的电码", "Personal 1 · Telecode that represents your name")
    sex: Sex | None = _f("性别", "Personal 1 · Sex", options=SEX_OPTIONS)
    date_of_birth: date | None = _f("出生日期", "Personal 1 · Date of Birth", sensitive=True)
    birth_city: str | None = _f("出生城市", "Personal 1 · Place of Birth · City")
    birth_province: str | None = _f("出生省份", "Personal 1 · Place of Birth · State/Province")
    birth_country: str | None = _f("出生国家", "Personal 1 · Place of Birth · Country/Region")
    nationality: str | None = _f("国籍", "Personal 2 · Country/Region of Origin (Nationality)")
    other_nationalities: list[OtherNationality] = _f(
        "其他国籍（现有或曾有）", "Personal 2 · Do you hold or have you held any nationality other than ...?", default=[])
    permanent_resident_countries: list[str] = _f(
        "在其他国家有永久居留权", "Personal 2 · Are you a permanent resident of a country/region other than ...?", default=[])
    national_id_number: str | None = _f("身份证号", "Personal 2 · National Identification Number", sensitive=True)
    us_ssn: str | None = _f("美国社会安全号（SSN）", "Personal 2 · U.S. Social Security Number", sensitive=True)
    us_taxpayer_id: str | None = _f("美国纳税人识别号（TIN）", "Personal 2 · U.S. Taxpayer ID Number", sensitive=True)


# ---------- 分组 2：护照与证件 ----------


class LostPassport(_ProfilePart):
    passport_number: str | None = _f("遗失/被盗的护照号（不知道就留空）", sensitive=True)
    issuing_country: str | None = _f("签发国家")
    explanation: str | None = _f("经过说明", widget="textarea")


class PassportInfo(_ProfilePart):
    passport_type: PassportType | None = _f("护照类型", "Passport · Passport/Travel Document Type",
                                            options=PASSPORT_TYPE_OPTIONS)
    passport_number: str | None = _f("护照号", "Passport · Passport/Travel Document Number", sensitive=True)
    passport_book_number: str | None = _f("护照本号（Book Number）", "Passport · Passport Book Number", sensitive=True)
    issuing_authority: str | None = _f("签发国家/机关", "Passport · Country/Authority that Issued")
    issue_city: str | None = _f("签发城市", "Passport · Where was the Passport Issued? · City")
    issue_province: str | None = _f("签发省/州", "Passport · Where was the Passport Issued? · State/Province")
    issue_country: str | None = _f("签发国家/地区", "Passport · Where was the Passport Issued? · Country/Region")
    issue_date: date | None = _f("签发日期", "Passport · Issuance Date")
    expiry_date: date | None = _f("有效期至", "Passport · Expiration Date")
    lost_passports: list[LostPassport] = _f(
        "遗失或被盗过的护照", "Passport · Have you ever lost a passport or had one stolen?", default=[])


# ---------- 分组 3：联系方式与住址 ----------


class ContactInfo(_ProfilePart):
    home_address: Address = _f("家庭住址", "Address and Phone · Home Address", default=Address)
    mailing_same_as_home: bool | None = _f("邮寄地址与家庭住址相同", "Address and Phone · Is your Mailing Address the same as your Home Address?")
    mailing_address: Address = _f("邮寄地址（与家庭住址不同时填）", "Address and Phone · Mailing Address", default=Address)
    primary_phone: str | None = _f("主要电话", "Address and Phone · Primary Phone Number")
    secondary_phone: str | None = _f("备用电话", "Address and Phone · Secondary Phone Number")
    work_phone: str | None = _f("工作电话", "Address and Phone · Work Phone Number")
    other_phones: list[str] = _f("过去 5 年用过的其他电话", "Address and Phone · Have you used any other phone numbers in the last five years?", default=[])
    email: str | None = _f("主要邮箱", "Address and Phone · Email Address")
    other_emails: list[str] = _f("过去 5 年用过的其他邮箱", "Address and Phone · Have you used any other email addresses in the last five years?", default=[])


# ---------- 分组 4：社交媒体 ----------


class SocialAccount(_ProfilePart):
    platform: str | None = _f("平台（例如 微博 / 小红书 / LinkedIn）")
    identifier: str | None = _f("账号 / 用户名")


class SocialMediaInfo(_ProfilePart):
    accounts: list[SocialAccount] = _f("过去 5 年用过的社交媒体账号", "Address and Phone · Social Media Provider/Platform + Identifier", default=[])
    other_platforms: list[SocialAccount] = _f(
        "其他发布内容的网站/应用", "Address and Phone · Do you wish to provide information about your presence on any other websites or applications ...?", default=[])


# ---------- 分组 5：家庭与婚育 ----------


class ParentInfo(_ProfilePart):
    surname: str | None = _f("姓（拼音）")
    given_names: str | None = _f("名（拼音）")
    date_of_birth: date | None = _f("出生日期（不知道就留空）", sensitive=True)
    in_us: bool | None = _f("目前在美国")
    us_status: UsStatus | None = _f("在美身份（在美国时填）", options=US_STATUS_OPTIONS)


class SpouseInfo(_ProfilePart):
    surname: str | None = _f("姓（拼音）")
    given_names: str | None = _f("名（拼音）")
    date_of_birth: date | None = _f("出生日期", sensitive=True)
    nationality: str | None = _f("国籍")
    birth_city: str | None = _f("出生城市")
    birth_country: str | None = _f("出生国家")
    address_type: SpouseAddressType | None = _f("配偶住址", options=SPOUSE_ADDRESS_OPTIONS)
    address: Address = _f("配偶住址（选「其他」时填）", default=Address)


class FormerSpouse(_ProfilePart):
    surname: str | None = _f("姓（拼音）")
    given_names: str | None = _f("名（拼音）")
    date_of_birth: date | None = _f("出生日期", sensitive=True)
    nationality: str | None = _f("国籍")
    birth_city: str | None = _f("出生城市")
    birth_country: str | None = _f("出生国家")
    marriage_start: date | None = _f("结婚日期")
    marriage_end: date | None = _f("婚姻结束日期")
    how_ended: str | None = _f("婚姻如何结束（离婚原因 / 丧偶）", widget="textarea")
    country_ended: str | None = _f("在哪个国家结束")


class ChildInfo(_ProfilePart):
    surname: str | None = _f("姓（拼音）")
    given_names: str | None = _f("名（拼音）")
    native_full_name: str | None = _f("中文姓名")
    date_of_birth: date | None = _f("出生日期", sensitive=True)
    nationality: str | None = _f("国籍")


class UsRelative(_ProfilePart):
    surname: str | None = _f("姓（拼音）")
    given_names: str | None = _f("名（拼音）")
    relationship: UsRelativeType | None = _f("与我的关系", options=US_RELATIVE_OPTIONS)
    us_status: UsStatus | None = _f("在美身份", options=US_STATUS_OPTIONS)


class FamilyInfo(_ProfilePart):
    marital_status: MaritalStatus | None = _f("婚姻状况", "Personal 1 · Marital Status", options=MARITAL_OPTIONS)
    father: ParentInfo = _f("父亲", "Family · Relatives · Father's Full Name and Date of Birth", default=ParentInfo)
    mother: ParentInfo = _f("母亲", "Family · Relatives · Mother's Full Name and Date of Birth", default=ParentInfo)
    spouse: SpouseInfo = _f("配偶（已婚时填）", "Family · Spouse", default=SpouseInfo)
    former_spouses: list[FormerSpouse] = _f("前配偶 / 已故配偶", "Family · Former Spouse", default=[])
    children: list[ChildInfo] = _f("子女", None, default=[])
    us_immediate_relatives: list[UsRelative] = _f(
        "在美国的直系亲属（父母以外）", "Family · Relatives · Do you have any immediate relatives, not including parents, in the United States?", default=[])
    other_relatives_in_us: bool | None = _f("在美国还有其他亲属", "Family · Relatives · Do you have any other relatives in the United States?")


# ---------- 分组 6：教育经历 ----------


class SchoolEntry(_ProfilePart):
    name: str | None = _f("学校名称（英文）")
    name_native: str | None = _f("学校名称（中文）")
    address: Address = _f("学校地址", default=Address)
    course_of_study: str | None = _f("专业 / 课程（中学写 academic）")
    degree: str | None = _f("学历 / 学位（例如 本科 学士）")
    start_date: date | None = _f("入学日期")
    end_date: date | None = _f("毕业日期（在读留空）")


class EducationInfo(_ProfilePart):
    schools: list[SchoolEntry] = _f(
        "就读过的学校（中学及以上）", "Previous Work/Education/Training · Have you attended any educational institutions at a secondary level or above?", default=[])


# ---------- 分组 7：工作经历 ----------


class CurrentEmployer(_ProfilePart):
    name: str | None = _f("单位 / 学校名称（英文）")
    name_native: str | None = _f("单位 / 学校名称（中文）")
    address: Address = _f("单位 / 学校地址", default=Address)
    phone: str | None = _f("单位电话")
    job_title: str | None = _f("职位")
    start_date: date | None = _f("入职 / 入学日期")
    monthly_income: str | None = _f("税前月收入（含币种，例如 CNY 10000）", sensitive=True)
    duties: str | None = _f("工作职责简述", widget="textarea")


class PreviousEmployer(_ProfilePart):
    name: str | None = _f("单位名称（英文）")
    name_native: str | None = _f("单位名称（中文）")
    address: Address = _f("单位地址", default=Address)
    phone: str | None = _f("单位电话")
    job_title: str | None = _f("职位")
    supervisor_surname: str | None = _f("上司姓（拼音，不知道留空）")
    supervisor_given_names: str | None = _f("上司名（拼音，不知道留空）")
    start_date: date | None = _f("开始日期")
    end_date: date | None = _f("结束日期")
    duties: str | None = _f("工作职责简述", widget="textarea")


class EmploymentInfo(_ProfilePart):
    primary_occupation: Occupation | None = _f("主要职业", "Present Work/Education/Training · Primary Occupation",
                                               options=OCCUPATION_OPTIONS)
    occupation_explanation: str | None = _f("职业补充说明（待业 / 其他时填）", "Present Work/Education/Training · Explain / Specify", widget="textarea")
    current: CurrentEmployer = _f("目前的单位或学校", "Present Work/Education/Training · Present Employer or School", default=CurrentEmployer)
    previous: list[PreviousEmployer] = _f("以前的工作", "Previous Work/Education/Training · Were you previously employed?", default=[])


# ---------- 分组 8：旅行与签证历史（出行记录 travel_history 仍在顶层，见 PersonalProfile） ----------


class UsVisit(_ProfilePart):
    arrival_date: date | None = _f("入境美国日期")
    length_of_stay: str | None = _f("停留时长（例如 20 天 / 7 个月）")


class UsDriverLicense(_ProfilePart):
    number: str | None = _f("驾照号", sensitive=True)
    state: str | None = _f("所属州")


class VisaRecord(_ProfilePart):
    country: str | None = _f("国家 / 地区")
    visa_type: str | None = _f("签证类型（例如 B1/B2、F1、申根 C）")
    visa_number: str | None = _f("签证号（不知道留空）", sensitive=True)
    issue_date: date | None = _f("签发日期")
    expiry_date: date | None = _f("有效期至")
    issued_at: str | None = _f("签发地（使领馆）")
    lost_or_stolen: str | None = _f("遗失 / 被盗说明（含年份，没有就留空）", widget="textarea")
    cancelled_or_revoked: str | None = _f("被注销 / 撤销说明（没有就留空）", widget="textarea")


class VisaRefusal(_ProfilePart):
    country: str | None = _f("国家 / 地区")
    refused_date: date | None = _f("被拒日期")
    visa_type: str | None = _f("申请的签证类型")
    explanation: str | None = _f("情况说明", widget="textarea")


class TravelVisaInfo(_ProfilePart):
    us_visits: list[UsVisit] = _f("去过美国（最近 5 次）", "Previous U.S. Travel · Have you ever been in the U.S.? · Date Arrived / Length of Stay", default=[])
    us_driver_licenses: list[UsDriverLicense] = _f("美国驾照", "Previous U.S. Travel · Do you or did you ever hold a U.S. Driver's License?", default=[])
    visas: list[VisaRecord] = _f(
        "以往签证（各国）", "Previous U.S. Travel · Have you ever been issued a U.S. Visa?（取 country 为美国的最近一条）", default=[])
    us_ten_printed: bool | None = _f("办美签时录过十指指纹", "Previous U.S. Travel · Have you been ten-printed?")
    refusals: list[VisaRefusal] = _f(
        "拒签 / 拒绝入境记录（各国）", "Previous U.S. Travel · Have you ever been refused a U.S. Visa, or been refused admission ...?（取美国的）", default=[])
    us_immigrant_petition: str | None = _f(
        "有人为我在美国移民局提交过移民申请（说明；没有就留空）", "Previous U.S. Travel · Has anyone ever filed an immigrant petition on your behalf ...?", widget="textarea")


# ---------- 分组 9：其他背景 ----------


class MilitaryService(_ProfilePart):
    country: str | None = _f("服役国家")
    branch: str | None = _f("军种")
    rank: str | None = _f("级别 / 职务")
    specialty: str | None = _f("军事特长")
    start_date: date | None = _f("开始日期")
    end_date: date | None = _f("结束日期")


class BackgroundInfo(_ProfilePart):
    languages: list[str] = _f("会说的语言", "Additional Work/Education/Training · Provide a List of Languages You Speak", default=[])
    clan_or_tribe: str | None = _f("所属宗族或部落（没有留空）", "Additional Work/Education/Training · Do you belong to a clan or tribe?")
    organizations: list[str] = _f("参加过的专业/社会/慈善组织", "Additional Work/Education/Training · Have you belonged to, contributed to, or worked for any professional, social, or charitable organization?", default=[])
    specialized_skills: str | None = _f(
        "特殊技能或培训（枪械、爆炸物、核/生/化；没有留空）", "Additional Work/Education/Training · Do you have any specialized skills or training ...?", widget="textarea")
    military_service: list[MilitaryService] = _f("服兵役经历", "Additional Work/Education/Training · Have you ever served in the military?", default=[])


# ---------- 整份 ----------

# 分组 key → (中文名, 模型)。顺序就是界面上的显示顺序；PUT /api/personal-profile/{group} 只接受这些 key。
PROFILE_GROUPS: dict[str, tuple[str, type[BaseModel]]] = {
    "identity": ("基本身份", IdentityInfo),
    "passport": ("护照与证件", PassportInfo),
    "contact": ("联系方式与住址", ContactInfo),
    "family": ("家庭与婚育", FamilyInfo),
    "education": ("教育经历", EducationInfo),
    "employment": ("工作经历", EmploymentInfo),
    "travel": ("旅行与签证历史", TravelVisaInfo),
    "social_media": ("社交媒体", SocialMediaInfo),
    "background": ("其他背景", BackgroundInfo),
}

# 第一版（schema_version 1，没有这个字段）的平铺字段 → 新位置（分组, 字段）
LEGACY_PROFILE_FIELDS: dict[str, tuple[str, str]] = {
    "full_name": ("identity", "native_full_name"),
    "date_of_birth": ("identity", "date_of_birth"),
    "nationality": ("identity", "nationality"),
    "passport_number": ("passport", "passport_number"),
}


class PersonalProfile(_ProfilePart):
    """申请人级别的结构化个人信息，不挂在某次具体签证申请下（spec.md FR-011，specs/003）。

    这份数据本身就是"真实个人信息"，实际内容 MUST NOT 出现在 materials_index/（仓库会追踪
    的部分）——存储位置见 src/core/profile_storage.py 的说明。

    travel_history 留在顶层（而不是挪进 travel 分组）：「出行记录」标签页和出行记录接口
    都按 `profile.travel_history` 读它，挪位置得不偿失。
    """

    schema_version: int = PROFILE_SCHEMA_VERSION
    identity: IdentityInfo = Field(default_factory=IdentityInfo)
    passport: PassportInfo = Field(default_factory=PassportInfo)
    contact: ContactInfo = Field(default_factory=ContactInfo)
    family: FamilyInfo = Field(default_factory=FamilyInfo)
    education: EducationInfo = Field(default_factory=EducationInfo)
    employment: EmploymentInfo = Field(default_factory=EmploymentInfo)
    travel: TravelVisaInfo = Field(default_factory=TravelVisaInfo)
    social_media: SocialMediaInfo = Field(default_factory=SocialMediaInfo)
    background: BackgroundInfo = Field(default_factory=BackgroundInfo)
    travel_history: list[TravelHistoryEntry] = Field(default_factory=list)
    # 用户亲口确认"没有"的字段路径（例如 "identity.other_names"）。空值本身只表示"没填"，
    # 进了这个清单才表示"确认没有"，填表 Agent 可以直接答 No。字段有值时保存会自动移出清单。
    confirmed_none: list[str] = Field(default_factory=list)

    @field_validator("confirmed_none")
    @classmethod
    def _check_confirmed_none(cls, paths: list[str]) -> list[str]:
        out: list[str] = []
        for path in paths:
            group, _, key = path.partition(".")
            if group not in PROFILE_GROUPS or key not in PROFILE_GROUPS[group][1].model_fields:
                raise ValueError(f"confirmed_none 里的字段路径不存在：{path}")
            annotation = _strip_optional(PROFILE_GROUPS[group][1].model_fields[key].annotation)
            if annotation is bool:
                raise ValueError(f"{path} 是是非题，直接写 false，不用放进 confirmed_none")
            if path not in out:
                out.append(path)
        return out

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_fields(cls, data: Any) -> Any:
        """把第一版的平铺字段（full_name / date_of_birth / nationality / passport_number）
        搬进对应分组。新位置已经有值时以新位置为准（说明用户已经在新界面里改过了）。"""
        if not isinstance(data, dict):
            return data
        if not any(k in data for k in LEGACY_PROFILE_FIELDS):
            return data
        data = dict(data)
        for old_key, (group, new_key) in LEGACY_PROFILE_FIELDS.items():
            if old_key not in data:
                continue
            value = data.pop(old_key)
            group_data = data.get(group)
            if group_data is None:
                group_data = {}
            elif isinstance(group_data, BaseModel):
                group_data = group_data.model_dump()
            else:
                group_data = dict(group_data)
            if group_data.get(new_key) in (None, "") and value not in (None, ""):
                group_data[new_key] = value
            data[group] = group_data
        return data

    # 旧字段名的只读别名：Python 里按老名字读（profile.full_name）的代码不用跟着改。
    # 只是别名，不会出现在 JSON / YAML 里。
    @property
    def full_name(self) -> str | None:
        return self.identity.native_full_name

    @property
    def date_of_birth(self) -> date | None:
        return self.identity.date_of_birth

    @property
    def nationality(self) -> str | None:
        return self.identity.nationality

    @property
    def passport_number(self) -> str | None:
        return self.passport.passport_number


# ---------- 字段说明（给网页表单和 MCP 工具用） ----------


def _strip_optional(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _describe_model(model: type[BaseModel]) -> list[dict[str, Any]]:
    fields = []
    for key, info in model.model_fields.items():
        extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
        ann = _strip_optional(info.annotation)
        item: dict[str, Any] = {
            "key": key,
            "label": info.title or key,
            "ds160": extra.get("ds160"),
            "sensitive": bool(extra.get("sensitive", False)),
        }
        if get_origin(ann) is list:
            (inner,) = get_args(ann)
            if isinstance(inner, type) and issubclass(inner, BaseModel):
                item["type"] = "list"
                item["item_fields"] = _describe_model(inner)
            else:
                item["type"] = "list_text"
        elif isinstance(ann, type) and issubclass(ann, BaseModel):
            item["type"] = "object"
            item["fields"] = _describe_model(ann)
        elif get_origin(ann) is Literal:
            labels = extra.get("options") or {}
            item["type"] = "select"
            item["options"] = [{"value": v, "label": labels.get(v, v)} for v in get_args(ann)]
        elif ann is date:
            item["type"] = "date"
        elif ann is bool:
            item["type"] = "bool"
        else:
            item["type"] = extra.get("widget") or "text"
        fields.append(item)
    return fields


def describe_personal_profile() -> list[dict[str, Any]]:
    """按分组列出全部字段：key / 中文标签 / 类型 / 是否敏感 / DS-160 提示（列表和对象递归展开）。"""
    return [
        {"key": key, "label": label, "fields": _describe_model(model)}
        for key, (label, model) in PROFILE_GROUPS.items()
    ]
