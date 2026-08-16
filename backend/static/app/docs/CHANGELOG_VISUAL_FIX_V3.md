# V3 Visual Fix

## 修掉的重大问题

1. **全局底栏穿透**
   - 原因：中央麦克风上凸区域使用了半透明抠图，且遮罩高度不够。
   - 修复：改为原稿 `nav_voice_control` 的不透明 cream patch；导航上凸遮罩从 -30px 扩展至 -48px；页面 bottom safe area 提升到 188px。

2. **服务图标被截断 / 带卡片横线**
   - 重新从 `source/services.png` 精确裁 10 个图标。
   - 使用 border-connected flood extraction，只移除外部纸色，保留白色图标内芯。
   - `紧急联系人 / 生活缴费 / 我的凭证 / 用药提醒` 均重新裁切。

3. **服务卡水墨条带文字**
   - 淘汰原来的 `service_*_mountain` 残缺小条。
   - 换成 8 个无文字 watercolor wash，作为卡片底部气氛层。

4. **成功章混入橙色太阳**
   - `success_check` 改为主连通区域提取，清掉右上太阳污染。

5. **可信凭证金印混入“交易成功”文字**
   - `cert_gold_seal` 只保留暖金色印记；绿色状态文字改回 DOM。

6. **安全盾牌裁半**
   - 重新扩展裁切区域，保证盾牌完整。

7. **倾听页 4 个水墨章带卡片边线**
   - 全部重新下移/收紧裁切，删除 card top line。

8. **假 SVG**
   - runtime 中彻底移除 raster-backed SVG wrapper，避免 Claude 误以为这些是可自由缩放 path。
