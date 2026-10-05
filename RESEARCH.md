# Pinned local research evidence

## Steam achievements

The installed Steam manifest identifies AppID `3306200`. The local native DLL
exports `SteamAPI_InitFlat`, manual dispatch callbacks, UserStats interface
`v012`, and Utils interface `v010`; these versions are explicitly bound by the
bridge. `GetAppID` must match before any achievement read or write.

Official references checked 2026-10-04:

- [ISteamUserStats](https://partner.steamgames.com/doc/api/ISteamUserStats):
  request current stats, enumerate achievements, SetAchievement and StoreStats;
  success callbacks are required before reporting a confirmed submission.
- [Steam API](https://partner.steamgames.com/doc/api/steam_api): initialization,
  shutdown and native manual dispatch.

Local read-only initialization and enumeration succeeded. No actual achievement
was unlocked during development. Tests use synthetic IDs and mocked write APIs;
account state and native diagnostic logs stay in ignored local storage.

Inspected the local game on 2026-10-04. The save `GameVer` is `1.0.0`; installed assets use Unity `6000.3.4f1`, serialized file version 22, little-endian, with stripped type trees.

Verified `cs_Data/Managed/Assembly-CSharp.dll` SHA-256:

`3c49bb55acd33b52aabb6eeaaccecfed9ca180f139e2af749949a8a49fd95acf`

The extension rules are restricted to this code fingerprint. Master tables are read from the user's local `resources.assets`, not redistributed. The reader independently parses the serialized metadata and seeks only selected objects. Scene and prefab settings are decoded by the verified field layout and required to agree.

## Code evidence

| Behavior | Local type / method inspected |
| --- | --- |
| Root fields, actual money caps | CoffeeShop.CSSaveData |
| Save/load gzip and JSON | CoffeeShop.CSSaveDataLoader |
| Shop EXP, ratings, inventory, learned menus, dates | CoffeeShop.Data.CSSaveDataManager |
| Character fields and attributes | CoffeeShop.CSCharaSaveData / CSMaidAttributes |
| Runtime values, clamps, HP initialization, skill loading | CoffeeShop.CSMaidData |
| Rarity limits, EXP thresholds, random level growth | CoffeeShop.CSMaidSettings / CSMaidLvUpExp |
| Skill ID, preserved EXP, buff configuration | CSSkillSData / CSSkill / CSSkillMst / CSBuffMst |
| Duplicate skill families | CoffeeShop.CSHelper.IsHadAnyDuplicatesBySkillType |
| Warehouse records and add/remove/load behavior | CSItemSaveData / CSInventory / CSItemEntity |
| Item names, stack, flags, sub-objects, recipe links | CSItemMst / CSMapObjMst / CSFoodMst |
| Parallel menu arrays and remaining amounts | CSMenusSaveData / KitchenProcess / Menu |
| Normal menu quantity cap | CoffeeShop.UI.CMSTomorrowMenus.MaxCount |
| Work priority and name length constants | CoffeeShop.CSSettings / UI.WorkPriorityUIItem |
| Task progress and reward flag meaning | CSMissionSaveData / CSMissionManager |
| Master table separators and comments | MstDataLocalFile / Arpg.GamePlay.Data.BaseMst |

## Pinned tooling and references

Appearance evidence from the same supported assembly:

- `CharaColors` and `RandomGenerateMaid.SetRandomLook`: saved appearance fields;
  `CSCharaModel.ApplyCharaColorsToModel` clamps breast size to 0–100 and loads the selected hair.
- `CSCharaModel.UpdateBodyShapeKey`: body size and pointed-ear blend shapes.
- `CSHelper.GetBreastsSizeKeyIfNeeded`: clothing uses `clothes_breasts_size`, not
  the body's `breasts_size`; this difference is reflected in the viewer.
- `CSResourcesLoader.GetClothesModel` and `CSClothesModel.SetMaterials`: left/right
  accessory prefabs and ordered clothing materials.
- `CSMaidLooksSDatas.GetCharaIcon`: existing PNG bytes remain a cached portrait.
- Local v22 resources contain ordinary vertex streams (float/half-float UV),
  triangle index buffers, sparse blend-shape deltas, and RGB24/RGBA32/BC1/BC3
  textures. The preview reader seeks individual objects and external texture
  stream ranges; it does not load the entire resource file.

Analysis-only `UnityPy 1.25.4` was installed under ignored `.local/asset-tools`
to cross-check built-in class field layouts and selected reader outputs. The
shipped parser and WebGL viewer are independently implemented, standard library
and browser APIs only. [UnityPy project](https://github.com/K0lb3/UnityPy),
[pinned analysis package](https://pypi.org/project/UnityPy/1.25.4/).

The prototype loads all seven maids in the local development save without missing
model warnings. Browser checks verify actual rendered pixel changes for breast
size and hair color, hairstyle reload, and explicit appearance export. This is
not Unity renderer parity or proof of in-game save loading.

- Analysis-only ILSpy command-line package: `ilspycmd 9.1.0.7988`, downloaded into ignored `.local/tools/`. No dependency in the shipped editor.
- Unity serialized metadata layout cross-check: [UnityPy SerializedFile.py, commit 998b3120489aac1b824bcb20e716f4ec1e59103f](https://github.com/K0lb3/UnityPy/blob/998b3120489aac1b824bcb20e716f4ec1e59103f/UnityPy/files/SerializedFile.py). No UnityPy code or dependency is bundled; the format reader is independently implemented for this verified layout.
- Python 3.11 standard-library API references: [gzip](https://docs.python.org/3.11/library/gzip.html), [sqlite3](https://docs.python.org/3.11/library/sqlite3.html), [json](https://docs.python.org/3.11/library/json.html), [http.server](https://docs.python.org/3.11/library/http.server.html).

All decompiled code, tables, source paths, saves, private reports, screenshots and validation outputs remain ignored in `.local/` or `exports/`. No modified file has been installed into the game, and no in-game load validation is claimed.

Face shader verification: locally disassembled the selected `def_face_high` Direct3D program with Windows D3DDisassemble. Main texture, eye makeup and tattoos sample TEXCOORD0; the lip mask samples TEXCOORD1 and its alpha channel. The viewer now retains both mesh UV sets, uses the second set for lips, and applies saved lip shadow color. Analysis outputs remain ignored.

Sclera correction: the local `eyeballs_bg` mesh has one implicit unit bone influence and a nontrivial renderer import transform. Preview positions now use prefab-relative bone transforms multiplied by serialized inverse bind matrices, rather than the renderer transform. Eye materials use the verified Legacy Particles alpha blend (2x tint, unlit, no depth writes); highlights use additive blending. Browser checks confirm white sclera and a blue-only sclera recolor without changing the iris.
