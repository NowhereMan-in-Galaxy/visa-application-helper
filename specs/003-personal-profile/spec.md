# Feature Specification: 基本信息（结构化个人资料，PersonalProfile 第二版）

**Created**: 2026-09-23

**Status**: 已实现第一版（数据结构 + 接口 + 「我的资料 → 基本信息」页 + 只读 MCP 工具）

**Input**: 项目主希望把"可以反复复用、但不是文件形式"的个人资料（姓名拼音、护照号、出生日期/地点、联系方式、住址、教育、工作、家庭成员、婚育、旅行史、以往签证/拒签、社交媒体……）做成结构化数据：在本地网页里填写，保存在本机材料根目录下（不进 git）。**将来另一个 Agent 会读取它辅助填写 DS-160 等官网表格**——填表不是本 spec 的范围，但数据结构要为它设计好。

字段是参考真实的 DS-160 表格结构（美国非移民签证在线申请表）和一份中介用的 DS-160 资料收集表归纳出来的，**只提取了"问什么"，没有使用任何真实值**。本文档和测试里的所有示例都是虚构的（张三 / ZHANG SAN / E12345678 / 2000-01-01）。

## 与已有文档的关系

- **扩展** `specs/001-visa-material-hub/spec.md` 的 FR-011 / Key Entities 里的 `PersonalProfile`：原来只有 `full_name` / `date_of_birth` / `nationality` / `passport_number` / `travel_history` 五个字段，现在按分组扩展。FR-011 的约束（真实个人信息只存在材料根目录、申请人级别单一文档、不经过 `MaterialRecord`）**继续有效**。
- **不改变** FR-013（出行记录的增改接口和「出行记录」标签页），`travel_history` 仍在文件顶层。
- 与 specs/002 的关系：Track 里记录的是"这一次办事"的情况；本 spec 记录的是"这个人"的长期资料。一次行程专属的信息（见下"不收什么"）属于 Track 或将来的填表 Agent，不进这份资料。

## 名词解释（给新手）

- **分组（group）**：把几十个字段按主题分成 9 块（基本身份、护照……）。网页上一块一个面板、一个保存按钮；接口也按分组保存。
- **列表字段 / 条目**：有些信息天生是"好几条"，比如上过的几所学校、做过的几份工作。它们存成列表，每一条叫一个"条目"，条目有自己的固定结构（例如学校条目 = 名称 + 地址 + 专业 + 起止日期）。
- **敏感（sensitive）**：证件号、出生日期、收入这类一旦泄露风险较高的字段。它们照样存、照样给填表 Agent 用，只是标记出来，让调用方知道不要在对话里随便复述。
- **ds160 提示**：这个字段对应 DS-160 哪一页、哪一问（用 DS-160 页面英文标题 + 问题原文，例如 `Personal 1 · Surnames`）。填表 Agent 靠它把资料对到表格上。和 DS-160 无关的字段写 `null`。
- **`extra="forbid"`**：pydantic（Python 数据校验库）的一个设置：遇到没定义过的字段名就报错。用来抓拼写错误，见"数据校验"。

## 存储

- 位置不变：`<材料根目录>/personal-profile.yaml`。材料根目录默认是仓库下的 `materials/`（`.gitignore` 第一条就是 `materials/`），或 `config.yaml` 里配置的仓库外目录。**这个文件永远不进 git。**
- 文件结构：

```yaml
schema_version: 2
identity: {...}        # 分组 1
passport: {...}        # 分组 2
contact: {...}
family: {...}
education: {...}
employment: {...}
travel: {...}
social_media: {...}
background: {...}
travel_history: [...]  # 出行记录，保持在顶层（FR-013）
```

- 每次保存都把整份文件重新写一遍（`yaml.safe_dump`，`allow_unicode=True`，保留字段顺序），没填的字段写成 `null`、空列表写成 `[]`——这样用户手动打开文件时能看到全部可填的位置。

## 向后兼容与迁移

第一版文件长这样（虚构值）：

```yaml
full_name: 张三
date_of_birth: '2000-01-01'
nationality: 中国
passport_number: E12345678
travel_history:
- {country: 日本, entry_date: '2026-05-01', exit_date: '2026-05-10', purpose: 旅游}
```

- **读的时候自动迁移，不需要跑脚本**：`PersonalProfile` 的 `model_validator(mode="before")` 在校验之前把旧字段搬家：

  | 旧字段 | 新位置 |
  |---|---|
  | `full_name` | `identity.native_full_name` |
  | `date_of_birth` | `identity.date_of_birth` |
  | `nationality` | `identity.nationality` |
  | `passport_number` | `passport.passport_number` |

  `full_name` 放进"中文姓名"：第一版界面上它就叫"姓名"，中文用户填的大多是中文名；如果当时填的是拼音，用户在「基本信息」里挪一下即可。
- 新旧位置都有值时，**以新位置为准**（说明用户已经在新界面改过），旧值丢弃。
- **下一次保存时才以新格式写回**（旧字段名从文件里消失，出现 `schema_version: 2`）。只读不写的话，磁盘上的旧文件保持原样。
- Python 代码里 `profile.full_name` / `.date_of_birth` / `.nationality` / `.passport_number` 仍然可以读（只读属性，指向新位置），也可以用旧关键字构造 `PersonalProfile(full_name=...)`，所以已有调用方不用改。JSON / YAML 里不再出现这四个旧 key。
- `travel_history` 的结构（`TravelHistoryEntry`）完全不变，旧版材料维护页、工作台、「出行记录」标签页都不受影响。
- 以后再改结构时：把 `schema_version` 加一，在同一个 `model_validator` 里按版本号补迁移分支。

## 数据校验

- 所有分组和条目模型都是 `extra="forbid"`：
  - **请求里**拼错字段名（例如 `surnme`）→ 接口返回 422，`detail` 里写出错的字段路径，文件不会被改动。
  - **文件里**拼错字段名、YAML 语法错、日期写错 → `load_personal_profile` 抛 `ProfileFileError`，`GET /api/personal-profile` 返回 500 + 中文 `detail`（含文件名），**任何保存接口也都拒绝执行**，原文件不会被覆盖。
  - 为什么不"忽略未知字段"：因为保存是整份重写，忽略 = 下一次保存时把用户手写的内容悄悄删掉。宁可报错让人修。
  - 例外：`TravelHistoryEntry` 保持第一版的行为（未知字段被忽略），不在本次改动范围内。
- 日期字段一律是 `YYYY-MM-DD`，由 pydantic 的 `date` 类型校验：`2000-13-01`、`2000-02-30`、`not-a-date` 都返回 422。"不知道"就留空（`null`），不支持"只填年月"。
- 下拉字段（`select`）只接受表里列出的英文值，其他值 422。存英文值、界面显示中文，是为了以后换界面语言或给 Agent 读时含义稳定。
- **不做**跨字段的逻辑校验（例如"毕业日期不能早于入学日期""护照有效期要晚于签发日期"），留给以后。
- 空字符串：网页在提交前把空输入转成 `null`；接口本身不做这个转换（`""` 会原样存下）。

## 空值的含义（填表 Agent 必须遵守）

- `null` / `[]` 表示"**用户没填**"，**不等于**回答"否 / 没有"。例如 `travel.refusals == []` 不能直接理解成"从没被拒签"——填表 Agent 遇到必答的是非题时，应该先向用户确认。
- `bool` 字段三态：`true` / `false` / `null`（未填）。
- 是非题 + 详情的问题（例如"是否属于某个宗族"），用"详情字段有值 = 是"表达，不另设布尔字段。

## 分组与字段

共 **9 个分组、62 个顶层字段**；列表条目和子对象的结构在本节末尾单列（例如 `schools` 的条目结构）。表格由代码里的字段定义生成（`describe_personal_profile()`），`tests/unit/test_personal_profile.py::test_every_field_key_is_documented_in_spec` 会检查代码里的每个 key 都在本文档中出现。

### `identity` 基本身份（17 个字段）

| key | 中文标签 | 类型 | 敏感 | ds160 提示 |
|---|---|---|---|---|
| `surname` | 姓（拼音，同护照） | text |  | Personal 1 · Surnames |
| `given_names` | 名（拼音，同护照） | text |  | Personal 1 · Given Names |
| `native_full_name` | 中文姓名 | text |  | Personal 1 · Full Name in Native Alphabet |
| `other_names` | 曾用名 | list[条目]（结构见 §other_names） |  | Personal 1 · Have you ever used other names? |
| `telecode_surname` | 姓的电码 | text |  | Personal 1 · Telecode that represents your name |
| `telecode_given_names` | 名的电码 | text |  | Personal 1 · Telecode that represents your name |
| `sex` | 性别 | select：`male` / `female` |  | Personal 1 · Sex |
| `date_of_birth` | 出生日期 | date | 是 | Personal 1 · Date of Birth |
| `birth_city` | 出生城市 | text |  | Personal 1 · Place of Birth · City |
| `birth_province` | 出生省份 | text |  | Personal 1 · Place of Birth · State/Province |
| `birth_country` | 出生国家 | text |  | Personal 1 · Place of Birth · Country/Region |
| `nationality` | 国籍 | text |  | Personal 2 · Country/Region of Origin (Nationality) |
| `other_nationalities` | 其他国籍（现有或曾有） | list[条目]（结构见 §other_nationalities） |  | Personal 2 · Do you hold or have you held any nationality other than ...? |
| `permanent_resident_countries` | 在其他国家有永久居留权 | list[text] |  | Personal 2 · Are you a permanent resident of a country/region other than ...? |
| `national_id_number` | 身份证号 | text | 是 | Personal 2 · National Identification Number |
| `us_ssn` | 美国社会安全号（SSN） | text | 是 | Personal 2 · U.S. Social Security Number |
| `us_taxpayer_id` | 美国纳税人识别号（TIN） | text | 是 | Personal 2 · U.S. Taxpayer ID Number |

### `passport` 护照与证件（10 个字段）

| key | 中文标签 | 类型 | 敏感 | ds160 提示 |
|---|---|---|---|---|
| `passport_type` | 护照类型 | select：`regular` / `official` / `diplomatic` / `other` |  | Passport · Passport/Travel Document Type |
| `passport_number` | 护照号 | text | 是 | Passport · Passport/Travel Document Number |
| `passport_book_number` | 护照本号（Book Number） | text | 是 | Passport · Passport Book Number |
| `issuing_authority` | 签发国家/机关 | text |  | Passport · Country/Authority that Issued |
| `issue_city` | 签发城市 | text |  | Passport · Where was the Passport Issued? · City |
| `issue_province` | 签发省/州 | text |  | Passport · Where was the Passport Issued? · State/Province |
| `issue_country` | 签发国家/地区 | text |  | Passport · Where was the Passport Issued? · Country/Region |
| `issue_date` | 签发日期 | date |  | Passport · Issuance Date |
| `expiry_date` | 有效期至 | date |  | Passport · Expiration Date |
| `lost_passports` | 遗失或被盗过的护照 | list[条目]（结构见 §lost_passports） |  | Passport · Have you ever lost a passport or had one stolen? |

### `contact` 联系方式与住址（9 个字段）

| key | 中文标签 | 类型 | 敏感 | ds160 提示 |
|---|---|---|---|---|
| `home_address` | 家庭住址 | object（结构见 §home_address） |  | Address and Phone · Home Address |
| `mailing_same_as_home` | 邮寄地址与家庭住址相同 | bool |  | Address and Phone · Is your Mailing Address the same as your Home Address? |
| `mailing_address` | 邮寄地址（与家庭住址不同时填） | object（结构见 §home_address） |  | Address and Phone · Mailing Address |
| `primary_phone` | 主要电话 | text |  | Address and Phone · Primary Phone Number |
| `secondary_phone` | 备用电话 | text |  | Address and Phone · Secondary Phone Number |
| `work_phone` | 工作电话 | text |  | Address and Phone · Work Phone Number |
| `other_phones` | 过去 5 年用过的其他电话 | list[text] |  | Address and Phone · Have you used any other phone numbers in the last five years? |
| `email` | 主要邮箱 | text |  | Address and Phone · Email Address |
| `other_emails` | 过去 5 年用过的其他邮箱 | list[text] |  | Address and Phone · Have you used any other email addresses in the last five years? |

### `family` 家庭与婚育（8 个字段）

| key | 中文标签 | 类型 | 敏感 | ds160 提示 |
|---|---|---|---|---|
| `marital_status` | 婚姻状况 | select：`single` / `married` / `common_law` / `civil_union` / `divorced` / `widowed` / `separated` / `other` |  | Personal 1 · Marital Status |
| `father` | 父亲 | object（结构见 §father） |  | Family · Relatives · Father's Full Name and Date of Birth |
| `mother` | 母亲 | object（结构见 §father） |  | Family · Relatives · Mother's Full Name and Date of Birth |
| `spouse` | 配偶（已婚时填） | object（结构见 §spouse） |  | Family · Spouse |
| `former_spouses` | 前配偶 / 已故配偶 | list[条目]（结构见 §former_spouses） |  | Family · Former Spouse |
| `children` | 子女 | list[条目]（结构见 §children） |  | null |
| `us_immediate_relatives` | 在美国的直系亲属（父母以外） | list[条目]（结构见 §us_immediate_relatives） |  | Family · Relatives · Do you have any immediate relatives, not including parents, in the United States? |
| `other_relatives_in_us` | 在美国还有其他亲属 | bool |  | Family · Relatives · Do you have any other relatives in the United States? |

### `education` 教育经历（1 个字段）

| key | 中文标签 | 类型 | 敏感 | ds160 提示 |
|---|---|---|---|---|
| `schools` | 就读过的学校（中学及以上） | list[条目]（结构见 §schools） |  | Previous Work/Education/Training · Have you attended any educational institutions at a secondary level or above? |

### `employment` 工作经历（4 个字段）

| key | 中文标签 | 类型 | 敏感 | ds160 提示 |
|---|---|---|---|---|
| `primary_occupation` | 主要职业 | select：`agriculture` / `artist_performer` / `business` / `communications` / `computer_science` / `culinary_food_services` / `education` / `engineering` / `government` / `homemaker` / `legal_profession` / `medical_health` / `military` / `natural_science` / `not_employed` / `physical_sciences` / `religious_vocation` / `research` / `retired` / `social_science` / `student` / `other` |  | Present Work/Education/Training · Primary Occupation |
| `occupation_explanation` | 职业补充说明（待业 / 其他时填） | text（多行） |  | Present Work/Education/Training · Explain / Specify |
| `current` | 目前的单位或学校 | object（结构见 §current） |  | Present Work/Education/Training · Present Employer or School |
| `previous` | 以前的工作 | list[条目]（结构见 §previous） |  | Previous Work/Education/Training · Were you previously employed? |

### `travel` 旅行与签证历史（6 个字段）

| key | 中文标签 | 类型 | 敏感 | ds160 提示 |
|---|---|---|---|---|
| `us_visits` | 去过美国（最近 5 次） | list[条目]（结构见 §us_visits） |  | Previous U.S. Travel · Have you ever been in the U.S.? · Date Arrived / Length of Stay |
| `us_driver_licenses` | 美国驾照 | list[条目]（结构见 §us_driver_licenses） |  | Previous U.S. Travel · Do you or did you ever hold a U.S. Driver's License? |
| `visas` | 以往签证（各国） | list[条目]（结构见 §visas） |  | Previous U.S. Travel · Have you ever been issued a U.S. Visa?（取 country 为美国的最近一条） |
| `us_ten_printed` | 办美签时录过十指指纹 | bool |  | Previous U.S. Travel · Have you been ten-printed? |
| `refusals` | 拒签 / 拒绝入境记录（各国） | list[条目]（结构见 §refusals） |  | Previous U.S. Travel · Have you ever been refused a U.S. Visa, or been refused admission ...?（取美国的） |
| `us_immigrant_petition` | 有人为我在美国移民局提交过移民申请（说明；没有就留空） | text（多行） |  | Previous U.S. Travel · Has anyone ever filed an immigrant petition on your behalf ...? |

### `social_media` 社交媒体（2 个字段）

| key | 中文标签 | 类型 | 敏感 | ds160 提示 |
|---|---|---|---|---|
| `accounts` | 过去 5 年用过的社交媒体账号 | list[条目]（结构见 §accounts） |  | Address and Phone · Social Media Provider/Platform + Identifier |
| `other_platforms` | 其他发布内容的网站/应用 | list[条目]（结构见 §accounts） |  | Address and Phone · Do you wish to provide information about your presence on any other websites or applications ...? |

### `background` 其他背景（5 个字段）

| key | 中文标签 | 类型 | 敏感 | ds160 提示 |
|---|---|---|---|---|
| `languages` | 会说的语言 | list[text] |  | Additional Work/Education/Training · Provide a List of Languages You Speak |
| `clan_or_tribe` | 所属宗族或部落（没有留空） | text |  | Additional Work/Education/Training · Do you belong to a clan or tribe? |
| `organizations` | 参加过的专业/社会/慈善组织 | list[text] |  | Additional Work/Education/Training · Have you belonged to, contributed to, or worked for any professional, social, or charitable organization? |
| `specialized_skills` | 特殊技能或培训（枪械、爆炸物、核/生/化；没有留空） | text（多行） |  | Additional Work/Education/Training · Do you have any specialized skills or training ...? |
| `military_service` | 服兵役经历 | list[条目]（结构见 §military_service） |  | Additional Work/Education/Training · Have you ever served in the military? |

### 条目 / 子对象结构

#### §other_names

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `surname` | 姓（拼音） | text |  |
| `given_names` | 名（拼音） | text |  |

#### §other_nationalities

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `country` | 国籍国家 | text |  |
| `passport_number` | 该国护照号（没有就留空） | text | 是 |

#### §lost_passports

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `passport_number` | 遗失/被盗的护照号（不知道就留空） | text | 是 |
| `issuing_country` | 签发国家 | text |  |
| `explanation` | 经过说明 | text（多行） |  |

#### §home_address（`Address`：所有地址字段共用这个结构）

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `street` | 街道地址（门牌、楼栋、单元、房号） | text |  |
| `city` | 城市 | text |  |
| `province` | 省 / 州 | text |  |
| `postal_code` | 邮编 | text |  |
| `country` | 国家 / 地区 | text |  |

#### §father

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `surname` | 姓（拼音） | text |  |
| `given_names` | 名（拼音） | text |  |
| `date_of_birth` | 出生日期（不知道就留空） | date | 是 |
| `in_us` | 目前在美国 | bool |  |
| `us_status` | 在美身份（在美国时填） | select：`us_citizen` / `lpr` / `nonimmigrant` / `other` |  |

#### §spouse

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `surname` | 姓（拼音） | text |  |
| `given_names` | 名（拼音） | text |  |
| `date_of_birth` | 出生日期 | date | 是 |
| `nationality` | 国籍 | text |  |
| `birth_city` | 出生城市 | text |  |
| `birth_country` | 出生国家 | text |  |
| `address_type` | 配偶住址 | select：`same_as_home` / `same_as_mailing` / `same_as_us_contact` / `other` |  |
| `address` | 配偶住址（选「其他」时填） | object（结构见 §home_address） |  |

#### §former_spouses

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `surname` | 姓（拼音） | text |  |
| `given_names` | 名（拼音） | text |  |
| `date_of_birth` | 出生日期 | date | 是 |
| `nationality` | 国籍 | text |  |
| `birth_city` | 出生城市 | text |  |
| `birth_country` | 出生国家 | text |  |
| `marriage_start` | 结婚日期 | date |  |
| `marriage_end` | 婚姻结束日期 | date |  |
| `how_ended` | 婚姻如何结束（离婚原因 / 丧偶） | text（多行） |  |
| `country_ended` | 在哪个国家结束 | text |  |

#### §children

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `surname` | 姓（拼音） | text |  |
| `given_names` | 名（拼音） | text |  |
| `native_full_name` | 中文姓名 | text |  |
| `date_of_birth` | 出生日期 | date | 是 |
| `nationality` | 国籍 | text |  |

#### §us_immediate_relatives

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `surname` | 姓（拼音） | text |  |
| `given_names` | 名（拼音） | text |  |
| `relationship` | 与我的关系 | select：`spouse` / `fiance` / `child` / `sibling` |  |
| `us_status` | 在美身份 | select：`us_citizen` / `lpr` / `nonimmigrant` / `other` |  |

#### §schools

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `name` | 学校名称（英文） | text |  |
| `name_native` | 学校名称（中文） | text |  |
| `address` | 学校地址 | object（结构见 §home_address） |  |
| `course_of_study` | 专业 / 课程（中学写 academic） | text |  |
| `degree` | 学历 / 学位（例如 本科 学士） | text |  |
| `start_date` | 入学日期 | date |  |
| `end_date` | 毕业日期（在读留空） | date |  |

#### §current

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `name` | 单位 / 学校名称（英文） | text |  |
| `name_native` | 单位 / 学校名称（中文） | text |  |
| `address` | 单位 / 学校地址 | object（结构见 §home_address） |  |
| `phone` | 单位电话 | text |  |
| `job_title` | 职位 | text |  |
| `start_date` | 入职 / 入学日期 | date |  |
| `monthly_income` | 税前月收入（含币种，例如 CNY 10000） | text | 是 |
| `duties` | 工作职责简述 | text（多行） |  |

#### §previous

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `name` | 单位名称（英文） | text |  |
| `name_native` | 单位名称（中文） | text |  |
| `address` | 单位地址 | object（结构见 §home_address） |  |
| `phone` | 单位电话 | text |  |
| `job_title` | 职位 | text |  |
| `supervisor_surname` | 上司姓（拼音，不知道留空） | text |  |
| `supervisor_given_names` | 上司名（拼音，不知道留空） | text |  |
| `start_date` | 开始日期 | date |  |
| `end_date` | 结束日期 | date |  |
| `duties` | 工作职责简述 | text（多行） |  |

#### §us_visits

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `arrival_date` | 入境美国日期 | date |  |
| `length_of_stay` | 停留时长（例如 20 天 / 7 个月） | text |  |

#### §us_driver_licenses

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `number` | 驾照号 | text | 是 |
| `state` | 所属州 | text |  |

#### §visas

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `country` | 国家 / 地区 | text |  |
| `visa_type` | 签证类型（例如 B1/B2、F1、申根 C） | text |  |
| `visa_number` | 签证号（不知道留空） | text | 是 |
| `issue_date` | 签发日期 | date |  |
| `expiry_date` | 有效期至 | date |  |
| `issued_at` | 签发地（使领馆） | text |  |
| `lost_or_stolen` | 遗失 / 被盗说明（含年份，没有就留空） | text（多行） |  |
| `cancelled_or_revoked` | 被注销 / 撤销说明（没有就留空） | text（多行） |  |

#### §refusals

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `country` | 国家 / 地区 | text |  |
| `refused_date` | 被拒日期 | date |  |
| `visa_type` | 申请的签证类型 | text |  |
| `explanation` | 情况说明 | text（多行） |  |

#### §accounts

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `platform` | 平台（例如 微博 / 小红书 / LinkedIn） | text |  |
| `identifier` | 账号 / 用户名 | text |  |

#### §military_service

| key | 中文标签 | 类型 | 敏感 |
|---|---|---|---|
| `country` | 服役国家 | text |  |
| `branch` | 军种 | text |  |
| `rank` | 级别 / 职务 | text |  |
| `specialty` | 军事特长 | text |  |
| `start_date` | 开始日期 | date |  |
| `end_date` | 结束日期 | date |  |


## 不收什么（以及为什么）

| DS-160 里的内容 | 为什么不收 |
|---|---|
| Security and Background 第 1–5 页（传染病、犯罪记录、毒品、恐怖活动、被驱逐……约 30 个是非题） | ①这些是每次申请都要本人重新作答的法律声明，由程序"预填"容易让人不看就提交；②几乎所有人都答"否"，存下来没有复用价值；③少数答"是"的情况属于最高敏感度的信息，不应该在本机明文 YAML 里长期保存。填表 Agent 应该把这几页留给用户自己逐题确认。 |
| Travel（本次行程：目的、到达日期、停留时长、在美地址、谁付钱） | 属于"这一次办事"，每次都不同，应该放在 Track 或由填表 Agent 当场问。 |
| Travel Companions（同行人） | 同上，每次行程不同。 |
| U.S. Point of Contact（在美联系人） | 同上；多数情况下跟随本次行程（邀请人、学校、酒店）。 |
| Student/Exchange 页（SEVIS ID、学校、两个国内联系人） | 只针对 F/J/M 签证的某一次申请；SEVIS ID 每个项目不同。 |
| Location / Preparer（在哪里递签、谁帮忙填表） | 每次申请不同。 |
| 递签用的邮寄/取件方式、预约账号密码 | 与表格本身无关；密码类信息绝不存。 |

"以往签证 / 拒签 / 去过美国 / 美国驾照"虽然出现在 DS-160 的 Previous U.S. Travel 页，但属于长期的个人历史，会在多次申请里复用，所以收（`travel` 分组）。`visas` 和 `refusals` 设计成"各国通用"（每条带 `country`），申根、英签等表格也会问以往签证和拒签；DS-160 只取其中 `country` 为美国的条目。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/personal-profile` | 整份资料（新结构）。文件格式有误时 500 + `detail`。 |
| GET | `/api/personal-profile/fields` | 字段说明：`[{key, label, fields: [{key, label, type, sensitive, ds160, options?, fields?, item_fields?}]}]`，`type` ∈ `text` / `textarea` / `date` / `bool` / `select` / `list_text` / `list` / `object`。网页按它生成表单。 |
| PUT | `/api/personal-profile/{group}` | 整组保存。`group` 必须是 9 个分组 key 之一（否则 404）；请求体是该分组的完整 JSON；只替换这一组，其他分组和 `travel_history` 保持不变；返回保存后的整份资料。校验失败 422，`detail` 是一句中文字符串（含字段路径，例如 `schools.0.start_date`）。 |
| POST | `/api/personal-profile/travel-history` | 不变（FR-013）。 |
| PUT | `/api/personal-profile/travel-history/{index}` | 不变（FR-013）。 |

- **为什么按分组保存，而不是整份 PUT**：「基本信息」和「出行记录」两个标签页、以及同一页里的不同面板各自保存，互不覆盖对方刚保存的内容。
- **列表条目的增删改**：没有单独的"加一条学校"接口，前端在本地改好整个分组（含列表）后整组 PUT。列表很短（几条到十几条），整组发送最简单，也不会出现"按下标删错条目"的问题。
- 没有删除整份资料的接口。

## MCP 工具（给本地 Agent）

- `get_personal_profile()`：**只读**。返回 `{"profile": <整份资料 JSON>, "fields": <同 /fields 的字段说明>}`。实现在 `src/agent_tools/tools.py`，注册在 `src/agent_tools/mcp_server.py`。
- 工具描述里写明：内容是真实个人信息；不要在对话里整段复述 `sensitive` 字段；空值 ≠ "否"，要先问用户；没有写工具。
- **不提供任何写工具**：个人资料只能由用户本人在网页上改，避免 Agent 把猜测写进去。

## 界面：「我的资料 → 基本信息」

- `web/my.html` 的标签页新增「基本信息」（地址 `/my.html#profile`），与「材料库」「出行记录」并列。
- 每个分组一个可折叠面板（`<details>`，第一个默认展开），面板里按字段说明生成表单：
  - `text` → 单行输入框；`textarea` → 多行；`date` → 日期选择；`bool` → 下拉「未填 / 是 / 否」；`select` → 下拉（第一项「未填」）；`list_text` → 每行一个输入框 + 「＋ 添加」「删除」；`list` → 每个条目一个小卡片 + 「＋ 添加一条」「删除这条」；`object` → 带标题的一组输入框。
  - 敏感字段的标签后面有「敏感」小标记。
  - 每个面板底部一个「保存」按钮；保存成功在按钮旁显示「已保存 HH:MM」，失败在页面顶部红色横幅显示接口返回的 `detail`。
  - 编辑中的内容存在页面内存里（每个分组一份草稿），切换标签页、增删条目都不会丢；刷新页面会丢掉**未保存**的修改。
- 遵守现有前端约定：原生 JS；DOM 一律用 `my.js` 里的 `el()` 构造，不用 `innerHTML`；不用 `alert` / `confirm`；依赖全局 `[hidden]{display:none!important}`。
- 手机宽度（≤650px）下表单单列排列，输入框占满宽度，不出现横向滚动。

## 验收标准（可机械检查）

1. `uv run pytest -q` 全部通过（含原有测试与 `tests/unit/test_personal_profile.py`）。
2. 把本文"向后兼容与迁移"一节的第一版 YAML 放进临时材料根目录，`load_personal_profile` 返回的对象满足：`identity.native_full_name == "张三"`、`identity.date_of_birth == 2000-01-01`、`identity.nationality == "中国"`、`passport.passport_number == "E12345678"`、`len(travel_history) == 1`。
3. 对第 2 条的对象调用 `save_personal_profile` 后，文件里有 `schema_version: 2`，没有 `full_name` / `date_of_birth` / `nationality` / `passport_number` 四个顶层 key。
4. `PUT /api/personal-profile/education` 发送一个含 1 所学校（含地址子对象和两个日期）的分组后，`GET /api/personal-profile` 的 `education` 与发送内容逐字段相等。
5. `PUT /api/personal-profile/contact` 之后，`identity` 分组和 `travel_history` 与保存前相同。
6. `PUT /api/personal-profile/identity`，`date_of_birth` 为 `2000-13-01` / `2000-02-30` / `not-a-date` 时返回 422，`detail` 含 `date_of_birth`，文件未被创建/修改。
7. 请求体含未定义字段（如 `surnme`）→ 422；文件里含未定义字段 → `GET` 返回 500 且 `detail` 含 `personal-profile.yaml`，随后的 `PUT` 也返回 500，文件内容不变。
8. `PUT /api/personal-profile/travel_history` 和 `PUT /api/personal-profile/nope` 返回 404。
9. `GET /api/personal-profile/fields` 返回 9 个分组，顺序为 `identity, passport, contact, family, education, employment, travel, social_media, background`；每个字段都有含中文的 `label`。
10. 代码中每个字段 key（含条目和子对象里的）都以反引号形式出现在本文档中（测试 `test_every_field_key_is_documented_in_spec`）。
11. `agent_tools.tools.get_personal_profile()` 返回的 dict 有 `profile` 和 `fields` 两个 key；`mcp_server.py` 里没有名字形如 `set_/save_/update_/put_…profile` 的工具。
12. 浏览器打开 `/my.html#profile`：能看到 9 个分组面板；在「教育经历」里点「＋ 添加一条」会多出一个空条目卡片，点「删除这条」会移除；点「保存」后出现「已保存」字样；刷新页面后已保存的值仍在。
13. `grep -nE "\.innerHTML|alert\(|confirm\(" web/assets/my.js` 没有输出。
14. 仓库里（含本文档、测试、提交信息）不出现任何真实姓名、证件号、电话、地址、学校、单位；示例一律为虚构值。

## 待定 / 以后再说

- **教育经历与材料库关联**：`education.schools[*]` 可以加一个 `material_ids`，指向材料库里的毕业证 / 学位证 / 成绩单（词表类型 `graduation_certificate` / `degree_certificate` / `transcript` / `overseas_degree_certification`）；工作经历同理可关联在职证明。本版不做，先观察实际填表时是否需要。
- **家庭成员的其他资料**：申根 / 英签常要父母职业、联系方式、子女是否同行等；目前父母只收 DS-160 问到的字段，等接入第二种表格时再扩展。
- **跨字段校验**（日期先后、护照是否快过期提醒）。
- **从现有文件导入**（例如从旧的 DS-160 打印页 PDF 自动抽取填入）：需要 OCR/解析，属于 Agent 层，另开 spec。
- **填表 Agent** 本身：读 `get_personal_profile()` → 按 `ds160` 提示映射 → 本次行程信息从 Track 或对话获得 → Security 页交给用户。另开 spec。
