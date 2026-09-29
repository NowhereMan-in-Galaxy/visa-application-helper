# DS-160（CEAC）页面对照表

来源：试验 #6（2026-09-24）在真实 CEAC 上实际走过、核实过的内容。**只写核实过的**；没走到的页标"未核实"。
这是提示，不是映射配置——页面改版时以页面实际为准，发现不符就改这里。不含任何个人信息。

- 网址：`https://ceac.state.gov/GenNIV/Default.aspx`（开始 / 找回申请）；表格各页 URL 形如 `/GenNIV/General/complete/complete_xxx.aspx?node=Xxx`。
- 元素 id 前缀统一是 `ctl00_SiteContentPlaceHolder_FormView1_`，下表省略。
- 按钮：`ctl00_SiteContentPlaceHolder_UpdateButton1` = Back，`UpdateButton2` = Save（只存草稿），`UpdateButton3` = Next。
- "基本信息"一列是 `specs/003` 的字段路径；"行程"表示本次行程专属信息，当场问、不写回。

## 通用规律（ASP.NET 表单）

- 选"是"后展开的子字段、"Add Another" 加的新行，常常要等**下一次保存**才出现；点完先等页面刷新完再读状态。
- 下拉框里有一部分自带刷新（例如社交平台），要用正常的选择动作触发；**不要用脚本直接改值，也不要用脚本触发 "Add Another / Remove"**，否则下一次请求会 Application Error。
- 20 分钟无操作超时；Application Error 或超时后要用户回答安全问题找回（当页未保存内容丢失，之前加过的空行会被服务器保留）。
- 日期：日、月是下拉框（月份值因页而异，有的是 `MAR`、有的是 `3`，按选项文字选），年是文本框。

## 各页

### Getting Started（开始）
- 由用户完成：选使领馆（必须和之后预约的一致，按领区选）、验证码、设置安全问题。

### Personal 1 — `complete_personal.aspx?node=Personal1`（标志：`tbxAPP_SURNAME`）
| 题目 | 基本信息 | 备注 |
|---|---|---|
| Surnames / Given Names / Full Name in Native Alphabet | identity.surname / given_names / native_full_name | |
| Have you ever used other names? | identity.other_names | 列表；confirmed_none → No |
| Telecode | identity.telecode_surname / telecode_given_names | 选 Yes 后出现两个输入框 |
| Sex | identity.sex | 下拉框（不是单选） |
| Marital Status | family.marital_status | 下拉 `ddlAPP_MARITAL_STATUS` |
| Date of Birth | identity.date_of_birth | `ddlDOBDay` / `ddlDOBMonth` / 文本框 `tbxDOBYear` |
| Place of Birth | identity.birth_city / birth_province / birth_country | |

### Personal 2 — `complete_personalcont.aspx?node=Personal2`
| 题目 | 基本信息 | 备注 |
|---|---|---|
| Nationality | identity.nationality | 下拉 |
| Other nationality? / Permanent resident elsewhere? | identity.other_nationalities / permanent_resident_countries | 单选 |
| National Identification Number | identity.national_id_number | |
| U.S. SSN | identity.us_ssn | 三个框，第 2、3 个是 `tbxAPP_SSN2` / `tbxAPP_SSN3` |
| U.S. Taxpayer ID | identity.us_taxpayer_id | 没有就勾 Does Not Apply |

### Travel — `complete_travel.aspx?node=Travel`（全部是行程信息）
- Purpose of Trip（下拉）→ 选 B 后出现 Specify（B1/B2 等）。
- Specific travel plans? 选 No 时：到达日期 `ddlTRAVEL_DTEDay` / `ddlTRAVEL_DTEMonth` / `tbxTRAVEL_DTEYear`，停留时长 `tbxTRAVEL_LOS` + 单位 `ddlTRAVEL_LOS_CD`，随后出现在美住址。
- Person/Entity Paying（下拉）。

### Travel Companions — `complete_travelcompanions.aspx`
- 一道是非题（行程信息）。

### Previous U.S. Travel — `complete_previousustravel.aspx`
| 题目 | 基本信息 | 备注 |
|---|---|---|
| Ever been in the U.S.? + 最近 5 次 | travel.us_visits | 行 id `dtlPREV_US_VISIT_ctl0N_…`（`ddlPREV_US_VISIT_DTEDay/DTEMonth`、`tbxPREV_US_VISIT_DTEYear`、`tbxPREV_US_VISIT_LOS`、`ddlPREV_US_VISIT_LOS_CD`）；加行用 `…_ctl0N_InsertButtonPREV_US_VISIT`，**真实点击**可用；最多 5 行 |
| U.S. Driver's License | travel.us_driver_licenses | |
| Ever been issued a U.S. visa? `rblPREV_VISA_IND` | travel.visas（country=美国的最新一张） | 签发日期、红色签证号（不是控制号） |
| Same type `_SAME_TYPE_IND` / same country `_SAME_CNTRY_IND` | 视本次申请而定 | 同国问的是"在上次签发国申请且为主要居住地" |
| Ten-printed `_TEN_PRINT_IND` | travel.us_ten_printed | |
| Lost or stolen `_LOST_IND` | travel.visas[*].lost_or_stolen | Yes 后出现 `tbxPREV_VISA_LOST_YEAR` 和说明框，要等刷新 |
| Cancelled / revoked `_CANCELLED_IND` | travel.visas[*].cancelled_or_revoked | 列表条目里的是非题，confirmed_none 表达不了，要问 |
| Refused / denied entry `rblPREV_VISA_REFUSED_IND` | travel.refusals | |
| Immigrant petition `rblIV_PETITION_IND` | travel.us_immigrant_petition | |
- 单选 id 规律：`_0` = Yes，`_1` = No。

### Address and Phone — `complete_contact.aspx?node=AddressPhone`（标志：`tbxAPP_ADDR_LN1`）
| 题目 | 基本信息 | 备注 |
|---|---|---|
| Home Address | contact.home_address | `tbxAPP_ADDR_LN1/LN2/CITY/STATE/POSTAL_CD`，国家 `ddlCountry` |
| Mailing same as home? | contact.mailing_same_as_home | |
| Primary Phone | contact.primary_phone | `tbxAPP_HOME_TEL` |
| Secondary Phone | contact.secondary_phone | `tbxAPP_MOBILE_TEL` |
| Work Phone | contact.work_phone | `tbxAPP_BUS_TEL`；没有就勾 Does Not Apply（必答） |
| Other phones in 5 years | contact.other_phones | 行 `dtlAddPhone_ctl0N_tbxAddPhoneInfo` |
| Email / other emails | contact.email / other_emails | `tbxAPP_EMAIL_ADDR`；行 `dtlAddEmail_ctl0N_tbxAddEmailInfo` |
| Social Media | social_media.accounts | `dtlSocial_ctl0N_ddlSocialMedia`（自带刷新，选完 Identifier 才解锁）+ `…_tbxSocialMediaIdent` |
| Other websites/apps | social_media.other_platforms | `dtlAddSocial_ctl0N_tbxAddSocialPlat/Hand` |
- 试验 #10：引擎一次填 8 格（地址、国家、两个电话、邮箱），无报错；单选题和多行列表由用户处理后保存成功。
- ⚠️ **这一页的多行列表不稳定**：试验 #6 共 4 次 Application Error。"其他平台"填了值保存就报错（选 No 正常）；脚本触发加行也报错；真实点击 Add Another / Remove 常被悬停提示挡住。**多行部分请用户手动点，Agent 只填单行字段。**

### Passport — `Passport_Visa_Info.aspx?node=PptVisa`（试验 #10 核实，标志：`tbxPPT_NUM`）
| 题目 | 基本信息 | 备注 |
|---|---|---|
| Passport/Travel Document Type | passport.passport_type | 下拉 `ddlPPT_TYPE`（REGULAR = `R`），**改了会刷新页面**，手动选 |
| Passport/Travel Document Number | passport.passport_number | `tbxPPT_NUM` |
| Passport Book Number | passport.passport_book_number | `tbxPPT_BOOK_NUM` |
| Country/Authority that Issued | passport.issuing_authority | 下拉 `ddlPPT_ISSUED_CNTRY`（CHINA = `CHIN`），不刷新 |
| Where Issued: City / State / Country | passport.issue_city / issue_province / issue_country | `tbxPPT_ISSUED_IN_CITY` / `_STATE`，下拉 `ddlPPT_ISSUED_IN_CNTRY` |
| Issuance Date / Expiration Date | passport.issue_date / expiry_date | 日、月下拉（月份值 `01`–`12`，文字 `JAN`…），年文本框 |
| Lost or stolen? | passport.lost_passports | 单选 `rblLOST_PPT`，有记录选 Yes 后填说明 |
- 试验 #10：引擎一次填 11 格，无报错；护照类型手动选。

### U.S. Contact / Family / Work-Education-Training / Security and Background（未核实）
- 试验 #6 没走到。基本信息里对应分组：passport、family、employment、education、background。护照页注意"签发国（passport.issuing_authority）"和"签发地所在国（passport.issue_country）"是两题。Security and Background 由用户本人作答。
