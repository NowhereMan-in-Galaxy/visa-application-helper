# materials_index/

这里存的是材料记录的**结构化元数据**（YAML），不是真实材料文件本身——真实文件放在 `materials_root`
配置指向的目录（见 `config.example.yaml`），两者通过每条记录里的 `file_ref`（相对路径）关联。

## 目录结构

- `applications/<id>.yaml` —— 一次签证申请（`VisaApplication`）
- `records/<id>.yaml` —— 一条材料记录（`MaterialRecord`），必须有 `belongs_to` 字段指向某个 `applications/` 里的 `id`（子目录特意不叫 `materials`，避免跟仓库外层的"材料根目录" `materials/` 撞名、也避免被同一条 `.gitignore` 规则意外忽略）

字段说明见 `src/core/models.py` 里的注释，或者直接照抄现有的示例文件改。

## 示例数据

`example-` 开头的文件是演示用的**虚构数据**，用来让你第一次跑起来就能在页面上看到效果。确认能跑通之后，
把这些 `example-*.yaml` 删掉，换成你自己的真实申请信息就行——记住这里只填元数据（日期、类型、状态这些），
真实文件本身放在 `materials_root` 指向的目录，不要把扫描件内容写进这些 YAML 里。
