# 存档字段与关联分析

本文记录已经从本机游戏代码及配置核对的结构，不包含用户存档快照或完整提取资源。版本依据见 `RESEARCH.md`。

## 文件与字节结构

`cs_player_files/cs_save_datas#<槽位>.sd` 是 GZip 压缩的 UTF-8 JSON，没有另加密封装。根对象对应 `CoffeeShop.CSSaveData`。编号目录下的 `.hs` 是独立历史记录文件；`cs_settings.sd` 是设置存档，编辑器不修改这两类文件。

`CreateDate` 与 `LastChangeDate` 为 .NET DateTime ticks，JSON 中是超过 JavaScript 精确整数范围的整数，因此只读并以十进制字符串送至浏览器。`SlotNum`、`Seed`、`GameVer`、`SaveCount` 与 `PlayTime_Minutes` 为槽位、随机种子、游戏版本、保存次数和累计分钟数，均只读。

`DaysInGame` 与 `IsNight` 控制游戏日期/阶段，关联邮件、价格和事件。游戏的日期推进还跳过周末，因此不能把它们当作独立无副作用数值编辑；当前只读。

## 店铺

| 字段 | 类型 | 含义与关联 |
| --- | --- | --- |
| TotalCash | Int64 | 资金；游戏代码限制 0–999,999,999 |
| HPoint | Int64 | H 点；游戏代码限制 0–99,999,999 |
| CoffeeShopName | string | 店铺名称 |
| ShopLevel | Int32 | 对应本机店铺等级主表；决定基础客流和工作员工上限 |
| ShopExp | Int32 | 当前等级进度；低于目标等级的 NextExp，最终等级无下一阶时为 0 |
| ShopStars | float[] | 最近最多七次评分，新值插入索引 0；平均值由游戏计算 |
| Difficulty | enum | 0 = Normal，1 = Easy |
| FinancingCount | Int32 | 剩余融资次数，配置上限读取本机 CSSettings；设值不自动发钱 |
| PlayerCharaType | enum | 玩家角色模板类型；当前只读 |

直接设置店铺等级与经验不会模拟结算、领取升级任务奖励或更新历史记录。等级配置表在网页中可查看；不是存档里可独立修改的“基础客流”字段。

## 员工与玩家

`Charas[]` 每条记录对应一个角色，包括 `IsPlayerChara`、`Work`、`Pos`、`Attr`、`Looks` 和 `UnlockHPoses`。玩家也有基础属性，但不开放将玩家分配为工作员工。`Work` 为 0 = Hall、1 = Kitchen、2 = MaidRoom、3 = StandBy。`Pos` 保存世界位置，当前只读。

`Attr` 中的属性均为基础值。技能和设备等增益在运行时叠加，并对部分实际属性限幅。`NowHp` 属于运行时对象，不在这份存档里，创建员工运行数据时初始化为 `MaxHp`。

| Attr 字段 | 类型 | 含义 / 已核对规则 |
| --- | --- | --- |
| MaxHp | Int32 | 最大体力；须为正数，影响疲劳与健康阈值 |
| HpRecovery | float | 每秒体力恢复 |
| MoveSpeed | float | 移动速度 |
| CharaCharm | Int32 | 基础魅力；实际值 = 基础 × 魅力倍率增益，再限幅到 0–9999 |
| CookingTime | float | 料理耗时，越低越快；实际值限幅到 1–999 |
| OrderingTime | float | 点单耗时；同上 |
| CheckoutTime | float | 结账耗时；同上 |
| CleaningUpTime | float | 清桌耗时；同上 |
| CookingHpCost | float | 料理体力消耗，越低越省；实际值限幅到 1–999 |
| OrderingHpCost | float | 点单体力消耗；同上 |
| CheckoutHpCost | float | 结账体力消耗；同上 |
| CleaningUpHpCost | float | 清桌体力消耗；同上 |
| ExpGetRate | float | 经验获得倍率；基础 + 技能增量后实际值限幅到 1–99 |
| HPointGetRate | float | H 点获得倍率；同上 |
| UseMaidDeviceRate | float | 使用休息室设备概率；实际值限幅到 0.01–1 |
| MaidLevel | Int32 | 等级，上限由稀有度对应本机设置决定 |
| MaidLevelExp | Int32 | 当前等级经验；需低于本等级阈值，满级为 0 |
| NowLike | Int32 | 好感度，0–100 |
| BasicSalary | Int32 | 基本工资，升级时正常游戏逻辑会增加工资 |
| OrderingPriority | Int32 | 点单优先级，0–3 |
| CheckoutPriority | Int32 | 结账优先级，0–3 |
| CleaningUpPriority | Int32 | 清桌优先级，0–3 |
| DeliveryPriority | Int32 | 送餐优先级，0–3；没有单独的送餐耗时字段 |
| Rarity | enum | 0 = N、1 = R、2 = SR、3 = SSR |
| SkillSDatas | object[] | 技能列表，见下一节 |

自然升级会随机增加体力、恢复、移动、魅力、工资及倍率，并降低耗时/体力消耗。因此编辑器不会仅凭改等级猜测或重算成长属性。直接编辑等级是精确设值，属性按用户的独立设置保留。

编辑器对无明确游戏硬上限的体力、恢复、移动速度、工资和售价采用额外防溢出输入界限，并在界面说明；它们不被宣称为自然成长或玩法上限。

`Looks` 包含默认名字 `DefName`、自定义名字 `CustomName`、简介、角色模板、衣装、颜色与形态、头像字节。开放 `CustomName` 编辑，限制为游戏代码规定的 8 个字符，空值表示使用默认名。普通女仆的已确认 `Colors` 标量可编辑，服装、模板及未知字段只读。头像是 `_charaIconByte` 数字数组，数量庞大，不能将其视作海量可编辑玩法字段。

### 女仆外观

可编辑范围限于 `IsPlayerChara=false`、`Looks.IsMaleChara=false`、`Looks.CharaType=1`、`Looks.PrefabName=new_chara_body`，且本机代码指纹与目录有效。

| Colors 字段 | 意义与规则 |
| --- | --- |
| BreastSize | 整数 0–100；身体 `breasts_size` 变形权重。服装使用单独的 `clothes_breasts_size`，不是罩杯单位 |
| HairModel | 有效、未禁止的 CSHairMst ID；组合多个 PrefabNames。招聘稀有度不是现有人物发型限制 |
| EarType | CSCharaCustomMst 的 EarType ID；配置 int_value1/2/3 控制 pointed_ears1/2/3 |
| EyeTex / EyeHighLightTex | EyeType / EyeHighType ID；不是随意填写的贴图文件名 |
| Tattoo1Tex / Tattoo2Tex | TattooType ID；配置引用纹理。无纹身也是目录中的有效选项 |
| 各颜色的 r/g/b/a | 浮点数 0–1；27 组颜色分别保存主/第二发色、阴影、高光、肤色、眉睫、虹膜、眼白、妆容、指甲和纹身 |

没有已确认的独立胸型、脸型、身高或腰围保存字段。外观编辑仅替换所选标量的 JSON 值，不删除或重建 Looks，不清空头像，不改变性别/模板，不重置技能或等级。

`_charaIconByte` 是 PNG 缓存。游戏 `GetCharaIcon()` 优先复用它，因此模型外观改变不代表旧头像自动刷新。3D 预览独立从本机资源读取实际网格与贴图；使用静止绑定姿势和近似浏览器着色器，未复刻游戏动画/物理。所有导出还须游戏内载入确认。

`UnlockHPoses.u[]` 表示按设备类型关联的动作等级解锁列表；与 `KnownHObjTypes` 不同，当前只读。

## 技能

每条 `SkillSDatas[]` 是 `{ "SkillMstID": "有效技能ID", "Exp": 整数 }`。载入时查找主表并建立技能对象，再重新应用主表指定的 Buff。效果、名称、档位均由 ID 指向的主表决定，没有独立的可任意填写“技能等级”字段。

`Exp` 的保存与载入已核对；在当前技能代码中未发现它触发技能升级的逻辑，编辑经验不等于提升技能档位。要修改档位，选择本机目录中的另一有效技能 ID。

原代码对随机技能选择禁止重复非小费技能类型，允许多种小费技能。编辑器不允许重复相同 ID，同一非 `Tip` 类型不可叠加，并按最终稀有度的技能数量上限检查列表。主表的招聘稀有度表示生成条件，不被额外猜测为已有技能的持有资格。

## 仓库与菜谱

`Items[]` 对应 `CSItemSaveData`：`m` 是物品主表 ID，`c` 是持有数量。游戏仓库从这张清单重建，保存时再生成清单。

名称、分类、堆叠数 `StackLimit`、购入基价与卖价来自本机主表。编辑器按此配置校验数量，不猜测未知容量。已有未知 ID 条目可原样保留或明确移除，不能改成猜测的名称或未知新 ID。

添加过滤禁止物品、无限物品、不可取得物品、未实现或测试物品、家具子物件。提供消耗品、礼物、家具、衣装与料理书的有效条目。食材和菜品不作为普通仓库条目添加：食材 ID 参与成本/物价计算，当前菜品份数另存于菜单数组。

已学菜单由持有料理书和食物主表的 `CookingBook` 关联计算，不是单独保存的“已学菜谱”数组。查询料理书时按条目类型取清单，没有检查数量必须大于零，所以要撤掉料理书来源应明确删除条目，不能假设数量 0 等价于完全不持有。

## 菜单

`MenusSaveData` 包含三个平行数组：`m` = 菜品 ID、`c` = 剩余份数、`s` = 单份售价。索引必须对应。厨房载入时使用保存的 `c` 初始化剩余份数和该轮最大份数，销售时再减少剩余量。正常菜单配置 UI 最大 30 份。

本版编辑既有菜单的份数和售价，不随意替换 ID 或改变三个数组的长度，以免产生重复菜品、未解锁菜品或索引错位。食材成本、配方和学习条件读取主表。

## 地图、任务及其他数据

| 数据区 | 已解析的含义 | 当前行为 |
| --- | --- | --- |
| MapObjs | ItemMstID、GridIndex.x/y、Dir；主表对应家具类型、占地和魅力 | 分页查看，保留摆放/子物体关联 |
| MapSaveData | Hall/Kitchen/MaidRoom_UnlockedGridIndexs 为三类房间的解锁网格 | 查看，不猜测网格容量和形状 |
| MissionSaveData.ms | id = 任务 ID，v = 当前值，i = 奖励已经领取 | 查看目标、奖励与关联成就；只读 |
| Mails | 游戏日期、发件人、标题和正文 | 路径分页查看，报告列全量内容 |
| OldEvents | 过去事件及开始/结束游戏日期 | 只读，可出现空数组 |
| PriceRercods | 历史日期和食材 ID/价格倍率 | 只读；不是库存数量 |
| KnownHObjTypes | 获取设备时记录的已知设备类型 | 只读，与具体动作解锁不同 |
| TutorialFlags | 各教程和初始对话完成状态 | 只读 |
| SaveNewMark | 游戏界面新内容标记 | 只读，不当作物品拥有状态 |
| CameraPos / CameraRot | 镜头坐标 / 角度 | 只读 |

任务进度有多个类型，部分按当前余额、等级或累计行为更新。奖励标志与自动成就检测可能关联，不作为普通无关联计数处理。编辑器没有调用 Steam 成就接口。

界面保存先验证修改后的新文件，再将原存档完整复制到同目录 `.sd.bak` 并原子替换原存档。备份在下一次保存时更新为该次保存前的版本；源文件变化或验证失败时拒绝覆盖。上传文件只覆盖上传副本。

### 衣装清单与仓库转移

`/Charas/{index}/Looks/WearingClothes` 是小型对象数组，每项为 `ItemMstID` 和整数数组 `Slots`。编辑按本机 `CSClothesMst.OccupiedSlots` 校验，不允许重复或冲突槽位。上装/下装为 1/2，内衣为 3/4，其他衣装为 5–8；配饰使用 30–37。左右臂、腕、腿饰按单侧分别消耗一件。多槽位衣装作为一件处理。

游戏 `CSDressUpDetailsUI.WearClothes` 穿上后从仓库移除一件，`CSDressUpWindow.RemoveClothes` 脱下后返还一件。编辑器采用同样的计数规则，替换冲突衣装时先返还，再穿上新衣；显式“新增一件并穿上”增加角色持有的一件衣装。数组修改只重写衣装和仓库的对应有界数组，其他 JSON 字节保持原样。显示开关为浏览器状态，不写入存档。
